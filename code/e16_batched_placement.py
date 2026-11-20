#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""e16_batched_placement.py —— E16：并发负载下的 placement 税（缩减版 R-3）。

预注册：week1/prereg/预注册_E16_并发placement税_2026-10-05_DRAFT.md
        （判据先于数据冻结；sizing probe 只读 /metrics，不看任何 TTFT/ITL）。
问题：K 条稳态背景流的连续批处理下，30k 上下文一次 memory update 的 victim TTFT：
      尾部追加墓碑（ours）vs system-prompt 槽替换（sysend）。排序是否保持、差距是否
      随 K 摊平、背景流在哪一臂受扰更大。

victim 协议逐字节复用 e15_ttft_scale.py（同 SYS_BASE/FILLER_SENTS/TURN/TOMBSTONE、
同 chat()/target_repeats()、同自检门），本脚本只新增：背景流、/metrics 门、probe 模式。

模式：
  --mode probe    sizing：K∈{7,3} 逐级试（K 条背景流 + 一次 30k dummy prefill + 读
                  preempt/cache 指标），输出可运行的 K 集合。**不记录任何延迟读数**。
  --mode measure  正式测量：K ∈ 给定集合 × 两臂，每格 1 warmup + 20 reps victim +
                  K 条背景流（同 K 两臂的背景 prompt 逐字节一致，seed 固定）。

自检门（每格）：victim ours recompute ≤128 tok；sysend recompute ≥0.9×L_actual；
K>0 全程 num_preemptions 增量 = 0 且无 abort；背景流 prompt 两臂逐字节一致。
退路口径（P2/P3 不成立时）：token/FLOP —— 两臂 recompute tokens per update 之差。
"""
import argparse
import hashlib
import json
import re
import threading
import time
import uuid

import requests

# ---------- victim：与 e15_ttft_scale.py 逐字节同款（E15 sha 261ec21540b92a2c）----------
SYS_BASE = (
    "You are a coding agent working in a repository. You answer strictly and briefly.\n"
    "[MEMORY]\n"
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
        raise SystemExit("[x] 流式响应没有 usage（include_usage 未生效）—— E16 拒绝无 token 的 TTFT")
    return usage, ttft


def target_repeats(url, model, arm, L):
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


# ---------- E16 新增：背景流 + /metrics 门 ----------
BG_TARGET = 4000        # 背景流 prompt 目标 token（4–8k 带内，取下限给 KV 留余量）
BG_MAX_TOKENS = 2048    # 背景流 decode 上限（实测会在 victim 格结束后主动断开）
BG_STEADY_TOKENS = 8    # 每条背景流至少产出这么多 token 才算进入稳态
BG_FILLER = [
    "Session %d replays a log of a build agent that copies artefacts between staging directories.",
    "The planner proposes shell commands, the runner executes them, and the checker inspects exit codes.",
    "A manifest lists the expected outputs, and any mismatch is recorded with its diff and a timestamp.",
]
STOP = object()


def bg_messages(stream_id, n_repeats):
    """背景流 prompt：内容只依赖 stream_id 与重复数（同 K 两臂逐字节一致）。"""
    sents = []
    for i in range(n_repeats):
        sents.append(BG_FILLER[i % len(BG_FILLER)].replace("%d", str(stream_id + 1)))
    return [{"role": "user", "content": " ".join(sents) +
             " Summarise the last sentence in one short line."}]


def bg_probe_n(url, model, stream_id, target):
    def probe(n):
        u, _ = chat(url, model, bg_messages(stream_id, n), stream=False, max_tokens=1)
        return u["prompt_tokens"]
    p1 = probe(1)
    p2 = probe(2)
    per = p2 - p1
    base = p1 - per
    n = max(1, round((target - base) / per))
    got = probe(n)
    if abs(got - target) / target > 0.05:
        n = max(1, n + round((target - got) / per))
        got = probe(n)
    return n, got


def read_metrics(url):
    """返回 (preemptions_total, audit_lines)。解析失败不静默：字段缺失记 None。"""
    txt = requests.get(url + "/metrics", timeout=30).text
    pre = None
    audit = []
    for line in txt.splitlines():
        low = line.lower()
        if ("preempt" in low or "cache_usage" in low or "cache_config" in low) \
                and not line.startswith("#"):
            audit.append(line.strip()[:200])
            if "num_preemptions_total" in low and "num_preemptions_created" not in low:
                try:
                    v = float(line.rsplit(" ", 1)[1])
                    pre = (pre or 0.0) + v
                except (ValueError, IndexError):
                    pass
    return pre, audit


class BackgroundStream(threading.Thread):
    """一条稳态 decode 流：反复发起同一 prompt 的流式请求，记录窗口内 ITL。"""

    def __init__(self, url, model, stream_id, n_repeats, stop_event, window):
        super().__init__(daemon=True)
        self.url, self.model = url, model
        self.stream_id, self.n_repeats = stream_id, n_repeats
        self.stop_event = stop_event
        self.window = window            # dict: {"start": t, "end": None}
        self.events = []                # (t, kind)  kind in {"first","tok"}
        self.error = None
        self.tokens = 0

    def run(self):
        try:
            while not self.stop_event.is_set():
                payload = {"model": self.model, "messages": bg_messages(self.stream_id, self.n_repeats),
                           "max_tokens": BG_MAX_TOKENS, "temperature": 0.0,
                           "stream": True, "stream_options": {"include_usage": True}}
                payload["chat_template_kwargs"] = {"enable_thinking": False}
                with requests.post(self.url + "/v1/chat/completions", json=payload,
                                   stream=True, timeout=600) as r:
                    r.raise_for_status()
                    first = True
                    for raw in r.iter_lines():
                        if self.stop_event.is_set():
                            return
                        if not raw or not raw.startswith(b"data: "):
                            continue
                        data = raw[len(b"data: "):]
                        if data.strip() == b"[DONE]":
                            break
                        chunk = json.loads(data)
                        if chunk.get("choices"):
                            now = time.perf_counter()
                            self.events.append((now, "first" if first else "tok"))
                            first = False
                            self.tokens += 1
        except Exception as e:      # 断连退出是正常停机方式；其他异常记录
            if not self.stop_event.is_set():
                self.error = repr(e)

    def itls_ms(self):
        """窗口内（victim 测量期间）的逐 token 延迟，毫秒列表。"""
        out = []
        prev = None
        for t, kind in self.events:
            if t < self.window["start"]:
                prev = t
                continue
            if self.window["end"] is not None and t > self.window["end"]:
                break
            if prev is not None:
                out.append((t - prev) * 1000.0)
            prev = t
        return out


def pct(vals, q):
    s = sorted(vals)
    if not s:
        return None
    return round(s[min(len(s) - 1, int(q * len(s)))], 2)


def wait_steady(streams, deadline=120.0):
    t_end = time.perf_counter() + deadline
    while time.perf_counter() < t_end:
        if all(s.tokens >= BG_STEADY_TOKENS for s in streams):
            return True
        if any(s.error for s in streams):
            return False
        time.sleep(0.2)
    return False


def start_backgrounds(url, model, K, bg_ns):
    stop = threading.Event()
    window = {"start": None, "end": None}
    streams = [BackgroundStream(url, model, i, bg_ns[i], stop, window) for i in range(K)]
    for s in streams:
        s.start()
    if not wait_steady(streams):
        stop.set()
        raise SystemExit("[x] 背景流 %d s 内未进入稳态或有错误 —— 判 void" % 120)
    return streams, stop, window


# ---------- 主流程 ----------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=18203)
    ap.add_argument("--model", default="Qwen3-4B")
    ap.add_argument("--mode", choices=["probe", "measure"], required=True)
    ap.add_argument("--out", default=None)
    ap.add_argument("--reps", type=int, default=20)
    ap.add_argument("--ks", default="")          # measure: 逗号分隔，如 "0,3"
    ap.add_argument("--victim-L", type=int, default=30000)
    ap.add_argument("--probe-order", default="7,3")
    a = ap.parse_args()
    url = "http://127.0.0.1:%d" % a.port

    sha = hashlib.sha256(open(__file__, "rb").read()).hexdigest()[:16]
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    print("E16 batched placement | mode=%s | script sha256[:16] = %s | %s"
          % (a.mode, sha, stamp))
    pre0, _ = read_metrics(url)
    print("server preemptions baseline: %s" % pre0)

    # victim 定标（30k，probe 与 measure 都需要）
    vn, vtok = target_repeats(url, a.model, "sysend", a.victim_L)
    print("[victim] L=%d -> repeats=%d prompt_tokens=%d" % (a.victim_L, vn, vtok))

    if a.mode == "probe":
        # 只看指标，不记录任何 TTFT/ITL
        decision = {"probe_order": a.probe_order, "K": None, "trials": []}
        for K in [int(x) for x in a.probe_order.split(",") if x.strip()]:
            # 背景流定标：内容只依赖 stream_id（同 K 两臂一致；probe 只用于占位体积）
            bg_ns = []
            for i in range(K):
                n_i, got_i = bg_probe_n(url, a.model, i, BG_TARGET)
                bg_ns.append(n_i)
            pre_a, aud_a = read_metrics(url)
            streams, stop, window = start_backgrounds(url, a.model, K, bg_ns)
            # 一次 30k dummy prefill 压测（不读延迟）
            u, _ = chat(url, a.model, build_messages("sysend", vn, nonce()), stream=True, max_tokens=1)
            time.sleep(2.0)
            pre_b, aud_b = read_metrics(url)
            dpre = (pre_b - pre_a) if (pre_a is not None and pre_b is not None) else None
            ok = (dpre == 0)
            decision["trials"].append({"K": K, "preemptions_delta": dpre,
                                       "metrics_audit": (aud_a[-3:] + aud_b[-3:])})
            print("[probe] K=%d preempt_delta=%s -> %s" % (K, dpre, "OK" if ok else "PREEMPT"))
            stop.set()
            time.sleep(3.0)
            if ok:
                decision["K"] = K          # 可行即从大到小取第一个
                break
        out = {"script_sha256_16": sha, "mode": "probe", "finished_at": stamp,
               "victim_L": a.victim_L, "victim_repeats": vn, "victim_prompt_tokens": vtok,
               "bg_target_tokens": BG_TARGET, "decision": decision,
               "note": "probe blind to TTFT/ITL by design (prereg red line 2)"}
        path = a.out or "e16_sizing_probe.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
        print("[probe] K set -> %s, wrote %s" % (decision["K"], path))
        return

    # ---- measure ----
    Ks = [int(x) for x in a.ks.split(",") if x.strip()]
    if not Ks:
        raise SystemExit("[x] measure 需要 --ks，如 --ks 0,3（来自 probe 的冻结决定）")
    records, cells = [], {}
    for K in Ks:
        # 背景流定标：每条流 i 的 prompt 固定（同 K 两臂一致）
        bg_ns = []
        bg_tok = []
        for i in range(K):
            n_i, got_i = bg_probe_n(url, a.model, i, BG_TARGET)
            bg_ns.append(n_i)
            bg_tok.append(got_i)
        for arm in ["ours", "sysend"]:
            # victim 定标（arm 相关：ours 的 user 尾部有墓碑，sysend 的 system 有槽文本）
            n_arm, got_arm = target_repeats(url, a.model, arm, a.victim_L)
            pre_a, aud_a = read_metrics(url)
            window = {"start": None, "end": None}
            streams = stop = None
            if K > 0:
                streams, stop, window = start_backgrounds(url, a.model, K, bg_ns)
            window["start"] = time.perf_counter()
            chat(url, a.model, build_messages(arm, n_arm, nonce()), stream=True)  # warmup
            recs = []
            for i in range(a.reps):
                u, ttft = chat(url, a.model, build_messages(arm, n_arm, nonce()), stream=True)
                cached = 0
                if u.get("prompt_tokens_details"):
                    cached = u["prompt_tokens_details"].get("cached_tokens") or 0
                rec = {"arm": arm, "K": K, "rep": i,
                       "L_actual": u["prompt_tokens"], "ttft_ms": round(ttft, 2),
                       "prompt_tokens": u["prompt_tokens"], "cached_tokens": cached,
                       "recomputed": u["prompt_tokens"] - cached}
                recs.append(rec)
                records.append(rec)
                print("  [K=%d %s] rep=%02d recompute=%d TTFT=%.1f ms"
                      % (K, arm, i, rec["recomputed"], rec["ttft_ms"]))
            window["end"] = time.perf_counter()
            time.sleep(2.0)
            pre_b, aud_b = read_metrics(url)
            dpre = (pre_b - pre_a) if (pre_a is not None and pre_b is not None) else None
            if stop:
                stop.set()
                time.sleep(3.0)
            # victim 自检门
            rec_max = max(r["recomputed"] for r in recs)
            rec_min = min(r["recomputed"] for r in recs)
            gate_victim = (rec_max <= 128) if arm == "ours" else (rec_min >= 0.9 * got_arm)
            # 背景流统计
            bg_stats = []
            gate_bg = True
            for s in (streams or []):
                if s.error:
                    gate_bg = False
                it = s.itls_ms()
                bg_stats.append({"stream": s.stream_id, "tokens_in_window": len(it),
                                 "itl_p50_ms": pct(it, 0.5), "itl_p99_ms": pct(it, 0.99),
                                 "error": s.error})
            gate_preempt = (dpre == 0)
            med = sorted(r["ttft_ms"] for r in recs)[len(recs) // 2]
            cells["%s@K%d" % (arm, K)] = {
                "K": K, "arm": arm, "L_actual": got_arm, "n": len(recs),
                "ttft_median_ms": round(med, 2),
                "ttft_p25_ms": pct([r["ttft_ms"] for r in recs], 0.25),
                "ttft_p75_ms": pct([r["ttft_ms"] for r in recs], 0.75),
                "recompute_min": rec_min, "recompute_max": rec_max,
                "gate_victim": gate_victim, "gate_preempt": gate_preempt,
                "gate_bg_streams": gate_bg, "gate_pass": gate_victim and gate_preempt and gate_bg,
                "preemptions_delta": dpre,
                "bg_prompt_tokens": bg_tok,
                "bg_itl": bg_stats,
                "metrics_audit": (aud_a[-2:] + aud_b[-2:])}
            c = cells["%s@K%d" % (arm, K)]
            print("[cell] %s@K%d median=%.1f ms gates=%s/%s/%s bg_p99=%s"
                  % (arm, K, med, gate_victim, gate_preempt, gate_bg,
                     [b["itl_p99_ms"] for b in bg_stats]))

    out = {"script_sha256_16": sha, "mode": "measure", "finished_at": stamp,
           "victim_L": a.victim_L, "reps": a.reps, "ks": Ks,
           "bg_target_tokens": BG_TARGET, "bg_max_tokens": BG_MAX_TOKENS,
           "cells": cells, "records": records}
    path = a.out or "e16_batched_placement.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("wrote", path)


if __name__ == "__main__":
    main()
