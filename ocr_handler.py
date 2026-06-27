#!/usr/bin/env python3
"""
OCR 处理器 — 截图 → 文字 → 幻觉检测
支持: Tesseract (优先) / 纯文本回退 (降级)

用法:
  python3 ocr_handler.py screenshot.png           # OCR + 检测
  python3 ocr_handler.py --text "假新闻内容"      # 纯文本检测
  python3 ocr_handler.py --demo                   # 演示模式
"""

import sys
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional


def ocr_tesseract(image_path: str, lang: str = "chi_sim+eng") -> str:
    """使用 Tesseract OCR 提取图片文字"""
    result = subprocess.run(
        ["tesseract", image_path, "stdout", "-l", lang, "--psm", "6"],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Tesseract 失败: {result.stderr[:100]}")
    return result.stdout.strip()


def ocr_fallback(image_path: str) -> str:
    """
    降级方案：从同名 .txt 文件读取
    适用于用户手动提取文字后保存的场景
    """
    txt_path = Path(image_path).with_suffix(".txt")
    if txt_path.exists():
        return txt_path.read_text().strip()
    raise FileNotFoundError(
        f"Tesseract 不可用，且未找到 {txt_path}。"
        f"请手动提取图片文字保存到该文件，或使用 --text 参数。"
    )


def extract_text(image_path: str) -> str:
    """统一 OCR 入口：自动选择可用引擎"""
    # 尝试 Tesseract
    try:
        result = subprocess.run(
            ["tesseract", "--version"], capture_output=True, timeout=5
        )
        if result.returncode == 0:
            return ocr_tesseract(image_path)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass
    # 降级
    return ocr_fallback(image_path)


def detect_claims(text: str) -> dict:
    """将 OCR 文字送入幻觉检测器"""
    from hallucination_detector import HallucinationDetector, Reporter
    detector = HallucinationDetector()
    report = detector.analyze(text)
    return {
        "input_text": text,
        "claims_count": len(report.claims),
        "hallucination_ratio": report.hallucination_ratio,
        "overall_score": report.overall_score,
        "results": [
            {
                "claim": r.claim,
                "verdict": r.verdict,
                "confidence": r.confidence,
                "evidence": r.evidence[:200],
                "source": r.source,
                "anchor_type": r.anchor_type,
            }
            for r in report.results
        ],
        "warnings": report.warnings,
        "text_report": Reporter.generate(report),
    }


def demo():
    """演示模式：生成模拟截图文字并检测"""
    demo_texts = [
        "朱元璋发明了火锅，这是明代的一大创举。",
        "地球是平的，这是毫无疑问的事实。NASA一直在隐瞒真相。",
        "Python 是 1989 年发布的编程语言，它绝对是世界上最好的语言。",
    ]
    for text in demo_texts:
        print(f"\n{'='*60}")
        print(f"📷 OCR 文字: {text}")
        print(f"{'='*60}")
        result = detect_claims(text)
        print(result["text_report"])


if __name__ == "__main__":
    if "--demo" in sys.argv:
        demo()
    elif "--text" in sys.argv:
        idx = sys.argv.index("--text")
        text = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else sys.stdin.read()
        import json
        result = detect_claims(text)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif len(sys.argv) > 1:
        image_path = sys.argv[1]
        text = extract_text(image_path)
        import json
        result = detect_claims(text)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(__doc__)
