#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""E9：SWE-agent 真实轨迹（nebius/SWE-agent-trajectories）上的确定性账本

与 E7（CacheWise）/ pi 的口径一致，但**三处升级**：
  1) 有全文 → token 用 tokenizer 现算，不需要外部计数
  2) 有 target(bool) 任务级标签 → 能做论文「失败任务 1.8x」的任务级口径（E7 做不到）
  3) 失败 oracle 有**工具层固定模板**可用（比 CacheWise/pi 的启发式更硬）

账本口径（写死，别改）：
  prompt_k = 第 k 轮请求的 prompt token 数 = system + issue + 前 k-1 轮已提交内容
  Σcontext = Σ_k prompt_k                    （KV-时间积分）
  b0   : ctx_{k+1} = ctx_k + turn_k.tok
  ours : ctx_{k+1} = ctx_k + (TAG if 该轮判失败 else turn_k.tok)
  turn_k.tok = (ai 文本 + 其后的观测文本) 的 token 数 + 每条消息 4 token 模板开销

oracle 分三档（必须三档都报，否则等于把结论建在未验证的分类器上）：
  T1 保守  —— 只认**工具层固定模板**（SWE-agent 自己生成的反馈）
  T2 中    —— T1 + shell 层无歧义失败（command not found / No such file ... ）
  T3 激进  —— T2 + Traceback / AssertionError / FAILED
  ★ 明确不把「裸 Traceback」放进 T1/T2：SWE-bench 里**复现用户报的 bug** 就是故意跑出
    Traceback 的，那是信息量最高的一轮，不是「无进展」。

用法（一次跑一个分片；--all 会把 11 个分片的正文都留在内存里，别用）：
  python analyze_swe_traces.py --limit 2000                       # 先小样本看形状
  python analyze_swe_traces.py --shard 0 --model swe-agent-llama-70b
  python analyze_swe_traces.py --shard 1 --model swe-agent-llama-70b   # 换分片再看一批
注意：本脚本用 tiktoken o200k_base，与回放用的 Qwen3 分词器不同 ——
      绝对值差一成上下，只比**形状**。
"""
import argparse
import collections
import glob
import json
import os
import re
import statistics as st
import sys

import pyarrow as pa
import tiktoken

# 数据是 **Arrow IPC stream**（不是 parquet，也不是 IPC file）→ 只能 pa.ipc.open_stream()
ROOTS = [r"D:\task\erro_back\dataset\nebius___swe-agent-trajectories",
         "/home/ws/dataset/dataset/nebius___swe-agent-trajectories"]


def find_root(explicit=None):
    if explicit:
        return explicit
    for r in ROOTS:
        if os.path.isdir(r):
            return r
    raise SystemExit("[FATAL] 找不到数据集目录，用 --data 指定")


ENC = tiktoken.get_encoding("o200k_base")
TAG = 40           # 墓碑 token 数（与方案一致）
MSG_OVERHEAD = 4   # 每条消息的 chat 模板开销
NIMG = 0

# ---------- oracle 三级规则（按前 40~200 字符的固定模板匹配）----------
# T1：SWE-agent **工具层自己生成**的反馈，模板固定、精度高
T1 = [
    (r"^Your proposed edit has introduced new syntax error\(s\)", "edit-lint 语法错误"),
    (r"^Usage: search_file ", "工具调用格式错"),
    (r"not found\. Please provide a valid file name\.", "文件不存在"),
    (r"^Directory .* not found", "目录不存在"),
    (r"^No matches found for ", "检索零匹配"),
    (r"^(File|Directory) .* not found", "文件/目录不存在"),
    (r"^Your command ran successfully and did not produce any output\.", "成功但零输出"),
]
# T2：shell 层**无歧义**失败（不含 Traceback）
T2 = T1 + [
    (r"command not found", "命令不存在"),
    (r"No such file or directory", "路径不存在"),
    (r"syntax error near unexpected token", "shell 语法错"),
    (r"invalid option -- ", "参数错"),
    (r"Permission denied", "权限"),
    (r"cannot open |can't open ", "打开失败"),
    (r"^error: ", "编译/构建错误"),
    (r"^make: \*\*\*", "make 失败"),
    (r"^E   ", "pytest 断言"),
    (r"^FAILED |^FAIL: ", "测试失败"),
]
# T3：激进，加 Traceback 等
T3 = T2 + [
    (r"Traceback \(most recent call last\)", "python 异常"),
    (r"AssertionError", "断言失败"),
    (r"^\w*Error: ", "错误行"),
]
TIERS = {"T1": T1, "T2": T2, "T3": T3}
RX = {k: [(re.compile(p, re.M), n) for p, n in v] for k, v in TIERS.items()}

# T1 里的「成功但零输出」在 SWE-agent 里可能是正常无输出命令(cd/git checkout)，
# 单独标记，供敏感性对照
ZEROINFO = re.compile(r"^Your command ran successfully and did not produce any output\.")


def nt(s):
    return len(ENC.encode(s or "", disallowed_special=())) if s else 0


def hit(tier, obs):
    for r, name in RX[tier]:
        if r.search(obs):
            return name
    return None


def turns_of(row):
    traj = row["trajectory"]
    msgs = []
    for t in traj:
        txt = t["text"] or ""
        if t["role"] == "system":
            txt = t.get("system_prompt") or txt
        msgs.append((t["role"], txt))
    # 第一条 ai 之前的都算 prompt 前缀（system + issue）
    prefix = 0
    i = 0
    while i < len(msgs) and msgs[i][0] != "ai":
        prefix += nt(msgs[i][1]) + MSG_OVERHEAD
        i += 1
    turns = []
    cur = None
    for role, txt in msgs[i:]:
        if role == "ai":
            if cur:
                turns.append(cur)
            cur = {"ai": nt(txt) + MSG_OVERHEAD, "obs": [], "raww": nt(txt) + MSG_OVERHEAD}
        elif cur is not None:
            cur["obs"].append(txt)
        else:
            prefix += nt(txt) + MSG_OVERHEAD
    if cur:
        turns.append(cur)
    for t in turns:
        t["obs_txt"] = "\n".join(t["obs"])
        t["tok"] = t["ai"] + sum(nt(o) + MSG_OVERHEAD for o in t["obs"])
    return prefix, turns


def analyze(path, limit, model_filter=None):
    src = pa.memory_map(path, "r")
    rows = []
    marks = collections.Counter()
    tb_pos = []
    n = 0
    for batch in pa.ipc.open_stream(src):
        for row in batch.to_pylist():
            if limit and n >= limit:
                break
            n += 1
            if model_filter and row["model_name"] != model_filter:
                continue
            prefix, turns = turns_of(row)
            if len(turns) < 3:
                continue
            rec = {"inst": row["instance_id"], "model": row["model_name"],
                   "target": bool(row["target"]), "exit": row["exit_status"],
                   "prefix": prefix, "turns": turns, "nfail": {}, "maps": {}}
            for tier in TIERS:
                f = []
                for idx, t in enumerate(turns):
                    nm = hit(tier, t["obs_txt"])
                    f.append(nm)
                    if nm:
                        marks[tier + "|" + nm] += 1
                        if idx == 0:
                            marks[tier + "|__首轮命中__"] += 1
                        if nm == "python 异常":
                            tb_pos.append(idx / max(1, len(turns)))
                rec["nfail"][tier] = sum(1 for x in f if x)
                rec["maps"][tier] = f
            rows.append(rec)
        if limit and n >= limit:
            break
    return rows, marks, tb_pos


def increments(rows, tier, use_zeroinfo=True):
    """失败轮 / 成功轮 的**每轮增量**分布。省下的上限由它决定：
       省下 ≈ 失败轮 token 份额 × (1 − 墓碑 / 失败轮平均长度)"""
    tf, ts = [], []
    for r in rows:
        for t, nm in zip(r["turns"], r["maps"][tier]):
            fail = bool(nm) and (use_zeroinfo or nm != "成功但零输出")
            (tf if fail else ts).append(t["tok"])
    return tf, ts


def ledger(rows, tier, use_zeroinfo=True):
    B = O = T = 0
    for r in rows:
        cb = co = r["prefix"]
        for t, nm in zip(r["turns"], r["maps"][tier]):
            B += cb
            O += co
            T += 1
            fail = bool(nm) and (use_zeroinfo or nm != "成功但零输出")
            cb += t["tok"]
            co += TAG if fail else t["tok"]
    return B, O, T


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=None, help="数据集根目录，自动递归找 *.arrow")
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="0 = 不限")
    ap.add_argument("--model", default=None, help="只看某个 model_name")
    ap.add_argument("--dump-increments", default=None,
                    help="把 L0/成功增量/失败增量写成 JSON，供 extrapolate_failure_density.py --dist 用")
    ap.add_argument("--dump-tier", default="T2", choices=["T1", "T2", "T3"],
                    help="已废弃：现在一次导出三档")
    a = ap.parse_args()

    root = find_root(a.data)
    paths = sorted(glob.glob(os.path.join(root, "**", "*.arrow"), recursive=True))
    if not paths:
        sys.exit("[FATAL] %s 下没有 *.arrow" % root)
    print("数据根：%s（%d 个分片）" % (root, len(paths)))
    if not a.all:
        paths = [paths[a.shard]]
    rows, marks, tb_pos = [], collections.Counter(), []
    for p in paths:
        r, m, tb = analyze(p, a.limit, a.model)
        rows += r
        marks += m
        tb_pos += tb
    if not rows:
        print("没有可用轨迹"); sys.exit(0)

    T = sum(len(r["turns"]) for r in rows)
    print("会话 %d   总轮 %d   模型 %s" % (len(rows), T, a.model or "全部"))
    print("instance 去重后 %d 个  ← 统计显著性必须按这个粒度聚类，不能按 %d 条轨迹"
          % (len(set(r["inst"] for r in rows)), len(rows)))
    print()

    if a.dump_increments:
        tiers = {}
        for tier in ("T1", "T2", "T3"):
            tf, ts = increments(rows, tier)
            tiers[tier] = {"inc_ok": ts, "inc_fail": tf}
        json.dump({"source": "nebius/SWE-agent-trajectories shard0 %s" % (a.model or "all"),
                   "tag": TAG, "l0": [r["prefix"] for r in rows], "tiers": tiers},
                  open(a.dump_increments, "w", encoding="utf-8"))
        print("增量分布已导出 → %s（L0 %d）" % (a.dump_increments, len(rows)))
        for tier in ("T1", "T2", "T3"):
            print("   %s: 成功增量 %d / 失败增量 %d"
                  % (tier, len(tiers[tier]["inc_ok"]), len(tiers[tier]["inc_fail"])))
        print()

    print("=== 任务级口径（用 target 标签，**不依赖 oracle**）===")
    for lab, sel in [("未解出 target=False", [r for r in rows if not r["target"]]),
                     ("已解出 target=True", [r for r in rows if r["target"]])]:
        if not sel:
            continue
        B = O = TT = 0
        peaks = []
        for r in sel:
            cb = r["prefix"]; pk = cb
            for t in r["turns"]:
                B += cb; TT += 1; cb += t["tok"]; pk = max(pk, cb)
            peaks.append(pk)
        print("  %-20s 会话 %5d  轮数均值 %5.1f  峰值上下文中位 %8.0f  Σcontext均值 %12.0f"
              % (lab, len(sel), TT / len(sel), st.median(peaks), B / len(sel)))
    print()
    print("=== exit_status ===")
    for k, v in collections.Counter(r["exit"] for r in rows).most_common(8):
        print("   %-30s %6d  %.1f%%" % (k, v, 100.0 * v / len(rows)))
    print()
    for tier in ("T1", "T2", "T3"):
        nf = sum(r["nfail"][tier] for r in rows)
        B, O, TT = ledger(rows, tier)
        print("=== oracle %s ===" % tier)
        print("   判失败轮 %d / %d = 失败率 %.2f%%" % (nf, TT, 100.0 * nf / TT))
        print("   Σcontext  b0 = %s   ours = %s   → 省 %.2f%%"
              % (f"{B:,}", f"{O:,}", 100.0 * (B - O) / max(1, B)))
        print("   每轮足迹  b0 = %.0f   ours = %.0f" % (B / TT, O / TT))
        tf, ts = increments(rows, tier)
        if tf and ts:
            sf, ss = sum(tf), sum(ts)
            mf, ms = st.median(tf), st.median(ts)
            print("   ★ 失败轮 %d 条(%.1f%%) 但占 token %.1f%%   | 失败轮 中位%d 均值%.0f  vs 成功轮 中位%d 均值%.0f"
                  % (len(tf), 100.0 * len(tf) / (len(tf) + len(ts)), 100.0 * sf / (sf + ss),
                     mf, sf / len(tf), ms, ss / len(ts)))
            print("     饱和因子 (1−%d/失败轮均值) = %.3f  →  上限估计 %.1f%%"
                  % (TAG, 1 - TAG / (sf / len(tf)), 100.0 * (sf / (sf + ss)) * (1 - TAG / (sf / len(tf)))))
        # 分层
        print("   按失败率分层：")
        for lo, hi in ((0, .05), (.05, .1), (.1, .2), (.2, .35), (.35, .5), (.5, .8), (.8, 1.01)):
            sel = []
            for r in rows:
                fr = r["nfail"][tier] / max(1, len(r["turns"]))
                if lo <= fr < hi:
                    sel.append(r)
            if not sel:
                continue
            B2 = O2 = 0
            for r in sel:
                cb = co = r["prefix"]
                for t, nm in zip(r["turns"], r["maps"][tier]):
                    B2 += cb; O2 += co
                    if nm:
                        cb += t["tok"]; co += TAG
                    else:
                        cb += t["tok"]; co += t["tok"]
            print("      %4.0f%%~%4.0f%%  会话 %5d  省 %6.2f%%"
                  % (lo * 100, hi * 100, len(sel), 100.0 * (B2 - O2) / max(1, B2)))
        print()
    print("=== oracle 命中的模板（T3 口径）===")
    for k, v in marks.most_common(30):
        if k.startswith("T3|"):
            print("   %-40s %8d" % (k.split("|", 1)[1], v))
    print()
    if tb_pos:
        tb_pos.sort()
        print("★ Traceback 命中的**相对轮次**分布：中位 %.2f  p10 %.2f  p90 %.2f"
              % (st.median(tb_pos), tb_pos[int(.1 * len(tb_pos))], tb_pos[int(.9 * len(tb_pos))]))
        print("  （若大量集中在很小的值 → 那是**故意复现 bug**，把它判失败会丢信息量最高的一轮）")


if __name__ == "__main__":
    main()
