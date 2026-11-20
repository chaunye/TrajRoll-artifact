#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""E9-b 步骤 1：从 SWE-agent 轨迹里切出可回放的子集（本地 / 服务器同一份）

要点
  · 数据是 **Arrow IPC stream**，不是 parquet 也不是 IPC file → 只能用 pa.ipc.open_stream()
  · 峰值 token 用**Qwen3 自己的分词器**算（回放就是喂给 Qwen3-4B），窗口守卫才对得上
  · 分层抽样：每个失败率档各取 N 条 → 得到实测的剂量-反应曲线，而不是挑樱桃

用法
  # 服务器
  python swe_slice.py --data /home/ws/dataset/dataset/nebius___swe-agent-trajectories \
                      --tok-model /home/ws/.cache/modelscope/Qwen/Qwen3-4B \
                      --per-bin 4 --out e9_replay.jsonl
  # 本机（Windows）不加参数即用默认路径
  python week1\swe_slice.py --per-bin 4
"""
import argparse, glob, json, os, re, sys, time

import pyarrow as pa

LOCAL = r"D:\task\erro_back\dataset\nebius___swe-agent-trajectories"
SERVER = "/home/ws/dataset/dataset/nebius___swe-agent-trajectories"
TOKMODEL = "/home/ws/.cache/modelscope/Qwen/Qwen3-4B"
MSG_OVH = 4

# T1：工具层固定模板（与 analyze_swe_traces.py / replay_swe_prefix.py 同一套）
FAIL_PAT = re.compile(
    r"^Your proposed edit has introduced new syntax error\(s\)"
    r"|^No matches found for "
    r"|^(File|Directory) .* not found"
    r"|^Usage: \w+ "
    r"|command not found"
    r"|No such file or directory"
    r"|syntax error near unexpected token"
    r"|invalid option -- ", re.M)


def make_counter(kind, model_path):
    if kind in ("auto", "qwen"):
        try:
            from transformers import AutoTokenizer
            tk = AutoTokenizer.from_pretrained(model_path, use_fast=True)
            print("[tokenizer] Qwen3 分词器：%s" % model_path)
            return lambda s: len(tk.encode(s, add_special_tokens=False)), "qwen"
        except Exception as e:
            if kind == "qwen":
                raise
            print("[tokenizer] Qwen 分词器不可用（%s），退回 tiktoken" % type(e).__name__)
    import tiktoken
    enc = tiktoken.get_encoding("o200k_base")
    print("[tokenizer] tiktoken o200k_base（近似，非 Qwen 分词）")
    return (lambda s: len(enc.encode(s, disallowed_special=()))), "tiktoken"


def parse(row):
    msgs = []
    for t in row["trajectory"]:
        txt = t["text"] or ""
        if t["role"] == "system":
            txt = t.get("system_prompt") or txt
        msgs.append({"role": t["role"], "text": txt})
    system = msgs[0]["text"] if msgs and msgs[0]["role"] == "system" else ""
    issue, turns, cur = "", [], None
    for m in msgs:
        if m["role"] == "system":
            continue
        if m["role"] == "ai":
            if cur:
                turns.append(cur)
            cur = {"ai": m["text"], "obs": []}
        elif cur is None:
            issue += ("\n" if issue else "") + m["text"]
        else:
            cur["obs"].append(m["text"])
    if cur:
        turns.append(cur)
    return system, issue, turns


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=None, help="数据集根目录（自动找 **/*.arrow）")
    ap.add_argument("--tok-model", default=TOKMODEL)
    ap.add_argument("--tok", default="auto", choices=["auto", "qwen", "tiktoken"])
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--all-shards", action="store_true")
    ap.add_argument("--n", type=int, default=30, help="--per-bin=0 时按分数取前 n 条")
    ap.add_argument("--per-bin", type=int, default=0, help=">0 → 分层抽样，每档取这么多条")
    ap.add_argument("--min-turns", type=int, default=25)
    ap.add_argument("--max-peak", type=int, default=30000, help="峰值 prompt 上限（Qwen3-4B 窗口 40960）")
    ap.add_argument("--model", default="swe-agent-llama-70b")
    ap.add_argument("--out", default="e9_replay.jsonl")
    a = ap.parse_args()

    root = a.data
    if root is None:
        for cand in (LOCAL, SERVER):
            if os.path.isdir(cand):
                root = cand
                break
    if not root or not os.path.isdir(root):
        print("[FATAL] 找不到数据集目录，用 --data 指定"); sys.exit(2)
    shards = sorted(glob.glob(os.path.join(root, "**", "*.arrow"), recursive=True))
    if not shards:
        print("[FATAL] %s 下没有 *.arrow" % root); sys.exit(2)
    if not a.all_shards:
        shards = [shards[a.shard % len(shards)]]
    print("数据集 %s\n分片 %d 个，本次用: %s" % (root, len(shards), os.path.basename(shards[0])))

    nt, tok_kind = make_counter(a.tok, a.tok_model)

    t0, nrow, cands, pref = time.time(), 0, [], {"T1 工具层固定模板": 0, "观测总数": 0}
    for sp in shards:
        for batch in pa.ipc.open_stream(pa.memory_map(sp, "r")):
            for row in batch.to_pylist():
                nrow += 1
                if a.model and row["model_name"] != a.model:
                    continue
                system, issue, turns = parse(row)
                if len(turns) < a.min_turns:
                    continue
                ctx, peak, nfail = nt(system) + nt(issue), 0, 0
                for t in turns:
                    tk = nt(t["ai"]) + MSG_OVH + sum(nt(o) + MSG_OVH for o in t["obs"])
                    peak = max(peak, ctx)
                    ctx += tk
                    pref["观测总数"] += len(t["obs"])
                    if FAIL_PAT.search("\n".join(t["obs"])):
                        nfail += 1
                        pref["T1 工具层固定模板"] += 1
                peak = max(peak, ctx)
                if peak > a.max_peak:
                    continue
                cands.append({"score": nfail * len(turns), "nfail": nfail, "n": len(turns),
                              "peak": peak, "fr": nfail / len(turns), "system": system,
                              "issue": issue, "turns": turns, "instance_id": row["instance_id"],
                              "model_name": row["model_name"], "target": bool(row["target"]),
                              "exit_status": row["exit_status"]})
    print("扫过 %d 行，候选（≥%d 轮且峰值≤%d）%d 条，用时 %.0fs"
          % (nrow, a.min_turns, a.max_peak, len(cands), time.time() - t0))

    BINS = [(0, .01), (.01, .05), (.05, .15), (.15, .30), (.30, .50), (.50, .80), (.80, 1.01)]
    if a.per_bin > 0:
        sel = []
        print("\n=== 分层抽样（每档 %d 条）===" % a.per_bin)
        for lo, hi in BINS:
            grp = sorted([c for c in cands if lo <= c["fr"] < hi], key=lambda c: -c["score"])
            take = grp[: a.per_bin]
            sel += take
            print("  %5.0f%%~%5.0f%%  候选 %5d  取 %d" % (lo * 100, hi * 100, len(grp), len(take)))
    else:
        sel = sorted(cands, key=lambda c: -c["score"])[: a.n]

    with open(a.out, "w", encoding="utf-8") as fh:
        for c in sel:
            fh.write(json.dumps({"instance_id": c["instance_id"], "model_name": c["model_name"],
                                 "target": c["target"], "exit_status": c["exit_status"],
                                 "system": c["system"], "issue": c["issue"], "turns": c["turns"]},
                                ensure_ascii=False) + "\n")
    print("\n选中 %d 条 → %s (%.2f MB)" % (len(sel), a.out, os.path.getsize(a.out) / 1e6))
    print("%-34s %5s %6s %9s %7s" % ("instance_id", "轮数", "失败轮", "峰值tok", "失败率"))
    for c in sel:
        print("%-34s %5d %6d %9d %6.1f%%" % (c["instance_id"][:34], c["n"], c["nfail"], c["peak"], 100 * c["fr"]))
    print("\n下一步：python replay_swe_prefix.py --jsonl %s" % a.out)


if __name__ == "__main__":
    main()
