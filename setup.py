"""pip install hallucination-detector"""
from setuptools import setup, find_packages
from pathlib import Path

long_desc = (Path(__file__).parent / "README.md").read_text(encoding="utf-8")

setup(
    name="llm-fact-guard",
    version="1.0.0",
    description="Zero-dependency LLM hallucination detection middleware · 零依赖大模型幻觉检测中间件",
    long_description=long_desc,
    long_description_content_type="text/markdown",
    author="Li Qiao",
    author_email="hubeiligang420@gmail.com",
    url="https://github.com/malaxiya20250530-glitch/anchor-llm-in-truth",
    py_modules=[
        "hallucination_detector", "checker_classes", "checker_registry",
        "knowledge_graph", "awareness_gateway", "billing",
        "kb_loader", "dashboard_server", "logger", "observer_security",
    ],
    python_requires=">=3.10",
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Intended Audience :: Developers",
        "License :: Other/Proprietary License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.13",
        "Topic :: Scientific/Engineering :: Artificial Intelligence",
        "Topic :: Security",
        "Operating System :: OS Independent",
    ],
    keywords="llm hallucination detection fact-checker ai-safety openai nlp chinese",
)
