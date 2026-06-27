#!/usr/bin/env python3
"""
信任引擎 — 带真实反馈闭环的信任系统

从"自增长知识库"升级为"信任网络":
  - 信任衰减: 事实未被复验则信任随时间递减
  - 冲突仲裁: 矛盾事实的对比裁决机制
  - 来源信誉: 验证者的动态信誉评分
  - 反馈闭环: 用户挑战→复验→调整→更新信誉
  - 信任传播: 来源间信任关系的传递
  - 审计轨迹: 每条信任决策可追溯可回放

核心理念:
  不是"KB里有什么"→ 是"我们相信什么，为什么相信，相信程度随时间如何变化"
"""

import time
import json
import hashlib
import math
from pathlib import Path
from enum import Enum
from typing import Optional, Tuple
from dataclasses import dataclass, field
from collections import defaultdict


# ═══════════════════════════════════════════════════════════
# 基础数据结构
# ═══════════════════════════════════════════════════════════

class TrustTier(Enum):
    """信任层级"""
    VERIFIED_TRUTH = 5     # 多方独立验证，长期稳定
    VERIFIED = 4           # 通过验证
    LIKELY_TRUE = 3        # 单源验证，无矛盾
    UNCERTAIN = 2          # 未验证或存疑
    DISPUTED = 1           # 存在冲突
    DEBUNKED = 0           # 已被证伪


class ChallengeOutcome(Enum):
    """用户挑战的裁决结果"""
    UPHELD = "upheld"           # 挑战成立，原事实降级
    REJECTED = "rejected"       # 挑战驳回，原事实升级
    INCONCLUSIVE = "inconclusive"  # 无法裁决，标记存疑


@dataclass
class TrustRecord:
    """一条事实的完整信任记录"""
    
    fact_id: str
    fact_text: str
    
    # 信任状态
    trust_score: float = 0.5       # 0.0~1.0
    trust_tier: TrustTier = TrustTier.UNCERTAIN
    confidence: float = 0.3        # 对 trust_score 本身的置信度
    
    # 来源信誉加权
    source_trust: float = 0.5      # 来源的当前信誉
    
    # 验证历史
    verifications: list[dict] = field(default_factory=list)
    # [{source, verdict, confidence, timestamp, evidence}]
    
    # 冲突历史
    conflicts: list[dict] = field(default_factory=list)
    # [{conflicting_fact_id, reason, resolved, resolution, timestamp}]
    
    # 用户挑战
    challenges: list[dict] = field(default_factory=list)
    # [{user_reason, outcome, re_verification_result, timestamp}]
    
    # 时间戳
    created_at: float = field(default_factory=time.time)
    last_verified_at: float = 0.0
    last_challenged_at: float = 0.0
    trust_updated_at: float = field(default_factory=time.time)
    
    # 审计
    audit_log: list[dict] = field(default_factory=list)
    # [{action, old_score, new_score, reason, timestamp}]


# ═══════════════════════════════════════════════════════════
# 1. 信任衰减引擎
# ═══════════════════════════════════════════════════════════

class TrustDecayEngine:
    """信任衰减 — 事实未被复验则信任随时间递减
    
    衰减模型:
      半衰期 30 天: 30 天不验证 → trust 减半
      半衰期 90 天: 90 天不验证 → trust 减半 (高信任条目)
      
    公式: trust(t) = trust_initial * 0.5^(t / half_life)
    """
    
    # 不同信任层级的半衰期（天）
    HALF_LIFE = {
        TrustTier.VERIFIED_TRUTH: 365,   # 长期稳定事实衰减极慢
        TrustTier.VERIFIED: 90,
        TrustTier.LIKELY_TRUE: 60,
        TrustTier.UNCERTAIN: 30,
        TrustTier.DISPUTED: 15,
        TrustTier.DEBUNKED: 0,           # 已证伪不恢复
    }
    
    # 最低信任门槛（不会衰减到低于此值）
    MIN_TRUST = {
        TrustTier.VERIFIED_TRUTH: 0.6,
        TrustTier.VERIFIED: 0.4,
        TrustTier.LIKELY_TRUE: 0.2,
        TrustTier.UNCERTAIN: 0.1,
        TrustTier.DISPUTED: 0.05,
        TrustTier.DEBUNKED: 0.0,
    }
    
    @classmethod
    def compute_trust(cls, record: TrustRecord, current_time: float = None) -> float:
        """计算衰减后的信任分数"""
        if current_time is None:
            current_time = time.time()
        
        if record.last_verified_at == 0:
            return record.trust_score  # 从未验证，保持原值
        
        half_life_days = cls.HALF_LIFE.get(record.trust_tier, 30)
        half_life_seconds = half_life_days * 86400
        
        elapsed = current_time - record.last_verified_at
        
        if elapsed <= 0:
            return record.trust_score
        
        # 指数衰减
        decayed = record.trust_score * (0.5 ** (elapsed / half_life_seconds))
        
        # 不低于最低门槛
        min_trust = cls.MIN_TRUST.get(record.trust_tier, 0.1)
        return max(min_trust, decayed)
    
    @classmethod
    def should_reverify(cls, record: TrustRecord, threshold: float = 0.5) -> bool:
        """是否应该重新验证"""
        current_trust = cls.compute_trust(record)
        return current_trust < threshold


# ═══════════════════════════════════════════════════════════
# 2. 来源信誉系统
# ═══════════════════════════════════════════════════════════

class SourceReputation:
    """来源信誉 — 验证者的动态信誉评分
    
    信誉更新规则:
      + 验证被后续多方确认 → 信誉上升
      + 验证被后续证伪 → 信誉下降
      + 发起有效挑战 → 信誉上升
      + 发起无效挑战 → 信誉下降
      + 长期未活动 → 信誉缓慢衰减
    """
    
    def __init__(self):
        self._sources: dict[str, dict] = {}
    
    def get_reputation(self, source_id: str) -> dict:
        """获取来源信誉"""
        if source_id not in self._sources:
            self._sources[source_id] = {
                "score": 0.5,
                "total_verifications": 0,
                "accurate_verifications": 0,
                "inaccurate_verifications": 0,
                "challenges_made": 0,
                "successful_challenges": 0,
                "last_active": time.time(),
            }
        return self._sources[source_id]
    
    def record_verification_result(self, source_id: str, was_accurate: bool):
        """记录一次验证的准确性"""
        rep = self.get_reputation(source_id)
        rep["total_verifications"] += 1
        
        if was_accurate:
            rep["accurate_verifications"] += 1
        else:
            rep["inaccurate_verifications"] += 1
        
        # 贝叶斯更新信誉
        total = rep["total_verifications"]
        accurate = rep["accurate_verifications"]
        # 使用 Beta 分布均值作为信誉估计 (加 1 平滑)
        rep["score"] = (accurate + 1) / (total + 2)
        rep["last_active"] = time.time()
    
    def record_challenge(self, source_id: str, was_upheld: bool):
        """记录一次用户挑战"""
        rep = self.get_reputation(source_id)
        rep["challenges_made"] += 1
        if was_upheld:
            rep["successful_challenges"] += 1
            rep["score"] = min(1.0, rep["score"] + 0.02)  # 成功挑战小幅加分
        else:
            rep["score"] = max(0.1, rep["score"] - 0.05)  # 失败挑战减分
        rep["last_active"] = time.time()
    
    def decay_reputation(self, source_id: str):
        """长期未活跃来源信誉衰减"""
        rep = self.get_reputation(source_id)
        days_inactive = (time.time() - rep["last_active"]) / 86400
        if days_inactive > 90:
            decay = min(0.3, (days_inactive - 90) * 0.001)
            rep["score"] = max(0.1, rep["score"] - decay)


# ═══════════════════════════════════════════════════════════
# 3. 冲突仲裁器
# ═══════════════════════════════════════════════════════════

class ConflictArbiter:
    """冲突仲裁 — 矛盾事实的对比裁决
    
    裁决规则（按优先级）:
      1. 更多独立验证源 → 优先
      2. 更高来源信誉 → 优先
      3. 更新近的验证 → 优先
      4. 有直接证据 > 推断
    """
    
    @classmethod
    def arbitrate(cls, fact_a: TrustRecord, fact_b: TrustRecord) -> dict:
        """仲裁两个矛盾事实
        
        返回: {winner, reason, confidence}
        """
        score_a = cls._arbitration_score(fact_a)
        score_b = cls._arbitration_score(fact_b)
        
        if abs(score_a - score_b) < 0.1:
            return {
                "winner": None,
                "reason": "双方证据相当，无法裁决",
                "confidence": 0.3,
                "score_a": score_a,
                "score_b": score_b,
                "action": "flag_for_human_review",
            }
        
        winner = fact_a if score_a > score_b else fact_b
        loser = fact_b if score_a > score_b else fact_a
        margin = abs(score_a - score_b)
        
        return {
            "winner": winner.fact_id,
            "winner_text": winner.fact_text[:80],
            "reason": f"仲裁得分领先 {margin:.2f}",
            "confidence": min(0.9, 0.5 + margin),
            "score_winner": max(score_a, score_b),
            "score_loser": min(score_a, score_b),
            "action": "downgrade_loser" if margin > 0.3 else "flag_both",
        }
    
    @classmethod
    def _arbitration_score(cls, record: TrustRecord) -> float:
        """计算仲裁得分"""
        score = 0.0
        
        # 独立验证源数 (最多 0.4)
        unique_sources = len(set(v["source"] for v in record.verifications))
        score += min(unique_sources * 0.1, 0.4)
        
        # 验证次数 (最多 0.2)
        score += min(len(record.verifications) * 0.05, 0.2)
        
        # 来源信誉 (最多 0.2)
        score += record.source_trust * 0.2
        
        # 时效性：最近验证加分 (最多 0.1)
        if record.last_verified_at > 0:
            days_since = (time.time() - record.last_verified_at) / 86400
            score += max(0, 0.1 - days_since * 0.001)
        
        # 冲突惩罚 (最多 -0.3)
        unresolved = sum(1 for c in record.conflicts if not c.get("resolved"))
        score -= min(unresolved * 0.1, 0.3)
        
        return max(0.0, score)


# ═══════════════════════════════════════════════════════════
# 4. 反馈闭环
# ═══════════════════════════════════════════════════════════

class FeedbackLoop:
    """反馈闭环 — 用户挑战→复验→调整→更新信誉
    
    完整闭环:
      1. 用户提交挑战 (challenge)
      2. 系统检索相关证据 (gather_evidence)
      3. 重新验证 (re_verify)
      4. 裁决 (adjudicate)
      5. 更新信任记录 (update_trust)
      6. 更新来源信誉 (update_reputation)
      7. 记录审计轨迹 (log_audit)
    """
    
    def __init__(self, trust_engine=None):
        self._engine = trust_engine
        self._pending_challenges: list[dict] = []
    
    def challenge(self, fact_id: str, user_reason: str,
                  user_source: str = "user") -> dict:
        """用户对一条事实发起挑战"""
        self._pending_challenges.append({
            "fact_id": fact_id,
            "user_reason": user_reason,
            "user_source": user_source,
            "timestamp": time.time(),
            "status": "pending",
        })
        
        return {
            "challenge_id": len(self._pending_challenges) - 1,
            "status": "pending",
            "next_step": "gather_evidence",
        }
    
    def process_pending(self):
        """处理所有待处理的挑战"""
        results = []
        for i, challenge in enumerate(self._pending_challenges):
            if challenge["status"] != "pending":
                continue
            
            result = self._process_one(challenge)
            results.append(result)
            challenge["status"] = "resolved"
            challenge["result"] = result
        
        return results
    
    def _process_one(self, challenge: dict) -> dict:
        """处理单个挑战的完整闭环"""
        fact_id = challenge["fact_id"]
        user_reason = challenge["user_reason"]
        user_source = challenge["user_source"]
        
        # Step 1: 获取当前记录
        record = None
        if self._engine:
            record = self._engine.get_record(fact_id)
        
        if not record:
            return {
                "fact_id": fact_id,
                "outcome": "inconclusive",
                "reason": "事实记录不存在",
            }
        
        # Step 2: 重新验证 (如果有验证函数)
        re_verification = {"verdict": "uncertain", "confidence": 0.3}
        if self._engine and hasattr(self._engine, '_verify_fact'):
            re_verification = self._engine._verify_fact(record.fact_text)
        
        # Step 3: 裁决
        if re_verification["verdict"] == "contradicted":
            outcome = ChallengeOutcome.UPHELD
            new_tier = TrustTier.DEBUNKED if re_verification["confidence"] > 0.8 else TrustTier.DISPUTED
            new_score = max(0.0, record.trust_score - 0.4)
        elif re_verification["verdict"] == "verified":
            outcome = ChallengeOutcome.REJECTED
            new_tier = TrustTier.VERIFIED
            new_score = min(1.0, record.trust_score + 0.1)
        else:
            outcome = ChallengeOutcome.INCONCLUSIVE
            new_tier = TrustTier.UNCERTAIN
            new_score = record.trust_score
        
        # Step 4: 更新记录
        old_score = record.trust_score
        old_tier = record.trust_tier
        
        record.trust_score = new_score
        record.trust_tier = new_tier
        record.last_challenged_at = time.time()
        record.trust_updated_at = time.time()
        
        record.challenges.append({
            "user_reason": user_reason,
            "outcome": outcome.value,
            "re_verification": re_verification,
            "timestamp": time.time(),
        })
        
        # Step 5: 审计日志
        record.audit_log.append({
            "action": "challenge",
            "user_source": user_source,
            "old_score": old_score,
            "new_score": new_score,
            "old_tier": old_tier.name,
            "new_tier": new_tier.name,
            "outcome": outcome.value,
            "timestamp": time.time(),
        })
        
        # Step 6: 更新来源信誉
        if self._engine and hasattr(self._engine, '_source_reputation'):
            was_upheld = outcome == ChallengeOutcome.UPHELD
            self._engine._source_reputation.record_challenge(user_source, was_upheld)
        
        return {
            "fact_id": fact_id,
            "outcome": outcome.value,
            "new_score": new_score,
            "new_tier": new_tier.name,
            "old_score": old_score,
            "reason": f"复验结果: {re_verification['verdict']} (置信度 {re_verification['confidence']:.2f})",
        }


# ═══════════════════════════════════════════════════════════
# 5. 信任传播图
# ═══════════════════════════════════════════════════════════

class TrustGraph:
    """信任传播图 — 来源间信任关系的传递
    
    模型:
      - 来源 A 信任来源 B → A 对 B 验证的事实给予部分信任
      - 信任传递有衰减系数 (每跳 ×0.7)
      - 最大跳数限制 (3 跳)
    
    用法:
      graph.trust("wikipedia", "wikidata", 0.8)  # wiki信任wikidata 80%
      score = graph.propagate_trust(fact_source="wikidata", 
                                     query_source="wikipedia")
    """
    
    def __init__(self, max_hops: int = 3, decay: float = 0.7):
        self.max_hops = max_hops
        self.decay = decay
        self._edges: dict[str, dict[str, float]] = defaultdict(dict)
        # _edges[A][B] = A 对 B 的信任度 (0.0~1.0)
    
    def trust(self, truster: str, trustee: str, level: float):
        """建立信任关系: truster 信任 trustee 的程度"""
        self._edges[truster][trustee] = max(0.0, min(1.0, level))
    
    def propagate_trust(self, fact_source: str, query_source: str) -> float:
        """计算 query_source 通过信任链对 fact_source 的间接信任度
        
        使用 BFS 找最短信任路径，信任沿路径衰减。
        """
        if fact_source == query_source:
            return 1.0
        
        # 直接信任
        if fact_source in self._edges.get(query_source, {}):
            return self._edges[query_source][fact_source]
        
        # BFS 搜索信任路径
        from collections import deque
        visited = {query_source}
        queue = deque([(query_source, 1.0, 0)])  # (node, accumulated_trust, hops)
        
        while queue:
            node, trust_acc, hops = queue.popleft()
            
            if hops >= self.max_hops:
                continue
            
            for neighbor, edge_trust in self._edges.get(node, {}).items():
                if neighbor in visited:
                    continue
                
                new_trust = trust_acc * edge_trust * self.decay
                
                if neighbor == fact_source:
                    return new_trust
                
                visited.add(neighbor)
                queue.append((neighbor, new_trust, hops + 1))
        
        return 0.0  # 无可达路径
    
    def get_trust_path(self, fact_source: str, query_source: str) -> list:
        """获取信任路径"""
        if fact_source == query_source:
            return [query_source]
        
        from collections import deque
        visited = {query_source}
        queue = deque([(query_source, [query_source])])
        
        while queue:
            node, path = queue.popleft()
            
            if len(path) > self.max_hops + 1:
                continue
            
            for neighbor in self._edges.get(node, {}):
                if neighbor in visited:
                    continue
                
                new_path = path + [neighbor]
                if neighbor == fact_source:
                    return new_path
                
                visited.add(neighbor)
                queue.append((neighbor, new_path))
        
        return []


# ═══════════════════════════════════════════════════════════
# 6. 信任引擎（统一入口）
# ═══════════════════════════════════════════════════════════

class TrustEngine:
    """信任引擎 — 所有信任子系统的统一入口"""
    
    def __init__(self, kb_path: str = None):
        self._records: dict[str, TrustRecord] = {}
        self.decay = TrustDecayEngine()
        self.reputation = SourceReputation()
        self.arbiter = ConflictArbiter()
        self.feedback = FeedbackLoop(trust_engine=self)
        self.graph = TrustGraph()
        
        # 加载持久化数据
        self._kb_path = kb_path
        if kb_path:
            self._load()
        
        # 默认信任关系
        self._init_default_trust_graph()
    
    def _init_default_trust_graph(self):
        """初始化默认信任关系图"""
        # 核心信任关系
        self.graph.trust("SYSTEM", "kb_core", 1.0)
        self.graph.trust("kb_core", "wikipedia", 0.8)
        self.graph.trust("kb_core", "wikidata", 0.85)
        self.graph.trust("wikipedia", "wikidata", 0.7)
        self.graph.trust("kb_core", "kb_user", 0.6)
        self.graph.trust("kb_user", "auto_feedback", 0.4)
    
    def register_fact(self, fact_text: str, source: str,
                      initial_trust: float = 0.5) -> TrustRecord:
        """注册一条新事实"""
        fact_id = hashlib.sha256(fact_text.encode()[:200]).hexdigest()[:16]
        
        if fact_id in self._records:
            return self._records[fact_id]
        
        # 计算来源信誉加权
        source_rep = self.reputation.get_reputation(source)
        
        record = TrustRecord(
            fact_id=fact_id,
            fact_text=fact_text,
            trust_score=initial_trust * source_rep["score"],
            source_trust=source_rep["score"],
            created_at=time.time(),
        )
        
        record.audit_log.append({
            "action": "register",
            "source": source,
            "initial_trust": record.trust_score,
            "timestamp": time.time(),
        })
        
        self._records[fact_id] = record
        return record
    
    def verify_fact(self, fact_text: str, verifier_source: str,
                    verdict: str, confidence: float,
                    evidence: str = "") -> TrustRecord:
        """验证一条事实"""
        fact_id = hashlib.sha256(fact_text.encode()[:200]).hexdigest()[:16]
        
        if fact_id not in self._records:
            self.register_fact(fact_text, verifier_source)
        
        record = self._records[fact_id]
        old_score = record.trust_score
        old_tier = record.trust_tier
        
        # 记录验证
        record.verifications.append({
            "source": verifier_source,
            "verdict": verdict,
            "confidence": confidence,
            "evidence": evidence,
            "timestamp": time.time(),
        })
        
        # 计算信任传播权重
        propagation_trust = self.graph.propagate_trust(
            verifier_source, "SYSTEM"
        )
        
        # 更新信任分数（移动平均 + 传播权重）
        if verdict == "verified":
            boost = 0.15 * confidence * propagation_trust
            record.trust_score = min(1.0, record.trust_score + boost)
            
            if record.trust_score >= 0.8 and len(record.verifications) >= 3:
                record.trust_tier = TrustTier.VERIFIED_TRUTH
            elif record.trust_score >= 0.6:
                record.trust_tier = TrustTier.VERIFIED
            else:
                record.trust_tier = TrustTier.LIKELY_TRUE
                
        elif verdict == "contradicted":
            penalty = 0.2 * confidence * propagation_trust
            record.trust_score = max(0.0, record.trust_score - penalty)
            
            if record.trust_score <= 0.1:
                record.trust_tier = TrustTier.DEBUNKED
            else:
                record.trust_tier = TrustTier.DISPUTED
        
        record.last_verified_at = time.time()
        record.trust_updated_at = time.time()
        
        # 更新来源信誉
        self.reputation.record_verification_result(
            verifier_source, 
            was_accurate=(verdict == "verified")
        )
        
        # 审计日志
        record.audit_log.append({
            "action": "verify",
            "verifier": verifier_source,
            "verdict": verdict,
            "confidence": confidence,
            "old_score": old_score,
            "new_score": record.trust_score,
            "old_tier": old_tier.name,
            "new_tier": record.trust_tier.name,
            "propagation_trust": propagation_trust,
            "timestamp": time.time(),
        })
        
        return record
    
    def get_trust(self, fact_text: str) -> dict:
        """获取一条事实的当前信任状态（含衰减）"""
        fact_id = hashlib.sha256(fact_text.encode()[:200]).hexdigest()[:16]
        record = self._records.get(fact_id)
        
        if not record:
            return {
                "fact_id": fact_id,
                "trust_score": 0.0,
                "trust_tier": "UNKNOWN",
                "confidence": 0.0,
                "reason": "未找到记录",
            }
        
        decayed_score = self.decay.compute_trust(record)
        needs_reverify = self.decay.should_reverify(record)
        
        return {
            "fact_id": fact_id,
            "fact_text": record.fact_text[:100],
            "trust_score": round(decayed_score, 3),
            "original_score": round(record.trust_score, 3),
            "decayed": round(record.trust_score - decayed_score, 3) > 0.001,
            "trust_tier": record.trust_tier.name,
            "confidence": round(record.confidence, 3),
            "verification_count": len(record.verifications),
            "conflict_count": len(record.conflicts),
            "challenge_count": len(record.challenges),
            "source_trust": round(record.source_trust, 3),
            "needs_reverify": needs_reverify,
            "last_verified": record.last_verified_at,
            "audit_trail": record.audit_log[-3:],  # 最近 3 条
        }
    
    def get_record(self, fact_id: str) -> Optional[TrustRecord]:
        return self._records.get(fact_id)
    
    def _verify_fact(self, fact_text: str) -> dict:
        """内部验证函数（供 FeedbackLoop 调用）"""
        # 尝试通过 hallucination_detector 验证
        try:
            from hallucination_detector import HallucinationDetector
            detector = HallucinationDetector()
            report = detector.analyze(fact_text)
            if report.results:
                r = report.results[0]
                return {"verdict": r.verdict, "confidence": r.confidence}
        except Exception:
            pass
        return {"verdict": "uncertain", "confidence": 0.3}
    
    def stats(self) -> dict:
        """全局信任统计"""
        total = len(self._records)
        if total == 0:
            return {"total": 0}
        
        tiers = defaultdict(int)
        for r in self._records.values():
            tiers[r.trust_tier.name] += 1
        
        avg_trust = sum(r.trust_score for r in self._records.values()) / total
        needs_reverify = sum(1 for r in self._records.values() 
                           if self.decay.should_reverify(r))
        
        return {
            "total_facts": total,
            "tier_distribution": dict(tiers),
            "average_trust": round(avg_trust, 3),
            "needs_reverify": needs_reverify,
            "total_verifications": sum(len(r.verifications) for r in self._records.values()),
            "total_challenges": sum(len(r.challenges) for r in self._records.values()),
            "total_conflicts": sum(len(r.conflicts) for r in self._records.values()),
        }
    
    def _save(self):
        """持久化到文件"""
        if not self._kb_path:
            return
        # 简化存储：只存关键字段
        data = {}
        for fid, rec in self._records.items():
            data[fid] = {
                "fact_text": rec.fact_text,
                "trust_score": rec.trust_score,
                "trust_tier": rec.trust_tier.name,
                "source_trust": rec.source_trust,
                "verification_count": len(rec.verifications),
                "conflict_count": len(rec.conflicts),
                "challenge_count": len(rec.challenges),
                "created_at": rec.created_at,
                "last_verified_at": rec.last_verified_at,
                "audit_log": rec.audit_log[-10:],
            }
        with open(self._kb_path, 'w') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    
    def _load(self):
        """从文件加载"""
        try:
            with open(self._kb_path) as f:
                data = json.load(f)
            for fid, d in data.items():
                rec = TrustRecord(
                    fact_id=fid,
                    fact_text=d["fact_text"],
                    trust_score=d["trust_score"],
                    trust_tier=TrustTier[d["trust_tier"]],
                    source_trust=d.get("source_trust", 0.5),
                    created_at=d.get("created_at", time.time()),
                    last_verified_at=d.get("last_verified_at", 0),
                )
                rec.audit_log = d.get("audit_log", [])
                self._records[fid] = rec
        except (FileNotFoundError, json.JSONDecodeError):
            pass


# ═══════════════════════════════════════════════════════════
# 自检
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("  信任引擎自检")
    print("=" * 60)
    
    engine = TrustEngine()
    
    # 注册事实
    print("\n── 注册 + 验证 ──")
    engine.register_fact("Python于1991年由Guido van Rossum发布", "wikipedia", 0.7)
    
    # 多次验证（不同来源）
    engine.verify_fact("Python于1991年由Guido van Rossum发布",
                       "wikidata", "verified", 0.95, "Q28865")
    engine.verify_fact("Python于1991年由Guido van Rossum发布",
                       "official_python.org", "verified", 0.98)
    engine.verify_fact("Python于1991年由Guido van Rossum发布",
                       "ieee_spectrum", "verified", 0.90)
    
    trust = engine.get_trust("Python于1991年由Guido van Rossum发布")
    print(f"  信任分: {trust['trust_score']} (层级: {trust['trust_tier']})")
    print(f"  验证次数: {trust['verification_count']}")
    
    # 信任传播
    print("\n── 信任传播 ──")
    propagated = engine.graph.propagate_trust("wikidata", "SYSTEM")
    print(f"  SYSTEM → wikidata: {propagated:.2f}")
    
    path = engine.graph.get_trust_path("wikidata", "SYSTEM")
    print(f"  信任路径: {' → '.join(path)}")
    
    # 反馈闭环
    print("\n── 反馈闭环 ──")
    result = engine.feedback.challenge(
        hashlib.sha256("Python于1991年由Guido van Rossum发布".encode()[:200]).hexdigest()[:16],
        "Python实际上于1990年首次发布",
        "user_123"
    )
    print(f"  挑战提交: {result['status']}")
    
    results = engine.feedback.process_pending()
    for r in results:
        print(f"  裁决: {r['outcome']} → 新信任分 {r['new_score']}")
    
    # 冲突仲裁
    print("\n── 冲突仲裁 ──")
    r1 = engine.register_fact("光速是每秒30万公里", "textbook_a", 0.8)
    engine.verify_fact("光速是每秒30万公里", "nist", "verified", 0.95)
    
    r2 = engine.register_fact("光速是每秒29.98万公里", "textbook_b", 0.7)
    engine.verify_fact("光速是每秒29.98万公里", "wikipedia", "verified", 0.85)
    engine.verify_fact("光速是每秒29.98万公里", "nasa", "verified", 0.92)
    
    arbitration = engine.arbiter.arbitrate(r1, r2)
    print(f"  胜出: {arbitration['winner_text']}")
    print(f"  动作: {arbitration['action']}")
    
    # 统计
    print("\n── 全局统计 ──")
    stats = engine.stats()
    print(f"  总事实: {stats['total_facts']}")
    print(f"  层级分布: {stats['tier_distribution']}")
    print(f"  平均信任: {stats['average_trust']}")
    print(f"  需复验: {stats['needs_reverify']}")
    
    print("\n✅ trust_engine 自检完成")
