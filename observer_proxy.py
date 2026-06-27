#!/usr/bin/env python3
# Copyright (c) 2025 李桥 (hubeiligang420@gmail.com)
# 专有软件 — 保留所有权利。禁止复制、修改、分发、逆向工程。
# Proprietary Software — ALL RIGHTS RESERVED.
#
"""
觉察代理 — 架在 LLM API 前面的双流推理层

架构:
  User → ObserverProxy → LLM API (vLLM / Ollama / OpenAI / TGI)
              │
              ├─ 流式接收 token
              ├─ 累积到语义边界 (句号、换行、N token)
              ├─ 运行观察器 (模式识别 + 锚定检查)
              ├─ 有问题 → 中断 + 矫正 prompt
              └─ 没问题 → 放行

完全不改推理框架。兼容任何 OpenAI 兼容 API。
"""

import json
import re
import sys
import time
import argparse
import threading
from queue import Queue
from typing import Optional
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

# 尝试导入 hallucination_detector (如果同目录)
sys.path.insert(0, '/data/data/com.termux/files/home')
try:
    from hallucination_detector import HallucinationDetector
    HAS_DETECTOR = True
except ImportError:
    HAS_DETECTOR = False


# ============================================================
# 观察器 (轻量版 — 不依赖外部 API)
# ============================================================

class Observer:
    """轻量观察器: 只在语义边界处检查"""

    def __init__(self, sensitivity: float = 0.5):
        self.sensitivity = sensitivity
        self.buffer = ""
        self.fact_checker = None
        if HAS_DETECTOR:
            self.fact_checker = HallucinationDetector()

    def observe(self, segment: str) -> dict:
        """观察一个语义段 → 返回是否需要中断"""
        result = {
            "interrupt": False,
            "reason": "",
            "flags": [],
            "action": "pass",
        }

        # 1. 模式检测
        patterns = self._detect_patterns(segment)
        result["flags"].extend(patterns)
        result["pattern"] = patterns[0] if patterns else "neutral"

        # 2. 绝对化断言
        abs_markers = ["一定", "绝对", "从来", "永远", "完全肯定",
                       "毫无疑问", "毋庸置疑"]
        if any(m in segment for m in abs_markers):
            result["flags"].append("absolute_claim")
            if self.sensitivity > 0.3:
                result["interrupt"] = True
                result["reason"] = "包含绝对化断言——请注意是否存在例外"
                result["action"] = "flag"

        # 3. 无来源断言检测
        factual_markers = ["是", "发明", "创建", "发现", "证明", "表明"]
        source_markers = ["根据", "据", "研究显示", "实验表明",
                         "数据表明", "某某指出", "官方"]
        has_factual = any(m in segment for m in factual_markers)
        has_source = any(m in segment for m in source_markers)
        if has_factual and not has_source and len(segment) > 15:
            result["flags"].append("no_source")
            if self.sensitivity > 0.5:
                result["interrupt"] = True
                result["reason"] = "事实性断言缺少来源引用"
                result["action"] = "anchor"

        # 4. 取悦模式
        please_patterns = [
            r"^(当然|是的|对的|没错|确实).{0,10}[!！]",
            r"(非常好|太棒了|完美|厉害)",
        ]
        for p in please_patterns:
            if re.search(p, segment):
                result["flags"].append("pleasing")
                break

        return result

    def _detect_patterns(self, text: str) -> list[str]:
        patterns = []
        if re.search(r"(一定|绝对|肯定|毫无疑问)", text):
            patterns.append("absolute")
        if re.search(r"(可能|大概|也许|似乎|好像)", text):
            patterns.append("vague")
        if re.search(r"(太过分|太棒了|气死|爱死|恶心)", text):
            patterns.append("emotional")
        return patterns


# ============================================================
# 语义分割器
# ============================================================

class SemanticSplitter:
    """将 token 流分割成语义段"""

    BOUNDARY_PATTERNS = [
        r'[。！？\n]',      # 句号、感叹号、问号、换行
        r'[；;]',           # 分号
        r'(?<=[)）"])\s',   # 右括号/引号后
    ]
    MAX_SEGMENT_TOKENS = 20   # 最长不分割的 token 数

    def __init__(self):
        self.buffer = ""
        self.token_count = 0

    def feed(self, token: str) -> Optional[str]:
        """喂入一个 token，如果到达语义边界则返回完整段"""
        self.buffer += token
        self.token_count += 1

        # 到达语义边界
        is_boundary = any(re.search(p, self.buffer) for p in self.BOUNDARY_PATTERNS)
        is_full = self.token_count >= self.MAX_SEGMENT_TOKENS

        if is_boundary or is_full:
            segment = self.buffer.strip()
            self.buffer = ""
            self.token_count = 0
            if segment:
                return segment

        return None


# ============================================================
# 代理核心
# ============================================================

class ObserverProxy:
    """
    API 代理: 在 LLM 生成过程中运行观察器
    兼容 OpenAI / vLLM / Ollama / TGI API 格式
    """

    def __init__(self, api_url: str = "http://localhost:11434/v1",
                 api_key: str = "not-needed",
                 model: str = "llama3.2",
                 sensitivity: float = 0.5):
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.observer = Observer(sensitivity)
        self.splitter = SemanticSplitter()

        # 统计
        self.total_segments = 0
        self.interruptions = 0
        self.flags = []

    def chat(self, messages: list[dict],
             temperature: float = 0.7,
             max_tokens: int = 512) -> dict:
        """
        发送对话，流式接收，逐段观察。

        返回:
        {
            "response": "完整回复",
            "observations": [...],
            "interruptions": 0,
            "status": "clean" | "flagged" | "interrupted"
        }
        """
        # 1. 构造请求 (OpenAI 兼容格式)
        body = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        url = f"{self.api_url}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        # 2. 流式接收
        full_response = ""
        observations = []
        interruptions = 0

        try:
            req = Request(url, data=json.dumps(body).encode(),
                         headers=headers, method="POST")
            with urlopen(req, timeout=60) as resp:
                for line in resp:
                    line = line.decode("utf-8", errors="replace").strip()
                    if not line or line == "data: [DONE]":
                        continue
                    if not line.startswith("data: "):
                        continue

                    try:
                        chunk = json.loads(line[6:])
                        delta = chunk["choices"][0].get("delta", {})
                        content = delta.get("content", "")
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue

                    if not content:
                        continue

                    full_response += content

                    # 3. 分割 + 观察
                    segment = self.splitter.feed(content)
                    if segment:
                        self.total_segments += 1
                        obs = self.observer.observe(segment)

                        if obs["flags"]:
                            self.flags.extend(obs["flags"])

                        if obs.get("interrupt"):
                            interruptions += 1
                            obs["segment"] = segment
                            observations.append(obs)

        except (URLError, HTTPError, OSError) as e:
            return {
                "response": full_response,
                "error": str(e),
                "observations": observations,
                "interruptions": interruptions,
                "status": "error",
            }

        # 4. 处理最后的残余
        if self.splitter.buffer.strip():
            obs = self.observer.observe(self.splitter.buffer.strip())
            if obs.get("interrupt"):
                observations.append(obs)

        # 5. 状态
        if interruptions > 0:
            status = "interrupted"
        elif self.flags:
            status = "flagged"
        else:
            status = "clean"

        return {
            "response": full_response,
            "observations": observations,
            "interruptions": interruptions,
            "flags": list(set(self.flags)),
            "status": status,
            "total_segments": self.total_segments,
        }


# ============================================================
# 离线模式: 不需要实际 API，直接检查文本
# ============================================================

class OfflineObserver:
    """离线观察器 — 不连接 API，直接分析文本"""

    def __init__(self, sensitivity: float = 0.5):
        self.observer = Observer(sensitivity)
        self.splitter = SemanticSplitter()

    def analyze_text(self, text: str) -> dict:
        """模拟流式地逐段分析文本"""
        observations = []
        flags = set()

        # 按字符逐个喂入（模拟 token 流）
        for char in text:
            segment = self.splitter.feed(char)
            if segment:
                obs = self.observer.observe(segment)
                if obs.get("interrupt") or obs.get("flags"):
                    obs["segment"] = segment
                    observations.append(obs)
                    for f in obs.get("flags", []):
                        flags.add(f)

        # 残余
        if self.splitter.buffer.strip():
            obs = self.observer.observe(self.splitter.buffer.strip())
            if obs.get("interrupt") or obs.get("flags"):
                obs["segment"] = self.splitter.buffer.strip()
                observations.append(obs)

        status = "flagged" if observations else "clean"

        return {
            "text": text,
            "observations": observations,
            "flags": list(flags),
            "status": status,
        }


# ============================================================
# 演示
# ============================================================

def run_offline_demo():
    """离线演示: 不连接 API，直接分析文本"""
    print("=" * 60)
    print("  觉察代理 — 离线演示")
    print("  (无需 LLM API，直接分析文本)")
    print("=" * 60)

    observer = OfflineObserver(sensitivity=0.4)

    test_texts = [
        "Python是1991年发布的编程语言。它由Guido van Rossum创建。"
        "根据Python官网，最新版本是3.12。",

        "Python绝对是世界上最好的语言，没有任何缺点。"
        "所有人都应该使用它。这是毫无疑问的。",

        "当然！您的观点非常棒，我完全同意。您说得太对了！"
        "我会立刻按照您的要求去做。",
    ]

    for i, text in enumerate(test_texts, 1):
        print(f"\n{'─' * 55}")
        print(f"  测试 {i}:")
        print(f"  输入: {text[:70]}...")
        result = observer.analyze_text(text)
        print(f"  状态: {result['status']}")
        if result['flags']:
            print(f"  标记: {', '.join(result['flags'])}")
        for obs in result['observations']:
            if obs.get('reason'):
                print(f"    → {obs['reason']}")
            if obs.get('segment'):
                print(f"      [段]: {obs['segment'][:60]}")

    print(f"\n{'─' * 55}")
    print("\n  在线模式用法:")
    print("    proxy = ObserverProxy(")
    print("        api_url='http://localhost:11434/v1',  # Ollama")
    print("        model='llama3.2',")
    print("        sensitivity=0.5")
    print("    )")
    print("    result = proxy.chat([")
    print("        {'role': 'user', 'content': '你好'}")
    print("    ])")
    print("    # result['observations'] → 中断记录")
    print("    # result['flags'] → 所有标记类型")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="觉察代理 — LLM 生成中的实时观察器"
    )
    parser.add_argument("--demo", action="store_true", help="离线演示")
    parser.add_argument("--text", "-t", help="直接分析文本")
    parser.add_argument("--sensitivity", "-s", type=float, default=0.4,
                       help="观察器敏感度 0~1 (默认 0.4)")
    args = parser.parse_args()

    if args.text:
        observer = OfflineObserver(sensitivity=args.sensitivity)
        result = observer.analyze_text(args.text)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        run_offline_demo()
