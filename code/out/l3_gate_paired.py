#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""L3 自检门三条 FAIL 的配对量化（只读 SUMMARY，离线）。

1) truncate 臂是否真的触发了裁剪（msgs 终值 vs HEAD_KEEP(2)+n+1/2）
2) 逐 seed 配对：label vs b0 同轮数时 integral 谁大；foot 排序稳定性
3) H1 的 Fisher 精确检验（手算，双侧）
用法：python l3_gate_paired.py l3_qwen3_8b_summary.txt
"""
import re
import sys
from collections import defaultdict, Counter
from math import comb

FIELD = re.compile(r"(\w+)=(\S+)")
INTK = ("turns", "msgs", "integral", "prefill", "correct", "rejects", "tools_fail", "seed", "wn", "dup")
HEAD_KEEP = 2  # e5_loop.slide_window 实测：t4 终值 8 = 2+4+2（reject 行印的是 +2 之后）


def parse(path):
    recs = []
    for ln in open(path, encoding="utf-8"):
        if not ln.startswith("SUMMARY"):
            continue
        d = dict(FIELD.findall(ln))
        if "mode" not in d:
            continue
        for k in INTK:
            if k in d:
                try:
                    d[k] = int(d[k])
                except ValueError:
                    pass
        recs.append(d)
    return recs


def gkey(r):
    return r["mode"] + ("-%d" % r["wn"] if r.get("wn") else "")


def fisher_2x2(a, b, c, d):
    """双侧 Fisher 精确检验：表 [[a,b],[c,d]]。"""
    n = a + b + c + d
    r1, r2, c1 = a + b, c + d, a + c

    def p(x):
        return comb(r1, x) * comb(r2, c1 - x) / comb(n, c1)

    lo = max(0, c1 - r2)
    hi = min(r1, c1)
    p0 = p(a)
    return min(1.0, sum(p(x) for x in range(lo, hi + 1) if p(x) <= p0 + 1e-12))


def main():
    recs = parse(sys.argv[1])
    by = defaultdict(list)
    for r in recs:
        by[gkey(r)].append(r)

    print("=" * 76)
    print("1) truncate 臂：触发裁剪了吗（HEAD_KEEP=%d，窗口 n，answer +1 / 其余 +2）" % HEAD_KEEP)
    print("=" * 76)
    for k, n in (("truncate-4", 4), ("truncate-8", 8), ("truncate-16", 16)):
        rs = by[k]
        msgs = [r["msgs"] for r in rs]
        floor = HEAD_KEEP + n
        trig = sum(1 for m in msgs if m >= floor)   # 终值 >= floor 才可能是裁剪后的状态
        print("  %-12s floor=%2d  msgs 分布=%s  终值>=floor 的 run: %d/20"
              % (k, floor, dict(sorted(Counter(msgs).items())), trig))

    print()
    print("=" * 76)
    print("2) 逐 seed 配对（同 seed 同沙盒，只有臂不同）")
    print("=" * 76)
    idx = defaultdict(dict)
    for r in recs:
        idx[r["seed"]][gkey(r)] = r

    same = [s for s in idx if "b0" in idx[s] and "label" in idx[s]
            and idx[s]["b0"]["turns"] == idx[s]["label"]["turns"]]
    win = sum(1 for s in same if idx[s]["label"]["integral"] >= idx[s]["b0"]["integral"])
    print("  [判据2 配对] label 与 b0 **同轮数** 的 seed: %d/20；其中 integral(label)>=integral(b0): %d/%d"
          % (len(same), win, len(same)))
    neq = [s for s in idx if "b0" in idx[s] and "label" in idx[s]
           and idx[s]["b0"]["turns"] != idx[s]["label"]["turns"]]
    print("            轮数不同的 seed: %d/20 -> 聚合均值在比两个不同长度的样本"
          % len(neq))
    lt = [s for s in neq if idx[s]["label"]["turns"] < idx[s]["b0"]["turns"]]
    print("            其中 label 轮数更少（先做完）的 seed: %d/%d" % (len(lt), len(neq)))

    order = ["b0", "truncate-16", "truncate-8", "truncate-4"]
    mono = [s for s in idx if all(k in idx[s] for k in order)]
    ok1 = [s for s in mono
           if idx[s]["b0"]["integral"] / idx[s]["b0"]["turns"]
           > idx[s]["truncate-16"]["integral"] / idx[s]["truncate-16"]["turns"]
           > idx[s]["truncate-8"]["integral"] / idx[s]["truncate-8"]["turns"]
           > idx[s]["truncate-4"]["integral"] / idx[s]["truncate-4"]["turns"]]
    ok1t = [s for s in mono
            if idx[s]["truncate-16"]["integral"] / idx[s]["truncate-16"]["turns"]
            > idx[s]["truncate-8"]["integral"] / idx[s]["truncate-8"]["turns"]
            > idx[s]["truncate-4"]["integral"] / idx[s]["truncate-4"]["turns"]]
    print("  [判据1 配对] b0>t16>t8>t4 逐 seed 成立: %d/20   （只在 truncate 三臂内部: %d/20）"
          % (len(ok1), len(ok1t)))

    okh = [s for s in idx if "ours" in idx[s] and "b0" in idx[s]
           and idx[s]["ours"]["integral"] / idx[s]["ours"]["turns"]
           < idx[s]["b0"]["integral"] / idx[s]["b0"]["turns"]]
    print("  [H3-① 配对] foot(ours)<foot(b0) 逐 seed 成立: %d/20" % len(okh))

    ok4 = [s for s in idx if "rollback" in idx[s] and "b0" in idx[s]
           and idx[s]["rollback"]["integral"] / idx[s]["rollback"]["turns"]
           < idx[s]["b0"]["integral"] / idx[s]["b0"]["turns"]]
    print("  [判据4 替代] foot(rollback)<foot(b0) 逐 seed 成立: %d/20" % len(ok4))

    print()
    print("=" * 76)
    print("3) H1 Fisher 精确检验（ours vs b0，N=20/臂）")
    print("=" * 76)
    o = sum(r["correct"] for r in by["ours"])
    b = sum(r["correct"] for r in by["b0"])
    p = fisher_2x2(o, 20 - o, b, 20 - b)
    print("  ours %d/20  vs  b0 %d/20   双侧 Fisher p = %.4f  -> H1 %s"
          % (o, b, p, "PASS" if (o > b and p < 0.05) else "FAIL"))
    print("  参照 4B E10 官方批：ours 11/20 vs b0 1/20  p = %.4f" % fisher_2x2(11, 9, 1, 19))


if __name__ == "__main__":
    main()
