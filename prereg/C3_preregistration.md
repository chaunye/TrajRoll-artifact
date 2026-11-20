# 预注册：C 类解禁三实验（E12 安慰剂阶梯 / E13 采样复核 / E14 TTFT）
> ℹ️ **2026-10-05 目录整理**：本档只同步了内部引用路径（预注册档统一进 `week1/prereg/`、结果判读档统一进 `week1/results/`）；**判据、数字、结论一字未改**。

> **✅ 已跑完并判读（2026-10-04）**：判据自冻结起**未改一字**；判定 = E12 → **H-C**、E13 → **S-B**、
> E14 → **V1 ✗ 照登 / V2 ✓ / V3 ✓**。逐条对表见 `week1/results/C类解禁_结果_判读.md`；
> 数据 `week1/out/c3/`。E13 门#3 的 FAIL 按 L3 先例判「判据侧」并在判读文档披露。

> 立此存照：**2026-10-03，判据在任何一次运行之前写死**（项目铁律：验收标准跑之前冻结）。
> 背景：用户于 2026-10-03 **解除「不再为投稿加实验」红线**（原红线 = 规划.md §8 / HANDOFF §8.1-1，
> 系 09-18 的日程性纪律）。解除后按五席评审 C 类清单分诊，只做三个有明确证据价值的实验；
> lazy-recall 臂 / 富记忆臂 / 500 条双标注仍不做（理由见 §6）。
> 依据：`paper/ARS五席评审_2026-10-03.md`（Persp W4、Meth W2/W6、DA M6、EIC W2、Domain W3、Persp W1/W3）。

---

## 0. 代码变更与冻结哈希（先例：L2/L3 的加性披露）

`week1/e5_loop.py` 冻结哈希 `843243FF0ECCD290` → **本次加性改动后 `B94A3B41131496DB`**。
改动全部加性：新臂 `placebo` / `generic`、`--temperature`（默认 0.0 = 原行为）、`--stream`（默认关）。
**既有模式逐字节等价**：本机 script-provider 冒烟 6 臂（b0/ours/rollback/worldonly/placebo/generic）
全过，ours 在 n=2 仍触发 advice、worldonly 不触发、placebo 的 world 内容为常数
`(no environment facts recorded)`、generic 为常数墓碑。新哈希跑完后照 L2/L3 先例记入补充材料 Appendix A。
**五个既有模式一行未动**（advice 门从 `!= "worldonly"` 改为 `not in ("worldonly","placebo","generic")`，
对既有模式行为恒等）。

服务器侧要求：**不装不下载**；vLLM 0.18.1 + Qwen3-4B 原服务（18201）照旧；
每批跑前 `nvidia-smi` 确认空闲卡。三个实验总机时 ≈ **25–35 min**。

---

## 1. E12 · 安慰剂阶梯（Persp W4 / Meth W4 的等值 rival）

**问题**：§5.3/§6.2 说「accuracy 效果在 world facts 上存活（N=20 无差别）」。对手解释：
起作用的是**随便一个紧凑的尾部标记**（recency/compactness），不是 world 内容。这是五席评审
唯一建议解禁的实验。

**设计**：同 E10/L2 口径（longtail、error-padding 3000、max-turns 20、temp 0、seed 外层臂内层交错、
**一个批内**）。五臂阶梯，每层只多一层内容：

| 臂 | 丢弃 | 墓碑内容 | 隔离层 |
|---|---|---|---|
| b0 | ✗ | — | 基线 |
| generic | ✓ | `[TAG] The previous turn made no progress and has been discarded.`（常数，≈12 tok，最短） | 「有没有任何尾部标记」（recency/compactness 的最强形态） |
| placebo | ✓ | act/target/err/n + `world=(no environment facts recorded)` | 「metadata 结构」 |
| worldonly | ✓ | act/target/err/n + 真实 world | 「+ world 内容」 |
| ours | ✓ | 全字段（含 advice/strategy/reset） | 「+ 计数器提示」（复现 L2 形态用） |

NSEED=20 → **100 次运行 ≈ 8–10 min**。批内 b0/worldonly/ours 重跑是为了配对（**跨批不比**，
L2 批数字只在叙述中作历史值）。墓碑长度差异（generic 更短）是设计的一部分，写论文时披露。

**判据（跑前冻结）**：主对比 = placebo vs worldonly、generic vs worldonly（Fisher 双边 α=0.05），
配 15pp 方向带判读（与 A1/A2/L2 同款纪律）；N=20 功效有限，中间态一律报区间不站队。

- **H-A（world 内容承载）**：placebo 显著低于 worldonly（或点差 ≥15pp 同向）且 generic 同向更低
  → §5.3/§6.2 主张**升格**为 placebo-controlled（"the world-fact content, not mere compactness,
  carries the effect"）；Persp W4 关闭，论文加 E12 半段（≤8 行）。
- **H-B（任何紧凑标记即可）**：generic ≈ worldonly（n.s.）→ **「world fact carries the effect」被推翻**
  （照登为第 6 条被推翻预测），§5.3/§6.2/abstract 改写为 "a compact end-of-context marker suffices;
  the rule-extracted content is not the active ingredient"——这不是失败，是 A1 同款的发现。
- **H-C（结构承载、内容不承载）**：generic < placebo ≈ worldonly → 改写为 "the structured record
  (act/target/err) carries it; world facts add nothing beyond"。
- **附带读出**：dup（字面重复）、rejects、turns —— 内容层对盲试/徘徊的影响。

## 2. E13 · 采样复核（Meth W2 / DA M6：temp-0 塌陷是不是 artifact）

**问题**：§5.3 的 discard-only 0/20 塌陷被自己归因于 temperature-0 确定性重发（§8.4），
因此「independently reproduces」降级成了「corroborates」。采样下 rollback 若仍不足，
2×2 结论就不依赖解码方式。

**设计**：**temperature=0.7**（`--temperature 0.7`，vLLM 默认 top_p=1.0，不加其他采样参数——
写死，免得事后挑参数），三臂 b0 / rollback / ours × 20 seeds = **60 次 ≈ 6–8 min**，
同 longtail 口径、一个批、seed 外层。b0 必须重跑：采样也改变基线，禁止拿 temp-0 的 b0 比。

**判据（跑前冻结）**：
- **S-A**：rollback(0.7) 仍 ≤15% 且 ours−rollback ≥20pp（Fisher α=0.05）→ 2×2 结论**不依赖确定性解码**；
  §5.3/§8.4 的 caveat 改为"已在 temp 0.7 复核"；§1.4/abstract 的「corroborates」保持，但删去
  decoding-specific 的让步从句。
- **S-B**：rollback 逃逸（>15%）但仍 < ours → 如实报；necessity 主张弱化为
  "discard alone is insufficient at both temperatures"。
- **S-C**：rollback ≈ ours → **中心 2×2 主张在采样下塌**（照登为第 7 条被推翻预测），
  §5.3/§6.2/abstract/§9 按预注册收窄为 "necessary under deterministic decoding"。

## 3. E14 · TTFT 微基准（EIC W2 / Domain W3 / Persp W1、W3：没有 serving 单位）

**问题**：全文只有 token 账。评审最大共识弱点（4/5 席）。最小可信版：**真实 agent 负载**
（同一个 longtail 任务族）下逐轮 TTFT 实测 + tokens→时间标定 + 4 路并发共享。

**设计**（`--stream`，SUMMARY 口径不变，TTFT 另起行）：
- **阶段 1（单流）**：三放置 ours / sysend / truncate-4（--truncate-n 4）× 20 seeds = 60 次 ≈ 6–10 min，
  temp 0，逐轮记录 `(TTFT, prefill_tokens)`。
- **阶段 2（4 路并发）**：同一批拆 4 份进程同时跑（共享同一 vLLM 前缀缓存池）→ 4-way 下的 TTFT。
  E14 是性能基准不做正确率比较，配对纪律只用于批内。

**判据（跑前冻结）**：
- **V1**：三臂 TTFT 中位数排序与逐臂 recomputed-prefill 排序**一致**（预期 ours < sysend < truncate-4）
  → 论文 §4.4/§5.4 加「TTFT 实测」段 + tokens→ms 标定斜率；"recomputed prefill" 轴获得时间轴。
- **V2**：4-way 下 TTFT 绝对值上升、排序保持 → 单租户限定放宽为 "ordering preserved under 4-way
  cache sharing"；排序翻转 → 照登（并发下前缀缓存失效的诚实发现）。
- **V3**：Pearson r(TTFT, prefill) 与 95% CI（Fisher z），作为 token↔时间桥。
- **风险预案**：`--stream` 路径拿不到 usage 会**硬报错**（已实现，拒绝静默降级）；
  若 vLLM 0.18.1 不支持 `stream_options.include_usage` → 备选：改读 vLLM `/metrics` 的
  `ttft` 直方图（预注册此备选，判据不变）。

---

## 4. 自检门（跑前写死，跑完先过门再解读）

1. 每臂 SUMMARY 行数 = 20/20（服务掉线即停，保留已有 SUMMARY）。
2. SUMMARY 字段完整；`correct∈{0,1}`；`turns ≤ 20`；`seed 1..20` 各一次。
3. **形态对照（非跨批比较）**：ours 足迹 ~666 量级、b0 ~2,443 量级、rollback 最低——偏离量级
   先查实现再解读。
4. E12 五臂同 seed 的沙盒文件名相同（seed 驱动沙盒 → 任务可比）。
5. `check_ablations.py` 的通用不变量跑一遍存档；臂专属判据按本文档覆盖。

## 5. 论文写回纪律

- 每个实验无论结果落在哪个假设档，**都写进论文**（被推翻照登先例：§1.5/§8.9）。
- 版面上限：E12/E13/E14 合计新增 ≤ 25 行（届时再复核 10 页；必要时按 §8 的等价增删再换版面）。
- 判读文档：`week1/results/C类解禁_结果_判读.md`（跑完写），格式沿 `week1/results/L3_结果.md`。

## 6. 明确不做（红线解除 ≠ 全做）

- **lazy-recall 臂 / 富记忆（tail-appended rich memory）臂**：开新设计轴，不是补弱点，
  留 §6.3 展望。
- **500 条双标注 kappa**：需要第二个**人类**标注者（AI 标注不能算，那是学术不端线）；
  你找同学/导师标 100 条即可，与机时无关。
- **多租户 E2 全量重做**：E14 阶段 2 的 4-way 已覆盖最小版本。
