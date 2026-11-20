#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A5 / E9-d（规划.md）：T2 失败 oracle 的人工标注抽样表 —— 本地、无 GPU、不碰任何冻结文件。

池（与 实验报告.md §E9 的 T2 账本同一口径：shard 0 + swe-agent-llama-70b + 轮数≥3）：
    hit  = A.hit("T2", obs) 命中的轮  → 估**精确率**（验收线：≥85%，否则退 T1 并在论文写明）
    miss = 未命中的轮                  → 估**召回率**（没有这一池，召回率根本算不出来）

抽样（seed 写死 = 20260927，可复现）：
    hit  100 条：按命中模板**比例配额**（每层下限 3，最大余数法收敛）+ 层内简单随机抽
                 （流式 reservoir，一趟读完，不把 50k 条观测全塞内存）
    miss  30 条：简单随机抽（--miss 0 可关，但关了就没法报召回率）
    去重：同一 (instance, 完整观测文本) 只算一次 —— 同 instance ~20 条 rollout 会把一模一样的
          失败重复 20 次，不去重纯浪费标注量；去重前后池大小都写进 meta

输出（week1/out/）：
    e9d_sample.csv        标注表（utf-8-sig，Excel 直接开；label/notes 两列留空给人填）
    e9d_sample_meta.txt   分层配额、池大小、估计公式、标注说明、复现命令
    e9d_pool_sizes.json   供 week1/e9d_score.py 算精确率/召回率
"""
import argparse
import csv
import glob
import hashlib
import json
import os
import random
import sys
import time
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pyarrow as pa                                # noqa: E402
import analyze_swe_traces as A                      # noqa: E402

if hasattr(sys.stdout, "reconfigure"):              # Windows 控制台默认 GBK，希腊字母会炸
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SHARD = 0
MODEL = "swe-agent-llama-70b"
SEED = 20260927
HIT_N = 100
MISS_N = 30
HIT_CAP = 400      # 每个模板的 reservoir 上限（不是池上限）
MISS_CAP = 1000
KEEP_HEAD = 1600   # 观测保留头/尾字数（标注够看，CSV 不爆）
KEEP_TAIL = 400
KEEP_AI = 400

HEADERS = ["id", "pool", "stratum_template", "also_T1", "also_T3",
           "instance_id", "turn_i", "n_turns", "target", "exit_status",
           "ai_action", "observation", "label_1无进展_0有信息量", "notes"]


def clip(s, head, tail=0):
    s = s or ""
    if len(s) <= head + tail:
        return s
    return s[:head] + "\n……[中略 %d 字]……\n" % (len(s) - head - tail) + s[-tail:]


def turns_raw(row):
    """轻量版 turns_of：只要轮边界与原文，不算 token（抽样用不着分词，省一大半时间）。"""
    msgs = []
    for t in row["trajectory"]:
        txt = t["text"] or ""
        if t["role"] == "system":
            txt = t.get("system_prompt") or txt
        msgs.append((t["role"], txt))
    i = 0
    while i < len(msgs) and msgs[i][0] != "ai":
        i += 1
    turns, cur = [], None
    for role, txt in msgs[i:]:
        if role == "ai":
            if cur:
                turns.append(cur)
            cur = {"ai": txt, "obs": []}
        elif cur is not None:
            cur["obs"].append(txt)
    if cur:
        turns.append(cur)
    for t in turns:
        t["obs_txt"] = "\n".join(t["obs"])
    return turns


def allocate(counts, total):
    """比例配额 + 每层下限 min(3, cnt) + 逐轮补到恰好 total；层容量不足就封顶。"""
    keys = sorted(counts)
    a = {k: min(3, counts[k]) for k in keys}
    guard = 0
    while sum(a.values()) < total and guard < 10000:
        guard += 1
        cand = [k for k in keys if a[k] < counts[k]]
        if not cand:
            break
        rest = total - sum(a.values())
        S = sum(counts[k] for k in cand)
        exact = {k: rest * counts[k] / S for k in cand}
        step = {k: min(int(exact[k]), counts[k] - a[k]) for k in cand}
        if sum(step.values()) == 0:
            order = sorted(cand, key=lambda k: (-(exact[k] % 1), -counts[k], k))
            step[order[0]] = min(1, counts[order[0]] - a[order[0]])
        for k in step:
            a[k] += step[k]
    while sum(a.values()) > total:              # 极端小池时可能超发，回收
        k = max(keys, key=lambda k: (a[k], k))
        if a[k] > 1:
            a[k] -= 1
        else:
            break
    return a


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=None)
    ap.add_argument("--shard", type=int, default=SHARD)
    ap.add_argument("--hit", type=int, default=HIT_N)
    ap.add_argument("--miss", type=int, default=MISS_N)
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--outdir", default=os.path.join(here, "out"))
    a = ap.parse_args()

    t0 = time.time()
    root = A.find_root(a.data)
    paths = sorted(glob.glob(os.path.join(root, "**", "*.arrow"), recursive=True))
    if not paths:
        sys.exit("[FATAL] %s 下没有 *.arrow" % root)
    path = paths[a.shard]

    rng_res = random.Random(a.seed)             # reservoir 用
    seen = set()
    hit_res, miss_res = defaultdict(list), defaultdict(list)
    hit_cnt, miss_cnt = Counter(), Counter()
    raw_hit = raw_miss = dup = 0
    nrow = nturn = 0

    for batch in pa.ipc.open_stream(pa.memory_map(path, "r")):
        for row in batch.to_pylist():
            if row["model_name"] != MODEL:
                continue
            turns = turns_raw(row)
            if len(turns) < 3:
                continue
            nrow += 1
            inst = row["instance_id"]
            for i, t in enumerate(turns):
                nturn += 1
                obs = t["obs_txt"]
                nm = A.hit("T2", obs)
                key = (inst, hashlib.md5(obs.encode("utf-8", "replace")).digest())
                if key in seen:
                    dup += 1
                    continue
                seen.add(key)
                pool, cnt = (hit_res, hit_cnt) if nm else (miss_res, miss_cnt)
                stratum = nm or "__miss__"
                if nm:
                    raw_hit += 1
                else:
                    raw_miss += 1
                item = {"inst": inst, "i": i + 1, "n": len(turns),
                        "target": int(bool(row["target"])),
                        "exit": str(row["exit_status"]),
                        "tmpl": nm or "", "t1": "Y" if A.hit("T1", obs) else "",
                        "t3": "Y" if A.hit("T3", obs) else "",
                        "ai": clip(t["ai"], KEEP_AI), "obs": clip(obs, KEEP_HEAD, KEEP_TAIL)}
                cap = HIT_CAP if nm else MISS_CAP
                lst = pool[stratum]
                c = cnt[stratum]
                cnt[stratum] = c + 1
                if c < cap:
                    lst.append(item)
                else:
                    j = rng_res.randrange(c + 1)
                    if j < cap:
                        lst[j] = item

    if not hit_cnt:
        sys.exit("[FATAL] T2 命中池为空")
    alloc = allocate(dict(hit_cnt), a.hit)
    if sum(alloc.values()) < a.hit:
        sys.exit("[FATAL] 池容量不足，分不出 %d 条" % a.hit)
    rng = random.Random(a.seed + 1)
    picked = []
    for tmpl in sorted(hit_cnt):
        n = alloc[tmpl]
        if n <= 0:
            continue
        pool = hit_res[tmpl]
        for it in (pool if n >= len(pool) else rng.sample(pool, n)):
            picked.append((tmpl, it))
    picked.sort(key=lambda x: (x[0], x[1]["inst"], x[1]["i"]))

    miss_picked = []
    if a.miss > 0:
        pool = miss_res["__miss__"]
        if len(pool) < a.miss:
            sys.exit("[FATAL] miss reservoir 不足 %d" % a.miss)
        miss_picked = [("", it) for it in rng.sample(pool, a.miss)]
        miss_picked.sort(key=lambda x: (x[1]["inst"], x[1]["i"]))

    os.makedirs(a.outdir, exist_ok=True)
    csv_path = os.path.join(a.outdir, "e9d_sample.csv")
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(HEADERS)
        for k, (tmpl, it) in enumerate(picked, 1):
            w.writerow(["H%03d" % k, "hit", tmpl, it["t1"], it["t3"], it["inst"],
                        it["i"], it["n"], it["target"], it["exit"],
                        it["ai"], it["obs"], "", ""])
        for k, (tmpl, it) in enumerate(miss_picked, 1):
            w.writerow(["M%03d" % k, "miss", "(未命中)", it["t1"], it["t3"], it["inst"],
                        it["i"], it["n"], it["target"], it["exit"],
                        it["ai"], it["obs"], "", ""])

    pool_json = {"seed": a.seed, "shard": a.shard, "model": MODEL,
                 "N_hit": sum(hit_cnt.values()), "N_miss": sum(miss_cnt.values()),
                 "n_hit_labeled": len(picked), "n_miss_labeled": len(miss_picked),
                 "hit_strata": {k: {"N": hit_cnt[k], "n": alloc.get(k, 0)}
                                for k in sorted(hit_cnt)},
                 "dedup_skipped": dup, "raw_hit_turns": raw_hit, "raw_miss_turns": raw_miss}
    json.dump(pool_json, open(os.path.join(a.outdir, "e9d_pool_sizes.json"), "w",
                              encoding="utf-8"), ensure_ascii=False, indent=1)

    M = []
    M.append("=== A5 / E9-d：T2 oracle 人工标注抽样表 ===")
    M.append("生成 %s | 脚本 week1/e9d_sample.py | 本地、无 GPU" % time.strftime("%Y-%m-%d %H:%M:%S"))
    M.append("口径  : shard %d + model_name == %s + 轮数≥3（= 实验报告 §E9 的 T2 账本同一批）"
             % (a.shard, MODEL))
    M.append("seed  : %d（抽样可复现；改 seed 会换样本，改了要在这里写明）" % a.seed)
    M.append("读取  : %s" % path)
    M.append("")
    M.append("--- 池大小（去重后）---")
    M.append("  会话 %d 条 / 轮 %d 条；去重丢弃重复观测 %d 条（同 instance 重复 rollout 造成）"
             % (nrow, nturn, dup))
    M.append("  T2 命中池 N_hit   = %d（原始命中轮 %d）" % (sum(hit_cnt.values()), raw_hit))
    M.append("  T2 未命中池 N_miss = %d（原始未命中轮 %d）" % (sum(miss_cnt.values()), raw_miss))
    M.append("")
    M.append("--- 配额（命中池按模板比例，下限 3）---")
    M.append("  %-26s %8s %6s" % ("模板", "池 N", "抽 n"))
    for k in sorted(hit_cnt):
        M.append("  %-26s %8d %6d" % (k, hit_cnt[k], alloc.get(k, 0)))
    M.append("  %-26s %8d %6d" % ("【合计·命中池】", sum(hit_cnt.values()), len(picked)))
    if miss_picked:
        M.append("  %-26s %8d %6d" % ("(未命中) 随机", sum(miss_cnt.values()), len(miss_picked)))
    M.append("")
    M.append("--- 标注说明（你来标，建议 1~2 h）---")
    M.append("  每行 = 一轮观测。`ai_action` 是 agent 这一轮的动作，`observation` 是它看到的回显")
    M.append("  （超长已截头留尾，中略字数标在正文里）。填 `label` 列：")
    M.append("      1 = **确实无进展**：这条观测里没有可行动的新信息（同一报错重复、纯失败回显、")
    M.append("                              命令本身打错等）")
    M.append("      0 = **有信息量**：哪怕它是报错，也给出了定位线索（堆栈、diff、行号、状态变化）")
    M.append("  拿不准就写 2，并在 `notes` 写一句为什么 —— 不要硬凑。")
    M.append("  H001–H%03d = 命中池（算**精确率**，验收线 ≥85%% → 才敢主推 T2）"
             % len(picked))
    if miss_picked:
        M.append("  M001–M%03d = 未命中池（算**召回率**；没有它，T2 漏了多少永远报不出来）"
                 % len(miss_picked))
    M.append("")
    M.append("--- 算法（填完跑 week1/e9d_score.py，别手算）---")
    M.append("  精度 p̂ = 后分层加权 Σ_t (N_t/N_hit)·p̂_t（层是按池大小配额的，小层配额偏高，")
    M.append("           直接把 100 条混着算会高估小模板的权重）；95% CI 用层内 bootstrap。")
    M.append("  召回 r̂ = TP/(TP+FN)，TP = N_hit·p̂，FN = N_miss·q̂，q̂ = 未命中池里标 1 的比例。")
    M.append("  验收（规划 A5 写死）：T2 精度 ≥85% 才把它当主推口径，否则退 T1 并在论文写明。")
    M.append("")
    M.append("--- 复现 ---")
    M.append("  python week1/e9d_sample.py --shard %d --hit %d --miss %d --seed %d"
             % (a.shard, a.hit, a.miss, a.seed))
    M.append("  耗时 %.1f s" % (time.time() - t0))
    M.append("")
    meta_path = os.path.join(a.outdir, "e9d_sample_meta.txt")
    open(meta_path, "w", encoding="utf-8").write("\n".join(M) + "\n")
    print("\n".join(M))
    print("[OK] %s\n[OK] %s\n[OK] %s" % (csv_path, meta_path,
                                          os.path.join(a.outdir, "e9d_pool_sizes.json")))


if __name__ == "__main__":
    main()
