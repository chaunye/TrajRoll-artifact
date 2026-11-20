#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""c3_ttft_stats.py —— E14 TTFT 判读（只实现预注册 §3 冻结的 V1/V2/V3，不新增判据）。

背景：run_C3.sh 的 run() 把 run 级 TTFT_SUMMARY 落盘到 "${summary%.txt}_ttft.txt"，而
e14seq 阶段截断/统计的是 e14_ttft.txt —— 文件名错位导致首批误报「TTFT 0/60」。数据本体在
  * e14_ttft_summary_ttft.txt        阶段1 run 级（每运行一行 mean/p50/max）
  * ab_{ours,sysend}_t0_s*.log       阶段1 逐轮日志（"TTFT turn=.. prefill=.. ms=.." 行）
  * ab_truncate_n4_t0_s*.log
  * e14_ttft_4way.txt / ab_4w_*.log  阶段2（4 路并发）同上
（10-04 起 run_C3.sh 已改为统一落盘名，后续批次不会再错位。）

判据（week1/prereg/预注册_C类解禁三实验_2026-10-03.md §3，跑前冻结）：
  V1  三臂 TTFT 中位数排序 == 逐臂 recomputed-prefill 排序（预期 ours < sysend < truncate-4）
  V2  4-way 下 TTFT 绝对值上升，且排序保持（翻转照登）
  V3  Pearson r(TTFT, prefill) + Fisher z 95% CI + OLS 斜率（token↔时间标定桥）

用法：python week1/c3_ttft_stats.py [--dir week1/out/c3]
退出码：0 = 判读完成；1 = 数据缺失/行数不足（先修数据再解读，别硬判）。
"""
import argparse
import glob
import math
import os
import re
import sys

TURN_RE = re.compile(r"TTFT turn=(\d+) prefill=(\d+) ms=([\d.]+)")
SUM_RE = re.compile(r"^SUMMARY mode=(\S+)..*?prefill=(\d+)")
TTFT_SUM_RE = re.compile(r"^TTFT_SUMMARY mode=(\S+) n=(\d+) mean_ms=([\d.]+) "
                         r"p50_ms=([\d.]+) max_ms=([\d.]+)")

# 臂的规范名；TTFT_SUMMARY/SUMMARY 里的 mode=truncate 统一映射成 truncate-4
ARM_OF = {"ours": "ours", "sysend": "sysend", "truncate": "truncate-4"}
ARMS = ["ours", "sysend", "truncate-4"]

# 日志文件名 → 臂（run_C3.sh 的命名；阶段1 的 --truncate-n 4 写成 truncate_n4）
SEQ_GLOBS = [("ours", "ab_ours_t0_s*.log"),
             ("sysend", "ab_sysend_t0_s*.log"),
             ("truncate-4", "ab_truncate_n4_t0_s*.log")]
PAR_GLOBS = [("ours", "ab_4w_ours_s*.log"),
             ("sysend", "ab_4w_sysend_s*.log"),
             ("truncate-4", "ab_4w_truncaten4_s*.log")]

SEQ_TTFT = "e14_ttft_summary_ttft.txt"      # 首批的落盘名（run_C3.sh 10-04 修正后同名）
SEQ_SUM = "e14_ttft_summary.txt"
PAR_TTFT = "e14_ttft_4way.txt"
PAR_SUM = "e14_ttft_4way_summary.txt"


def read_lines(path):
    with open(path, encoding="utf-8") as f:
        return [ln.rstrip("\n") for ln in f]


def parse_summary_prefill(path):
    """SUMMARY 行 → 臂 → [每次运行的 recomputed-prefill 总量]。"""
    per = {}
    for ln in read_lines(path):
        m = SUM_RE.match(ln)
        if m:
            per.setdefault(ARM_OF.get(m.group(1), m.group(1)), []).append(int(m.group(2)))
    return per


def parse_ttft_summary(path):
    """run 级 TTFT_SUMMARY → 臂 → [(n, mean_ms, p50_ms, max_ms), ...]。"""
    per = {}
    for ln in read_lines(path):
        m = TTFT_SUM_RE.match(ln)
        if m:
            per.setdefault(ARM_OF.get(m.group(1), m.group(1)), []).append(
                dict(n=int(m.group(2)), mean=float(m.group(3)),
                     p50=float(m.group(4)), mx=float(m.group(5))))
    return per


def parse_turns(dirpath, pattern):
    """逐轮 (prefill, ttft_ms) 对 —— 来自 ab_*.log 里的 'TTFT turn=' 行。"""
    pairs = []
    for fp in sorted(glob.glob(os.path.join(dirpath, pattern))):
        for ln in read_lines(fp):
            m = TURN_RE.search(ln)
            if m:
                pairs.append((int(m.group(2)), float(m.group(3))))
    return pairs


def median(xs):
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else 0.5 * (s[n // 2 - 1] + s[n // 2])


def pearson(xs, ys):
    """r + Fisher z 95% CI + OLS 斜率/截距。"""
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    r = sxy / math.sqrt(sxx * syy)
    z = 0.5 * math.log((1 + r) / (1 - r))
    se = 1.0 / math.sqrt(n - 3)
    lo, hi = math.tanh(z - 1.96 * se), math.tanh(z + 1.96 * se)
    slope = sxy / sxx
    return r, lo, hi, slope, my - slope * mx, n


def order_str(per_med):
    return " < ".join(sorted(ARMS, key=lambda k: per_med[k]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                  "out", "c3"))
    a = ap.parse_args()
    d = a.dir
    problems = []

    def need(path, cond, msg):
        if not cond:
            problems.append("%s：%s" % (path, msg))

    for fn in (SEQ_TTFT, SEQ_SUM, PAR_TTFT, PAR_SUM):
        need(fn, os.path.isfile(os.path.join(d, fn)), "缺文件（先拷回）")

    seq_run = parse_ttft_summary(os.path.join(d, SEQ_TTFT)) if not problems else {}
    par_run = parse_ttft_summary(os.path.join(d, PAR_TTFT)) if not problems else {}
    seq_pf = parse_summary_prefill(os.path.join(d, SEQ_SUM)) if not problems else {}
    for arm in ARMS:
        need(SEQ_TTFT, len(seq_run.get(arm, [])) >= 20, "run 级 TTFT 只有 %d/20"
             % len(seq_run.get(arm, [])))
        need(PAR_TTFT, len(par_run.get(arm, [])) >= 20, "run 级 TTFT 只有 %d/20"
             % len(par_run.get(arm, [])))
        need(SEQ_SUM, len(seq_pf.get(arm, [])) >= 20, "SUMMARY 只有 %d/20"
             % len(seq_pf.get(arm, [])))
    if problems:
        for p in problems:
            print("[!] " + p)
        return 1

    seq_turns = {arm: parse_turns(d, pat) for arm, pat in SEQ_GLOBS}
    par_turns = {arm: parse_turns(d, pat) for arm, pat in PAR_GLOBS}
    for phase, tt in (("阶段1", seq_turns), ("阶段2", par_turns)):
        for arm in ARMS:
            need("ab_*.log(%s %s)" % (phase, arm), len(tt[arm]) > 0,
                 "逐轮 TTFT 行 0 条 —— 日志没拷回？")

    print("=== E14 TTFT 判读（判据 = 预注册 §3，冻结）===")
    print()
    print("--- 数据完整性 ---")
    for arm in ARMS:
        nrun = len(seq_run[arm])
        nturn = sum(r["n"] for r in seq_run[arm])
        print("  阶段1 %-11s run级 %2d/20，逐轮 TTFT 行 %4d（run级合计 %4d）"
              % (arm, nrun, len(seq_turns[arm]), nturn))
        if nturn and len(seq_turns[arm]) != nturn:
            print("      [!] 逐轮行数(%d) ≠ run级 n 合计(%d) —— 有日志缺行，先查"
                  % (len(seq_turns[arm]), nturn))
    print()

    # ---- V1：TTFT 中位数排序 vs recomputed-prefill 排序 ----
    print("--- V1 单流：TTFT 中位数排序 vs 重算 prefill 排序（预期 ours < sysend < truncate-4）---")
    seq_med, pf_mean, run_p50 = {}, {}, {}
    for arm in ARMS:
        seq_med[arm] = median([t for _, t in seq_turns[arm]])
        pf_mean[arm] = sum(seq_pf[arm]) / len(seq_pf[arm])
        run_p50[arm] = median([r["p50"] for r in seq_run[arm]])
    print("  臂            逐轮TTFT中位  run级p50中位  重算prefill均值")
    for arm in ARMS:
        print("  %-11s  %10.1f ms  %11.1f  %12.0f" % (arm, seq_med[arm], run_p50[arm], pf_mean[arm]))
    o_t, o_p = order_str(seq_med), order_str(pf_mean)
    print("  TTFT 排序    = %s" % o_t)
    print("  prefill 排序 = %s" % o_p)
    print("  V1 判定：%s" % ("✓ 两轴排序一致" if o_t == o_p else "✗ 排序不一致 —— 照登，不解释成支持"))
    print()

    # ---- V2：4-way 并发 ----
    print("--- V2 4 路并发：绝对值上升 + 排序保持 ---")
    par_med = {arm: median([t for _, t in par_turns[arm]]) for arm in ARMS}
    for arm in ARMS:
        print("  %-11s  单流 %8.1f ms → 4way %8.1f ms （×%.2f）"
              % (arm, seq_med[arm], par_med[arm],
                 (par_med[arm] / seq_med[arm]) if seq_med[arm] else float("nan")))
    rises = all(par_med[a] > seq_med[a] for a in ARMS)
    o_par = order_str(par_med)
    print("  4way 排序 = %s" % o_par)
    v2 = []
    v2.append("绝对值上升 ✓" if rises else "绝对值未全升 ✗")
    v2.append("排序保持 ✓" if o_par == o_t else "排序翻转 ✗（照登：并发下前缀缓存失效的诚实发现）")
    print("  V2 判定：%s；%s" % tuple(v2))
    print()

    # ---- V3：Pearson r(TTFT, prefill) + 斜率（token↔时间桥）----
    print("--- V3 token↔时间桥（阶段1 逐轮，prefill 为重算 token 数）---")
    pooled = [p for arm in ARMS for p in seq_turns[arm]]
    for name, tt in (("合并(3臂)", pooled),
                     ("仅ours", seq_turns["ours"]),
                     ("仅sysend", seq_turns["sysend"]),
                     ("仅truncate-4", seq_turns["truncate-4"])):
        xs = [p[0] for p in tt]
        ys = [p[1] for p in tt]
        r, lo, hi, slope, icept, n = pearson(xs, ys)
        print("  %-12s n=%4d  r=%.3f  95%%CI [%.3f, %.3f]  斜率 %.4f ms/tok（截距 %.1f ms）"
              % (name, n, r, lo, hi, slope, icept))
    print()
    print(">>> 判读判据只有 V1/V2/V3 三条（预注册 §3）；本脚本只出数，档位判定写 week1/results/C类解禁_结果_判读.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
