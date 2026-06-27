# -*- coding: utf-8 -*-
'''记忆衰减系统 —— 指数衰减 + 遗忘清理。

公式：
  importance(t) = importance₀ × exp(-λ × t)
  其中 λ = decay_rate，t = 距今秒数

规则：
  - 如果 importance < 遗忘阈值 AND 长时间未访问 → 归档或删除
  - 每次访问重置衰减计时器
'''

import math
import time
from memory_engine_v2.store import MemoryStore


class DecayManager:
    '''记忆衰减管理器。'''

    def __init__(self, store: MemoryStore,
                 forget_threshold: float = 0.05,
                 archive_dir: str | None = None):
        self.store = store
        self.forget_threshold = forget_threshold
        self.archive_dir = archive_dir

    def apply_decay(self) -> dict:
        '''
        对所有记忆应用衰减，返回统计。

        衰减公式：importance *= exp(-decay_rate * days)
        '''
        now = int(time.time())
        decayed = 0
        archived = 0

        for mem in self.store.all():
            age_seconds = now - mem.get('last_accessed', mem.get('timestamp', now))
            age_days = age_seconds / 86400.0
            decay_rate = mem.get('decay_rate', 0.01)
            old_imp = mem.get('importance', 0.5)
            new_imp = old_imp * math.exp(-decay_rate * age_days)
            mem['importance'] = round(max(0.0, new_imp), 4)
            if abs(old_imp - new_imp) > 0.001:
                decayed += 1

        # 清理低于阈值的记忆
        kept = []
        for mem in self.store.all():
            if mem.get('importance', 0) < self.forget_threshold:
                archived += 1
            else:
                kept.append(mem)

        if archived > 0:
            self.store._memories = kept
            self.store._rewrite_all()

        return {
            'decayed': decayed,
            'archived': archived,
            'remaining': len(kept),
        }

    def boost(self, mem_id: str, amount: float = 0.1) -> bool:
        '''手动提升记忆重要性。'''
        mem = self.store.get(mem_id)
        if not mem:
            return False
        mem['importance'] = min(1.0, mem.get('importance', 0.5) + amount)
        mem['last_accessed'] = int(time.time())
        return True

    def decay_forecast(self, days: int = 30) -> list[dict]:
        '''预测 N 天后哪些记忆会低于阈值。'''
        forecasts = []
        for mem in self.store.all():
            imp = mem.get('importance', 0.5)
            rate = mem.get('decay_rate', 0.01)
            future_imp = imp * math.exp(-rate * days)
            if future_imp < self.forget_threshold:
                forecasts.append({
                    'id': mem['id'],
                    'content': mem.get('content', '')[:80],
                    'current_importance': round(imp, 4),
                    f'importance_in_{days}d': round(future_imp, 4),
                })
        return sorted(forecasts, key=lambda x: x[f'importance_in_{days}d'])


def decay_store(store: MemoryStore) -> dict:
    '''快捷衰减。'''
    dm = DecayManager(store)
    return dm.apply_decay()
