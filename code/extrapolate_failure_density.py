#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""E7-c / E9-c：把真实轨迹的"每轮增量分布"重采样，外推到高失败率区间

方法：抽经验分布（首轮上下文 L0、成功回合增量、失败回合增量），按指定失败率 p
      重采样生成会话，算 b0 vs ours。**这是外推，不是实测** —— 但它锚在真实的增量分布上。

E9-c 要回答的问题：
   E7-c 用 CacheWise 的增量分布推出"95% 失败率 + 786 轮 → ~80%"，
   而 E9 在 SWE-agent 真实轨迹上实测同区间只有 47.6%~49.4%。差在哪？
   → 把分布换成 SWE-agent 的实测分布，**跑同一套模拟器**，看 66% 会不会掉到 ~49%。

用法：
  python extrapolate_failure_density.py                                  # 原始（CacheWise 分布）
  python extrapolate_failure_density.py --dist swe_increments.json       # 换分布 + 自动并排对比
"""
import argparse
import glob
import json
import os
import random
import statistics as st

ROOT = r"D:\task\erro_back\_refs\cachewise-traces\parsed_traces"
TAG = 40
random.seed(20260917)


def ctx(e):
    return ((e.get("input_tokens") or 0) + (e.get("cache_read_input_tokens") or 0)
            + (e.get("cache_creation_input_tokens") or 0))


def load_cachewise():
    """原来的 E7-c 路径：从 CacheWise 解析轨迹里抽增量分布"""
    L0s, inc_ok, inc_fail, lens = [], [], [], []
    for p in sorted(glob.glob(os.path.join(ROOT, "**", "events.json"), recursive=True)):
        with open(p, encoding="utf-8") as f:
            evs = json.load(f)
        llm, tools = {}, {}
        for e in evs:
            if e.get("event_type") == "llm_call":
                m = e.get("message_id")
                if m not in llm or ctx(e) > ctx(llm[m]):
                    llm[m] = e
            elif e.get("event_type") == "tool_call":
                tools.setdefault(e.get("associated_llm_call_id"), []).append(e)
        calls = sorted(llm.values(), key=lambda e: (e.get("timestamp") or "", e.get("message_id") or ""))
        if len(calls) < 3:
            continue
        L = [ctx(e) for e in calls]
        L0s.append(L[0]); lens.append(len(L) - 1)
        for i in range(len(L) - 1):
            d = L[i + 1] - L[i]
            if d <= 0:                     # compaction 不算增量
                continue
            if any(t.get("is_error") is True for t in tools.get(calls[i].get("message_id"), [])):
                inc_fail.append(d)
            else:
                inc_ok.append(d)
    return L0s, inc_ok, inc_fail, lens


def load_dump(path, tier="T2"):
    """E9-c 路径：读 analyze_swe_traces.py --dump-increments 产出的 JSON（一次含三档）"""
    d = json.load(open(path, encoding="utf-8"))
    if "tiers" in d:                      # 新格式
        t = d["tiers"][tier]
        src = "%s（tier=%s）" % (d.get("source", path), tier)
        return d["l0"], t["inc_ok"], t["inc_fail"], None, {
            "source": src, "tier": tier, "tag": d.get("tag", TAG)}
    return d["l0"], d["inc_ok"], d["inc_fail"], None, d   # 旧格式（单档）


def describe(name, L0s, inc_ok, inc_fail, lens):
    print("=== %s ===" % name)
    print("  L0 %d 个样本（中位 %d），成功增量 %d，失败增量 %d%s"
          % (len(L0s), st.median(L0s), len(inc_ok), len(inc_fail),
             "" if lens is None else "，会话轮数 %d" % len(lens)))
    for lab, arr in (("成功增量", inc_ok), ("失败增量", inc_fail)):
        a = sorted(arr)
        print("  %s 中位 %d / 均值 %.0f / p90 %d" % (lab, st.median(a), st.mean(a), a[int(len(a) * .9)]))
    print()


def simulate(p_fail, n_turns, trials, dist, seed=None):
    """seed=None → 用模块级 random（**原版顺序消耗**），可逐位复现 E7-c 已发表的数字；
    seed=<int> → 逐格独立种子：① 结果与调用顺序无关；② A/B 两列共用同一种子 → **配对比较**，
    失败模式相同、只换增量分布，差值的噪声小得多。"""
    rng = random if seed is None else random.Random(seed)
    L0s, inc_ok, inc_fail = dist[0], dist[1], dist[2]   # dist 是 4 元组（第 4 项是 lens 或 None）
    sb = so = 0
    for _ in range(trials):
        c = rng.choice(L0s)
        cb, co = c, c
        b = o = 0
        for _t in range(n_turns):
            b += cb; o += co
            if rng.random() < p_fail:
                d = rng.choice(inc_fail)
                cb += d; co += TAG
            else:
                d = rng.choice(inc_ok)
                cb += d; co += d
        sb += b; so += o
    return 100.0 * (sb - so) / sb


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dist", default=None,
                    help="增量分布 JSON（analyze_swe_traces.py --dump-increments 产出）；给了就自动并排对比")
    ap.add_argument("--tier", default="T2", choices=["T1", "T2", "T3"],
                    help="用哪一档 oracle 的增量分布（T1 保守 / T2 中 / T3 激进）")
    ap.add_argument("--trials", type=int, default=300)
    ap.add_argument("--len-trials", type=int, default=200)
    ap.add_argument("--seed", type=int, default=20260917)
    ap.add_argument("--p-list", default="0,0.05,0.12,0.20,0.35,0.50,0.70,0.85,0.95")
    ap.add_argument("--len-list", default="10,30,100,300,1000")
    a = ap.parse_args()

    cw = load_cachewise()
    describe("分布 A：CacheWise（E7-c 用的那个）", *cw)
    D = {"A": cw}
    if a.dist:
        sw = load_dump(a.dist, a.tier)
        describe("分布 B：%s" % (sw[4].get("source", a.dist)), *sw[:4])
        D["B"] = sw[:4]

    # 不换分布时用原版顺序 RNG（逐位复现 E7-c）；换分布时用逐格种子（A/B 配对）
    sd = a.seed if a.dist else None
    ps = [float(x) for x in a.p_list.split(",")]
    print("=== 收益 vs 失败率（会话 100 轮，各 %d 次模拟）===" % a.trials)
    print("  失败率   %s" % "   ".join("%10s" % k for k in D))
    for p in ps:
        vals = {k: simulate(p, 100, a.trials, v, sd) for k, v in D.items()}
        row = "  ".join("%9.2f%%" % vals[k] for k in D)
        extra = ""
        if "B" in vals and "A" in vals:
            extra = "   差 %+.2fpp" % (vals["B"] - vals["A"])
        print("  %5.0f%%   %s%s" % (p * 100, row, extra))
    print()
    print("=== 同一失败率(95%)下，会话长度的影响 ===")
    print("  轮数     %s" % "   ".join("%10s" % k for k in D))
    for n in [int(x) for x in a.len_list.split(",")]:
        vals = {k: simulate(0.95, n, a.len_trials, v, sd) for k, v in D.items()}
        row = "  ".join("%9.2f%%" % vals[k] for k in D)
        extra = ""
        if "B" in vals and "A" in vals:
            extra = "   差 %+.2fpp" % (vals["B"] - vals["A"])
        print("  %5d    %s%s" % (n, row, extra))
    print()
    print("注意：全部是**外推**（真实增量分布 + 指定失败率重采样），不是实测负载。")
    if not a.dist:
        print("说明：未换分布 → 用原版顺序随机流，A 列应当**逐位复现** E7-c 已发表的")
        print("      0.00/2.73/6.35/11.76/21.48/29.61/45.34/59.04/66.00。")
        print("      对不上就是重构引入了 bug —— 先查这个，再信 --dist 的结果。")
    else:
        print("说明：A/B 两列**共用种子 %d（配对）**，失败模式相同、只换增量分布，差值噪声更小。" % a.seed)
        print("      此时 A 列不再逐位等于 E7-c，只应**统计等价**（差 ~1pp 量级；曲线最陡处更大）。")
    if a.dist:
        print("判读：若 B 列在 95% 失败率处落到 ~49%，说明 E7-c 的高估**完全来自增量分布选错**，")
        print("      修好的外推器即可作为验证过的工具保留（E7-c 改写成「修正后外推」）。")
        print("      若 B 列仍 60%+，说明外推里还有第二个错，继续挖。")


if __name__ == "__main__":
    main()
