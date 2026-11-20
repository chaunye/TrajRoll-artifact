"""A5 / E9-d：第二人类标注者的 Cohen's κ 计算（0 机时，本地，stdlib only）。

输入：
  --csv      标注者交回的 e9d_second_annotation.csv（列：tkey, label_1无进展_0有信息量, notes）
  --keymap   week1/out/e9d_二审_密钥表_2026-10-05_仅自留.csv（tkey -> 原始行 + 两轮标签，勿外发）
  --baseline κ 的比对基准（10-05 深夜作者裁定：论文改单轮口径，默认 = final = 终版表/LLM 轮；
             可选 first = 第一轮人工，仅供存档对照）。密钥表与主表交叉校验不一致会报错。

输出：week1/out/e9d_kappa_二审.txt
  - 总体一致率 + Cohen's κ（2×2 决定票；3×3 含存疑）
  - 第二标注者单独的命中池原始精度（Wilson 95% CI）与基准轮同批对照
  - 逐模板分歧表
  - Landis & Koch 强度解读

用法：python week1/e9d_kappa.py --csv <收回的csv路径>
"""
import argparse
import csv
import math
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
LAB = "label_1无进展_0有信息量"
CATS = ("0", "1", "2")
DECISIVE = ("0", "1")


def read_csv(p):
    with open(p, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def pick(row, names):
    for n in names:
        if n in row and row[n] != "":
            return row[n].strip()
    return ""


def wilson(k, n, z=1.96):
    if n == 0:
        return float("nan"), float("nan"), float("nan")
    p = k / n
    den = 1 + z * z / n
    ctr = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return p, ctr - half, ctr + half


def cohen_kappa(pairs, cats):
    """pairs: [(a,b)] 标签对；cats: 类别全集。返回 (po, pe, kappa, 混淆表)。"""
    n = len(pairs)
    if n == 0:
        return float("nan"), float("nan"), float("nan"), {}
    table = {(a, b): 0 for a in cats for b in cats}
    for a, b in pairs:
        table[(a, b)] += 1
    po = sum(v for (a, b), v in table.items() if a == b) / n
    ra = {a: sum(v for (x, y), v in table.items() if x == a) / n for a in cats}
    rb = {b: sum(v for (x, y), v in table.items() if y == b) / n for b in cats}
    pe = sum(ra[c] * rb[c] for c in cats)
    kap = (po - pe) / (1 - pe) if pe < 1 else float("nan")
    return po, pe, kap, table


def strength(k):
    if math.isnan(k):
        return "n/a"
    a = abs(k)
    if a < 0.20: return "slight"
    if a < 0.40: return "fair"
    if a < 0.60: return "moderate"
    if a < 0.80: return "substantial"
    return "almost perfect"


def norm(v):
    v = (v or "").strip()
    return v if v in CATS else ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True, help="标注者交回的 CSV")
    ap.add_argument("--keymap", default=os.path.join(OUT, "e9d_二审_密钥表_2026-10-05_仅自留.csv"))
    ap.add_argument("--baseline", choices=["final", "first"], default="final",
                    help="κ 基准：final=终版表/LLM 轮（默认，论文现报口径）；first=第一轮人工（存档对照）")
    ap.add_argument("--ref", default=None, help="基准主表（默认按 --baseline 自动选终版/已标注）")
    ap.add_argument("--out", default=os.path.join(OUT, "e9d_kappa_二审.txt"))
    a = ap.parse_args()

    ann_rows = read_csv(a.csv)
    keymap = {r["tkey"]: r for r in read_csv(a.keymap)}
    base_col = "终版_" + LAB if a.baseline == "final" else "第一轮人工_" + LAB
    ref_csv = a.ref or os.path.join(
        OUT, "e9d_sample_终版_2026-10-05.csv" if a.baseline == "final" else "e9d_sample_已标注.csv")
    ref_by_id = {r["id"]: norm(r[LAB]) for r in read_csv(ref_csv)}

    L = []
    L.append("=== E9-d 第二标注者 · Cohen's κ ===")
    L.append("标注 CSV = %s" % a.csv)
    L.append("行数 %d（应 100）" % len(ann_rows))

    pairs_all, pairs_dec, missing, unresolved = [], [], [], []
    tpl_of, ann_label, ref_label = {}, {}, {}
    for r in ann_rows:
        tkey = pick(r, ["tkey", "key", "Tkey", "T-key"])
        if tkey not in keymap:
            sys.exit(f"[FATAL] 交回表里的 {tkey!r} 不在密钥表中——是不是发错了文件？")
        km = keymap[tkey]
        if base_col not in km:
            sys.exit(f"[FATAL] 密钥表缺基准列 {base_col}——请重新运行 week1/e9d_second_pkg.py")
        tpl_of[tkey] = km["stratum_template"]
        ref = norm(km.get(base_col, ""))
        # 与基准主表交叉校验
        ref_main = ref_by_id.get(km["id"], "")
        if ref and ref_main and ref != ref_main:
            sys.exit(f"[FATAL] {tkey}({km['id']}) 密钥表第一轮标签 {ref} != 主表 {ref_main}")
        ref = ref or ref_main
        alab = norm(pick(r, [LAB, "label", "标注"]))
        if alab == "":
            missing.append(tkey)
            continue
        ann_label[tkey] = alab
        ref_label[tkey] = ref
        if ref:
            pairs_all.append((ref, alab))
            if ref in DECISIVE and alab in DECISIVE:
                pairs_dec.append((ref, alab))
        if alab == "2":
            unresolved.append(tkey)

    L.append("未标 %d 条；第二标注者存疑(2) %d 条" % (len(missing), len(unresolved)))
    if missing:
        L.append("  未标键: %s" % " ".join(sorted(missing)))
    L.append("")

    # 1) κ 2×2（双方都给决定票）
    po, pe, kap, tab = cohen_kappa(pairs_dec, DECISIVE)
    L.append("--- 1. Cohen's κ（2×2，双方均给 0/1 决定票，n=%d；基准=%s）---"
             % (len(pairs_dec), "终版/LLM 轮" if a.baseline == "final" else "第一轮人工"))
    L.append("  一致率 po = %.1f%%   期望一致 pe = %.1f%%   κ = %.3f（%s）"
             % (100 * po, 100 * pe, kap, strength(kap)))
    L.append("  混淆表（行=基准轮标签，列=第二标注者）:")
    L.append("             " + "".join("%8s" % c for c in DECISIVE))
    for rc in DECISIVE:
        L.append("  基准=%-6s " % rc + "".join("%8d" % tab[(rc, cc)] for cc in DECISIVE))
    both1 = tab[("1", "1")]; n_dec = len(pairs_dec)
    a_p, lo, hi = wilson(both1, n_dec)
    L.append("  第二标注者命中池原始精度（决定票内标 1 的比例）= %.1f%%  Wilson 95%% CI [%.1f, %.1f]"
             % (100 * a_p, 100 * lo, 100 * hi))
    L.append("")

    # 2) κ 3×3（含存疑）
    if pairs_all:
        po3, pe3, kap3, tab3 = cohen_kappa(pairs_all, CATS)
        L.append("--- 2. Cohen's κ（3×3，0/1/2 全类别，n=%d）---" % len(pairs_all))
        L.append("  一致率 po = %.1f%%   κ = %.3f（%s）" % (100 * po3, kap3, strength(kap3)))
        L.append("")

    # 3) 逐模板分歧
    dis = [(t, ref_label[t], ann_label[t]) for t in ann_label
           if t in ref_label and ref_label[t] and ref_label[t] != ann_label[t]]
    L.append("--- 3. 分歧逐条（基准轮 -> 第二标注者；%s）---" % ("终版/LLM 轮" if a.baseline == "final" else "第一轮人工"))
    L.append("  共 %d 条分歧" % len(dis))
    by_tpl = {}
    for t, r_, a_ in dis:
        by_tpl.setdefault(tpl_of[t], []).append((t, r_, a_))
    for t in sorted(by_tpl):
        L.append("  [%s] %d 条" % (t, len(by_tpl[t])))
        for tkey, r_, a_ in by_tpl[t]:
            L.append("    %s: %s -> %s" % (tkey, r_, a_))
    L.append("")

    # 4) 第一轮同批对照
    ref1 = [ref_label[t] for t in ann_label if ref_label[t] in DECISIVE]
    if ref1:
        k1 = sum(1 for v in ref1 if v == "1")
        p1, lo1, hi1 = wilson(k1, len(ref1))
        L.append("--- 4. 对照：基准轮（%s）在同 100 条上的原始精度 = %.1f%%  Wilson 95%% CI [%.1f, %.1f]（n=%d 决定票）---"
                 % ("终版/LLM 轮" if a.baseline == "final" else "第一轮人工",
                    100 * p1, 100 * lo1, 100 * hi1, len(ref1)))
    L.append("  （基准口径说明：10-05 深夜作者裁定论文改单轮口径，κ 默认对终版/LLM 轮标签计算；")
    L.append("    --baseline first 仅作存档对照，正式披露不得引用第一轮数字。）")
    L.append("")
    L.append("（正式 gate 数字仍以两轮标注口径为准；本文件只做标注者间信度与敏感性对照。）")

    with open(a.out, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    print("\n".join(L))
    print("\n写出:", a.out)


if __name__ == "__main__":
    main()
