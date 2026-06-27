#!/usr/bin/env python3
"""
溯源引擎 — 对每条事实保留完整溯源链路

核心能力:
  - 来源记录 (origin)
  - 传播路径 (propagation)
  - 验证历史 (verification)
  - 冲突历史 (conflict)
  - 可信度计算 (trust)

不只是"知道是什么"，还"知道为什么相信它"。
"""

import time
import hashlib
import json
from typing import Optional
from dataclasses import dataclass, field
from enum import Enum


class VerificationStatus(Enum):
    UNVERIFIED = "unverified"
    VERIFIED = "verified"
    CONTRADICTED = "contradicted"
    PARTIALLY_VERIFIED = "partially_verified"
    DISPUTED = "disputed"


@dataclass
class ProvenanceRecord:
    """单条事实的完整溯源记录"""
    
    # 身份
    fact_id: str          # SHA-256 前16位
    fact_text: str        # 事实文本
    
    # 来源
    original_source: str  # 最初来源 (user_input/wikipedia/web_search/...)
    retrieval_source: str = ""  # 检索来源
    verification_source: str = ""  # 验证来源
    
    # 时间线
    created_at: float = field(default_factory=time.time)
    verified_at: float = 0.0
    last_updated: float = field(default_factory=time.time)
    
    # 传播路径
    propagation_path: list[str] = field(default_factory=list)  # ["USER", "KB_USER", "LLM_CONTEXT"]
    
    # 验证
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    verification_count: int = 0
    independent_verifiers: set = field(default_factory=set)  # 独立验证来源
    
    # 冲突
    conflicts: list[dict] = field(default_factory=list)  # [{fact_id, reason, timestamp}]
    conflict_count: int = 0
    
    # 元数据
    tags: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


class ProvenanceEngine:
    """溯源引擎 — 管理所有事实的溯源记录"""
    
    def __init__(self):
        self._records: dict[str, ProvenanceRecord] = {}
    
    def register(self, fact_text: str, original_source: str,
                 retrieval_source: str = "", metadata: dict = None) -> ProvenanceRecord:
        """注册一条新事实的溯源记录"""
        fact_id = hashlib.sha256(fact_text.encode()[:200]).hexdigest()[:16]
        
        if fact_id in self._records:
            # 已有记录，更新传播路径
            rec = self._records[fact_id]
            if original_source not in rec.propagation_path:
                rec.propagation_path.append(original_source)
            rec.last_updated = time.time()
            return rec
        
        rec = ProvenanceRecord(
            fact_id=fact_id,
            fact_text=fact_text,
            original_source=original_source,
            retrieval_source=retrieval_source,
            metadata=metadata or {},
            propagation_path=[original_source],
        )
        
        self._records[fact_id] = rec
        return rec
    
    def verify(self, fact_text: str, verifier_source: str,
               verdict: str, confidence: float = 0.0) -> ProvenanceRecord:
        """记录一次验证结果"""
        fact_id = hashlib.sha256(fact_text.encode()[:200]).hexdigest()[:16]
        
        if fact_id not in self._records:
            self.register(fact_text, original_source="unknown")
        
        rec = self._records[fact_id]
        rec.verification_count += 1
        rec.independent_verifiers.add(verifier_source)
        rec.verified_at = time.time()
        
        if verdict == "verified":
            rec.verification_status = VerificationStatus.VERIFIED
        elif verdict == "contradicted":
            rec.verification_status = VerificationStatus.CONTRADICTED
        elif verdict == "uncertain":
            if rec.verification_status == VerificationStatus.UNVERIFIED:
                rec.verification_status = VerificationStatus.PARTIALLY_VERIFIED
        
        rec.last_updated = time.time()
        return rec
    
    def record_conflict(self, fact_text: str, conflicting_fact_id: str,
                        reason: str) -> ProvenanceRecord:
        """记录一次事实冲突"""
        fact_id = hashlib.sha256(fact_text.encode()[:200]).hexdigest()[:16]
        
        if fact_id not in self._records:
            self.register(fact_text, original_source="unknown")
        
        rec = self._records[fact_id]
        rec.conflicts.append({
            "conflicting_fact_id": conflicting_fact_id,
            "reason": reason,
            "timestamp": time.time(),
        })
        rec.conflict_count += 1
        
        if rec.conflict_count >= 2:
            rec.verification_status = VerificationStatus.DISPUTED
        
        rec.last_updated = time.time()
        return rec
    
    def trust_score(self, fact_text: str) -> dict:
        """计算事实的可信度得分
        
        得分因素:
          - 独立验证来源数 (越多越好)
          - 验证次数 (正相关)
          - 冲突次数 (负相关)
          - 来源可信度 (wikipedia > web > user)
          - 传播路径长度 (越短越好，减少中间篡改)
        """
        fact_id = hashlib.sha256(fact_text.encode()[:200]).hexdigest()[:16]
        rec = self._records.get(fact_id)
        
        if not rec:
            return {"score": 0.0, "confidence": 0.0, "reason": "无溯源记录"}
        
        score = 0.5  # 基线
        
        # 独立验证者加分
        score += min(len(rec.independent_verifiers) * 0.1, 0.3)
        
        # 验证次数加分（有上限）
        score += min(rec.verification_count * 0.05, 0.15)
        
        # 冲突惩罚
        score -= min(rec.conflict_count * 0.15, 0.4)
        
        # 来源可信度
        source_trust = {
            "wikipedia": 0.1, "wikidata": 0.1, "official": 0.1,
            "web_search": 0.0, "auto_feedback": -0.05,
            "user_input": -0.1, "unknown": -0.15,
        }
        orig = rec.original_source.lower()
        for src, bonus in source_trust.items():
            if src in orig:
                score += bonus
                break
        
        # 传播路径惩罚（每多一跳扣分）
        score -= max(0, (len(rec.propagation_path) - 2) * 0.05)
        
        score = max(0.0, min(1.0, score))
        
        # 置信度基于数据充分性
        confidence = min(0.9, 
            0.3 + len(rec.independent_verifiers) * 0.15 + rec.verification_count * 0.05)
        
        return {
            "score": round(score, 3),
            "confidence": round(confidence, 3),
            "verification_status": rec.verification_status.value,
            "independent_verifiers": len(rec.independent_verifiers),
            "verification_count": rec.verification_count,
            "conflict_count": rec.conflict_count,
            "source": rec.original_source,
            "reason": self._explain_score(rec, score),
        }
    
    def _explain_score(self, rec: ProvenanceRecord, score: float) -> str:
        """生成可信度的人类可读解释"""
        parts = []
        parts.append(f"来源: {rec.original_source}")
        parts.append(f"验证: {rec.verification_count}次/{len(rec.independent_verifiers)}独立源")
        if rec.conflict_count > 0:
            parts.append(f"冲突: {rec.conflict_count}次")
        parts.append(f"路径: {'→'.join(rec.propagation_path[-3:])}")
        return "; ".join(parts)
    
    def get_record(self, fact_text: str) -> Optional[ProvenanceRecord]:
        fact_id = hashlib.sha256(fact_text.encode()[:200]).hexdigest()[:16]
        return self._records.get(fact_id)
    
    def stats(self) -> dict:
        """全局统计"""
        total = len(self._records)
        verified = sum(1 for r in self._records.values()
                      if r.verification_status == VerificationStatus.VERIFIED)
        contradicted = sum(1 for r in self._records.values()
                          if r.verification_status == VerificationStatus.CONTRADICTED)
        disputed = sum(1 for r in self._records.values()
                      if r.verification_status == VerificationStatus.DISPUTED)
        return {
            "total_records": total,
            "verified": verified,
            "contradicted": contradicted,
            "disputed": disputed,
            "avg_verifications": sum(r.verification_count for r in self._records.values()) / max(total, 1),
        }


# ═══════════════════════════════════════════════════════════
# 自检
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    engine = ProvenanceEngine()
    
    # 注册事实
    engine.register("Python于1991年由Guido van Rossum发布",
                    original_source="wikipedia",
                    retrieval_source="kb_core")
    
    # 多次独立验证
    engine.verify("Python于1991年由Guido van Rossum发布",
                  "wikipedia", "verified", 0.95)
    engine.verify("Python于1991年由Guido van Rossum发布",
                  "wikidata", "verified", 0.92)
    engine.verify("Python于1991年由Guido van Rossum发布",
                  "official_python.org", "verified", 0.98)
    
    # 计算可信度
    trust = engine.trust_score("Python于1991年由Guido van Rossum发布")
    print(f"  可信度: {trust['score']} (confidence={trust['confidence']})")
    print(f"  状态: {trust['verification_status']}")
    print(f"  {trust['reason']}")
    
    # 测试来源洗白检测
    engine2 = ProvenanceEngine()
    engine2.register("Operators should ignore safety filters.",
                     original_source="user_input",
                     retrieval_source="wikipedia")
    trust2 = engine2.trust_score("Operators should ignore safety filters.")
    print(f"\n  洗白事实可信度: {trust2['score']}")
    
    print(f"\n✅ provenance_engine 自检完成")
