#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A6（规划.md）：任务级 1.60x 的 instance 级 cluster bootstrap 95% CI —— 本地、无 GPU。

口径写死（与 实验报告.md §E9-3 逐位一致，别改）：
    peak_r = max_k ( prefix_r + sum_{j<=k} turn_j.tok )
    点估计 = median(peak | target=False) / median(peak | target=True)   # E9 报的 1.60x

为什么必须按 instance：6,914 条轨迹只对应 348 个 instance（平均 20 rollout/instance），
同 instance 的轨迹共享 issue 与初始 repo 状态，不是独立样本 —— 按轨迹重采样会把 CI 假性收窄。
本脚本把「按轨迹」的结果并排打出来，正好当答辩证据。

bootstrap（percentile 法）：
    对 348 个 instance 有放回抽 348 个 → 把抽中 instance 的**全部轨迹**（重复抽中就重复计入）
    拼成伪样本 → 重算三对比值；reps=5000、seed=20260927；2.5%/97.5% 分位 = 95% CI。

用法：
    python week1/e9_bootstrap.py                 # 默认 shard 0 + swe-agent-llama-70b（E9 口径）
    python week1/e9_bootstrap.py --reps 20000
输出：week1/out/e9_bootstrap.txt
"""
import argparse
import glob
import os
import random
import statistics as st
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import analyze_swe_traces as A          # noqa: E402  （复用冻结的账本口径）

if hasattr(sys.stdout, "reconfigure"):   # Windows 控制台默认 GBK，希腊字母会炸
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SHARD = 0
MODEL = "swe-agent-llama-70b"
REPS = 5000
SEED = 20260927
NAMES = ("峰值中位比", "轮数均值比", "Σcontext均值比")


def load(shard=SHARD, model=MODEL, data=None):
    root = A.find_root(data)
    paths = sorted(glob.glob(os.path.join(root, "**", "*.arrow"), recursive=True))
    if not paths:
        sys.exit("[FATAL] %s 下没有 *.arrow" % root)
    rows, _, _ = A.analyze(paths[shard], 0, model)
    return root, len(paths), rows


def sess_stats(rows):
    out = []
    for r in rows:
        cb = r["prefix"]
        pk = cb
        B = T = 0
        for t in r["turns"]:
            B += cb
            T += 1
            cb += t["tok"]
            pk = max(pk, cb)
        out.append({"inst": r["inst"], "ok": r["target"], "peak": pk, "sum": B, "turns": T})
    return out


def ratio3(S):
    f = [s for s in S if not s["ok"]]
    t = [s for s in S if s["ok"]]
    if not f or not t:
        return None
    return (st.median([s["peak"] for s in f]) / st.median([s["peak"] for s in t]),
            (sum(s["turns"] for s in f) / len(f)) / (sum(s["turns"] for s in t) / len(t)),
            (sum(s["sum"] for s in f) / len(f)) / (sum(s["sum"] for s in t) / len(t)))


def boot(S, reps, seed, cluster):
    """cluster=True 按 instance 重采样（正解）；False 按轨迹重采样（对照，错误做法）。"""
    rng = random.Random(seed)
    acc = ([], [], [])
    if cluster:
        by = {}
        for s in S:
            by.setdefault(s["inst"], []).append(s)
        keys = sorted(by)
        n = len(keys)
        for _ in range(reps):
            buf = []
            for _ in range(n):
                buf.extend(by[keys[rng.randrange(n)]])
            r = ratio3(buf)
            if r:
                for i in range(3):
                    acc[i].append(r[i])
    else:
        n = len(S)
        for _ in range(reps):
            r = ratio3([S[rng.randrange(n)] for _ in range(n)])
            if r:
                for i in range(3):
                    acc[i].append(r[i])
    return acc


def pct(v, q):
    s = sorted(v)
    if not s:
        return float("nan")
    i = q / 100.0 * (len(s) - 1)
    lo = int(i)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (i - lo)


def fmt(x, d=3):
    return ("%." + str(d) + "f") % x


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=None)
    ap.add_argument("--shard", type=int, default=SHARD)
    ap.add_argument("--reps", type=int, default=REPS)
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                  "out", "e9_bootstrap.txt"))
    a = ap.parse_args()

    t0 = time.time()
    root, nshards, rows = load(a.shard, MODEL, a.data)
    S = sess_stats(rows)
    nF = sum(1 for s in S if not s["ok"])
    nT = len(S) - nF
    ninst = len(set(s["inst"] for s in S))
    turns = sum(s["turns"] for s in S)
    pt = ratio3(S)
    if pt is None:
        sys.exit("[FATAL] 某一侧 target 组为空，算不了比值")
    tload = time.time() - t0

    L = []
    L.append("=== A6：任务级 1.60x 的 instance 级 cluster bootstrap 95% CI ===")
    L.append("生成 %s | 脚本 week1/e9_bootstrap.py | 本地、无 GPU、未改任何冻结文件"
             % time.strftime("%Y-%m-%d %H:%M:%S"))
    L.append("数据 root   : %s（%d 个分片，本脚本只用 shard %d）" % (root, nshards, a.shard))
    L.append("口径        : model_name == %s（与 实验报告.md §E9 完全一致）" % MODEL)
    L.append("会话        : %d 条（未解出 %d / 已解出 %d）  轮 %d  instance %d"
             % (len(S), nF, nT, turns, ninst))
    L.append("读取耗时    : %.1f s" % tload)
    L.append("公式        : peak_r = max_k(prefix + sum_{j<=k} turn_j.tok)；")
    L.append("              比值 = median(peak|target=F) / median(peak|target=T)")
    L.append("")
    L.append("--- 点估计（应与 实验报告.md §E9-3 表逐位一致）---")
    L.append("%-16s %14s %14s %10s" % ("", "未解出 F", "已解出 T", "比值"))
    f = [s for s in S if not s["ok"]]
    t = [s for s in S if s["ok"]]
    L.append("%-16s %14d %14d %10s" % ("会话", len(f), len(t), "—"))
    L.append("%-16s %14.1f %14.1f %9.2fx   （E9 报 1.91x）"
             % ("轮数 均值", sum(s["turns"] for s in f) / len(f),
                sum(s["turns"] for s in t) / len(t), pt[1]))
    L.append("%-16s %14s %14s %9.2fx   ← 论文口径（E9 报 1.60x）"
             % ("峰值上下文 中位", "{:,}".format(int(st.median([s["peak"] for s in f]))),
                "{:,}".format(int(st.median([s["peak"] for s in t]))), pt[0]))
    L.append("%-16s %14s %14s %9.2fx   （含轮数差，别单报；E9 报 3.09x）"
             % ("Σcontext 均值", "{:,.0f}".format(sum(s["sum"] for s in f) / len(f)),
                "{:,.0f}".format(sum(s["sum"] for s in t) / len(t)), pt[2]))
    L.append("")
    L.append("--- 显示精度说明（与 实验报告 §E9-3 / 论文 §5.5 的对照，别当成数字打架）---")
    med_f = st.median([s["peak"] for s in f])
    med_t = st.median([s["peak"] for s in t])
    L.append("  峰值中位比原始值 = %d / %d = %.4f  → 报告/论文写 1.60x 是取 2 位有效数字；"
             % (med_f, med_t, med_f / med_t))
    L.append("  若按 2 位小数写应是 1.59x。同一数值，显示位数不同（本脚本没改报告的数）。")
    tmf = sum(s["turns"] for s in f) / len(f)
    tmt = sum(s["turns"] for s in t) / len(t)
    L.append("  轮数均值比 = %.1f / %.1f = %.4f ；报告 1.91x 是用已显示的 %.1f/%.1f 再除 = %.4f"
             % (tmf, tmt, tmf / tmt, round(tmf, 1), round(tmt, 1),
                round(tmf, 1) / round(tmt, 1)))
    L.append("")
    L.append("--- cluster bootstrap：按 %d 个 instance 有放回重采样（正解）---" % ninst)
    L.append("reps = %d   seed = %d   percentile 法" % (a.reps, a.seed))
    t1 = time.time()
    acc = boot(S, a.reps, a.seed, cluster=True)
    L.append("耗时 %.1f s" % (time.time() - t1))
    L.append("")
    L.append("%-14s %8s %28s %10s %10s" % ("", "点估计", "95% CI", "bootstrap中位", "P(>1)"))
    for i, nm in enumerate(NAMES):
        v = acc[i]
        lo, hi = pct(v, 2.5), pct(v, 97.5)
        pgt = sum(1 for x in v if x > 1.0) / len(v)
        L.append("%-14s %7.3fx  [%7.3fx , %7.3fx]   %8.3fx  %9.1f%%"
                 % (nm, pt[i], lo, hi, pct(v, 50), 100.0 * pgt))
        if i == 0:
            L.append("%-14s 95%% CI = [%.2fx, %.2fx]  ← 论文要报的就是这行"
                     % ("", lo, hi))
    L.append("")
    L.append("--- 对照：按 %d 条**轨迹**重采样（错误做法：忽略聚类，CI 假性变窄）---" % len(S))
    acc2 = boot(S, a.reps, a.seed + 1, cluster=False)
    for i, nm in enumerate(NAMES[:1]):
        lo, hi = pct(acc2[i], 2.5), pct(acc2[i], 97.5)
        L.append("%-14s 95%% CI = [%7.3fx, %7.3fx]   宽度比 = %.2f（>1 说明按轨迹确实偏窄）"
                 % (nm, lo, hi,
                    (pct(acc[i], 97.5) - pct(acc[i], 2.5)) / max(1e-9, hi - lo)))
    L.append("")
    lo0, hi0 = pct(acc[0], 2.5), pct(acc[0], 97.5)
    L.append("--- 结论（按 CI 位置判，别手改）---")
    if lo0 > 1.0:
        L.append("1. 峰值中位比 95%% CI [%.2fx, %.2fx] 下界 > 1 —— 未解出会话的峰值上下文显著"
                 % (lo0, hi0))
        L.append("   高于已解出；论文发现④的 1.8x 在真实轨迹上仍同号（本数据 %.3fx 同量级）。"
                 % pt[0])
    else:
        L.append("1. 峰值中位比 95%% CI [%.2fx, %.2fx] 下界 ≤ 1 —— 该口径在 instance 级聚类下"
                 % (lo0, hi0))
        L.append("   未过显著性：论文只能报点估计 + 区间，并把这条写进限制（不许只报点估计）。")
    L.append("2. 按 instance 聚类是必须的：按轨迹重采样的 CI 宽度只有它的 1/%.2f（假性变窄）。"
             % ((pct(acc[0], 97.5) - pct(acc[0], 2.5))
                / max(1e-9, pct(acc2[0], 97.5) - pct(acc2[0], 2.5))))
    L.append("3. 本脚本只读 shard %d 的 arrow + 冻结账本 analyze_swe_traces.py，未重跑任何 GPU 批次。" % a.shard)
    L.append("")
    txt = "\n".join(L) + "\n"
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    open(a.out, "w", encoding="utf-8").write(txt)
    print(txt)
    print("[OK] 写出 %s" % a.out)


if __name__ == "__main__":
    main()
