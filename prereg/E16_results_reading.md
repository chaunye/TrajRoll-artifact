# E16 结果判读 · 并发负载下的 placement 税（缩减版 R-3）

> **预注册**：`week1/prereg/预注册_E16_并发placement税_2026-10-05.md`（v2 冻结，判据先于数据）
> **脚本**：`week1/e16_batched_placement.py` sha256[:16] = **`6c6b7eb086359c00`**（跑前 = 跑后 ✓）
> **环境**：<server-host> GPU 1，端口 18203，Qwen3-4B，vLLM 0.18.1，`--max-model-len 40960 --gpu-memory-utilization 0.90 --enable-prefix-caching --enable-prompt-tokens-details`
> **调度器参数（预注册要求入披露）**：Chunked prefill enabled, `max_num_batched_tokens=2048`；Asynchronous scheduling enabled
> **数据**：`week1/out/e16_batched_placement.json`（120 records = 6 格 × 20 reps；probe：`e16_sizing_probe.json`）
> **时间线**：sizing probe（v1 `64a12d41a9e25cb0`，解析器缺陷见预注册 §8；v2 重跑通过）17:37 → 正式测量 17:38:17–17:43:19（JSON 的 `finished_at` 字段实为启动时间戳——v2 字段命名瑕疵，起止以日志/mtime 为准，不影响数据）

## 0. 一句话结论

> **placement 税不是单流伪影：7 流连续批处理下，30k 一次 system-prompt 替换更新的代价 3.53 s vs 尾部追加 93 ms，臂间差 3.44 s 且不随 K 收窄；背景流的 p99 ITL 在替换臂劣化 ~15–21×。三项预注册判数 P1/P2/P3 全部 ✅，退路口径未启用。声称范围如实收窄为「小 K（K≤7）连续批处理、单 victim」。**

## 1. sizing probe（冻结 K 集合 = {0, 3, 7}）

- probe 只读 `/metrics`，不看任何延迟读数（红线 2 ✓）。
- K=7：7 条 4k 背景流稳态 + 一次 30k dummy prefill 压测，`num_preemptions_total` 增量 = 0.0 → 可行。
- K 集合按规则取 {0, 3, 7}，测量前写死（v2 probe，baseline 0.0 干净读数）。

## 2. victim 结果（median TTFT ms，N=20/格，6/6 格自检门全 PASS）

| 格 | ours | sysend | 差（sysend−ours） | ours recompute | sysend recompute |
|---|---|---|---|---|---|
| K=0 | 79.4 | 3,453.5 | **3,374.1** | 31–34 tok | 29,930–29,934 |
| K=3 | 82.9 | 3,524.2 | **3,441.3** | 33–36 | 29,931–29,934 |
| K=7 | 92.5 | 3,533.0 | **3,440.5** | 28–45 | 29,597–29,602 |

- **K=0 复测 vs E15**：ours 79.4 vs 74.3（+7%，跨日一致性可接受）；sysend 3,453.5 vs 3,408.3（+1.3%）——预注册的复测一致性检查 ✓。

## 3. 预注册判数

| # | 判据 | 读数 | 判定 |
|---|---|---|---|
| **P1** | 每个 K 下 sysend median > ours（排序保持，延续 E14-V2） | K=0/3/7 下 3453.5/3524.2/3533.0 均 > 79.4/82.9/92.5 | **✅** |
| **P2** | 最大 K 的差 ≥ K=0 差的 50%（差距不被摊平） | 3,440.5 / 3,374.1 = **102%**（绝对差还略增 ~66 ms：批处理调度对 sysend 的 30k 重算多排 ~80 ms，对 ours 只多 13 ms） | **✅** |
| **P3** | 同 K 下背景流 ITL p99 在 sysend 臂劣化更大 | K=3：p99 中位 2,909 vs 137 ms（**21×**）；K=7：2,500 vs 169 ms（**15×**）；p50 两臂接近（14 vs 16 / 19 vs 21 ms）——劣化集中在尾部，正是 30k 重算挤占调度的形状 | **✅** |

**退路口径未启用**（P2/P3 成立）。token/FLOP 口径备查：每更重算 tokens sysend ≈ 29.9k vs ours ≈ 33，比值 ~900×，与引擎调度无关。

## 4. 论文写回（页数纪律：净增 ≈0）

- §6 的过渡句（10-05 早前设的占位）替换为 E16 实测：排序保持、差 3.44 s 不随 K 收窄、背景流 p99 劣化 ~15×；其余延迟数字维持"interference-free"限定。
- §4.10 E15 段补一句 E16 指针（等量压缩段内文字）。
- 范围句（§6）：批处理证据限定为 **small-K（K≤7）continuous batching, single victim**；K>7、多 victim、更大模型 = 未测，如实不声称。

## 5. 遗留与备注

- `finished_at` 字段 = 启动时间戳（v2 瑕疵，已如上注明；起止以日志首行 + JSON mtime 为准）。
- v1 probe 的解析器缺陷与审计证据见预注册 §8（`num_preemptions_total` 两次读数均为 0.0，v1 probe 结论有效，但按纪律以 v2 重跑为准）。
- 服务已关（GPU 1 释放）。
