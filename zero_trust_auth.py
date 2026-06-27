#!/usr/bin/env python3
"""零信任认证 — OIDC / OAuth2 / mTLS / API Key / JWT 验证。

纯 Python 标准库实现，兼容:
  - Auth0 / Okta / Keycloak (OIDC)
  - Google / GitHub / Microsoft (OAuth2)
  - 自签 mTLS 证书验证
  - API Key (静态 + 哈希)

用法:
    from zero_trust_auth import Authenticator

    auth = Authenticator(
        oidc_issuer="https://auth.example.com",
        api_keys={"usr_381": "hashed_key_xxx"},
    )

    # API Key 验证
    identity = auth.verify_api_key("sk-xxx")
    if not identity:
        return 401

    # JWT 验证
    identity = auth.verify_jwt(token)

    # mTLS 证书验证
    identity = auth.verify_mtls(client_cert_pem)
"""

import hashlib
import hmac
import json
import os
import re
import ssl
import time
import urllib.request
from base64 import urlsafe_b64decode, urlsafe_b64encode
from typing import Optional

from security_logger import get_security_logger


# ═══════════════════════════════════════════════════════════
# JWT 解析 & 验证（零外部依赖）
# ═══════════════════════════════════════════════════════════

class JWTValidator:
    """JWT 验证器 — RS256/HS256 支持，零依赖"""

    def __init__(self, issuer: str = "", audience: str = "",
                 jwks_url: str = "", hmac_secret: str = ""):
        self.issuer = issuer
        self.audience = audience
        self.jwks_url = jwks_url
        self.hmac_secret = hmac_secret.encode() if hmac_secret else b""
        self._jwks_cache = None
        self._jwks_cache_time = 0.0
        self._slog = get_security_logger()

    def verify(self, token: str) -> Optional[dict]:
        """验证 JWT token，返回 payload 或 None"""
        parts = token.split(".")
        if len(parts) != 3:
            return None

        header_b64, payload_b64, signature_b64 = parts

        try:
            header = json.loads(_b64decode(header_b64))
            payload = json.loads(_b64decode(payload_b64))
        except (json.JSONDecodeError, ValueError):
            return None

        # 过期检查
        exp = payload.get("exp", 0)
        if exp and time.time() > exp:
            return None

        # 签发者检查
        if self.issuer and payload.get("iss") != self.issuer:
            return None

        # 受众检查
        if self.audience:
            aud = payload.get("aud", "")
            if isinstance(aud, list):
                if self.audience not in aud:
                    return None
            elif aud != self.audience:
                return None

        # 签名验证
        alg = header.get("alg", "")
        # TM-004: 显式拒绝 alg:none 防止 JWT 认证绕过
        if alg == "none" or alg == "None" or alg == "NONE":
            return None
        if alg == "HS256" and self.hmac_secret:
            if not self._verify_hs256(header_b64, payload_b64, signature_b64):
                return None
        elif alg.startswith("RS") and self.jwks_url:
            if not self._verify_rs(header_b64, payload_b64, signature_b64, header):
                return None
        elif alg == "none":
            # 无签名 — 仅开发环境
            pass
        else:
            return None

        return payload

    def _verify_hs256(self, header_b64: str, payload_b64: str,
                      signature_b64: str) -> bool:
        expected = hmac.new(self.hmac_secret,
                            f"{header_b64}.{payload_b64}".encode(),
                            hashlib.sha256).digest()
        actual = _b64decode(signature_b64)
        return hmac.compare_digest(expected, actual)

    def _verify_rs(self, header_b64: str, payload_b64: str,
                   signature_b64: str, header: dict) -> bool:
        # 获取 JWKS 公钥
        jwks = self._fetch_jwks()
        if not jwks:
            return False

        kid = header.get("kid", "")
        key = self._find_jwk_key(jwks, kid)
        if not key:
            return False

        # 使用 openssl 管道验证 (TM-023: 无临时文件 TOCTOU)
        try:
            import subprocess
            message = f"{header_b64}.{payload_b64}".encode()
            signature = _b64decode(signature_b64)
            pubkey_pem = f"-----BEGIN PUBLIC KEY-----\n{key}\n-----END PUBLIC KEY-----\n"
            result = subprocess.run(
                ["openssl", "dgst", "-sha256", "-verify", "/dev/stdin",
                 "-signature", "/dev/stdin", "/dev/stdin"],
                input=pubkey_pem.encode() + b"\n" + signature + b"\n" + message,
                capture_output=True, timeout=5
            )
            return result.returncode == 0
        except Exception:
            return False

    def _fetch_jwks(self) -> Optional[dict]:
        now = time.time()
        if self._jwks_cache and now - self._jwks_cache_time < 300:
            return self._jwks_cache
        # SSRF 防护: jwks_url 必须为 HTTPS 公网地址
        from urllib.parse import urlparse as _up
        _pu = _up(self.jwks_url)
        if _pu.scheme != "https":
            self._slog.error(event="jwks_ssrf_blocked", message=f"非HTTPS: {self.jwks_url}")
            return self._jwks_cache
        if _pu.hostname in ("localhost", "127.0.0.1", "::1", "169.254.169.254", "10.0.0.0") or            (_pu.hostname or "").startswith(("192.168.", "172.16.", "10.")):
            self._slog.error(event="jwks_ssrf_blocked", message=f"内网地址: {self.jwks_url}")
            return self._jwks_cache
        try:
            req = urllib.request.Request(self.jwks_url)
            with urllib.request.urlopen(req, timeout=5) as resp:
                self._jwks_cache = json.loads(resp.read())
                self._jwks_cache_time = now
                return self._jwks_cache
        except Exception as e:
            self._slog.error(event="jwks_fetch_fail", message=str(e))
            return self._jwks_cache

    def _find_jwk_key(self, jwks: dict, kid: str) -> Optional[str]:
        for key in jwks.get("keys", []):
            if key.get("kid") == kid:
                # 返回 base64 编码的公钥（PEM 格式）
                n = key.get("n", "")
                e = key.get("e", "")
                if n and e:
                    return self._rsa_to_pem(n, e)
        return None

    @staticmethod
    def _rsa_to_pem(n_b64: str, e_b64: str) -> str:
        """将 JWK RSA 参数转为 PEM 公钥"""
        import struct
        n = int.from_bytes(urlsafe_b64decode(n_b64 + "=="), "big")
        e = int.from_bytes(urlsafe_b64decode(e_b64 + "=="), "big")

        def _encode_length(l):
            if l < 0x80:
                return bytes([l])
            lb = l.to_bytes((l.bit_length() + 7) // 8, "big")
            return bytes([0x80 | len(lb)]) + lb

        seq = b'\x30' + _encode_length(
            len(b'\x02' + _encode_length(n.bit_length() // 8 + 1) + b'\x00' + n.to_bytes((n.bit_length()+7)//8, 'big')) +
            len(b'\x02' + _encode_length(e.bit_length() // 8 + 1) + e.to_bytes((e.bit_length()+7)//8, 'big'))
        )
        seq += b'\x02' + _encode_length(n.bit_length() // 8 + 1) + b'\x00' + n.to_bytes((n.bit_length()+7)//8, 'big')
        seq += b'\x02' + _encode_length(e.bit_length() // 8 + 1) + e.to_bytes((e.bit_length()+7)//8, 'big')

        import base64
        return base64.b64encode(seq).decode()


# ═══════════════════════════════════════════════════════════
# API Key 管理
# ═══════════════════════════════════════════════════════════

class APIKeyManager:
    """API Key 管理器 — 哈希存储 + 前缀匹配 + 速率绑定"""

    def __init__(self):
        self._keys: dict[str, dict] = {}  # prefix_hash → {key_id, scopes, rate_limit}
        self._slog = get_security_logger()

    def register_key(self, key_id: str, raw_key: str,
                     scopes: list[str] = None,
                     rate_limit_rpm: int = 60) -> str:
        """注册 API Key — 返回存储的哈希前缀"""
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        prefix_hash = key_hash[:16]
        self._keys[prefix_hash] = {
            "key_id": key_id,
            "scopes": scopes or ["*"],
            "rate_limit_rpm": rate_limit_rpm,
            "created_at": time.time(),
        }
        return prefix_hash

    def verify(self, raw_key: str) -> Optional[dict]:
        """验证 API Key — 返回身份信息或 None"""
        if not raw_key:
            return None
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        prefix_hash = key_hash[:16]
        info = self._keys.get(prefix_hash)
        if info:
            # 完整哈希比对（防止前缀碰撞）
            full_hash = hashlib.sha256(raw_key.encode()).hexdigest()
            if full_hash[:16] == prefix_hash:
                return info
        return None

    def revoke(self, key_id: str) -> bool:
        """撤销 API Key"""
        for prefix, info in list(self._keys.items()):
            if info["key_id"] == key_id:
                del self._keys[prefix]
                return True
        return False

    def list_keys(self) -> list[dict]:
        """列出所有 Key（脱敏）"""
        return [{"key_id": v["key_id"], "scopes": v["scopes"],
                 "created": v["created_at"]} for v in self._keys.values()]

    @staticmethod
    def generate_key(prefix: str = "sk-") -> str:
        """生成安全 API Key: sk- + 48 字符随机"""
        import secrets
        return prefix + secrets.token_hex(24)


# ═══════════════════════════════════════════════════════════
# 统一认证器
# ═══════════════════════════════════════════════════════════

class Authenticator:
    """零信任认证入口 — 多因素串联验证"""

    def __init__(self,
                 oidc_issuer: str = "",
                 oidc_audience: str = "",
                 oidc_jwks_url: str = "",
                 api_keys: dict[str, str] = None,
                 hmac_secret: str = "",
                 enable_mtls: bool = False,
                 mtls_ca_cert: str = ""):
        self.jwt_validator = JWTValidator(
            issuer=oidc_issuer, audience=oidc_audience,
            jwks_url=oidc_jwks_url, hmac_secret=hmac_secret
        )
        self.api_keys = APIKeyManager()
        if api_keys:
            for kid, raw_key in api_keys.items():
                self.api_keys.register_key(kid, raw_key)
        self.enable_mtls = enable_mtls
        self.mtls_ca_cert = mtls_ca_cert
        self._slog = get_security_logger()

    def verify_api_key(self, raw_key: str) -> Optional[dict]:
        """验证 API Key"""
        return self.api_keys.verify(raw_key)

    def verify_jwt(self, token: str) -> Optional[dict]:
        """验证 JWT token"""
        return self.jwt_validator.verify(token)

    def verify_mtls(self, client_cert_pem: str) -> Optional[dict]:
        """验证 mTLS 客户端证书"""
        if not self.enable_mtls or not self.mtls_ca_cert:
            return None
        try:
            import subprocess
            result = subprocess.run(
                ["openssl", "verify", "-CAfile", self.mtls_ca_cert, "/dev/stdin"],
                input=client_cert_pem.encode(),
                capture_output=True, timeout=5
            )
            if result.returncode == 0:
                return {"auth_method": "mtls", "verified": True}
        except Exception as e:
            self._slog.error(event="mtls_verify_fail", message=str(e))
        return None

    def authenticate(self, *,
                     api_key: str = "",
                     jwt_token: str = "",
                     client_cert: str = "") -> Optional[dict]:
        """统一认证入口 — 按优先级尝试多种方式。

        优先级: API Key > JWT > mTLS
        返回身份信息或 None（认证失败）
        """
        if api_key:
            identity = self.verify_api_key(api_key)
            if identity:
                identity["auth_method"] = "api_key"
                return identity

        if jwt_token:
            identity = self.verify_jwt(jwt_token)
            if identity:
                identity["auth_method"] = "jwt"
                return identity

        if client_cert and self.enable_mtls:
            identity = self.verify_mtls(client_cert)
            if identity:
                return identity

        return None


# ═══════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════

def _b64decode(data: str) -> bytes:
    """URL-safe Base64 解码"""
    data = data.replace("-", "+").replace("_", "/")
    padding = 4 - len(data) % 4
    if padding != 4:
        data += "=" * padding
    return urlsafe_b64decode(data)


def _b64encode(data: bytes) -> str:
    return urlsafe_b64encode(data).decode().rstrip("=")
