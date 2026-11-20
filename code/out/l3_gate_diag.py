#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""L3 自检门三条 FAIL 的归因诊断（只读 SUMMARY，纯离线，不含任何新判据）。

四项：
  A 机制语义结构：rollback msgs 恒为 4 / ours < b0 / label ≈ b0 / t4 <= 8
  B 协议错误率：rejects, tools_fail, dup 分臂，8B vs 4B 同臂
  C 轮数分布：每臂 turns 逐 run（验证「路径不同长」解释）
  D H3 效率轴：prefill/turn 与 foot/turn，8B vs 4B

用法：python l3_gate_diag.py l3_qwen3_8b_summary.txt ablations_summary_N20.txt
"""
import re
import sys
from collections import defaultdict

FIELD = re.compile(r"(\w+)=(\S+)")
INTK = ("turns", "msgs", "integral", "prefill", "correct", "rejects", "tools_fail", "seed", "wn", "dup")


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


def agg(rs):
    t = sum(r.get("turns", 0) for r in rs)
    i = sum(r.get("integral", 0) for r in rs)
    pf = sum(r.get("prefill", 0) for r in rs)
    return {
        "n": len(rs),
        "turns": t,
        "integral": i,
        "prefill": pf,
        "foot": i / t if t else 0.0,
        "pft": pf / t if t else 0.0,
        "correct": sum(r.get("correct", 0) for r in rs),
        "rejects": sum(r.get("rejects", 0) for r in rs),
        "tools_fail": sum(r.get("tools_fail", 0) for r in rs),
        "dup": sum(r.get("dup", 0) for r in rs),
        "msgs_mean": sum(r.get("msgs", 0) for r in rs) / len(rs),
        "msgs_max": max(r.get("msgs", 0) for r in rs),
        "msgs_min": min(r.get("msgs", 0) for r in rs),
        "turns_runs": sorted(r.get("turns", 0) for r in rs),
    }


def load(path):
    by = defaultdict(list)
    for r in parse(path):
        by[gkey(r)].append(r)
    return {k: agg(v) for k, v in by.items()}, by


def hdr(title):
    print()
    print("=" * 78)
    print(title)
    print("=" * 78)


def main():
    p8 = sys.argv[1]
    p4 = sys.argv[2]
    A8, raw8 = load(p8)
    A4, raw4 = load(p4)
    order = ["b0", "ours", "rollback", "label", "truncate-4", "truncate-8", "truncate-16"]

    hdr("A 机制语义结构（msgs 分臂；8B vs 4B）")
    print("  %-14s %28s %28s" % ("臂", "8B msgs mean(min-max)", "4B msgs mean(min-max)"))
    for k in order:
        a, b = A8.get(k), A4.get(k)
        s8 = "%6.1f (%d-%d)" % (a["msgs_mean"], a["msgs_min"], a["msgs_max"]) if a else "-"
        s4 = "%6.1f (%d-%d)" % (b["msgs_mean"], b["msgs_min"], b["msgs_max"]) if b else "-"
        print("  %-14s %28s %28s" % (k, s8, s4))
    print()
    rb = A8.get("rollback")
    print("  [A1] 8B rollback msgs 恒为 4 : %s  (min=%s max=%s)"
          % ("PASS" if rb and rb["msgs_min"] == rb["msgs_max"] == 4 else "FAIL",
             rb["msgs_min"], rb["msgs_max"]))
    o, b0, lb, t4 = A8.get("ours"), A8.get("b0"), A8.get("label"), A8.get("truncate-4")
    print("  [A2] 8B ours msgs < b0      : %s  (ours=%.1f b0=%.1f)"
          % ("PASS" if o and b0 and o["msgs_mean"] < b0["msgs_mean"] else "FAIL",
             o["msgs_mean"], b0["msgs_mean"]))
    print("  [A3] 8B label msgs ≈ b0      : %s  (label=%.1f b0=%.1f  Δ=%.1f%%)"
          % ("PASS" if lb and b0 and abs(lb["msgs_mean"] - b0["msgs_mean"]) / b0["msgs_mean"] < 0.15 else "FAIL",
             lb["msgs_mean"], b0["msgs_mean"],
             100 * abs(lb["msgs_mean"] - b0["msgs_mean"]) / b0["msgs_mean"]))
    print("  [A4] 8B t4 msgs <= 8         : %s  (max=%s mean=%.1f)"
          % ("PASS" if t4 and t4["msgs_max"] <= 8 else "FAIL", t4["msgs_max"], t4["msgs_mean"]))

    hdr("B 协议错误率（每 100 轮）：8B vs 4B 同臂")
    print("  %-14s %26s %26s" % ("臂", "8B rej/fail/dup", "4B rej/fail/dup"))
    for k in order:
        a, b = A8.get(k), A4.get(k)
        def r(x):
            t = x["turns"] or 1
            return "%4.1f/%4.1f/%4.1f" % (100 * x["rejects"] / t, 100 * x["tools_fail"] / t, 100 * x["dup"] / t)
        print("  %-14s %26s %26s" % (k, r(a) if a else "-", r(b) if b else "-"))

    hdr("C 轮数分布（每 run 的 turns；总和决定 Σintegral 可比性）")
    print("  %-14s %8s %26s   %8s %26s" % ("臂", "8B Σturns", "8B turns 分布", "4B Σturns", "4B turns 分布"))
    for k in order:
        a, b = A8.get(k), A4.get(k)
        print("  %-14s %8d %26s   %8d %26s"
              % (k,
                 a["turns"] if a else 0, str(a["turns_runs"]) if a else "-",
                 b["turns"] if b else 0, str(b["turns_runs"]) if b else "-"))

    hdr("D 效率轴（H3 相关）：foot 与 prefill/turn，8B vs 4B")
    print("  %-14s %12s %12s %14s %14s" % ("臂", "8B foot", "4B foot", "8B prefill/轮", "4B prefill/轮"))
    for k in order:
        a, b = A8.get(k), A4.get(k)
        print("  %-14s %12.1f %12.1f %14.1f %14.1f"
              % (k,
                 a["foot"] if a else 0, b["foot"] if b else 0,
                 a["pft"] if a else 0, b["pft"] if b else 0))
    if A8.get("ours") and A8.get("truncate-4"):
        print()
        print("  H3-① foot(ours) < foot(b0)        : %.1f < %.1f  -> %s"
              % (A8["ours"]["foot"], A8["b0"]["foot"],
                 "PASS" if A8["ours"]["foot"] < A8["b0"]["foot"] else "FAIL"))
        print("  H3-② foot(ours) < foot(t4)        : %.1f < %.1f  -> %s"
              % (A8["ours"]["foot"], A8["truncate-4"]["foot"],
                 "PASS" if A8["ours"]["foot"] < A8["truncate-4"]["foot"] else "FAIL"))
        print("  H3-③ prefill/turn(t4) >= 2x ours : %.1f vs %.1f (%.2fx) -> %s"
              % (A8["truncate-4"]["pft"], A8["ours"]["pft"],
                 A8["truncate-4"]["pft"] / A8["ours"]["pft"],
                 "PASS" if A8["truncate-4"]["pft"] >= 2 * A8["ours"]["pft"] else "FAIL"))

    hdr("E 三条 FAIL 判据在两个批次下的前提对照")
    # 判据 1
    f = {k: A8[k]["foot"] for k in ["b0", "truncate-16", "truncate-8", "truncate-4"] if k in A8}
    ok1 = f["b0"] > f["truncate-16"] > f["truncate-8"] > f["truncate-4"]
    print("  [1] b0>t16>t8>t4 : 8B %s  顺序=%s   4B %s"
          % ("PASS" if ok1 else "FAIL", " > ".join("%.0f" % f[k] for k in ["b0", "truncate-16", "truncate-8", "truncate-4"]),
             "PASS" if A4["b0"]["foot"] > A4["truncate-16"]["foot"] > A4["truncate-8"]["foot"] > A4["truncate-4"]["foot"] else "FAIL"))
    print("       前提=各臂路径同长（b0 从不做成→跑满轮数→上下文膨胀）")
    print("       8B 实际 Σturns: b0=%d t16=%d t8=%d t4=%d  (4B: %d/%d/%d/%d)"
          % (A8["b0"]["turns"], A8["truncate-16"]["turns"], A8["truncate-8"]["turns"], A8["truncate-4"]["turns"],
             A4["b0"]["turns"], A4["truncate-16"]["turns"], A4["truncate-8"]["turns"], A4["truncate-4"]["turns"]))
    # 判据 2
    d2 = 100 * (A8["label"]["foot"] - A8["b0"]["foot"]) / A8["b0"]["foot"]
    d2_4 = 100 * (A4["label"]["foot"] - A4["b0"]["foot"]) / A4["b0"]["foot"]
    print("  [2] foot(label)>=foot(b0) : 8B Δ=%+.1f%% (%s)  4B Δ=%+.1f%% (%s)"
          % (d2, "PASS" if d2 >= 0 else "FAIL", d2_4, "PASS" if d2_4 >= 0 else "FAIL"))
    print("       前提=label ⊇ b0 同路径；8B label Σturns=%d vs b0 Σturns=%d"
          % (A8["label"]["turns"], A8["b0"]["turns"]))
    # 判据 4
    print("  [4] Σintegral(rollback)<b0 : 8B %d vs %d (%s)  4B %d vs %d (%s)"
          % (A8["rollback"]["integral"], A8["b0"]["integral"],
             "PASS" if A8["rollback"]["integral"] < A8["b0"]["integral"] else "FAIL",
             A4["rollback"]["integral"], A4["b0"]["integral"],
             "PASS" if A4["rollback"]["integral"] < A4["b0"]["integral"] else "FAIL"))
    print("       前提=两臂轮数相当；8B rollback 跑满 %d 轮(0 成功) 而 b0 %d 轮(%d 成功)"
          % (A8["rollback"]["turns"], A8["b0"]["turns"], A8["b0"]["correct"]))


if __name__ == "__main__":
    main()
