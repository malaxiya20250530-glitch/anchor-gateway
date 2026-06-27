#!/usr/bin/env python3
"""
KB 千万级生成器 v2 — 接入 FactStore
=====================================
流式生成 + 哈希去重 + SQLite 持久化

策略（分层推进）：
  182万 → 500万：1M 数字实体 × 5 属性
  500万 → 1000万：2M 数字实体 × 7 属性 + Wikipedia 收割

用法:
  python3 kb_10m_v2.py --target 5000000    # 目标 500 万
  python3 kb_10m_v2.py --target 10000000   # 目标 1000 万
"""
import sys, time, math
from pathlib import Path
from kb_fact_store import FactStore, hash_fact

ROOT = Path(__file__).parent
DB_PATH = ROOT / "fact_store.db"


def sieve(limit):
    """质数筛法"""
    is_prime = [True] * (limit + 1)
    is_prime[0] = is_prime[1] = False
    for i in range(2, int(limit ** 0.5) + 1):
        if is_prime[i]:
            step = i
            start = i * i
            for j in range(start, limit + 1, step):
                is_prime[j] = False
    return is_prime


def gen_number_facts(store: FactStore, max_n: int, start_n: int = 1):
    """数字实体批量生成（主力）"""
    print(f"\n🔢 数字实体: 1 ~ {max_n:,}")
    primes = sieve(max_n)
    total_added = 0
    t0 = time.time()

    for n in range(start_n, max_n + 1):
        batch = []

        # 数学属性
        batch.append(f"整数{n}是{'质数' if primes[n] else '合数'}")
        batch.append(f"整数{n}是{'奇数' if n % 2 == 1 else '偶数'}")
        batch.append(f"整数{n}{'可以' if n % 3 == 0 else '不可以'}被3整除")
        batch.append(f"整数{n}{'可以' if n % 5 == 0 else '不可以'}被5整除")
        batch.append(f"整数{n}{'可以' if n % 7 == 0 else '不可以'}被7整除")

        # 平方/立方
        if n <= 1000:
            batch.append(f"整数{n}的平方是{n*n}")
        if n <= 100:
            batch.append(f"整数{n}的立方是{n**3}")

        # FALSE 变体
        batch.append(f"整数{n}不是{'质数' if not primes[n] else '合数'}")
        batch.append(f"整数{n}不能{'被3整除' if n % 3 != 0 else '被7整除'}")

        store.insert_batch(batch)
        total_added += len(batch)

        if n % 100000 == 0:
            elapsed = time.time() - t0
            rate = n / elapsed
            stats = store.stats()
            print(f"  [{n//1000}k/{(max_n-start_n+1)//1000+start_n//1000}k] {stats['hash_set_size']:,} 事实 | {rate:.0f} 数/s | +{total_added:,}")

    print(f"  ✅ 完成: {time.time()-t0:.0f}s, +{total_added:,} 事实")


def gen_prime_cross(store: FactStore, max_n: int):
    """质数交叉事实"""
    print(f"\n🔀 质数交叉: 1 ~ {max_n:,}")
    primes = sieve(max_n)
    prime_list = [i for i in range(2, max_n + 1) if primes[i]]
    composite_list = [i for i in range(4, max_n + 1) if not primes[i]]

    # 相邻质数对
    added = 0
    for i in range(len(prime_list) - 1):
        p1, p2 = prime_list[i], prime_list[i+1]
        batch = [
            f"质数{p1}和质数{p2}是相邻质数",
            f"整数{p1+1}不是质数",
            f"在{p1}和{p2}之间没有其他质数",
        ]
        store.insert_batch(batch)
        added += len(batch)

        if i % 5000 == 0 and i > 0:
            print(f"  质数对: {i}/{len(prime_list)}")

    print(f"  ✅ 质数交叉: +{added:,}")


def gen_year_entities(store: FactStore):
    """年份实体"""
    print(f"\n📅 年份实体: 1 ~ 2025")
    for y in range(1, 2026):
        is_leap = (y % 4 == 0 and y % 100 != 0) or (y % 400 == 0)
        century = (y - 1) // 100 + 1
        batch = [
            f"公元{y}年是{'闰年' if is_leap else '平年'}",
            f"公元{y}年属于第{century}世纪",
            f"公元{y}年不是{'闰年' if not is_leap else '平年'}",
        ]
        store.insert_batch(batch)
    print(f"  ✅ 完成")


def gen_big_number_range(store: FactStore, max_n: int):
    """大数字区间全量否定"""
    print(f"\n📐 大数区间否定: 1 ~ {max_n:,}")

    # 每 500 个数生成一批区间事实
    for block_start in range(1, max_n + 1, 500):
        block_end = min(block_start + 499, max_n)
        # 不做太复杂的，就生成简单的否定链
        batch = []
        for n in range(block_start, block_end + 1):
            batch.append(f"数字{n}不是质数" if n % 2 == 0 or n > 2 else f"数字{n}可能是质数")
        store.insert_batch(batch)

        if block_start % 100000 == 0:
            stats = store.stats()
            print(f"  [{block_start//1000}k] {stats['hash_set_size']:,} 事实")


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", type=int, default=5_000_000)
    parser.add_argument("--start-n", type=int, default=1)
    parser.add_argument("--max-n", type=int, default=1_000_000)
    args = parser.parse_args()

    print(f"{'='*60}")
    print(f"  KB 千万级生成器 v2 (FactStore 架构)")
    print(f"  目标: {args.target:,} 事实")
    print(f"  数字范围: 1 ~ {args.max_n:,}")
    print(f"{'='*60}")

    with FactStore(str(DB_PATH), bloom_bits=200_000_000) as store:
        start_stats = store.stats()
        print(f"  当前: {start_stats['hash_set_size']:,} 事实 ({start_stats['db_size_mb']:.1f} MB)\n")

        # 阶段 1: 数字实体（主力）
        gen_number_facts(store, args.max_n, args.start_n)

        # 阶段 2: 质数交叉
        gen_prime_cross(store, min(args.max_n, 200000))

        # 阶段 3: 年份
        gen_year_entities(store)

        # 最终统计
        store.flush()
        final_stats = store.stats()
        print(f"\n{'='*60}")
        print(f"  📊 最终: {final_stats['hash_set_size']:,} 事实")
        print(f"  💾 磁盘: {final_stats['db_size_mb']:.1f} MB")
        print(f"  📈 新增: +{final_stats['hash_set_size'] - start_stats['hash_set_size']:,}")
        print(f"  📈 完成度: {final_stats['hash_set_size']/args.target*100:.1f}%")
        print(f"  🔁 重复率: {final_stats['total_duplicates']/max(final_stats['total_inserted'],1)*100:.1f}%")
        print(f"{'='*60}")


if __name__ == "__main__":
    main()
