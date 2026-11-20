#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""汇总 e5_loop.py 的 SUMMARY 行。用法： python summarize.py e6c_summary.txt

按模式分组报：轮数 / 积分 / 每轮足迹 / prefill 的均值与极差，正确率 + Fisher 精确检验。

A1/A2 之后组数从 2 变成 5+（b0 / ours / rollback / truncate-4/8/16），所以：
  * truncate 的三档 N 按 wn 分开成组（否则 Pareto 图的三点会并成一点）
  * Fisher 对**参照组**（--ref，默认 b0）逐个比较，不再要求恰好两组
  * --csv 直接吐出「成功率 vs 每轮足迹」的 Pareto 点
"""
import argparse
import csv
import math
import re
import sys
from collections import defaultdict

FIELD = re.compile(r"(\w+)=(\S+)")


def parse(lines):
    recs = []
    for ln in lines:
        if not ln.startswith("SUMMARY"):
            continue
        d = dict(FIELD.findall(ln))
        if "mode" not in d:
            continue
        for k in ("turns", "msgs", "integral", "prefill", "correct", "rejects", "tools_fail",
                  "seed", "wn", "dup"):
            if k in d:
                try:
                    d[k] = int(d[k])
                except ValueError:
                    pass
        recs.append(d)
    return recs


def fisher(a, b, c, d):
    """双侧 Fisher 精确检验，2x2 = [[a,b],[c,d]]"""
    n = a + b + c + d
    r1, c1 = a + b, a + c
    if n == 0:
        return 1.0

    def p(x):
        return math.comb(r1, x) * math.comb(n - r1, c1 - x) / math.comb(n, c1)

    obs = p(a)
    lo, hi = max(0, c1 - (n - r1)), min(r1, c1)
    return sum(p(x) for x in range(lo, hi + 1) if p(x) <= obs + 1e-12)


def wilson(k, n, z=1.96):
    """单臂正确率的 Wilson 95% 区间（比 Wald 在 N=20、p 接近 0/1 时可靠得多）"""
    if n <= 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def newcombe(k1, n1, k2, n2, z=1.96):
    """两臂正确率之差的 Newcombe 95% 区间（由两个 Wilson 区间平方相加得到）"""
    l1, u1 = wilson(k1, n1, z)
    l2, u2 = wilson(k2, n2, z)
    p1, p2 = (k1 / n1 if n1 else 0.0), (k2 / n2 if n2 else 0.0)
    d = p1 - p2
    lo = d - math.sqrt((p1 - l1) ** 2 + (u2 - p2) ** 2)
    hi = d + math.sqrt((u1 - p1) ** 2 + (p2 - l2) ** 2)
    return d, lo, hi


def mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


def rng(xs):
    return (min(xs), max(xs)) if xs else (0, 0)


def gkey(r):
    """分组键。truncate 的 N=4/8/16 必须分开报，否则 Pareto 图的三点会并成一点。"""
    return r["mode"] + ("-%d" % r["wn"] if r.get("wn") else "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?", default=None, help="含 SUMMARY 行的文本文件（缺省读 stdin）")
    ap.add_argument("--ref", default="b0", help="Fisher 检验的参照组（默认 b0）")
    ap.add_argument("--csv", default="", help="把 Pareto 点（组/N/正确率/每轮足迹）写一份 CSV")
    a = ap.parse_args()
    lines = (open(a.path, encoding="utf-8").read() if a.path else sys.stdin.read()).splitlines()
    recs = parse(lines)
    if not recs:
        print("没解析到 SUMMARY 行")
        return 2
    by = defaultdict(list)
    for r in recs:
        by[gkey(r)].append(r)
    print("解析到 %d 条：%s" % (len(recs), {k: len(v) for k, v in sorted(by.items())}))
    print()
    print("%-12s %4s %8s %10s %10s %10s %9s %6s %5s" %
          ("组", "N", "轮数", "积分均值", "每轮足迹", "prefill", "正确率", "驳回", "重复"))
    agg, foot = {}, {}
    for m in sorted(by):
        rs = by[m]
        tot_t = sum(r["turns"] for r in rs)
        tot_i = sum(r["integral"] for r in rs)
        cor = sum(r.get("correct", 0) for r in rs)
        agg[m] = (cor, len(rs))
        foot[m] = tot_i / tot_t if tot_t else 0.0
        print("%-12s %4d %8.1f %10.0f %10.0f %10.0f %6d/%-3d %6d %5d" %
              (m, len(rs), mean([r["turns"] for r in rs]), mean([r["integral"] for r in rs]), foot[m],
               mean([r["prefill"] for r in rs]), cor, len(rs),
               sum(r.get("rejects", 0) for r in rs), sum(r.get("dup", 0) for r in rs)))
    print()
    for lab, k, dflt in (("轮数极差", "turns", 0), ("积分极差", "integral", 0),
                         ("工具失败", "tools_fail", 0), ("字面重复", "dup", 0)):
        print("%s： %s" % (lab, "  ".join("%s=%s" % (m, rng([r.get(k, dflt) for r in by[m]]))
                                        for m in sorted(by))))

    ref = a.ref if a.ref in by else sorted(by)[0]
    name = {"b0": "全量追加", "ours": "丢弃+墓碑", "rollback": "丢弃无墓碑"}.get(ref, ref)
    print()
    print("正确率（Fisher 双侧精确检验 + Wilson/Newcombe 95% 区间，参照组 = " + ref + "：" + name + "）：")
    c0, n0 = agg[ref]
    for m in sorted(by):
        c1, n1 = agg[m]
        wl, wu = wilson(c1, n1)
        if m == ref:
            print("  %-12s %2d/%-2d  95%%CI [%.1f%%, %.1f%%]  （参照组）"
                  % (m, c1, n1, 100 * wl, 100 * wu))
            continue
        p = fisher(c0, n0 - c0, c1, n1 - c1)
        d, lo, hi = newcombe(c1, n1, c0, n0)
        print("  %-12s %2d/%-2d  95%%CI [%.1f%%, %.1f%%]   vs %s  差 %+.1fpp 95%%CI [%+.1f, %+.1f]  p = %.4f%s"
              % (m, c1, n1, 100 * wl, 100 * wu, ref, 100 * d, 100 * lo, 100 * hi, p,
                 "   ← p<0.05" if p < 0.05 else ""))

    print()
    print("每轮上下文足迹（Pareto 的横轴）：")
    for m in sorted(by):
        r = foot[ref] / foot[m] if foot[m] else 0.0
        print("  %-12s %6.0f token/轮   （%s 是它的 %.2f 倍）" % (m, foot[m], ref, r))

    if a.csv:
        with open(a.csv, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["group", "n", "correct", "rate", "ci_lo", "ci_hi", "turns_mean",
                        "integral_mean", "footprint", "prefill_mean", "rejects", "dup"])
            for m in sorted(by):
                rs = by[m]
                c, n = agg[m]
                wl, wu = wilson(c, n)
                w.writerow([m, n, c, "%.4f" % (c / n if n else 0), "%.4f" % wl, "%.4f" % wu,
                            "%.1f" % mean([r["turns"] for r in rs]),
                            "%.0f" % mean([r["integral"] for r in rs]), "%.0f" % foot[m],
                            "%.0f" % mean([r["prefill"] for r in rs]),
                            sum(r.get("rejects", 0) for r in rs), sum(r.get("dup", 0) for r in rs)])
        print()
        print("Pareto 点 → %s" % a.csv)
    return 0


if __name__ == "__main__":
    sys.exit(main())
