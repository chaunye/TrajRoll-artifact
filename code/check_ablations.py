#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A1/A2 的实现自检门 —— 就是 A1A2_预注册.md §4 那 5 条的可执行版本。

只读 SUMMARY 文本：不改任何测量路径、不含任何新判据（阈值全部抄自预注册 §4）。

用法：  python check_ablations.py ablations_summary.txt
退出码：0 = 全过（可以往下解读正确率）；1 = 有不过的（先修实现，别解读）
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
    c = sum(r.get("correct", 0) for r in rs)
    return {"n": len(rs), "turns": t, "integral": i, "foot": (i / t if t else 0.0),
            "correct": c, "rate": (c / len(rs) if rs else 0.0)}


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "ablations_summary.txt"
    recs = parse(path)
    if not recs:
        print("[x] 没解析到 SUMMARY 行 —— 先看 ab_*.log 的尾部")
        return 2
    by = defaultdict(list)
    for r in recs:
        by[gkey(r)].append(r)
    A = {k: agg(v) for k, v in by.items()}

    print("读到 %d 条 SUMMARY，共 %d 组：" % (len(recs), len(A)))
    print("  %-14s %4s %8s %10s %10s %10s" % ("组", "N", "总轮数", "Σintegral", "每轮足迹", "正确率"))
    for k in sorted(A):
        a = A[k]
        print("  %-14s %4d %8d %10d %10.1f %6d/%-3d"
              % (k, a["n"], a["turns"], a["integral"], a["foot"], a["correct"], a["n"]))
    print()

    fails, skips = [], []

    def need(*keys):
        miss = [k for k in keys if k not in A]
        if miss:
            skips.append("缺组 " + ",".join(miss))
            return False
        return True

    def chk(name, ok, detail=""):
        print("  [%s] %s%s" % ("OK  " if ok else "FAIL", name, "" if ok else "   " + detail))
        if not ok:
            fails.append(name)

    print("=== 预注册 §4：实现自检（不过就不要解读正确率）===")

    if need("b0", "truncate-4", "truncate-8", "truncate-16"):
        seq = [A["b0"]["foot"], A["truncate-16"]["foot"], A["truncate-8"]["foot"], A["truncate-4"]["foot"]]
        chk("1 足迹严格单调 b0 > t16 > t8 > t4",
            all(seq[i] > seq[i + 1] for i in range(3)),
            "实测 %.0f > %.0f > %.0f > %.0f" % tuple(seq))
    else:
        print("  [SKIP] 1 足迹单调（本次没跑全 truncate 三档）")

    if need("b0", "label"):
        chk("2 foot(label) >= foot(b0)",
            A["label"]["foot"] >= A["b0"]["foot"],
            "label=%.1f b0=%.1f" % (A["label"]["foot"], A["b0"]["foot"]))
    else:
        print("  [SKIP] 2 label 是纯增量（没跑这个臂）")

    if need("ours", "rollback"):
        fo, fr = A["ours"]["foot"], A["rollback"]["foot"]
        d = abs(fo - fr) / fo if fo else 9.9
        chk("3 |foot(ours)-foot(rollback)|/foot(ours) <= 15%",
            d <= 0.15, "实测 %.1f%%（ours=%.1f rollback=%.1f）" % (100 * d, fo, fr))
    else:
        print("  [SKIP] 3 两个丢弃臂足迹接近")

    if need("b0", "rollback"):
        chk("4 Σintegral(rollback) < Σintegral(b0)",
            A["rollback"]["integral"] < A["b0"]["integral"],
            "rollback=%d b0=%d" % (A["rollback"]["integral"], A["b0"]["integral"]))
    else:
        print("  [SKIP] 4 丢弃确实省总量")

    bad = []
    for k, rs in by.items():
        wn = rs[0].get("wn", 0)
        if k.startswith("truncate"):
            if wn not in (4, 8, 16) or k != "truncate-%d" % wn:
                bad.append(k)
        elif wn != 0:
            bad.append(k)
    chk("5 wn 分组没错位", not bad, "异常组：%s" % bad)

    print()
    if fails:
        print("[x] 实现自检 **不通过**（%d 条）：%s" % (len(fails), fails))
        print("    -> 先查实现，别去解读正确率；也不要把这批数拿去改论文。")
        return 1
    print("[OK] 实现自检全过 —— 可以往下解读正确率（判据见 A1A2_预注册.md §5/§6）")
    if skips:
        print("     （跳过：%s）" % "；".join(skips))
    return 0


if __name__ == "__main__":
    sys.exit(main())
