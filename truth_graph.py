#!/usr/bin/env python3
"""
Truth Graph — Layer 5: 动态加权信念图

三个缺口:
  1. 事实竞争图    — facts support/contradict/override each other
  2. 隐式反馈      — adoption signals + usage tracking + auto-reflow
  3. 动态信念引擎  — confidence = f(time, usage, contradiction, validation, source)

核心理念:
  KB 不是存储"有什么"，是维护"相信什么，为什么，正在如何变化"。
  事实不是条目，是相互竞争、相互支持的活节点。
"""

import time
import hashlib
import math
import json
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field
from collections import defaultdict
from enum import Enum


# ═══════════════════════════════════════════════════════════
# 基础类型
# ═══════════════════════════════════════════════════════════

class EdgeType(Enum):
    SUPPORTS = "supports"         # A 支持 B
    CONTRADICTS = "contradicts"   # A 与 B 矛盾
    OVERRIDES = "overrides"       # A 覆盖 B（更强证据）
    SUPERSEDES = "supersedes"     # A 取代 B（更新版本）
    CITES = "cites"               # A 引用 B


@dataclass
class FactNode:
    """事实图中的节点 — 带完整生命周期"""
    
    fact_id: str
    statement: str
    
    # 信任状态（动态）
    confidence: float = 0.5
    confidence_history: list[tuple] = field(default_factory=list)
    # [(timestamp, old_conf, new_conf, reason)]
    
    # 使用追踪（隐式反馈）
    usage_count: int = 0           # 被检索/使用的次数
    adoption_count: int = 0        # 被用户采纳的次数
    correction_count: int = 0      # 被纠正的次数
    last_used_at: float = 0.0
    
    # 验证状态
    validation_count: int = 0
    last_validated_at: float = 0.0
    validators: set = field(default_factory=set)
    
    # 溯源
    provenance: str = ""
    source_reliability: float = 0.5
    
    # 生命周期
    created_at: float = field(default_factory=time.time)
    decay_state: str = "active"   # active / decaying / disputed / archived / debunked
    archived_at: float = 0.0
    
    # 关系
    edges_out: dict[str, EdgeType] = field(default_factory=dict)
    edges_in: dict[str, EdgeType] = field(default_factory=dict)
    
    @property
    def age_days(self) -> float:
        return (time.time() - self.created_at) / 86400
    
    @property
    def adoption_rate(self) -> float:
        """采纳率：使用中被采纳的比例"""
        if self.usage_count == 0:
            return 0.0
        return self.adoption_count / self.usage_count
    
    @property 
    def support_count(self) -> int:
        return sum(1 for e in self.edges_in.values() if e == EdgeType.SUPPORTS)
    
    @property
    def contradiction_count(self) -> int:
        return sum(1 for e in self.edges_out.values() if e == EdgeType.CONTRADICTS) + \
               sum(1 for e in self.edges_in.values() if e == EdgeType.CONTRADICTS)


# ═══════════════════════════════════════════════════════════
# 1. 事实竞争图
# ═══════════════════════════════════════════════════════════

class FactGraph:
    """事实竞争图 — 节点间支持/矛盾/覆盖/取代关系"""
    
    def __init__(self):
        self._nodes: dict[str, FactNode] = {}
        self._edges: list[tuple[str, str, EdgeType]] = []  # (from, to, type)
    
    def add_fact(self, statement: str, provenance: str = "",
                 initial_confidence: float = 0.5) -> FactNode:
        """添加事实节点"""
        fact_id = hashlib.sha256(statement.encode()[:200]).hexdigest()[:16]
        
        if fact_id in self._nodes:
            return self._nodes[fact_id]
        
        node = FactNode(
            fact_id=fact_id,
            statement=statement,
            confidence=initial_confidence,
            provenance=provenance,
        )
        self._nodes[fact_id] = node
        return node
    
    def relate(self, fact_a_id: str, fact_b_id: str, edge_type: EdgeType):
        """建立两个事实之间的关系
        
        A supports B    → B 的置信度受益于 A
        A contradicts B → 双向损害
        A overrides B   → B 被降权
        A supersedes B  → B 被归档
        """
        if fact_a_id not in self._nodes or fact_b_id not in self._nodes:
            return
        
        node_a = self._nodes[fact_a_id]
        node_b = self._nodes[fact_b_id]
        
        # 避免自引用
        if fact_a_id == fact_b_id:
            return
        
        # 避免重复边
        if fact_b_id in node_a.edges_out:
            return
        
        node_a.edges_out[fact_b_id] = edge_type
        node_b.edges_in[fact_a_id] = edge_type
        self._edges.append((fact_a_id, fact_b_id, edge_type))
        
        # 关系触发置信度更新
        self._propagate_edge_effect(node_a, node_b, edge_type)
    
    def _propagate_edge_effect(self, source: FactNode, target: FactNode, 
                               edge_type: EdgeType):
        """关系建立后传播置信度影响"""
        if edge_type == EdgeType.SUPPORTS:
            # A 支持 B: B 受益（A的置信度越高，B受益越多）
            boost = source.confidence * 0.1
            self._update_confidence(target, target.confidence + boost, 
                                   f"supported_by:{source.fact_id[:8]}")
        
        elif edge_type == EdgeType.CONTRADICTS:
            # 矛盾：双方受损，置信度高者受损少
            penalty_a = target.confidence * 0.15
            penalty_b = source.confidence * 0.15
            self._update_confidence(source, max(0.05, source.confidence - penalty_a),
                                   f"contradicted_by:{target.fact_id[:8]}")
            self._update_confidence(target, max(0.05, target.confidence - penalty_b),
                                   f"contradicted_by:{source.fact_id[:8]}")
        
        elif edge_type == EdgeType.OVERRIDES:
            # A 覆盖 B: B 大幅降权
            self._update_confidence(target, target.confidence * 0.3,
                                   f"overridden_by:{source.fact_id[:8]}")
            target.decay_state = "disputed"
        
        elif edge_type == EdgeType.SUPERSEDES:
            # A 取代 B: B 归档
            target.decay_state = "archived"
            target.archived_at = time.time()
            target.confidence = target.confidence * 0.1
    
    def _update_confidence(self, node: FactNode, new_conf: float, reason: str):
        """更新置信度并记录历史"""
        old_conf = node.confidence
        node.confidence = max(0.0, min(1.0, new_conf))
        node.confidence_history.append((time.time(), old_conf, node.confidence, reason))
    
    def get_competitors(self, fact_id: str) -> list[FactNode]:
        """获取与某事实竞争（矛盾/覆盖）的其他事实"""
        node = self._nodes.get(fact_id)
        if not node:
            return []
        
        competitors = []
        for other_id, edge_type in node.edges_out.items():
            if edge_type in (EdgeType.CONTRADICTS, EdgeType.OVERRIDES):
                competitors.append(self._nodes[other_id])
        for other_id, edge_type in node.edges_in.items():
            if edge_type in (EdgeType.CONTRADICTS, EdgeType.OVERRIDES):
                competitors.append(self._nodes[other_id])
        
        return competitors
    
    def get_supporters(self, fact_id: str) -> list[FactNode]:
        """获取支持某事实的其他事实"""
        node = self._nodes.get(fact_id)
        if not node:
            return []
        return [self._nodes[oid] for oid, et in node.edges_in.items() 
                if et == EdgeType.SUPPORTS]
    
    def get_ecosystem(self, fact_id: str) -> dict:
        """获取事实的完整生态"""
        node = self._nodes.get(fact_id)
        if not node:
            return {}
        
        return {
            "fact": node.statement[:80],
            "confidence": round(node.confidence, 3),
            "decay_state": node.decay_state,
            "supporters": len(self.get_supporters(fact_id)),
            "competitors": len(self.get_competitors(fact_id)),
            "supports": sum(1 for e in node.edges_out.values() if e == EdgeType.SUPPORTS),
            "contradicts": sum(1 for e in node.edges_out.values() if e == EdgeType.CONTRADICTS),
            "overrides": sum(1 for e in node.edges_out.values() if e == EdgeType.OVERRIDES),
            "is_superseded": node.decay_state == "archived",
        }
    
    @property
    def stats(self) -> dict:
        total = len(self._nodes)
        if total == 0:
            return {"total_facts": 0}
        
        states = defaultdict(int)
        for n in self._nodes.values():
            states[n.decay_state] += 1
        
        return {
            "total_facts": total,
            "total_edges": len(self._edges),
            "states": dict(states),
            "avg_confidence": round(
                sum(n.confidence for n in self._nodes.values()) / total, 3
            ),
        }


# ═══════════════════════════════════════════════════════════
# 2. 隐式反馈收集器
# ═══════════════════════════════════════════════════════════

class ImplicitFeedbackCollector:
    """隐式反馈 — 使用信号自动回流
    
    三类反馈:
      implicit  → 点击/采纳/停留时间（自动采集）
      explicit  → 用户纠错/评分（用户主动）
      external  → 外部源冲突验证（系统检测）
    """
    
    def __init__(self, graph: FactGraph = None):
        self._graph = graph
        self._usage_log: list[dict] = []
        self._adoption_log: list[dict] = []
        self._correction_log: list[dict] = []
    
    def record_usage(self, fact_id: str, context: str = ""):
        """记录一次使用（检索命中/展示给用户）"""
        if self._graph and fact_id in self._graph._nodes:
            node = self._graph._nodes[fact_id]
            node.usage_count += 1
            node.last_used_at = time.time()
        
        self._usage_log.append({
            "fact_id": fact_id,
            "context": context,
            "timestamp": time.time(),
        })
    
    def record_adoption(self, fact_id: str, user_id: str = ""):
        """记录一次采纳（用户使用了该事实）"""
        if self._graph and fact_id in self._graph._nodes:
            node = self._graph._nodes[fact_id]
            node.adoption_count += 1
            
            # 采纳信号 → 微弱增强置信度
            boost = min(0.05, 1.0 / (node.usage_count + 10))
            node.confidence = min(1.0, node.confidence + boost)
        
        self._adoption_log.append({
            "fact_id": fact_id,
            "user_id": user_id,
            "timestamp": time.time(),
        })
    
    def record_correction(self, fact_id: str, correction_text: str,
                          user_id: str = ""):
        """记录一次纠正（用户指出事实有误）"""
        if self._graph and fact_id in self._graph._nodes:
            node = self._graph._nodes[fact_id]
            node.correction_count += 1
            
            # 纠正信号 → 置信度衰减
            penalty = 0.1 * (1 + node.correction_count * 0.05)
            node.confidence = max(0.05, node.confidence - penalty)
            
            # 多次纠正 → 标记为 disputed
            if node.correction_count >= 3:
                node.decay_state = "disputed"
        
        self._correction_log.append({
            "fact_id": fact_id,
            "correction": correction_text,
            "user_id": user_id,
            "timestamp": time.time(),
        })
    
    def record_external_validation(self, fact_id: str, external_source: str,
                                   verdict: str, confidence: float):
        """记录外部验证结果"""
        if self._graph and fact_id in self._graph._nodes:
            node = self._graph._nodes[fact_id]
            node.validation_count += 1
            node.last_validated_at = time.time()
            node.validators.add(external_source)
            
            if verdict == "verified":
                boost = 0.1 * confidence
                node.confidence = min(1.0, node.confidence + boost)
            elif verdict == "contradicted":
                penalty = 0.15 * confidence
                node.confidence = max(0.05, node.confidence - penalty)
                if confidence > 0.9:
                    node.decay_state = "debunked"
    
    def get_feedback_stats(self, fact_id: str) -> dict:
        """获取某事实的反馈统计"""
        usages = sum(1 for u in self._usage_log if u["fact_id"] == fact_id)
        adoptions = sum(1 for a in self._adoption_log if a["fact_id"] == fact_id)
        corrections = sum(1 for c in self._correction_log if c["fact_id"] == fact_id)
        
        return {
            "usage_count": usages,
            "adoption_count": adoptions,
            "correction_count": corrections,
            "adoption_rate": adoptions / max(usages, 1),
        }


# ═══════════════════════════════════════════════════════════
# 3. 动态信念引擎
# ═══════════════════════════════════════════════════════════

class BeliefEngine:
    """动态信念引擎 — confidence = f(time, usage, contradiction, validation, source)
    
    不是静态分数，是随时间、使用、矛盾、验证动态变化的函数。
    
    信念函数:
      B(f, t) = base_confidence
               × time_decay(t)
               × usage_boost(u, a)
               × contradiction_penalty(c)
               × validation_boost(v)
               × source_factor(s)
    """
    
    def __init__(self, graph: FactGraph = None, collector: ImplicitFeedbackCollector = None):
        self._graph = graph
        self._collector = collector
    
    def compute_belief(self, fact_id: str) -> dict:
        """计算一条事实的当前信念
        
        返回: 完整的信念分解，每项可独立解释
        """
        if not self._graph or fact_id not in self._graph._nodes:
            return {"belief": 0.0, "error": "fact not found"}
        
        node = self._graph._nodes[fact_id]
        
        # 如果已被归档/证伪，直接返回低信念
        if node.decay_state in ("archived", "debunked"):
            return {
                "belief": node.confidence,
                "decay_state": node.decay_state,
                "reason": f"fact is {node.decay_state}",
                "factors": {},
            }
        
        # 1. 时间衰减
        days_since_validation = ((time.time() - max(node.last_validated_at, node.created_at)) 
                                 / 86400)
        if node.last_validated_at > 0:
            time_factor = 0.5 ** (days_since_validation / 90)  # 90天半衰期
        else:
            time_factor = 0.5 ** (days_since_validation / 30)  # 未验证的更快衰减
        
        # 2. 使用增强
        usage_boost = 1.0
        if node.usage_count > 0:
            # 使用越多，信任越稳固（有上限）
            usage_boost = 1.0 + min(0.2, math.log(node.usage_count + 1) * 0.05)
            # 高采纳率进一步加强
            if node.adoption_rate > 0.5:
                usage_boost += 0.1
        
        # 3. 矛盾惩罚
        contradiction_penalty = 1.0
        if node.contradiction_count > 0:
            contradiction_penalty = max(0.3, 1.0 - node.contradiction_count * 0.15)
        
        # 4. 验证增强
        validation_boost = 1.0
        if node.validation_count > 0:
            validation_boost = 1.0 + min(0.3, len(node.validators) * 0.08)
        
        # 5. 来源因子
        source_factor = 0.5 + node.source_reliability * 0.5
        
        # 综合信念
        belief = (node.confidence 
                  * time_factor 
                  * usage_boost 
                  * contradiction_penalty 
                  * validation_boost 
                  * source_factor)
        
        belief = max(0.0, min(1.0, belief))
        
        # 生态影响：竞争者的存在降低信念
        competitors = self._graph.get_competitors(fact_id) if self._graph else []
        if competitors:
            avg_competitor_confidence = sum(c.confidence for c in competitors) / len(competitors)
            # 如果竞争者平均置信度更高，本事实信念受损
            if avg_competitor_confidence > node.confidence:
                competition_drag = (avg_competitor_confidence - node.confidence) * 0.3
                belief = max(0.0, belief - competition_drag)
        
        return {
            "belief": round(belief, 4),
            "base_confidence": round(node.confidence, 3),
            "decay_state": node.decay_state,
            "factors": {
                "time_decay": round(time_factor, 3),
                "usage_boost": round(usage_boost, 3),
                "contradiction_penalty": round(contradiction_penalty, 3),
                "validation_boost": round(validation_boost, 3),
                "source_factor": round(source_factor, 3),
                "competitor_drag": round(
                    (avg_competitor_confidence - node.confidence) * 0.3 
                    if competitors and avg_competitor_confidence > node.confidence 
                    else 0, 3
                ),
            },
            "usage": {
                "total": node.usage_count,
                "adoptions": node.adoption_count,
                "adoption_rate": round(node.adoption_rate, 2),
            },
            "competition": {
                "competitors": len(competitors),
                "supporters": len(self._graph.get_supporters(fact_id)),
            },
            "explanation": self._explain_belief(node, belief, time_factor, usage_boost,
                                                contradiction_penalty, validation_boost,
                                                source_factor),
        }
    
    def _explain_belief(self, node, belief, time, usage, contra, valid, source) -> str:
        """生成信念的人类可读解释"""
        parts = [f"置信度 {belief:.2f}"]
        
        if time < 0.8:
            parts.append(f"时间衰减({time:.0%})")
        if usage > 1.05:
            parts.append(f"使用增强(×{usage:.2f})")
        if contra < 0.9:
            parts.append(f"矛盾惩罚(×{contra:.2f})")
        if valid > 1.05:
            parts.append(f"验证增强(×{valid:.2f})")
        if node.adoption_rate > 0.5:
            parts.append(f"高采纳率({node.adoption_rate:.0%})")
        if node.correction_count > 0:
            parts.append(f"被纠正{node.correction_count}次")
        
        return "; ".join(parts)
    
    def rank_facts(self, fact_ids: list[str]) -> list[tuple[str, float]]:
        """对多个事实按信念排序"""
        scored = [(fid, self.compute_belief(fid)["belief"]) for fid in fact_ids]
        return sorted(scored, key=lambda x: x[1], reverse=True)


# ═══════════════════════════════════════════════════════════
# 4. 五层集成测试
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("  Truth Graph — Layer 5 自检")
    print("=" * 60)
    
    graph = FactGraph()
    collector = ImplicitFeedbackCollector(graph)
    engine = BeliefEngine(graph, collector)
    
    # ── 事实竞争图 ──
    print("\n── 1. 事实竞争图 ──")
    
    # 注册相互关联的事实
    f1 = graph.add_fact("光速约为每秒30万公里", "textbook_a", 0.7)
    f2 = graph.add_fact("光速精确值为299792458米/秒", "nist", 0.95)
    f3 = graph.add_fact("光速是每秒29.98万公里", "textbook_b", 0.6)
    f4 = graph.add_fact("光速在真空中是无限的", "outdated_theory", 0.1)
    
    # 建立关系
    graph.relate(f2.fact_id, f1.fact_id, EdgeType.SUPPORTS)   # 精确值支持近似值
    graph.relate(f2.fact_id, f3.fact_id, EdgeType.SUPPORTS)   # 精确值支持近似值
    graph.relate(f4.fact_id, f2.fact_id, EdgeType.CONTRADICTS) # 过时理论与现代测量矛盾
    graph.relate(f2.fact_id, f4.fact_id, EdgeType.OVERRIDES)   # 现代测量覆盖过时理论
    
    for fid in [f1.fact_id, f2.fact_id, f4.fact_id]:
        eco = graph.get_ecosystem(fid)
        print(f"  [{eco['decay_state']:9s}] conf={eco['confidence']:.2f} "
              f"supporters={eco['supporters']} competitors={eco['competitors']} "
              f"| {eco['fact'][:50]}")
    
    # ── 隐式反馈 ──
    print("\n── 2. 隐式反馈 ──")
    
    # 模拟用户使用
    for _ in range(20): collector.record_usage(f2.fact_id, "physics_query")
    for _ in range(15): collector.record_adoption(f2.fact_id)
    for _ in range(5):  collector.record_usage(f4.fact_id, "physics_query")
    for _ in range(2):  collector.record_correction(f4.fact_id, "光速不是无限的", "user_1")
    
    stats2 = collector.get_feedback_stats(f2.fact_id)
    stats4 = collector.get_feedback_stats(f4.fact_id)
    print(f"  精确值: 使用{stats2['usage_count']}次 采纳{stats2['adoption_count']}次 "
          f"采纳率{stats2['adoption_rate']:.0%}")
    print(f"  过时理论: 使用{stats4['usage_count']}次 纠正{stats4['correction_count']}次")
    
    # ── 动态信念 ──
    print("\n── 3. 动态信念引擎 ──")
    
    # 外部验证
    collector.record_external_validation(f2.fact_id, "NIST SP 330", "verified", 0.99)
    collector.record_external_validation(f2.fact_id, "BIPM SI Brochure", "verified", 0.98)
    
    for fid in [f2.fact_id, f1.fact_id, f3.fact_id, f4.fact_id]:
        b = engine.compute_belief(fid)
        factors = b["factors"]
        print(f"  信念={b['belief']:.3f} | {b['explanation'][:60]}")
    
    # ── 排序 ──
    print("\n── 4. 按信念排序 ──")
    ranked = engine.rank_facts([f1.fact_id, f2.fact_id, f3.fact_id, f4.fact_id])
    for fid, belief in ranked:
        node = graph._nodes[fid]
        print(f"  {belief:.3f} [{node.decay_state}] {node.statement[:50]}")
    
    print(f"\n  图统计: {graph.stats}")
    print("\n✅ Truth Graph 自检完成")
