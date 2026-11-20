# 预注册 · E16 并发负载下的 placement 税（缩减版 R-3）—— 2026-10-05 起草

> **状态：FROZEN & EXECUTED（2026-10-05，作者授权"你来写你来跑"）。** v2 脚本 sha256[:16] = **`6c6b7eb086359c00`**（跑前 = 跑后 ✓；v1 `64a12d41a9e25cb0` 的缺陷与修订见 §8）。
> **K 集合（v2 probe 17:37 实测冻结）= {0, 3, 7}**；测量 17:38:17–17:43:19，120 records，6/6 格自检门 PASS。
> **判读：`week1/results/E16_结果_判读.md` —— P1/P2/P3 全部 ✅，退路口径未启用。** 执行环境：<server-host> GPU 1、端口 18203、vLLM 0.18.1；调度器参数（入披露）：Chunked prefill enabled, max_num_batched_tokens=2048；Asynchronous scheduling enabled。
> **缘起**：二轮审稿（review_ispa/ISPA审稿_二轮_2026-10-05.md §四 R-3）：E15 证明了 30k 尺度 placement 税（sysend−ours = 3.41 s vs 74 ms/更新），但**全部在单流下测**；§4.9 只有 ~700-token 尺度的四路共享数据（排序保持）。残余缺口精确为：**30k 的 placement 税没有并发负载下的对应测**。
> **作者决策（10-05）**：R-2 走定位策略不补实验；R-3 做本缩减版——只测并发下的 placement 税，**放弃 ≥60k 实测点**（E15 预注册已写明 40960 窗口为硬约束、84k 不可达、换长窗模型 = 「明确不做」的第三个模型；YaRN 扩窗会动 E15 超线性所在的注意力数学，不做）。可选：若 sizing 后窗口富余，加一格 ~38k（40960 内），边际成本 <1 天。
> **脚本**：`week1/e16_batched_placement.py`（作者自写）。冻结时填 sha256[:16] = `________`（跑前跑后必须一致）。

## 1. 问题

在 K 条稳态背景流的连续批处理下，30k 上下文里一次 memory update 的 victim TTFT 是多少：
**尾部追加墓碑（ours）vs system-prompt 内记忆槽替换（sysend）**？臂间排序是否保持、
差距是否随 K 缩小、背景流在哪一臂受扰更大？

## 2. 协议（冻结项）

- 服务：Qwen3-4B，vLLM 0.18.1，`--enable-prefix-caching --enable-prompt-tokens-details`，
  窗口 40960（不降），`UTIL=0.90`；**启动调度器参数（chunked prefill、max-num-seqs 等）原样记录进披露**。
- victim：L=30,000（按引擎 prompt_tokens 计，定标探针校到 ±2%），两臂 = E15 协议同款
  （同 filler、同 user turn、nonce 每 rep 换）：ours 尾部追加 ~45 token 墓碑；sysend 的
  [MEMORY] 槽每 rep 替换（~15 token nonce）→ 其后全部块失效。
- 背景流：K 条独立会话，各 4–8k 上下文、稳态 decode（max_tokens 足够长、温度 0）。
  **K 的确定**：正式测量前先跑 sizing probe——逐步升 K，用 `/metrics` 的 KV 缓存占用与
  `num_preemptions` 实测确定最大可行 K；**从 {0, 3, 7} 中取不触发 preempt 的最大子集**，
  probe 结果一经理出即把 K 集合写死，之后不得为任何显著性考虑调整 K。
  4090 24GB 下 30k victim 的 KV 本身占数 GB，K 可能到不了 7——**到几支几，如实声称**。
- 每格 = 1 warmup + **20 reps**（K=0 格兼作 E15 30k 的跨日复测一致性检查）。
- 测量口径与 E14/E15 相同：stream + `include_usage`；victim TTFT = 发出到首个 chunk 的毫秒；
  背景流 ITL = 逐 inter-token 延迟，报 p50/p99；recompute = prompt_tokens − cached_tokens。
- max_tokens=8（victim；背景流 decode 至 K 窗口结束）、temperature=0、`enable_thinking=False`。

## 3. 自检门（解释任何 TTFT 前必须过；不过 = 实现侧问题，判 void 并照登）

- ours 臂：20/20 rep 的 recompute ≤ 128 token。
- sysend 臂：20/20 rep 的 recompute ≥ 0.9 × L_actual。
- K>0 全程：`num_preemptions` = 0、无 OOM、无 abort；背景流在两臂的 prompt 完全一致（逐字节核对）。
- 抽查 1 条：ours 臂 recompute 与墓碑 nonce 文本长度同量级（40–90 token）。

## 4. 预注册判数（方向性预测，逐条 ✅/❌ 照登，❌ 照登不惩罚）

- **P1（排序保持，延续 E14-V2）**：每个实测 K 下，sysend median victim-TTFT > ours。
- **P2（差距不被摊平）**：最大 K 下 sysend−ours 的 median 差 ≥ K=0 差的 **50%**。
- **P3（背景流受扰不对称）**：同一 K 下，背景流 ITL p99 在 sysend 臂的劣化幅度 > ours 臂
  （各背景流相对自身 K=0 基线的 p99 增幅，臂间比较）。

**退路措辞（预注册，P2/P3 不成立时启用）**：wall-clock 差距被 chunked prefill 摊平，
但每更 30k 无效前缀的 prefill **算力照付**——改以 token/FLOP 口径报告
（recompute tokens per update：sysend ≈ L vs ours ≈ 墓碑），该口径与引擎调度无关，
serving-cost 主轴不受影响。

## 5. 红线

1. 判据冻结先于任何正式测量；冻结后不得修改判数、门槛或 K。
2. sizing probe 只看 KV 占用与 preempt，**不看任何 TTFT/ITL 读数**。
3. ✅❌ 全部照登，包括自检门失败与 K 不可行降档。
4. 声称范围如实收窄为「**小 K 连续批处理**」（与红线 4 的只许收窄一致），论文与披露不得写成
   「批处理下已验证」。

## 6. 论文落点（页数纪律：净增 ≈0）

- §6 现句（10-05 已改为过渡态）："four-way prefix-cache sharing preserves the between-arm
  ordering (§4.9), but the 30k-token placement tax has no concurrent-load counterpart" ——
  E16 判读后**替换**为实测数字与范围声明（如 "under K-stream batching the 30k placement tax
  persists: sysend−ours = X s at K=Y" 或启用退路口径），不叠加新句。
- §4.9 尾部或 §4.10 的 E15 段补一句 E16 指针（约 1 行），同步压缩 E15 段内等量文字。

## 8. 修订记录（判数零改动）

- **v1** sha256[:16] `64a12d41a9e25cb0`（10-05 17:33 probe 运行版）。probe 结论 K=7 可行，但解析器把 Prometheus 的
  `num_preemptions_created`（时间戳序列，1.79e9）误计入 preempt 求和——**审计行证明两次读数的
  `num_preemptions_total` 均为 0.0，probe 结论有效**。v1 的 measure 在 K=0 格即崩溃（window 字典未初始化），
  **任何测量数据都未产生**。
- **v2** sha256[:16] `6c6b7eb086359c00`（当前有效版）。两处修正：① preempt 计数只匹配
  `num_preemptions_total`、显式排除 `_created` 序列；② K=0 时 window 初始化。判数（P1/P2/P3）、
  自检门、协议、红线均逐字未动。
- probe 在 v2 下**重跑**（clean 解析），K 集合以 v2 probe 为准。

## 7. 排期（2026-10-05 定）

| 日 | 事项 |
|---|---|
| 10-06 | 作者确认判数 + 交付驱动脚本 + 填 sha256 + sizing probe 定 K → **冻结** |
| 10-07/08 | 正式测量（预计 ≤1 晚机时，E15 为 200 格一晚的参照） |
| 10-09/10 | 判读写回 week1/results/，论文 §6/§4 替换 + 重编译（10 页复测） |
| 10-11/12 | 三轮评审 + 收口；10-13 前全部结束，留 2 天缓冲到 10-15 截稿 |

**并行提醒（作者动作，有前置期）**：κ 的第二人类标注者现在就要开始约人（二轮档 §五 的排序里
κ 是性价比最高的一项，且找人本身要时间）；约到后按 E9-d 的冻结 rubric 复标 130 条即可对接
现有打分管线（`week1/e9d_score.py --csv ...`）。
