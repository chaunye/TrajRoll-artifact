# 预注册 · E15 placement-TTFT 真实尺度实测（2026-10-04，判据先于数据冻结，跑后不许改）
> ℹ️ **2026-10-05 目录整理**：本档只同步了内部引用路径（预注册档统一进 `week1/prereg/`、结果判读档统一进 `week1/results/`）；**判据、数字、结论一字未改**。

> **缘起**：ISPA 版第三轮五席评审 DA-C1（裁决=部分成立）：§5.5 的 "seconds per memory update" 是把
> E14 桥（0.02–0.05 ms/tok，~700-token 尺度）外推 ~121× 的算术，**外推终点从未被测量**（5,512-turn replay
> 只回放 tail-append 臂）。席4-M1 同向。本实验 = 测出 placement 税的真实尺度端点。
> **授权**：用户 10-04 明确指示 AI 代跑（推翻 §3「不代跑」默认，仅限本实验）；红线 §8.1-1 的预注册流程照走。
> **脚本**：`week1/e15_ttft_scale.py`，冻结 sha256[:16] = **`261ec21540b92a2c`**（跑前跑后必须一致）。

## 1. 问题

在受控的真实尺度上下文长度下，一次 memory update 的 TTFT 是多少：
**尾部追加墓碑（ours）vs system-prompt 内记忆槽替换（sysend，即 RIR 的 placement [5]）**。
新自变量 = 上下文长度 L（E14 只测了 ~700 token 的合成任务尺度）。

## 2. 协议（冻结）

- 服务：Qwen3-4B，vLLM 0.18.1，`--enable-prefix-caching --enable-prompt-tokens-details`，
  窗口取模型自带 40960（不降），`UTIL=0.90`，**只用空闲卡（10-04 实测 = GPU 5）**，端口 18203。
- 两臂，同 filler、同 user turn，只变更新方式（nonce 每 rep 换，uuid hex）：
  - **ours**：system prompt 字节不变；user 内容 = filler + 尾部追加一条 ~45 token 墓碑（每 rep 换）。
    前缀逐字节不变 → 每 rep 只重算墓碑。
  - **sysend**：system prompt 内 [MEMORY] 槽每 rep 替换（nonce 文本 ~15 token）→ 其后全部块失效。
- L ∈ {4000, 8000, 16000, 24000, 30000}（按引擎 prompt_tokens 计，定标探针校到 ±2%）。
  30000 上限由 40960 窗口给定（与 E9 replay 的 <30k 峰值口径一致）；**84k 平均值不在本实验可达范围**
  （窗口硬约束，坑 10；换长窗口模型 = 「明确不做」的第三个模型）。
- 每格 = 2–4 次定标探针 + 1 warmup + **20 reps**（N=20 与全部既有批一致）。
- 测量口径与 E14 相同：stream + `include_usage`，TTFT = 发出到首个 chunk 的毫秒；
  recompute = prompt_tokens − cached_tokens（cached 为 0 时字段缺省按 0 计，坑 1）。
- max_tokens=8、temperature=0；`enable_thinking=False`（400 则回退，与 e5_loop 同）。
- **范围声明（写进论文的口径）**：本实验测的是**引擎物理**（失效前缀长度 → TTFT），filler 为受控文本，
  不承载工作负载语义；轨迹保真度由 5,512-turn replay 另行承担（算术验证）。单流测量，
  批处理调度干扰不在范围内（§7 已列）。

## 3. 自检门（解释 TTFT 前必须过；门不过 = 实现侧问题，该格 void 并照登）

- ours 格：20/20 rep 的 recompute ≤ 128 token。
- sysend 格：20/20 rep 的 recompute ≥ 0.9 × L_actual。
- 抽查 1 条：ours 的 recompute 与墓碑 nonce 文本长度同量级（40–90 token）。

## 4. 预注册读数（方向性预测，逐条 ✓/✗，✗ 照登）

- **P1（ours 平坦）**：ours median TTFT 在 L=4k 与 L=30k 之差 ≤ 20 ms（截距噪声量级）。
- **P2（sysend 线性上升）**：sysend median TTFT 随 L 单调上升，且 L=30k 处 sysend − ours ≥ 300 ms。
- **P3（数量级）**：L=30k 处 sysend − ours ∈ [0.3 s, 3.0 s]
  （E14 桥 0.02–0.05 ms/tok × ~30k 失效 ≈ 0.6–1.5 s 的预测带，放宽至 3 倍带宽）。
- 判读：三门全过 → 桥被实测锚定，论文 §5.5/§8 的 "seconds" 从纯外推升级为「实测 ≤30k 端点 + 84k 外推」；
  任一 ✗ → 照登并收窄相应表述（若 P3 下界跌破，"seconds" 降级为实测数字本身）。
- 无显著性检验（测量性实验，非假设检验）；报告 median/p25/p75。

## 5. 写回模板（以实测数字填充）

- §5.5："…seconds per update as an order-of-magnitude extrapolation of the measured bridge (the
  extrapolated endpoint is unmeasured, §7)…" → "…**measured directly at controlled context lengths up to
  30k tokens (E15: sysend update median <X> vs. tail-append <Y>; N=20)**, extrapolated beyond to the 84k
  average (§7)…"。
- §8：同步替换 "by order-of-magnitude extrapolation … at real-session scale"。
- §7 item 6 保留（batching 干扰仍未覆盖）。
- 预算：全文行数中性（替换句 +1–2 行，8 页贴边需复测）。

## 6. 明确不做

- 不加第三臂、不加 30k 以上尺度、不换模型、不做显著性检验、不动冻结脚本（e5_loop.py 等哈希不变）。
- 本实验**不改** §5.2–5.4 任何既有数字；只替换 §5.5/§8 的外推表述。

## 7. 执行记录（跑后回填）

- 服务器：<server-host>，GPU 5（空闲，15 MiB），端口 18203，serve 日志 `~/eb_probe/serve_e15.log`。
- 结果：`~/eb_probe/e15_ttft_scale.json`（副本 `week1/out/e15_ttft_scale.json`，sha256[:16] `99fd5ecfbef82ef8`）→ 判读档 `week1/results/E15_结果_判读.md`。
- **状态：✅ 已执行（2026-10-04）**。脚本跑后哈希 = 冻结值 `261ec21540b92a2c` ✓；10 格自检门 **10/10 PASS**（ours recompute 28–44 tok ≤128；sysend recompute 4,035–29,768 ≥ 0.9×L）。
- **读数**（median TTFT ms，N=20/格）：ours 23.5/32.0/48.5/62.1/74.3（4k→30k）；sysend 245.1/549.8/1390.2/2470.8/3408.3。
- **判定**：P1 ✗（ours 差 50.8 ms > 20 ms——TTFT 含对全部已缓存 KV 的注意力，随 L 增长；74 ms 仍可忽略）；P2 ✓（sysend 严格单调，@30k 差 3,334 ms ≥ 300 ms）；**P3 ✗（超上界）**：3.33 s > 3.0 s——实测边际 0.061→0.115 ms/tok（注意力超线性），线性桥低估 ~2.1×。
- **净结论**：placement 税真实尺度实测 **3.4 s @30k vs 74 ms（46×）**；线性桥方向正确但低估——placement-rule 主张**加固**；P1/P3 两条 ✗ 按纪律计入论文 refuted 清单（7→9）并照登。
- 论文写回：§5.5（实测句替换外推句）、§8、§5.4（桥非常数）、§1 P5/§1.5/§7-9（计数 7→9）、§4.4（第三份预注册）、§4.5（五辅助批）。重编译 **8 页全绿**，sha256[:16] `dd27f811071af51e`。服务已关（GPU 5 释放）。
