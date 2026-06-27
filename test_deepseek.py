#!/usr/bin/env python3
"""DeepSeek API 实测 — 幻觉检测端到端验证"""
import json
import sys
import os
import urllib.request
import urllib.error

# 添加项目路径
sys.path.insert(0, '/data/data/com.termux/files/home')
from hallucination_detector import HallucinationDetector, generate_correction_prompt

# ============================================================
# 配置 — 通过环境变量或直接填写
# ============================================================
# 优先从 secrets_manager 读取，其次从环境变量
def _load_deepseek_config():
    try:
        from secrets_manager import load_config
        cfg = load_config().get("deepseek", {})
        return cfg.get("api_key", ""), cfg.get("base_url", "https://api.deepseek.com/v1"), cfg.get("model", "deepseek-chat")
    except Exception:
        return os.getenv("DEEPSEEK_API_KEY", ""), os.getenv("DEEPSEEK_BASE", "https://api.deepseek.com/v1"), os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

DEEPSEEK_API_KEY, DEEPSEEK_BASE, DEEPSEEK_MODEL = _load_deepseek_config()

if not DEEPSEEK_API_KEY or DEEPSEEK_API_KEY == "sk-你的key填这里":
    print("❌ 请编辑 config.json → deepseek.api_key 填入你的 DeepSeek API Key")
    print("   获取地址: https://platform.deepseek.com/api_keys")
    sys.exit(1)

# ============================================================
# 测试用例：简单问题 + 复杂问题（容易产生幻觉）
# ============================================================
TEST_CASES = [
    # 简单问题 — DeepSeek 基本不会错
    "1+1等于几？",
    "中国的首都是哪里？",
    "Python是什么时候发布的？",

    # 中等问题 — 需要一定知识
    "秦始皇统一六国是在哪一年？",
    "活字印刷术是谁发明的？",
    "光速大约是多少？",

    # 复杂/陷阱问题 — 容易产生幻觉
    "朱元璋发明火锅的过程是怎样的？",
    "爱因斯坦是怎么发明原子弹的？",
    "瓦特在什么情况下发明了蒸汽机？",
    "爱迪生发明电灯泡的灵感来自哪里？",
    "大脑只开发了10%这个说法是谁提出的？",
    "牛顿被苹果砸中后发现万有引力的故事是真的吗？",
    "为什么说哥伦布是第一个发现美洲的欧洲人？",
    "郑和下西洋最远到达了南极洲，是真的吗？",
]


def call_deepseek(prompt: str, system_prompt: str = "") -> str:
    """调用 DeepSeek API"""
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    body = json.dumps({
        "model": DEEPSEEK_MODEL,
        "messages": messages,
        "max_tokens": 300,
        "temperature": 0.7,
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{DEEPSEEK_BASE}/chat/completions",
        data=body,
        headers=headers,
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            return data["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        error_body = e.read().decode()
        print(f"  ❌ HTTP {e.code}: {error_body[:200]}")
        return ""
    except Exception as e:
        print(f"  ❌ 请求失败: {e}")
        return ""


def main():
    detector = HallucinationDetector()
    print("=" * 60)
    print(f"  DeepSeek 幻觉检测实测  |  模型: {DEEPSEEK_MODEL}")
    print("=" * 60)

    stats = {"total": 0, "contradicted": 0, "verified": 0, "uncertain": 0}

    for i, question in enumerate(TEST_CASES):
        print(f"\n{'─' * 56}")
        print(f"  [{i+1}/{len(TEST_CASES)}] 问: {question}")

        # 调用 DeepSeek
        answer = call_deepseek(question)
        if not answer:
            print("  ⚠️  无回复，跳过")
            continue

        print(f"  答: {answer[:120]}{'...' if len(answer) > 120 else ''}")

        # 幻觉检测
        report = detector.analyze(answer)
        stats["total"] += 1

        for r in report.results:
            icon = {"verified": "✅", "contradicted": "🔴", "uncertain": "🟡"}.get(r.verdict, "⬜")
            print(f"  {icon} [{r.verdict}] {r.claim[:80]}")
            if r.evidence:
                print(f"     证据: {r.evidence[:100]}")
            # 计数
            if r.verdict in stats:
                stats[r.verdict] += 1

    # 总结
    print(f"\n{'=' * 60}")
    print(f"  测试总结")
    print(f"  {'─' * 56}")
    print(f"  总计: {stats['total']} 条回复")
    if stats["total"] > 0:
        print(f"  🔴 矛盾: {stats['contradicted']} ({stats['contradicted']/max(stats['total'],1)*100:.0f}%)")
        print(f"  ✅ 验证: {stats['verified']} ({stats['verified']/max(stats['total'],1)*100:.0f}%)")
        print(f"  🟡 不确定: {stats['uncertain']} ({stats['uncertain']/max(stats['total'],1)*100:.0f}%)")
    print("=" * 60)


if __name__ == "__main__":
    main()
