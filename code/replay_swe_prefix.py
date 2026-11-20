#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""E9-b 步骤 2（服务器跑）：在真实 SWE-agent 轨迹上**实测**前缀缓存

它与 E1/E2/E3 的区别只有一句：**prompt 是真实轨迹的原文，不是平铺的填充 token。**
它与 E7/E9 账本的区别也只有一句：**数字是 vLLM 报的 cached_tokens，不是账本估算。**

回放协议（每轮）
  b0   : 只发 1 次 —— prompt_k 本身。测到的 cached 覆盖前 k-1 轮已提交内容。
  ours : 先发 prompt_k（同样测一次）；
         若该轮判失败 → 可选再发一次 投机分支（prompt_k + 该轮的 ai + 观测）
            ！注意：投机请求**不进任何被统计的指标**（它既不改变下一轮的 cached —— 
              history_k 那一截本来就已命中 —— 也不被记录）。所以 --no-junk 与 --junk
              的**数字完全一样**，只差耗时。真实系统里失败分支确实生成过一次，但那笔
              账属于 decode，本脚本测的是 prompt 侧，测不到。
         然后丢弃，只在 history 末尾追加一句约 40 token 的墓碑。
         若该轮成功 → 与 b0 完全相同。

缓存隔离（E5 的教训，这里会被放大成假阳性）
  若不隔离，先跑的 b0 会把失败分支的 KV 留在池子里；后跑的 ours 每一轮 prompt 都是 b0 对应轮的
  **前缀**，于是全部命中 —— **命中率虚高、恰好偏向 ours**。
  故每 (轨迹, 模式) 在 system 开头注入等长 nonce： [run=b0-00012] / [run=ours-00012]

用法
  python replay_swe_prefix.py --jsonl e9_replay.jsonl --limit 3          # 冒烟
  python replay_swe_prefix.py --jsonl e9_replay.jsonl                    # 全量
"""
import argparse, csv, json, os, sys, time
import requests

FAIL_PATTERNS = [
    (r"^Your proposed edit has introduced new syntax error\(s\)", "EDIT_LINT", "edit"),
    (r"^No matches found for ", "NO_MATCH", "search"),
    (r"^(File|Directory) .* not found", "NOT_FOUND", "open"),
    (r"^Usage: (\w+) ", "BAD_CALL", "call"),
    (r"command not found", "NO_CMD", "bash"),
    (r"No such file or directory", "NO_PATH", "bash"),
    (r"syntax error near unexpected token", "SYNTAX", "bash"),
    (r"invalid option -- ", "BAD_OPT", "bash"),
]
import re
RX = [(re.compile(p, re.M), code, act) for p, code, act in FAIL_PATTERNS]


def oracle(obs_text):
    for rx, code, act in RX:
        if rx.search(obs_text):
            return code, act
    return None, None


def make_tag(code, act, n, obs_text):
    """§2.4 的墓碑：规则式、零 LLM 调用、约 40 token"""
    world = (obs_text.strip().splitlines() or [""])[0][:120]
    return "[TAG] act=%s err=%s n=%d world=%s" % (act, code, n, world)


class Client:
    def __init__(self, base, model, timeout):
        self.base, self.model, self.timeout = base, model, timeout
        self.s = requests.Session()

    def send(self, messages, max_tokens=1):
        r = self.s.post(self.base + "/v1/chat/completions",
                        json={"model": self.model, "messages": messages,
                              "max_tokens": max_tokens, "temperature": 0},
                        timeout=self.timeout)
        if r.status_code != 200:
            raise RuntimeError("HTTP %d %s" % (r.status_code, r.text[:300]))
        u = r.json().get("usage") or {}
        det = u.get("prompt_tokens_details") or {}
        return u.get("prompt_tokens", 0), det.get("cached_tokens")


def replay(cli, traj, mode, do_junk=True, block=16):
    nonce = "[run=%s-%05d] " % (mode, traj["_idx"])
    messages = [{"role": "system", "content": nonce + traj["system"]},
                {"role": "user", "content": traj["issue"]}]
    rows, prev_prompt, nfail_same = [], None, 0
    for k, turn in enumerate(traj["turns"]):
        obs = "\n".join(turn["obs"])
        code, act = oracle(obs)
        pt, ct = cli.send(messages)
        exp = None if prev_prompt is None else (prev_prompt // block) * block
        rows.append({"mode": mode, "traj": traj["_idx"], "inst": traj["instance_id"],
                     "round": k + 1, "judge": code or "ok", "prompt": pt,
                     "cached": ct if ct is not None else 0,
                     "recompute": pt - (ct or 0),
                     "expect_hit": exp if exp is not None else "",
                     "diff": ("" if exp is None else (ct or 0) - exp)})
        prev_prompt = pt
        branch = [{"role": "assistant", "content": turn["ai"] or "(no thought)"}]
        for o in turn["obs"]:
            branch.append({"role": "user", "content": o})
        if mode == "b0" or code is None:
            messages = messages + branch
        else:
            if do_junk:
                try:
                    cli.send(messages + branch)      # 投机分支：付一次 prefill，然后丢弃
                except RuntimeError as e:
                    print("   [junk 失败，跳过] %s" % str(e)[:120])
            nfail_same += 1
            messages = messages + [{"role": "user", "content": make_tag(code, act, nfail_same, obs)}]
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jsonl", default="e9_replay.jsonl")
    ap.add_argument("--base", default="http://127.0.0.1:18201")
    ap.add_argument("--model", default="Qwen3-4B")
    ap.add_argument("--out", default="out_e9")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--max-prompt", type=int, default=39000, help="超过就跳过该轨迹（Qwen3-4B 窗口 40960）")
    ap.add_argument("--no-junk", action="store_true", help="不做投机分支回放（更快，但口径变松）")
    ap.add_argument("--timeout", type=int, default=900)
    a = ap.parse_args()

    trajs = [json.loads(l) for l in open(a.jsonl, encoding="utf-8") if l.strip()]
    if a.limit:
        trajs = trajs[: a.limit]
    for i, t in enumerate(trajs):
        t["_idx"] = i
    os.makedirs(a.out, exist_ok=True)
    cli = Client(a.base, a.model, a.timeout)

    try:
        cli.send([{"role": "user", "content": "warmup"}])
        print("[OK] 服务可用：%s" % a.base)
    except Exception as e:
        print("[FATAL] 连不上 %s：%s" % (a.base, str(e)[:300]))
        sys.exit(2)

    all_rows, t0 = [], time.time()
    for t in trajs:
        for mode in ("b0", "ours"):
            tb = time.time()
            try:
                rows = replay(cli, t, mode, do_junk=not a.no_junk)
            except RuntimeError as e:
                print("  [跳过] %s %s : %s" % (t["instance_id"][:30], mode, str(e)[:140]))
                continue
            if rows and rows[-1]["prompt"] > a.max_prompt:
                print("  [警告] %s %s 末轮 prompt=%d 超过 max-prompt" % (t["instance_id"][:30], mode, rows[-1]["prompt"]))
            all_rows += rows
            S = sum(r["prompt"] for r in rows); R = sum(r["recompute"] for r in rows)
            print("  %-32s %-5s 轮 %3d  Σctx %10d  足迹 %6.0f  重算 %9d  (%.0fs)"
                  % (t["instance_id"][:32], mode, len(rows), S, S / max(1, len(rows)), R, time.time() - tb))

    csvp = os.path.join(a.out, "rounds.csv")
    with open(csvp, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(all_rows[0].keys()))
        w.writeheader(); w.writerows(all_rows)
    print("\n逐轮明细 → %s   （总 %.1f 分钟）" % (csvp, (time.time() - t0) / 60))

    print("\n=== 汇总（按轨迹配对：同一条轨迹的 b0 与 ours）===")
    by = {}
    for r in all_rows:
        by.setdefault((r["traj"], r["mode"]), []).append(r)
    ids = sorted({k[0] for k in by})
    print("%-6s %8s %10s %10s %8s | %10s %10s %8s | %s"
          % ("traj", "轮", "b0 Σctx", "ours Σctx", "比值", "b0 重算", "ours 重算", "轮比", "实例"))
    TB = TO = RB = RO = NB = NO = 0
    for i in ids:
        b, o = by.get((i, "b0")), by.get((i, "ours"))
        if not b or not o:
            continue
        sb = sum(r["prompt"] for r in b); so = sum(r["prompt"] for r in o)
        rb = sum(r["recompute"] for r in b); ro = sum(r["recompute"] for r in o)
        TB += sb; TO += so; RB += rb; RO += ro; NB += len(b); NO += len(o)
        print("%-6d %8s %10d %10d %8.3f | %10d %10d %8.3f | %s"
              % (i, "%d/%d" % (len(b), len(o)), sb, so, sb / max(1, so), rb, ro,
                 len(b) / max(1, len(o)), b[0]["inst"][:26]))
    print("-" * 110)
    print("合计   Σctx b0=%s  ours=%s  → 省 %.2f%%   |  重算 b0=%s  ours=%s  → 省 %.2f%%"
          % (f"{TB:,}", f"{TO:,}", 100.0 * (TB - TO) / max(1, TB),
             f"{RB:,}", f"{RO:,}", 100.0 * (RB - RO) / max(1, RB)))
    print("每轮足迹  b0=%.0f  ours=%.0f  （%.2f×）" % (TB / max(1, NB), TO / max(1, NO), (TB / max(1, NB)) / max(1e-9, TO / max(1, NO))))
    for m in ("b0", "ours"):
        diffs = [r["diff"] for r in all_rows if r["diff"] != "" and r["mode"] == m]
        if diffs:
            zero = sum(1 for d in diffs if d == 0)
            pos = sum(1 for d in diffs if isinstance(d, int) and d > 0)
            neg = sum(1 for d in diffs if isinstance(d, int) and d < 0)
            print("前缀稳定性 %-4s：%d/%d 轮 diff==0  正 %d  负 %d"
                  % (m, zero, len(diffs), pos, neg))


if __name__ == "__main__":
    main()
