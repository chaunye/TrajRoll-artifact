#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""e15_ttft_scale.py —— E15：memory update 在真实尺度上下文下的 TTFT 实测。

预注册：week1/预注册_E15_placement_ttft_scale_2026-10-04.md（判据先于数据冻结，跑后不许改）。
问题：system-prompt 替换式更新（RIR 的 placement）在真实尺度上下文里每次更新花多少 TTFT，
      尾部追加（ERROR-BACK）对照 —— 把 §5.5 的 "seconds" 外推换成实测端点。

两臂（同 filler、同 user turn，只变更新方式）：
  ours  = 前缀字节不变，user 内容尾部追加一条 ~45 token 墓碑（每 rep 换 nonce）→ 只算墓碑
  sysend= system prompt 内 [MEMORY] 槽替换（每 rep 换 nonce）→ 其后全部块失效，重算 ≈ L
尺度 L ∈ {4000, 8000, 16000, 24000, 30000}（按引擎 prompt_tokens 计，±2%）
每格 = 定标探针 + 1 warmup + N reps（默认 20）；stream，max_tokens=8，temperature=0
自检门（解释 TTFT 前必须过，否则该格 void）：ours recompute ≤128 tok；sysend recompute ≥ 0.9×L_actual
口径与 E14 一致：TTFT = 请求发出到首个流式 chunk 的毫秒；usage 走 stream_options.include_usage，
拿不到就硬报错（坑 1：cached_tokens 命中为 0 时字段可能缺省，按 0 计）。
只依赖 stdlib + requests；服务器 qwen_clean env 实测 requests 2.34.2。
"""
import argparse
import hashlib
import json
import time
import uuid

import requests

SCALES = [4000, 8000, 16000, 24000, 30000]
ARMS = ["ours", "sysend"]
REPS_DEFAULT = 20

SYS_BASE = (
    "You are a coding agent working in a repository. You answer strictly and briefly.\n"
    "[MEMORY]\n"          # sysend 臂在此槽内替换记忆文本；ours 臂此行为空占位、字节不变
)

FILLER_SENTS = [
    "The repository contains a module that parses configuration files and validates their schema.",
    "A utility script converts between the two encodings and writes a short summary line to stdout.",
    "The test suite runs the parser against a fixture directory and reports any mismatch by name.",
    "Documentation lives beside the code and is regenerated whenever the public interface changes.",
    "A small cache keeps the last parsed document in memory and invalidates it on file modification.",
    "Error messages include the offending path, the expected schema field, and the observed value.",
    "The build pipeline runs lint, type checks, and the test suite in sequence on every commit.",
    "A compatibility layer adapts the legacy interface to the new one without changing call sites.",
    "Benchmarks measure throughput and latency at several input sizes and print a compact table.",
    "Release notes list the behavioural changes, the migration steps, and the known limitations.",
]
TURN = "Report the current memory state in one short line."
TOMBSTONE = ("[TOMBSTONE] act=read_file target=data/config.json err=NO_SUCH_FILE n=3 "
             "world=the requested config file does not exist under data/")


def nonce():
    return uuid.uuid4().hex[:10]


def build_messages(arm, n_repeats, rep_nonce):
    filler = " ".join(FILLER_SENTS) + " "
    body = filler * n_repeats
    if arm == "ours":
        sys_prompt = SYS_BASE
        user = body + TOMBSTONE + " tag=" + rep_nonce + "\n" + TURN
    else:
        sys_prompt = SYS_BASE + "memory snapshot " + rep_nonce + ": config parse ok, cache warm, no errors.\n"
        user = body + TURN
    return [{"role": "system", "content": sys_prompt},
            {"role": "user", "content": user}]


def chat(url, model, messages, stream, max_tokens=8, timeout=600):
    payload = {"model": model, "messages": messages, "max_tokens": max_tokens,
               "temperature": 0.0}
    if stream:
        payload["stream"] = True
        payload["stream_options"] = {"include_usage": True}
    payload["chat_template_kwargs"] = {"enable_thinking": False}
    r = requests.post(url + "/v1/chat/completions", json=payload, stream=stream, timeout=timeout)
    if r.status_code != 200 and payload.pop("chat_template_kwargs", None) is not None:
        r = requests.post(url + "/v1/chat/completions", json=payload, stream=stream, timeout=timeout)
    r.raise_for_status()
    if not stream:
        j = r.json()
        return j["usage"], None
    t0 = time.perf_counter()
    ttft = None
    usage = None
    for raw in r.iter_lines():
        if not raw or not raw.startswith(b"data: "):
            continue
        data = raw[len(b"data: "):]
        if data.strip() == b"[DONE]":
            break
        chunk = json.loads(data)
        if ttft is None and chunk.get("choices"):
            ttft = (time.perf_counter() - t0) * 1000.0
        if chunk.get("usage"):
            usage = chunk["usage"]
    if usage is None:
        raise SystemExit("[x] 流式响应没有 usage（include_usage 未生效）—— E15 拒绝无 token 的 TTFT")
    return usage, ttft


def target_repeats(url, model, arm, L):
    """定标：让 prompt_tokens 落在 L ±2%。两次探针估每份 filler 的 token 数，再校一次。"""
    def probe(n):
        u, _ = chat(url, model, build_messages(arm, n, nonce()), stream=False, max_tokens=1)
        return u["prompt_tokens"]
    p1 = probe(1)
    p2 = probe(2)
    per = p2 - p1
    base = p1 - per
    n = max(1, round((L - base) / per))
    got = probe(n)
    if abs(got - L) / L > 0.02:
        n = max(1, n + round((L - got) / per))
        got = probe(n)
    return n, got


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=18203)
    ap.add_argument("--model", default="Qwen3-4B")
    ap.add_argument("--out", default="e15_ttft_scale.json")
    ap.add_argument("--reps", type=int, default=REPS_DEFAULT)
    a = ap.parse_args()
    url = "http://127.0.0.1:%d" % a.port

    sha = hashlib.sha256(open(__file__, "rb").read()).hexdigest()[:16]
    print("E15 placement-TTFT at scale | script sha256[:16] =", sha)
    print("arms:", ARMS, "scales:", SCALES, "reps:", a.reps)

    records = []
    cells = {}
    for arm in ARMS:
        for L in SCALES:
            n, got = target_repeats(url, a.model, arm, L)
            print("[target] arm=%s L=%d -> repeats=%d prompt_tokens=%d" % (arm, L, n, got))
            # warmup（不计入）
            chat(url, a.model, build_messages(arm, n, nonce()), stream=True)
            recs = []
            for i in range(a.reps):
                u, ttft = chat(url, a.model, build_messages(arm, n, nonce()), stream=True)
                cached = 0
                if u.get("prompt_tokens_details"):
                    cached = u["prompt_tokens_details"].get("cached_tokens") or 0
                rec = {"arm": arm, "L_target": L, "L_actual": u["prompt_tokens"], "rep": i,
                       "ttft_ms": round(ttft, 2), "prompt_tokens": u["prompt_tokens"],
                       "cached_tokens": cached,
                       "recomputed": u["prompt_tokens"] - cached}
                recs.append(rec)
                records.append(rec)
                print("  TTFT rep=%02d prefill=%d ms=%.1f" % (i, rec["recomputed"], rec["ttft_ms"]))
            recs_sorted = sorted(r["ttft_ms"] for r in recs)
            med = recs_sorted[len(recs_sorted) // 2]
            rec_max = max(r["recomputed"] for r in recs)
            rec_min = min(r["recomputed"] for r in recs)
            if arm == "ours":
                gate = rec_max <= 128
            else:
                gate = rec_min >= 0.9 * got
            cells["%s@%d" % (arm, L)] = {
                "L_target": L, "L_actual": got, "n": len(recs),
                "ttft_median_ms": round(med, 2),
                "ttft_p25_ms": round(recs_sorted[len(recs_sorted) // 4], 2),
                "ttft_p75_ms": round(recs_sorted[(3 * len(recs_sorted)) // 4], 2),
                "recompute_min": rec_min, "recompute_max": rec_max,
                "gate_pass": gate}
            print("[cell] %s@%d median=%.1f ms gate=%s recompute=[%d,%d]"
                  % (arm, L, med, gate, rec_min, rec_max))

    out = {"script_sha256_16": sha, "port": a.port, "model": a.model, "reps": a.reps,
           "scales": SCALES, "cells": cells, "records": records,
           "finished_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("wrote", a.out)


if __name__ == "__main__":
    main()
