#!/usr/bin/env python3
"""
任务总线 — 解耦检测流水线: KB → KG → Vector → Feedback → WAL
同步执行，组件隔离，方便独立替换
"""
import time, threading, json
from dataclasses import dataclass, field
from typing import Optional, Callable


@dataclass
class DetectionTask:
    id: str
    claim: str
    created: float = field(default_factory=time.time)
    kb_verdict: Optional[str] = None
    kb_confidence: float = 0.0
    kg_verdict: Optional[str] = None
    final_verdict: str = "pending"
    final_confidence: float = 0.0
    evidence: str = ""
    elapsed_ms: float = 0.0
    error: Optional[str] = None


class Pipeline:
    """可组合的检测流水线"""

    def __init__(self):
        self.stages: list[tuple[str, Callable]] = []
        self._hooks: dict[str, list[Callable]] = {"pre": [], "post": []}

    def add_stage(self, name: str, handler: Callable):
        """注册阶段处理器 handler(task) → task"""
        self.stages.append((name, handler))
        return self

    def on(self, event: str, callback: Callable):
        """注册钩子"""
        self._hooks[event].append(callback)
        return self

    def run(self, claim: str) -> DetectionTask:
        """执行完整流水线"""
        import uuid
        task = DetectionTask(id=uuid.uuid4().hex[:12], claim=claim)
        t0 = time.time()

        for cb in self._hooks["pre"]:
            cb(task)

        for name, handler in self.stages:
            try:
                handler(task)
            except Exception as e:
                task.error = f"{name}: {e}"
                break

        for cb in self._hooks["post"]:
            cb(task)

        task.elapsed_ms = (time.time() - t0) * 1000
        return task


# ============================================================
# 内置阶段处理器
# ============================================================

def stage_kb(task: DetectionTask):
    """阶段1: 知识库检测"""
    from hallucination_detector import FactExtractor, AnchorEngine
    engine = AnchorEngine(enable_web=False, enable_graph=False)
    extractor = FactExtractor()
    claims = extractor.extract(task.claim)
    if claims:
        result = engine.verify(claims[0])
        task.kb_verdict = result.verdict
        task.kb_confidence = result.confidence
        task.evidence = result.evidence


def stage_kg(task: DetectionTask):
    """阶段2: 知识图谱推理"""
    if task.kb_verdict and task.kb_verdict != "uncertain":
        return
    try:
        from knowledge_graph import get_reasoner
        reasoner = get_reasoner()
        r = reasoner.infer_contradiction(task.claim)
        if r:
            task.kg_verdict = r.get("verdict")
    except ImportError:
        pass


def stage_merge(task: DetectionTask):
    """阶段3: 判定融合"""
    if task.kb_verdict and task.kb_verdict != "uncertain":
        task.final_verdict = task.kb_verdict
        task.final_confidence = task.kb_confidence
    elif task.kg_verdict:
        task.final_verdict = task.kg_verdict
        task.final_confidence = 0.6
    else:
        task.final_verdict = "unverifiable"
        task.final_confidence = 0.3


def stage_wal(task: DetectionTask):
    """阶段4: 审计日志"""
    try:
        from wal_logger import log_detection
        log_detection(task.claim, task.final_verdict, task.final_confidence,
                      task.evidence)
    except ImportError:
        pass


def stage_vector(task: DetectionTask):
    """阶段V: 向量检索（快速通道，保留接口）"""
    pass


# ============================================================
# 预设流水线
# ============================================================

def create_default_pipeline() -> Pipeline:
    """创建标准检测流水线: KB → KG → Merge → WAL"""
    return (Pipeline()
            .add_stage("kb", stage_kb)
            .add_stage("kg", stage_kg)
            .add_stage("vector", stage_vector)
            .add_stage("merge", stage_merge)
            .add_stage("wal", stage_wal))


# 全局单例
_pipeline: Optional[Pipeline] = None
_lock = threading.Lock()


def get_pipeline() -> Pipeline:
    """返回全局 Pipeline 单例，用于跨模块获取同一实例"""
    global _pipeline
    if _pipeline is None:
        with _lock:
            if _pipeline is None:
                _pipeline = create_default_pipeline()
    return _pipeline


def detect(claim: str) -> DetectionTask:
    """便捷入口: 检测一条声明"""
    return get_pipeline().run(claim)


# ============================================================
# 自测
# ============================================================
if __name__ == "__main__":
    pipe = create_default_pipeline()
    claims = ["朱元璋发明了火锅", "毕昇发明了活字印刷术", "地球是平的"]
    for c in claims:
        task = pipe.run(c)
        print(f"[{task.id[:8]}] {c:<32} → {task.final_verdict:<14} {task.elapsed_ms:.0f}ms")
