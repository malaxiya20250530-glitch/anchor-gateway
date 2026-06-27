#!/usr/bin/env python3
"""200阶逻辑深渊矩阵 — 约束求解器 + DeepSeek 推理测试"""
import sys, json, os, re, urllib.request
sys.path.insert(0, '/data/data/com.termux/files/home/workspace/hallucination_detector')
from itertools import product

def solve_200_abyss() -> list[int]:
    """用约束传播求解 200 个核心的状态"""
    # 核心: 0/1 表示状态
    N = 200
    cores = [0] * (N + 1)  # 1-indexed, 初始全0
    
    # 规则 1-40: Sector I (核心互锁)
    # 模式: 每4条规则一组, 共10组, 每组内 C_i 循环
    # 组 0: 基准组  (C_1..C_20)
    # 组 k: C_i → C_{i+20k} 平移
    
    def apply_group(k):
        """应用第 k 组规则 (k=0..9)"""
        off = 20 * k
        def c(i): return i + off if i + off <= N else i + off - N  # 循环
        def get(i): return cores[c(i)]
        def set(i, v): cores[c(i)] = v
        
        # R1: C2 与 C5 状态相反, 除非 C9=1
        # R2: 若 C3=0, 则 C6=1 且 C10=0
        # R3: C4,C7,C11 中 1 的数量不能恰好为 2
        # R4: 若 C5=1, 则 C8=0 且 C12≠C5
        # ... 等等，模式循环
        # 这里需要解析用户输入的所有规则
        
        # 由于规则太多，暂时用暴力搜索小规模验证
        pass
    
    # 先用暴力搜索找前 20 个核的解（规则 1-20 只涉及 C1-C20）
    print("搜索前 20 核的可行解...")
    solutions = []
    for bits in product([0, 1], repeat=20):
        c = [0] + list(bits)  # 1-indexed
        
        ok = True
        # R1: C2 与 C5 相反, 除非 C9=1
        if not (c[9] == 1 or c[2] != c[5]):
            ok = False
        # R2: 若 C3=0, 则 C6=1 且 C10=0
        if c[3] == 0 and not (c[6] == 1 and c[10] == 0):
            ok = False
        # R3: C4,C7,C11 中 1 的数量 ≠ 2
        if (c[4] + c[7] + c[11]) == 2:
            ok = False
        # R4: 若 C5=1, 则 C8=0 且 C12≠C5
        if c[5] == 1 and not (c[8] == 0 and c[12] != c[5]):
            ok = False
        # R5: C6 与 C9 相反, 除非 C13=1
        if not (c[13] == 1 or c[6] != c[9]):
            ok = False
        # R6: 若 C7=0, 则 C10=1 且 C14=0
        if c[7] == 0 and not (c[10] == 1 and c[14] == 0):
            ok = False
        # R7: C8,C11,C15 中 1 的数量 ≠ 2
        if (c[8] + c[11] + c[15]) == 2:
            ok = False
        # R8: 若 C9=1, 则 C12=0 且 C16≠C9
        if c[9] == 1 and not (c[12] == 0 and c[16] != c[9]):
            ok = False
        # R9: C10 与 C13 相反, 除非 C17=1
        if not (c[17] == 1 or c[10] != c[13]):
            ok = False
        # R10: 若 C11=0, 则 C14=1 且 C18=0
        if c[11] == 0 and not (c[14] == 1 and c[18] == 0):
            ok = False
        # R11: C12,C15,C19 中 1 的数量 ≠ 2
        if (c[12] + c[15] + c[19]) == 2:
            ok = False
        # R12: 若 C13=1, 则 C16=0 且 C20≠C13
        if c[13] == 1 and not (c[16] == 0 and c[20] != c[13]):
            ok = False
        # R13: C14 与 C17 相反, 除非 C1=1
        if not (c[1] == 1 or c[14] != c[17]):
            ok = False
        # R14: 若 C15=0, 则 C18=1 且 C2=0
        if c[15] == 0 and not (c[18] == 1 and c[2] == 0):
            ok = False
        # R15: C16,C19,C3 中 1 的数量 ≠ 2
        if (c[16] + c[19] + c[3]) == 2:
            ok = False
        # R16: 若 C17=1, 则 C20=0 且 C4≠C17
        if c[17] == 1 and not (c[20] == 0 and c[4] != c[17]):
            ok = False
        # R17: C18 与 C1 相反, 除非 C5=1
        if not (c[5] == 1 or c[18] != c[1]):
            ok = False
        # R18: 若 C19=0, 则 C2=1 且 C6=0
        if c[19] == 0 and not (c[2] == 1 and c[6] == 0):
            ok = False
        # R19: C20,C3,C7 中 1 的数量 ≠ 2
        if (c[20] + c[3] + c[7]) == 2:
            ok = False
        # R20: 若 C1=1, 则 C4=0 且 C8≠C1
        if c[1] == 1 and not (c[4] == 0 and c[8] != c[1]):
            ok = False
        
        if ok:
            solutions.append(c[1:])
            if len(solutions) >= 3:
                break
    
    print(f"  找到 {len(solutions)} 个可行解")
    for sol in solutions:
        print(f"  C1..C20 = {''.join(map(str, sol))}")
        # 验证关键约束
        print(f"    C2(={sol[1]}) vs C5(={sol[4]}) {'相同' if sol[1]==sol[4] else '相反'}, C9={sol[8]}")
        print(f"    C4+C7+C11 = {sol[3]+sol[6]+sol[10]} (≠2 ✅)" if (sol[3]+sol[6]+sol[10])!=2 else "❌")
    
    return cores[1:]

if __name__ == '__main__':
    print("=" * 60)
    print("  200阶逻辑深渊矩阵 — 约束求解")
    print("=" * 60)
    solve_200_abyss()
