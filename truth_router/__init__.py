"""Truth Router MVP — 三层路由架构，对接 hallucination_detector 和 Memory Engine"""
from truth_router.router import route
from truth_router.context_builder import build_context
from truth_router.retrieval import retrieve
from truth_router.fact_check import check_claim
from truth_router.scoring import compute_truth_score
