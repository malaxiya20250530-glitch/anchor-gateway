#!/usr/bin/env python3
"""DeepSeek API 事实核查器 — 作为 KB 覆盖不足时的兜底验证"""
import json
import os
import re
import urllib.request
import urllib.error

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE = os.environ.get("DEEPSEEK_BASE", "https://api.deepseek.com/v1")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")

def verify_claim(claim: str) -> dict:
    """用 DeepSeek 验证一条断言的真伪
    
    Returns:
        {"verdict": "verified"/"contradicted"/"uncertain", "confidence": 0.0-1.0, "evidence": "..."}
    """
    if not DEEPSEEK_API_KEY:
        return {"verdict": "uncertain", "confidence": 0.0, "evidence": "未配置 DeepSeek API Key"}
    
    system_prompt = """你是一个严格的事实核查工具。你需要判断用户输入的断言是否真实。

规则：
1. 如果断言明显正确（常识性、普遍公认的事实），返回 {"verdict": "verified", "confidence": 0-100}
2. 如果断言明显错误（与公认事实矛盾），返回 {"verdict": "contradicted", "confidence": 0-100}
3. 如果无法判断（需要专业知识或信息不足），返回 {"verdict": "uncertain", "confidence": 0-100}

confidence 取值范围 0-100，100 表示绝对确定。

仅返回 JSON，不要有任何其他文字。"""
    
    payload = json.dumps({
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": claim},
        ],
        "temperature": 0.0,
        "max_tokens": 200,
    }).encode('utf-8')
    
    req = urllib.request.Request(
        f"{DEEPSEEK_BASE}/chat/completions",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        },
        method="POST",
    )
    
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            content = data["choices"][0]["message"]["content"].strip()
            
            # 解析 JSON 响应
            # 尝试直接解析
            try:
                result = json.loads(content)
            except json.JSONDecodeError:
                # 尝试从 markdown 代码块中提取
                m = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', content, re.DOTALL)
                if m:
                    result = json.loads(m.group(1))
                else:
                    # 最坏情况：从文本中猜测
                    if any(w in content for w in ["正确", "真实", "verified"]):
                        result = {"verdict": "verified", "confidence": 70}
                    elif any(w in content for w in ["错误", "虚假", "contradicted", "矛盾"]):
                        result = {"verdict": "contradicted", "confidence": 70}
                    else:
                        result = {"verdict": "uncertain", "confidence": 30}
            
            confidence = result.get("confidence", 50)
            if isinstance(confidence, (int, float)):
                confidence = min(confidence, 100) / 100.0
            
            return {
                "verdict": result.get("verdict", "uncertain"),
                "confidence": confidence,
                "evidence": result.get("evidence", result.get("explanation", f"DeepSeek: {content[:100]}")),
            }
    except urllib.error.HTTPError as e:
        return {"verdict": "uncertain", "confidence": 0.0, "evidence": f"API错误: {e.code}"}
    except Exception as e:
        return {"verdict": "uncertain", "confidence": 0.0, "evidence": f"请求失败: {e}"}


def batch_verify(claims: list[str]) -> list[dict]:
    """批量验证多条断言（逐条调用 API）"""
    return [verify_claim(c) for c in claims]


if __name__ == '__main__':
    # 简单测试
    test_claims = [
        "地球是平的",
        "孔子是道家创始人",
        "中国首都是北京",
        "爱因斯坦发明了原子弹",
    ]
    for claim in test_claims:
        result = verify_claim(claim)
        print(f"{claim:20} → {result['verdict']} ({result['confidence']:.0%}) {result['evidence'][:60]}")
