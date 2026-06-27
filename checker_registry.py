#!/usr/bin/env python3
# Copyright (c) 2025 李桥 (hubeiligang420@gmail.com)
# 专有软件 — 保留所有权利。
"""检查器插件系统 — 装饰器自动注册，替代字符串列表。

用法:
    from checker_registry import Checker, checker

    @checker
    class NumericChecker(Checker):
        \"\"\"数值冲突检测\"\"\"
        def check(self, claim: str, fact: str):
            # 返回 (result_type, confidence) 或 None
            ...

    # 遍历所有已注册检查器:
    for checker_cls in Checker.registry:
        instance = checker_cls()
        result = instance.check(claim, fact)
"""

from typing import Optional, Tuple, List, Type


class Checker:
    """检查器基类 — 所有检查器必须继承此类并实现 check() 方法。

    子类只需定义:
        check(self, claim: str, fact: str) -> Optional[Tuple[str, float]]

    返回:
        - ("contradicted", 0.85) — 检测到矛盾
        - ("verified", 0.70) — 检测到一致
        - None — 该检查器不适用
    """

    # 类级别注册表，按注册先后排序
    registry: List[Type["Checker"]] = []

    # 检查器权重 (基于 benchmark F1 表现，0.0~1.0)
    # 子类可覆盖，高权重检查器在加权决策中优先
    weight: float = 1.0

    def __init_subclass__(cls, **kwargs):
        """子类定义时自动注册（无需装饰器的备用路径）"""
        super().__init_subclass__(**kwargs)
        if cls not in Checker.registry:
            Checker.registry.append(cls)

    def check(self, claim: str, fact: str) -> Optional[Tuple[str, float]]:
        """子类必须重写此方法"""
        raise NotImplementedError("检查器子类必须实现 check(claim, fact)")


def checker(cls: Type[Checker]) -> Type[Checker]:
    """装饰器: 显式注册检查器类到全局注册表。

    用法:
        @checker
        class NumericChecker(Checker):
            ...
    """
    if cls not in Checker.registry:
        Checker.registry.append(cls)
    return cls


def get_registry() -> List[Type[Checker]]:
    """返回当前已注册的检查器类列表（按注册先后排序）"""
    return list(Checker.registry)


def clear_registry() -> None:
    """清空注册表（仅供测试使用）"""
    Checker.registry.clear()
