#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""E7-d：在 pi 真实轨迹上重做账本（有全文 + isError + 会话边界）

data: D:\task\erro_back\_refs\pi-traces\*.jsonl
口径与 E7 一致：
  b0   : 每轮增量 = assistant 消息 + 其 toolResult 的 token 数
  ours : 该轮内有任何 isError=true 的 toolResult → 整轮换成 TAG(40)
"""
import glob
import json
import os
import statistics as st
import sys

import tiktoken

ENC = tiktoken.get_encoding("o200k_base")
TAG = 40
IMG = 800          # 图片 token 粗估
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

    ctx_b = ctx_o = 0        # 第一条消息之前上下文为 0（原版把首条重复计了一次）
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
                 "mean": ib / max(1, len(turns))})

if not rows:
    print("还没有已下载的 jsonl，等下载完成")
    sys.exit(0)

B0 = sum(r["b0"] for r in rows)
OU = sum(r["ours"] for r in rows)
T = sum(r["n"] for r in rows)
print("会话 %d，总轮 %d" % (len(rows), T))
print("工具结果 %d，其中 isError=true %d → 失败率 %.1f%%"
      % (tot_tool, tot_err, 100.0 * tot_err / max(1, tot_tool)))
print()
print("Σcontext   b0 = %s   ours = %s   → ours 省 %.2f%%（b0 是 ours 的 %.3f 倍）"
      % (f"{B0:,}", f"{OU:,}", 100 * (B0 - OU) / B0, B0 / OU))
print("每轮足迹   b0 = %.0f   ours = %.0f" % (B0 / T, OU / T))
print()
print("=== 按失败率分层 ===")
print("%-14s %5s %10s %12s %9s" % ("失败率", "会话", "失败率均值", "平均上下文", "省下%"))
for lo, hi in [(0, 0.05), (0.05, 0.10), (0.10, 0.20), (0.20, 0.35), (0.35, 1.01)]:
    sel = [r for r in rows if lo <= r["fr"] < hi]
    if not sel:
        continue
    sb = sum(r["b0"] for r in sel)
    so = sum(r["ours"] for r in sel)
    print("%-14s %5d %10.1f%% %12.0f %8.2f%%"
          % ("%.0f%%~%.0f%%" % (lo * 100, hi * 100), len(sel),
             100 * st.mean([r["fr"] for r in sel]), st.mean([r["mean"] for r in sel]),
             100 * (sb - so) / sb))
