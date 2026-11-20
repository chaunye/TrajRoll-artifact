#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""E7-d hold-out: the two-factor upper bound, checked on pi traces.

Purpose: the law in paper 5.6 was fitted on four points (Claude Code + SWE-agent
T1/T2/T3). pi traces is a fifth, independent dataset, never used to fit anything.
This script computes, with the SAME definitions as analyze_swe_traces.py:

    A = failed-turn token share of the carried increments
    B = 1 - TAG / mean(failed-turn increment tokens)
    predicted upper bound = A * B
    measured saving        = the ledger's own b0 -> ours number

Data: D:\task\erro_back\_refs\pi-traces\*.jsonl   (178 sessions)
Usage: python week1/pi_holdout.py
"""
import glob
import json
import os
import statistics as st

import tiktoken

ENC = tiktoken.get_encoding("o200k_base")
TAG = 40
IMG = 800
OUT = r"D:\task\erro_back\_refs\pi-traces"


def nt(s):
    return len(ENC.encode(s or "", disallowed_special=()))


def msg_tokens(m):
    c = m.get("content")
    if isinstance(c, str):
        return nt(c)
    tot = 0
    for b in c or []:
        t = b.get("type")
        if t == "text":
            tot += nt(b.get("text"))
        elif t == "thinking":
            tot += nt(b.get("thinking"))
        elif t == "toolCall":
            tot += nt(json.dumps(b.get("arguments") or {}, ensure_ascii=False)) + 8
        elif t == "image":
            tot += IMG
    return tot


rows = []
tot_tool = tot_err = 0
for path in sorted(glob.glob(os.path.join(OUT, "*.jsonl"))):
    turns = []
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    j = json.loads(line)
                except Exception:                                 # noqa: BLE001
                    continue
                if j.get("type") != "message":
                    continue
                m = j["message"]
                role = m.get("role")
                n = msg_tokens(m)
                if role == "assistant":
                    turns.append({"kind": "a", "tok": n, "err": 0, "tools": 0})
                elif role == "toolResult":
                    if not turns or turns[-1]["kind"] != "a":
                        turns.append({"kind": "a", "tok": 0, "err": 0, "tools": 0})
                    turns[-1]["tok"] += n
                    turns[-1]["tools"] += 1
                    tot_tool += 1
                    if m.get("isError") is True:
                        turns[-1]["err"] += 1
                        tot_err += 1
                else:
                    turns.append({"kind": "u", "tok": n, "err": 0, "tools": 0})
    except OSError:
        continue
    if len(turns) < 3:
        continue

    ctx_b = ctx_o = 0
    ib = io = 0
    nfail = 0
    for t in turns:
        ib += ctx_b
        io += ctx_o
        fail = (t["kind"] == "a" and t["err"] > 0)
        if fail:
            nfail += 1
        ctx_b += t["tok"]
        ctx_o += TAG if fail else t["tok"]
    rows.append({"f": os.path.basename(path), "n": len(turns), "nfail": nfail,
                 "fr": nfail / max(1, len(turns)), "b0": ib, "ours": io,
                 "fail_tok": sum(t["tok"] for t in turns
                                 if t["kind"] == "a" and t["err"] > 0),
                 "a_tok": sum(t["tok"] for t in turns if t["kind"] == "a"),
                 "all_tok": sum(t["tok"] for t in turns),
                 "n_a": sum(1 for t in turns if t["kind"] == "a"),
                 "fail_lens": [t["tok"] for t in turns
                               if t["kind"] == "a" and t["err"] > 0]})

B0 = sum(r["b0"] for r in rows)
OU = sum(r["ours"] for r in rows)
T = sum(r["n"] for r in rows)
save = 100.0 * (B0 - OU) / B0

FT_a = sum(r["fail_tok"] for r in rows)
A_a = FT_a / sum(r["a_tok"] for r in rows)
A_all = FT_a / sum(r["all_tok"] for r in rows)
NF = sum(r["nfail"] for r in rows)
mean_fail = FT_a / NF
Bfac = 1 - TAG / mean_fail

print("sessions %d, turns %d (assistant turns %d), failed turns %d"
      % (len(rows), T, sum(r["n_a"] for r in rows), NF))
print("toolResults %d, isError %d -> %.1f%%" % (tot_tool, tot_err, 100.0 * tot_err / tot_tool))
print("turn-level failure share = %.1f%%" % (100.0 * NF / T))
print()
print("Sigma context   b0 = %s   ours = %s   -> saved %.2f%%"
      % (f"{B0:,}", f"{OU:,}", save))
print()
print("A  (failed-turn token share, assistant-turn denominator) = %.4f" % A_a)
print("A' (same, all-turn denominator)                          = %.4f" % A_all)
print("failed-turn token length: median %.0f" % st.median([x for r in rows for x in r["fail_lens"]]))
print("failed-turn tokens: total %s, n %d, mean %.0f"
      % (f"{FT_a:,}", NF, mean_fail))
print("B  (1 - %d / mean failed-turn tokens)                     = %.4f" % (TAG, Bfac))
print()
print("predicted upper bound  A x B  = %.2f%%" % (100.0 * A_a * Bfac))
print("measured saving (ledger)      = %.2f%%" % save)
print("gap (predicted - measured)    = %+.2f pp" % (100.0 * A_a * Bfac - save))
