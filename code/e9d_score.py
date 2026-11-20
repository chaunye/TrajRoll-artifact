#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A5 / E9-d：标注填完后算 T2 的精确率与召回率（只读 CSV + 池大小 JSON，无 GPU）。

  精度 p̂  = 后分层加权 Σ_t (N_t/N_hit)·p̂_t      95% CI：层内 bootstrap（B=5000）
  召回 r̂  = TP/(TP+FN)，TP = N_hit·p̂，FN = N_miss·q̂   q̂ = 未命中池标 1 的比例
  验收（规划 A5 写死）：p̂ ≥ 85% 才主推 T2，否则退 T1 并在论文写明

用法：
    python week1/e9d_score.py                                  # 默认读 week1/out/e9d_sample.csv
    python week1/e9d_score.py --csv 路径/xxx.csv --reps 20000
输出：week1/out/e9d_score.txt
"""
import argparse
import csv
import json
import os
import random
import sys
import time

if hasattr(sys.stdout, "reconfigure"):   # Windows 控制台默认 GBK，希腊字母会炸
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

YES = {"1", "y", "yes", "true", "t", "是", "无进展", "no-progress"}
NO = {"0", "n", "no", "false", "f", "否", "有信息量", "progress"}
THRESH = 0.85


def parse_label(s):
    v = (s or "").strip().lower()
    if v in YES:
        return 1
    if v in NO:
        return 0
    return None            # 空 / 2 = 拿不准


def pct(v, q):
    s = sorted(v)
    if not s:
        return float("nan")
    i = q / 100.0 * (len(s) - 1)
    lo = int(i)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (i - lo)


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=os.path.join(here, "out", "e9d_sample.csv"))
    ap.add_argument("--pool", default=None, help="默认同目录 e9d_pool_sizes.json")
    ap.add_argument("--reps", type=int, default=5000)
    ap.add_argument("--seed", type=int, default=20260927)
    ap.add_argument("--out", default=os.path.join(here, "out", "e9d_score.txt"))
    a = ap.parse_args()
    pool_path = a.pool or os.path.join(os.path.dirname(os.path.abspath(a.csv)),
                                       "e9d_pool_sizes.json")
    pool = json.load(open(pool_path, encoding="utf-8"))

    hit, miss = {}, []          # hit: {template: [(label, ...)]} ; miss: [label]
    n_unl = n_amb = n_tot = 0
    with open(a.csv, encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            n_tot += 1
            lab = parse_label(row.get("label_1无进展_0有信息量", ""))
            if lab is None:
                raw = (row.get("label_1无进展_0有信息量") or "").strip()
                if raw in ("2", "存疑", "?"):
                    n_amb += 1
                else:
                    n_unl += 1
                continue
            if row.get("pool") == "hit":
                hit.setdefault(row.get("stratum_template") or "(空)", []).append(lab)
            else:
                miss.append(lab)

    L = []
    L.append("=== A5 / E9-d：T2 oracle 标注打分 ===")
    L.append("生成 %s | csv = %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), a.csv))
    L.append("池 N_hit = %d  N_miss = %d  seed = %d  reps = %d"
             % (pool["N_hit"], pool["N_miss"], a.seed, a.reps))
    L.append("行数 %d：已标 %d，未填 %d，存疑(2) %d"
             % (n_tot, sum(len(v) for v in hit.values()) + len(miss), n_unl, n_amb))
    L.append("")
    if not hit:
        sys.exit("[FATAL] 命中池一行都没标，算不出精确率")

    strata = sorted(hit)
    n_hit_lab = sum(len(hit[s]) for s in strata)
    N_hit = pool["N_hit"]
    weights = {s: pool["hit_strata"].get(s, {}).get("N", 0) for s in strata}

    def prec_from(labels_by_s):
        num = den = 0.0
        for s in strata:
            v = labels_by_s[s]
            if not v:
                continue
            p = sum(v) / len(v)
            num += weights[s] * p
            den += weights[s]
        return num / den if den else float("nan")

    p_hat = prec_from(hit)
    crude = sum(sum(v) for v in hit.values()) / n_hit_lab
    n_miss_lab = len(miss)
    q_hat = (sum(miss) / n_miss_lab) if n_miss_lab else float("nan")

    rng = random.Random(a.seed)
    p_boot, r_boot = [], []
    for _ in range(a.reps):
        bs = {}
        for s in strata:
            v = hit[s]
            bs[s] = [v[rng.randrange(len(v))] for _ in v] if v else []
        pb = prec_from(bs)
        p_boot.append(pb)
        if n_miss_lab:
            bm = [miss[rng.randrange(n_miss_lab)] for _ in range(n_miss_lab)]
            qb = sum(bm) / n_miss_lab
            TP = pool["N_hit"] * pb
            FN = pool["N_miss"] * qb
            r_boot.append(TP / (TP + FN) if (TP + FN) > 0 else float("nan"))

    TP = N_hit * p_hat
    FN = pool["N_miss"] * q_hat if n_miss_lab else float("nan")
    recall = TP / (TP + FN) if n_miss_lab and (TP + FN) > 0 else float("nan")

    L.append("--- 1. 精确率（命中池；分母 = 标了的行）---")
    L.append("  分层配额加权 p̂ = %.1f%%   95%% CI [%.1f%%, %.1f%%]"
             % (100 * p_hat, 100 * pct(p_boot, 2.5), 100 * pct(p_boot, 97.5)))
    L.append("  算术粗算（不推荐，仅对照） = %.1f%%" % (100 * crude))
    L.append("  逐模板：")
    for s in strata:
        v = hit[s]
        L.append("    %-26s N=%-6d n=%-4d 命中率 %.0f%%"
                 % (s, weights[s], len(v), 100.0 * sum(v) / len(v)))
    ok = p_hat >= THRESH
    L.append("  验收线 85%% → **%s**（%s）"
             % ("PASS，T2 可作为主推口径" if ok else "FAIL，退 T1 并在论文写明",
                "%.1f%% ≥ 85%%" % (100 * p_hat) if ok else "%.1f%% < 85%%" % (100 * p_hat)))
    L.append("")
    L.append("--- 2. 召回率（需要未命中池的标注）---")
    if n_miss_lab:
        L.append("  未命中池 q̂ = %.1f%%（%d/%d 标 1）"
                 % (100 * q_hat, sum(miss), n_miss_lab))
        L.append("  TP = N_hit·p̂ = %.0f   FN = N_miss·q̂ = %.0f" % (TP, FN))
        L.append("  召回 r̂ = %.1f%%   95%% CI [%.1f%%, %.1f%%]"
                 % (100 * recall, 100 * pct(r_boot, 2.5), 100 * pct(r_boot, 97.5)))
        L.append("  （口径：把「人工判定确实无进展」当真值，估 T2 覆盖了多少）")
    else:
        L.append("  未命中池一行都没标 → **召回率算不出来**，只能报精确率。")
    L.append("")
    L.append("--- 3. 论文怎么写（填完再定，别提前写）---")
    if ok:
        L.append("  精度过线 → T2 主推，正文报 p̂ 与 CI，三档 13.09/17.06/21.43%% 保持。")
    else:
        L.append("  精度没过线 → 主推退到 T1（13.09%%），T2/T3 只作敏感性区间，并在")
        L.append("  正文与补充材料写明「oracle 经 %d 条人工标注，T2 精度 %.1f%% 未达预注册线」。"
                 % (n_hit_lab, 100 * p_hat))
    if n_unl or n_amb:
        L.append("  ⚠️ 还有 %d 行未填、%d 行存疑 —— 未填完就下结论会被人抓着问。"
                 % (n_unl, n_amb))
    L.append("")
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    open(a.out, "w", encoding="utf-8").write("\n".join(L) + "\n")
    print("\n".join(L))
    print("[OK] 写出 %s" % a.out)


if __name__ == "__main__":
    main()
