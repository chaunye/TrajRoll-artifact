# -*- coding: utf-8 -*-
"""
Figure 4 (ISPA): three-panel serving-cost evidence figure (figure*, double column).
  (a) E15  : TTFT vs context length, tail-append (ours) vs system-prompt replacement
             (data: week1/out/e15_ttft_scale.json, N=20/cell, medians; per-cell IQRs <= 3.4 ms)
  (b) S4.11: three-variable upper bound A x B vs measured saving, five ledger points
             (constants from S4.11 text; sources: E5b Claude Code ledger, E9 SWE tiers, pi hold-out)
  (c) E11  : recomputed tokens per memory update by placement
             (constants from S4.9 text; source week1/results/E11_结果.md)
Style mirrors make_figs.py (Times, 8pt, C_OURS/C_MID/C_BAD palette).
"""
import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "paper", "figs")

C_OURS = "#1b6ca8"
C_BASE = "#b0b0b0"
C_BAD = "#c0392b"
C_MID = "#e08a1e"

plt.rcParams.update({
    "font.size": 8,
    "font.family": "serif",
    "font.serif": ["Times New Roman", "Nimbus Roman", "STIXGeneral", "DejaVu Serif"],
    "mathtext.fontset": "stix",
    "axes.titlesize": 8.5,
    "axes.labelsize": 8,
    "xtick.labelsize": 7.5,
    "ytick.labelsize": 7.5,
    "legend.fontsize": 7,
    "axes.grid": True,
    "grid.alpha": 0.25,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "figure.dpi": 200,
    "pdf.fonttype": 42,
})

# ---------------- data ----------------
e15 = json.load(open(os.path.join(ROOT, "week1", "out", "e15_ttft_scale.json")))
SCALES = [4000, 8000, 16000, 24000, 30000]


def arm(prefix):
    med = [e15["cells"][f"{prefix}@{L}"]["ttft_median_ms"] for L in SCALES]
    p25 = [e15["cells"][f"{prefix}@{L}"]["ttft_p25_ms"] for L in SCALES]
    p75 = [e15["cells"][f"{prefix}@{L}"]["ttft_p75_ms"] for L in SCALES]
    return med, p25, p75


ours_med, ours_lo, ours_hi = arm("ours")
sys_med, sys_lo, sys_hi = arm("sysend")

# (label, A*B bound %, measured %)  -- S4.11, in bound order
BOUNDS = [
    ("pi traces (hold-out)", 3.21, 3.00),
    ("Claude Code (80 sess.)", 11.3, 10.42),
    ("SWE T1 (conservative)", 16.5, 13.09),
    ("SWE T2 (medium)", 19.3, 17.06),
    ("SWE T3 (aggressive)", 24.0, 21.43),
]

E11 = [("tail append\n(ours)", 67.5, "1.00x", C_OURS),
       ("sys. prompt\nend", 125.2, "1.85x", C_MID),
       ("sys. prompt\nstart", 187.4, "2.78x", C_BAD)]

# ---------------- figure ----------------
fig, (axa, axb, axc) = plt.subplots(
    1, 3, figsize=(7.05, 1.85), layout="constrained",
    gridspec_kw={"width_ratios": [1.1, 1.1, 1.0]})

# (a) E15 scaling, log-log
axa.plot(SCALES, sys_med, "s-", color=C_BAD, ms=3.5, lw=1.0, label="system-prompt replacement")
axa.plot(SCALES, ours_med, "o-", color=C_OURS, ms=3.5, lw=1.0, label="tail append (ours)")
axa.set_xscale("log", base=2)
axa.set_yscale("log")
axa.set_xticks(SCALES, ["4k", "8k", "16k", "24k", "30k"])
axa.minorticks_off()
axa.set_xlabel("context length (tokens)")
axa.set_ylabel("per-turn TTFT (ms)")
axa.annotate("3,408 ms", xy=(SCALES[-1], sys_med[-1]), xytext=(-3, 4),
             xycoords="data", textcoords="offset points",
             ha="right", fontsize=7, color=C_BAD)
axa.annotate("74 ms", xy=(SCALES[-1], ours_med[-1]), xytext=(-3, 4),
             xycoords="data", textcoords="offset points",
             ha="right", fontsize=7, color=C_OURS)
axa.annotate("46x at 30k", xy=(25500, 430), fontsize=7, color="black", ha="center")
axa.annotate("system-prompt\nreplacement", xy=(7500, 700), fontsize=7,
             color=C_BAD, ha="center", va="bottom")
axa.annotate("tail append (ours)", xy=(9000, 30), fontsize=7,
             color=C_OURS, ha="center", va="top")
axa.text(-0.02, 1.05, "(a)", transform=axa.transAxes, fontsize=8.5, weight="bold")

# (b) A x B bound vs measured, dumbbell
ys = list(range(len(BOUNDS)))[::-1]
for y, (lab, bnd, meas) in zip(ys, BOUNDS):
    axb.plot([meas, bnd], [y, y], color=C_BASE, lw=1.4, zorder=1)
axb.plot([b for _, b, _ in BOUNDS], ys, "o", ms=4.5, mfc="white", mec="black", mew=0.9,
         ls="none", zorder=2, label="AxB bound")
axb.plot([m for _, _, m in BOUNDS], ys, "o", ms=4, color=C_OURS, zorder=3,
         label="measured saving")
axb.set_yticks(ys, [b[0] for b in BOUNDS], fontsize=7)
axb.set_xlabel("time-integrated saving (%)")
axb.set_xlim(0, 27.5)
axb.legend(loc="upper right", frameon=False, handlelength=1.2, borderaxespad=0.1)
axb.text(-0.02, 1.05, "(b)", transform=axb.transAxes, fontsize=8.5, weight="bold")

# (c) E11 placement tax
xs = range(len(E11))
axc.bar(xs, [e[1] for e in E11], color=[e[3] for e in E11],
        edgecolor="black", linewidth=0.5, width=0.62)
for x, e in zip(xs, E11):
    axc.text(x, e[1] - 12, e[2], ha="center", fontsize=7, color="white", weight="bold")
    axc.text(x, e[1] + 4, f"{e[1]:g}", ha="center", fontsize=6.6, color="black")
axc.set_xticks(xs, [e[0] for e in E11], fontsize=6.5)
axc.set_ylabel("recomputed tokens / update")
axc.set_ylim(0, 215)
axc.text(-0.02, 1.05, "(c)", transform=axc.transAxes, fontsize=8.5, weight="bold")

fig.savefig(os.path.join(OUT, "fig4_cost_panels.pdf"))
fig.savefig(os.path.join(OUT, "fig4_cost_panels.png"))
print("saved fig4_cost_panels.pdf/.png")
