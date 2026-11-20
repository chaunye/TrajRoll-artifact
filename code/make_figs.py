#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""make_figs.py —— 生成论文用的图（英文标签，投稿版）

用法:  python week1/make_figs.py
输出:  paper/figs/fig1..fig5.png   （fig4 不在正文里，只在补充材料）

★★ 2026-09-19 重写要点：**按最终版面尺寸画图，不再"画大图再缩排"** ★★
  实测版面（IEEEtran conference / letter，见 week1/tools/_measure.sh）：
      columnwidth = 252.0pt = 3.50in   	extwidth = 516.0pt = 7.17in
      单栏图 0.84linewidth = 211.7pt = 2.94in；双栏图 	extwidth = 7.17in
  旧版按 6.4~7.4in 的画布作画、再排进 2.94in 的单栏 → 缩放只剩 40~46%，
  9pt 的标签落到纸面上约 **4pt**（几乎不可读）。现在画布宽度 = 版面宽度，
  缩放 ≈ 1.00，所以 rcParams 里的字号**就是**纸面上的字号：
      正文 8pt / 刻度 7.5pt / 小注 7.5pt / 标题 8.5pt
  随之而来的约束：版面变窄了，能放的字变少 —— 所以标签一律用短名，
  细节留给正文的表和图注（数字都还在表里，没有丢）。

数据来源（全部在仓库内，可复核）:
  fig1 / fig3 : E10 正式批 -> week1/out/ablations_summary_N20.txt（现算，非手抄）
  fig4        : E11 实测   -> 常量，来源 week1/results/E11_结果.md
  fig2        : E7-b / E9  -> 常量，来源 实验报告.md 的剂量-反应表
  fig5        : 示意图（b0 vs ours 的上下文对比）
"""
import math
import os
import re
from collections import defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "paper", "figs")
os.makedirs(OUT, exist_ok=True)

C_OURS = "#1b6ca8"
C_BASE = "#b0b0b0"
C_BAD = "#c0392b"
C_MID = "#e08a1e"

W1 = 2.90          # 单栏图宽度（in）。版面 2.94in -> 缩放 0.99，字号几乎不变

plt.rcParams.update({
    "font.size": 8,
    "font.family": "serif",
    "font.serif": ["Times New Roman", "Nimbus Roman", "STIXGeneral", "DejaVu Serif"],
    "mathtext.fontset": "stix",
    "axes.titlesize": 8.5,
    "axes.labelsize": 8,
    "xtick.labelsize": 7.5,
    "ytick.labelsize": 7.5,
    "legend.fontsize": 7.5,
    "axes.grid": True,
    "grid.alpha": 0.25,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "figure.dpi": 200,
    "savefig.bbox": "tight",
    "pdf.fonttype": 42,
})

# fig5 里每个 (矩形, 文字) 都登记下来，供 audit 检查"文字有没有溢出色块"
CELLS = []


def wilson(k, n, z=1.96):
    if n <= 0:
        return 0.0, 1.0
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


def parse_summary(path):
    recs = []
    for ln in open(path, encoding="utf-8"):
        if not ln.startswith("SUMMARY"):
            continue
        d = dict(re.findall(r"(\w+)=(\S+)", ln))
        if "mode" not in d:
            continue
        recs.append(d)
    return recs


def agg(recs):
    by = defaultdict(list)
    for r in recs:
        key = r["mode"] + ("-" + r["wn"] if int(r.get("wn", 0)) else "")
        by[key].append(r)
    out = {}
    for k, rs in by.items():
        t = sum(int(r["turns"]) for r in rs)
        i = sum(int(r["integral"]) for r in rs)
        p = sum(int(r["prefill"]) for r in rs)
        c = sum(int(r["correct"]) for r in rs)
        n = len(rs)
        out[k] = dict(n=n, correct=c, rate=c / n,
                      turns=t / n, integral=i / n, foot=i / t,
                      prefill=p / n, prefill_per_turn=p / t,
                      ci=wilson(c, n))
    return out


SUMMARY = os.path.join(ROOT, "week1", "out", "ablations_summary_N20.txt")
A = agg(parse_summary(SUMMARY))

ORDER = ["b0", "label", "rollback", "ours", "truncate-4", "truncate-8", "truncate-16"]
SHORT = {"b0": "b0", "label": "label", "rollback": "rollback", "ours": "OURS",
         "truncate-4": "w4", "truncate-8": "w8", "truncate-16": "w16"}
# 点很挤（ours/label/rollback 都在 x<800），标签偏移逐个手调 + audit 把关
OFF = {"b0": (-6, 2), "label": (-6, 4), "rollback": (-6, 6), "ours": (5, 5),
       "truncate-4": (4, 5), "truncate-8": (4, -11), "truncate-16": (-4, 5)}


def fig1_pareto():
    """成功率 vs 每轮足迹（E10 七臂）。"""
    fig, ax = plt.subplots(figsize=(W1, 1.80), layout="constrained")
    for k in ORDER:
        a = A[k]
        c = C_OURS if k == "ours" else (C_BASE if k in ("b0", "label") else C_MID)
        if k == "rollback":
            c = C_BAD
        ax.errorbar(a["foot"], 100 * a["rate"],
                    yerr=[[100 * (a["rate"] - a["ci"][0])], [100 * (a["ci"][1] - a["rate"])]],
                    fmt="o", ms=4, color=c, ecolor=c, elinewidth=1.0, capsize=2, zorder=3)
        dx, dy = OFF[k]
        ax.annotate(SHORT[k], (a["foot"], 100 * a["rate"]), textcoords="offset points",
                    xytext=(dx, dy), fontsize=7.5, color=c, zorder=4,
                    ha="left" if dx > 0 else "right", weight="bold" if k == "ours" else "normal")
    ax.set_xlabel("per-turn context footprint (tokens)")
    ax.set_ylabel("success rate (%)")
    ax.set_title("Success vs. footprint (E10, N=20/arm)")
    ax.set_ylim(-8, 82)
    ax.set_xlim(100, 3250)
    return fig, [ax]


def fig3_ablation():
    """2×2 消融（上）+ 两个边际效应（下），竖排以适应单栏。"""
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(W1, 3.40), layout="constrained")
    cells = [("b0", "neither"), ("label", "tomb\nonly"),
             ("rollback", "discard\nonly"), ("ours", "discard+\ntomb")]
    xs = list(range(len(cells)))
    vals = [100 * A[k]["rate"] for k, _ in cells]
    errs = [[100 * (A[k]["rate"] - A[k]["ci"][0]) for k, _ in cells],
            [100 * (A[k]["ci"][1] - A[k]["rate"]) for k, _ in cells]]
    cols = [C_BASE, C_MID, C_BAD, C_OURS]
    ax1.bar(xs, vals, yerr=errs, capsize=2, color=cols, edgecolor="black", linewidth=0.5)
    for x, (k, _) in zip(xs, cells):
        a = A[k]
        ax1.text(x, 100 * a["rate"] + 4, "%d/%d" % (a["correct"], a["n"]),
                 ha="center", fontsize=7.5)
    ax1.set_xticks(xs)
    ax1.set_xticklabels([lab for _, lab in cells], fontsize=7.5)
    ax1.set_ylabel("success rate (%)")
    ax1.set_ylim(0, 92)
    ax1.set_title("2x2 ablation (Wilson 95% CI)")

    fm = [("tombstone\n(on vs off)", 100 * (14 / 40 - 1 / 40), 0.00029, C_OURS),
          ("discard\n(on vs off)", 100 * (11 / 40 - 4 / 40), 0.083, C_BAD)]
    ys = [0, 1]
    ax2.barh(ys, [d for _, d, _, _ in fm], color=[c for *_, c in fm],
             edgecolor="black", linewidth=0.5)
    for y, (lab, d, p, _) in zip(ys, fm):
        ax2.text(d + 2, y, "+%.1f pp\np=%.4f" % (d, p), va="center", fontsize=7.5)
    ax2.set_yticks(ys)
    ax2.set_yticklabels([lab for lab, _, _, _ in fm], fontsize=7.5)
    ax2.set_xlabel("difference in success rate (pp)")
    ax2.set_xlim(0, 62)
    ax2.grid(axis="y", alpha=0)
    ax2.set_title("marginal effects")
    return fig, [ax1, ax2]


def fig4_placement():
    """E11 放置税（不在正文，只在补充材料）。"""
    E11 = [("ours", 67.5, 1.00, "no tax"),
           ("sys-end", 125.2, 1.85, "per upd."),
           ("sys-start", 187.4, 2.78, "per upd."),
           ("window-4", 347.0, 5.30, "every turn")]
    fig, ax = plt.subplots(figsize=(W1, 3.30), layout="constrained")
    xs = list(range(len(E11)))
    cols = [C_OURS, C_MID, "#c9803a", C_BAD]
    ax.bar(xs, [e[1] for e in E11], color=cols, edgecolor="black", linewidth=0.5)
    for x, e in zip(xs, E11):
        ax.text(x, e[1] + 10, "%.0f tok\n%.2fx" % (e[1], e[2]), ha="center", fontsize=7.5)
        ax.text(x, 14, e[3], ha="center", fontsize=7.5, color="white", weight="bold")
    ax.set_xticks(xs)
    ax.set_xticklabels([e[0] for e in E11], fontsize=7.5)
    ax.set_ylabel("recomputed prefill per turn (tokens)")
    ax.set_ylim(0, 450)
    ax.set_title("What recovery costs, by design")
    return fig, [ax]


def fig2_dose():
    """剂量-反应：CacheWise（上）+ SWE-agent 三档（下），竖排。"""
    cw_lab = ["0-2", "2-5", "5-10", "10-20", "20-35"]
    cw_x = [1, 3.5, 7.5, 15, 27]
    cw_y = [0.00, 3.44, 10.72, 10.86, 16.93]
    sw_lab = ["0-5", "5-10", "10-20", "20-35", "35-50", "50-80", "80-100"]
    sw_x = [2.5, 7.5, 15, 27.5, 42.5, 65, 90]
    sw_t1 = [1.46, 4.49, 6.80, 13.91, 21.02, 37.31, 57.32]
    sw_t2 = [1.61, 4.78, 7.22, 13.50, 22.18, 34.90, 49.35]
    sw_t3 = [1.96, 4.73, 6.23, 11.89, 20.54, 35.70, 50.51]

    fig, (a1, a2) = plt.subplots(2, 1, figsize=(W1, 3.80), layout="constrained")
    a1.plot(cw_x, cw_y, "o-", color=C_OURS, ms=4, lw=1.0)
    for x, y in zip(cw_x, cw_y):
        a1.annotate("%.1f" % y, (x, y), textcoords="offset points", xytext=(0, 5),
                    fontsize=7.5, ha="center", color=C_OURS)
    a1.set_xticks(cw_x)
    a1.set_xticklabels(cw_lab, fontsize=7.5)
    a1.set_xlabel("failure-rate stratum (%)")
    a1.set_ylabel("context saved (%)")
    a1.set_ylim(-3, 22)
    a1.set_title("CacheWise: 80 real Claude Code sessions")

    for series, lab, col in ((sw_t1, "T1 conserv.", C_OURS),
                             (sw_t2, "T2 medium", C_MID),
                             (sw_t3, "T3 aggr.", C_BAD)):
        a2.plot(sw_x, series, "o-", label=lab, color=col, ms=3.5, lw=1.0)
    a2.set_xticks(sw_x)
    a2.set_xticklabels(sw_lab, fontsize=7, rotation=45, ha="right", rotation_mode="anchor")
    a2.set_xlabel("failure-rate stratum (%)")
    a2.set_ylabel("context saved (%)")
    a2.legend(loc="upper left", fontsize=7.5)
    a2.set_title("SWE-agent: 6,914 real trajectories")
    return fig, [a1, a2]


def fig5_schematic():
    """b0 vs ours 的上下文对比（单栏紧凑版）。"""
    fig, ax = plt.subplots(figsize=(W1, 1.55), layout="constrained")
    ax.axis("off")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)

    X0, W, GAP, H = 0.13, 0.27, 0.012, 0.28
    Y_B, Y_O = 0.60, 0.12

    def cell(i, y, text, fc, ec="black", ls="-", tc="black", fs=7.5):
        x = X0 + i * (W + GAP)
        r = Rectangle((x, y), W, H, facecolor=fc, edgecolor=ec, linewidth=0.8, linestyle=ls)
        ax.add_patch(r)
        t = ax.text(x + W / 2, y + H / 2, text, ha="center", va="center",
                    fontsize=fs, color=tc)
        CELLS.append((r, t))
        return x

    row_b = [("prefix:\nsys + task\n+ OK turns", "#dfe9f3"),
             ("FAIL turn\n+ 3,000-char\nlog STAYS", "#f6d5d0"),
             ("re-read on\nevery turn", "white")]
    row_o = [("prefix:\nbyte-identical\n(always hits)", "#dfe9f3"),
             ("FAIL turn\ndiscarded", "white"),
             ("tombstone\n~40 tokens", "#dff0e0")]
    xb = [cell(i, Y_B, t, c) for i, (t, c) in enumerate(row_b)]
    xo = [cell(i, Y_O, t, c) for i, (t, c) in enumerate(row_o)]
    # b0 的失败格与 ours 的墓碑格加边框强调
    for i, col in ((1, C_BAD), (2, C_BAD)):
        ax.add_patch(Rectangle((xb[i], Y_B), W, H, facecolor="none",
                               edgecolor=col, linewidth=1.4, linestyle="--"))
    ax.add_patch(Rectangle((xo[2], Y_O), W, H, facecolor="none",
                           edgecolor="#2e7d32", linewidth=1.4))
    ax.text(0.005, Y_B + H / 2, "b0", fontsize=8, weight="bold", ha="left", va="center")
    ax.text(0.005, Y_O + H / 2, "ours", fontsize=8, weight="bold", ha="left", va="center")
    ax.text(X0, Y_B + H + 0.07, "failed turn stays in the prefix", fontsize=7.5, color=C_BAD)
    ax.text(X0, Y_O + H + 0.07, "failed turn discarded; one line survives",
            fontsize=7.5, color=C_OURS)
    return fig, [ax]


def fig6_overview():
    """方法总览（§3 用）：带分叉与回边的控制流 + 结果前缀条。

    2026-10-04 重画：旧版五框纯线性箭头，看不出 success/failure 分叉、看不出
    回滚回边，读不出 loop。新版：①checkpoint → ②speculative turn → 菱形 oracle
    判定；progress 沿右侧绿边保留分支回到 ①；no progress 走 ③丢弃(红) →
    ④追加墓碑(绿)，沿左侧蓝边"prefix extended"回到 ①；底部前缀条给出每次
    重入 prompt 的实际构成与 cache-hit 结果。画布按 ISPA 纸面宽 2.80in
    (0.80*252pt) 作画，名义字号=纸面字号（全部 >=7.5pt，fig_audit 达标线）。
    """
    from matplotlib.patches import FancyArrowPatch, Polygon
    W6 = 2.80
    # 示意图不走布局引擎：constrained 会因贴边元素把轴挤塌（2026-10-04 实测），
    # 直接全幅轴 + clip_on=False，tight bbox 自动裁到内容。
    fig = plt.figure(figsize=(W6, 3.40))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.axis("off")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)

    LX, RX = 0.10, 0.68
    CX = (LX + RX) / 2
    BW = RX - LX
    BH = 0.095
    y_cp, y_exe = 0.875, 0.700
    y_dec, dhh, dhw = 0.605, 0.075, 0.17
    y_dis, y_tom = 0.370, 0.195
    SY, SH = 0.030, 0.085
    C_GREEN = "#2e7d32"

    def box(y, text, fc):
        r = Rectangle((LX, y), BW, BH, facecolor=fc, edgecolor="black", linewidth=0.8)
        ax.add_patch(r)
        t = ax.text(CX, y + BH / 2, text, ha="center", va="center", fontsize=7.8)
        CELLS.append((r, t))

    box(y_cp, "\u2460 Checkpoint C:\ncopy of the message list", "#dfe9f3")
    box(y_exe, "\u2461 Speculative turn\n(model + tools, appended as usual)", "#dfe9f3")
    ax.add_patch(Polygon([(CX - dhw, y_dec), (CX, y_dec + dhh), (CX + dhw, y_dec), (CX, y_dec - dhh)],
                         closed=True, facecolor="#fdf3d8", edgecolor="black", linewidth=0.8))
    ax.text(CX, y_dec, "progress ?\n(oracle \u00a73.4)", ha="center", va="center", fontsize=7.5)
    box(y_dis, "\u2462 Discard branch \u2192 restore C\n(truncation; evidence \u2192 notebook)", "#f6d5d0")
    box(y_tom, "\u2463 Append one ~40-token\ntombstone at the tail", "#dff0e0")

    for y0, y1, col in [(y_cp, y_exe + BH, "black"),
                        (y_exe, y_dec + dhh, "black"),
                        (y_dec - dhh, y_dis + BH, C_BAD),
                        (y_dis, y_tom + BH, "black")]:
        ax.add_patch(FancyArrowPatch((CX, y0), (CX, y1), arrowstyle="-|>",
                                     mutation_scale=8, color=col, linewidth=0.9))
    ax.text(CX - 0.015, (y_dec - dhh + y_dis + BH) / 2, "no progress",
            fontsize=7.5, color=C_BAD, ha="right", va="center")

    # success 边（右）：菱形右点 → 右走廊 → 回到循环头 ①（每轮先 checkpoint）
    xr, y_tgt = 0.95, y_cp + BH / 2
    ax.plot([CX + dhw, xr], [y_dec, y_dec], color=C_GREEN, lw=0.9)
    ax.plot([xr, xr], [y_dec, y_tgt], color=C_GREEN, lw=0.9)
    ax.add_patch(FancyArrowPatch((xr, y_tgt), (RX + 0.005, y_tgt), arrowstyle="-|>",
                                 mutation_scale=8, color=C_GREEN, linewidth=0.9))
    ax.text((CX + dhw + xr) / 2, y_dec + 0.022, "progress \u2192 keep branch",
            fontsize=7.5, color=C_GREEN, ha="center", va="center")

    # loop 边（左）：④ → 左走廊 → 回到 ①（下一轮，prefix 已扩展）
    xl = 0.045
    ax.plot([LX, xl], [y_tom + BH / 2, y_tom + BH / 2], color=C_OURS, lw=0.9)
    ax.plot([xl, xl], [y_tom + BH / 2, y_tgt], color=C_OURS, lw=0.9)
    ax.add_patch(FancyArrowPatch((xl, y_tgt), (LX - 0.005, y_tgt), arrowstyle="-|>",
                                 mutation_scale=8, color=C_OURS, linewidth=0.9))
    ax.text(0.024, (y_tom + BH / 2 + y_tgt) / 2, "next turn: prefix extended",
            fontsize=7.5, color=C_OURS, ha="center", va="center", rotation=90)

    # 底部前缀条：每轮重入时 prompt 的实际构成
    SY = 0.052
    cells = [((LX, 0.38), "sys+task+OK turns\n(byte-identical)", "#dfe9f3"),
             ((0.48, 0.20), "tombstone\n~40 tokens", "#dff0e0")]
    for (x0, w), txt, fc in cells:
        r = Rectangle((x0, SY), w, SH, facecolor=fc, edgecolor="black", linewidth=0.8)
        ax.add_patch(r)
        t = ax.text(x0 + w / 2, SY + SH / 2, txt, ha="center", va="center", fontsize=7.5)
        CELLS.append((r, t))
    for y0, y1 in [(y_tom, SY + SH)]:
        ax.add_patch(FancyArrowPatch((CX, y0), (CX, y1), arrowstyle="-|>",
                                     mutation_scale=8, color="black", linewidth=0.9))
    ax.text(CX, 0.018, "\u2192 cache hit, \u22480 recomputed tokens",
            fontsize=7.5, color=C_OURS, ha="center", va="center")
    return fig, [ax]


FIGURES = [("fig1_pareto", fig1_pareto), ("fig2_dose_response", fig2_dose),
           ("fig3_ablation", fig3_ablation), ("fig4_placement_tax", fig4_placement),
           ("fig5_invariants", fig5_schematic), ("fig6_overview", fig6_overview)]


def main():
    for name, fn in FIGURES:
        CELLS.clear()
        fig, axes = fn()
        fig.savefig(os.path.join(OUT, name + ".png"))
        fig.savefig(os.path.join(OUT, name + ".pdf"))  # 矢量版（正文用，fonttype 42 内嵌）
        plt.close(fig)
    print("wrote:")
    for f in sorted(os.listdir(OUT)):
        print("   paper/figs/" + f)


if __name__ == "__main__":
    main()
