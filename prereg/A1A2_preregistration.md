# A1 / A2 预注册 —— 判据在**看到任何数据之前**写死
> ℹ️ **2026-10-05 目录整理**：本档只同步了内部引用路径（预注册档统一进 `week1/prereg/`、结果判读档统一进 `week1/results/`）；**判据、数字、结论一字未改**。

> **冻结时间**：2026-09-18（写完本文件即冻结；跑完不许回头改阈值）
> **冻结代码**（sha256 前 16 位，改一个字节本文件全部作废、需重写）：
> `e5_loop.py` = `7006ED537A8DB647`　`summarize.py` = `71778466DD1C7266`　`run_ablations.sh` = `FF3A011828455CBB`
> **冻结方式**：把这三个哈希抄进论文附录；跑完再核一次哈希 = 证明「判据先于数据」。

---

## 0. 要回答的两个问题

| | 问题 | 为什么它决定论文生死 |
|---|---|---|
| **A1** | 墓碑那一句 ~40 token，**值不值**？把 ours 里的墓碑拿掉（= `rollback`，即方案 §7.1 的 B3），正确率会不会掉回去？ | 现在只有 b0 一个对照 → 审稿人第一刀就是「你这就是把失败轮截断掉」。B3 是唯一能把这刀挡回去的对照。 |
| **A2** | 「你这就是截断」——**按失败丢** 与 **按新旧丢**（滑窗），在**同一每轮足迹**下谁的正确率高？ | 若滑窗在同一足迹下打成平手，本方案的机制主张不成立。 |

## 1. 臂（对应 `error_back.md` §7.1 的 2×2 + 滑窗基线）

| 臂 | `--mode` | 丢弃失败轮 | 墓碑 | 进上下文的失败轮形态 | 隔离出什么 |
|---|---|---|---|---|---|
| b0 | `b0` | ✗ | ✗ | assistant 动作 + 完整工具结果（含 3000 字符假 traceback） | 基线 |
| **B2** | `label` | ✗ | ✓ | 同上，**并在同一条 user 消息末尾多一行** `[TAG] ...` | **B2 − b0 = 标签单独的效应**（轨迹在场时那句话还有用吗） |
| **B3** | `rollback` | ✓ | ✗ | 无（`del msgs[ckpt:]`，不追加任何东西） | **b0 − B3 = 遗忘本身的效应** |
| **ours** | `ours` | ✓ | ✓ | 只有 `[TAG] act/target/err/n/world/advice` | **ours − B3 = 墓碑的效应 ← Table 1 核心格** |
| truncate-4/8/16 | `truncate --truncate-n N` | ✗ | ✗ | 与 b0 相同，但**发送前**只保留最近 N 条历史消息（system+任务钉住） | 按新旧丢 vs 按失败丢 |

**上下文语义已实测**（`week1/tools/test_modes.py`，离线，24 项全过；不需要 GPU 就能复核）：
b0 第 2 轮 = 4 条消息、无 `[TAG]`；ours = 3 条、只留 `[TAG]`；rollback = **2 条、与失败前那一刻逐字节相同**；
label = 4 条、有完整结果**且**有 `[TAG]`；truncate 每轮 ≤ 头部+n+2 且角色严格交替。

## 2. 命令（可粘贴）

```powershell
# 本地 → 服务器（服务器 ~/eb_probe/ 上不下载不安装）
scp D:\task\erro_back\week1\e5_loop.py D:\task\erro_back\week1\summarize.py D:\task\erro_back\week1\run_ablations.sh <server-alias>:~/eb_probe/
```

```bash
# 服务器：先 nvidia-smi 挑空闲卡起 vLLM（命令见 HANDOFF §2）。
#   必须带 --enable-prefix-caching --enable-prompt-tokens-details，否则 prefill/cached 两列没有
curl -sf http://127.0.0.1:18201/health && echo READY

cd ~/eb_probe
NSEED=4 NTRUNC=4 bash run_ablations.sh 2>&1 | tee abl_pilot.log   # ① 试水：量单跑耗时 + 看有没有报错
bash run_ablations.sh 2>&1 | tee ablations.log                    # ② 正式（20 seed，~110 次运行）

# 判读（两条：主表 + A2 的主对比）
~/miniconda3/envs/qwen_clean/bin/python summarize.py ablations_summary.txt --ref b0   --csv pareto.csv
~/miniconda3/envs/qwen_clean/bin/python summarize.py ablations_summary.txt --ref ours
```

## 3. 主终点与统计（写死）

- **主终点**：`correct`（0/1，规则式目标校验，同 E6）。**次终点**：每轮足迹 `Σintegral/Σturns`、`rejects`、`dup`。
- **检验**：Fisher 双侧精确检验，α = 0.05；正确率同时报 **Wilson 95% 区间**，两臂之差报 **Newcombe 95% 区间**（`summarize.py` 自动算）。
- **只认两个「主要」对比**，其余一律 exploratory（报 p，不主张显著性）——5 个臂做 10 次比较，不校正的话族错误率会到 ~40%：
  - **A1 主要对比**：`ours` vs `rollback`（N=20）
  - **A2 主要对比**：`ours` vs **足迹最接近 ours 的那一档 truncate**（预测 truncate-8；实际取 |foot − foot_ours| 最小者，并列取大 N）
- **配对**：同一批种子、**单批次内交错**（seed 外层 / arm 内层）运行。
  **不许**拿历史批次（E6 各批）的 b0/ours 数值当对照 —— 实验报告 E6 §4b 已证 temperature=0 下 b0 自己两批之间就会变。

## 4. 实现自检 —— 先过这一关，再解读正确率

跑完先看这 5 条；**任何一条不合 = 实现有 bug，停，不要去解读 correct**：

| # | 自检 | 期望 |
|---|---|---|
| 1 | 足迹单调 | foot(b0) > foot(truncate-16) > foot(truncate-8) > foot(truncate-4) **严格**成立（截断没生效就会相等） |
| 2 | 标签是纯增量 | foot(label) ≥ foot(b0) |
| 3 | 两个丢弃臂足迹接近 | abs(foot(ours) − foot(rollback)) / foot(ours) ≤ 15% |
| 4 | 丢弃确实省总量 | Σintegral(rollback) < Σintegral(b0)（rollback 失败后上下文冻结） |
| 5 | 分组没错位 | SUMMARY 里 wn：truncate 三档 = 4/8/16，其余 = 0 |

## 5. A1 判据（墓碑值不值）

**H1（论文要证的）**：rate(ours) − rate(rollback) ≥ 25pp **且** Fisher 双侧 p < 0.05。

| 观测 | 判定 | 论文动作 |
|---|---|---|
| ≥ 25pp 且 p<0.05 | **H1 成立** | Table 1 照写：墓碑的效应被量化，对照是 b0 与 B3 双基线 |
| 15 ~ 25pp | 方向对、势不够 | 补到 N=40 再判；**不改主张** |
| < 15pp（含负） | **墓碑无独立价值** | 主张改为「最小化失败噪声」；E6 的 55% vs 10% 仍成立（规划 §5 已备好对策） |
| rollback 比 b0 **差 ≥15pp 且显著** | **丢弃本身有害** | 机制重新定位：价值全在墓碑，不在丢弃 |

**机制签名（A1 真正要验的是这条）**：`dup` = 连续两轮出现同一 (工具, 参数) 的回合数。

- 预注册：dup(rollback) ≥ 3 × dup(ours) **或** dup(rollback) ≥ 0.5 × turns(rollback)。
- 成立 → 「无墓碑的纯回滚会字面重复」从**推断**升级为**实测证据**（现在它只是 `error_back.md` §7.1 表格里的一个括注）。
- **不成立** → 这条论证被自己的实验反驳，必须从 `error_back.md` §7.1/§9.7 删掉，改写成「丢弃后模型自己会换路」。

**预注册的方向性预测**：rate(rollback) ≤ rate(ours)，且 rate(rollback) ≈ rate(b0) 或更低（b0 至少还看得见失败痕迹）。

## 6. A2 判据（按失败丢 vs 按新旧丢）

画 6 个点 (foot, rate)：b0 / ours / rollback / truncate-4 / 8 / 16。

- **占优定义**：若存在某档 truncate 同时满足 foot ≤ foot(ours) 且 rate ≥ rate(ours) → **ours 被支配，主张不成立**。
- **主判据**：在 foot = foot(ours) 处对 truncate 相邻两档做线性插值得 rate_trunc*；
  - rate(ours) − rate_trunc* ≥ 20pp 且 ours vs 该档 p < 0.05 → 主张成立（「按失败丢」≠「按新旧丢」）
  - 10 ~ 20pp → 弱占优，补种子后再判
  - < 10pp → **无差异**，主张必须改成「墓碑 + 足迹」的复合论证，去掉「结构性更优」的说法

**预注册的方向性预测（可被反驳）**：
1. rate(truncate) 随 N **单调不减**（保留越多越接近 b0）→ 若某档反而更低，先查协议错乱，别急着解释。
2. foot(truncate) 随 N **单调增**（同时是 §4 的实现自检）。

## 7. 运行纪律

1. 中途**不许改** `e5_loop.py` / `summarize.py`；改了本文件作废，全批重跑（E6 §4b 的教训）。
2. 所有臂同参数：--scenario longtail --error-padding 3000 --max-turns 20。
3. 试水（NSEED=4 NTRUNC=4）先跑，确认无异常再跑全量。
4. 报错/掉服务的那几次不算样本：`run_ablations.sh` 末尾会核对 SUMMARY 条数，缺了就补跑缺的 (arm, seed)。

## 8. 跑之前先承认的弱点（不许事后找补）

1. **temperature=0 是消融臂的最大软肋**：rollback 的「字面重复」有相当部分是**贪心解码的必然**，真实系统多用采样 → 结论要限定在「确定性解码」下，写进 limitation。
2. 仍是**单模型（Qwen3-4B）+ 单一合成任务族（longtail）**，跨模型/跨负载未验证（阶段 B 才补第二个模型）。
3. N=20 下 **95% 区间极宽**：E6-d 的 11/20 是 [34.2%, 74.2%]、2/20 是 [2.8%, 30.1%]（Wilson）→ 即使 p<0.05，**效应量必须连同区间一起报**，不许只写「55% vs 10%」。
4. `integral` 是 **token·turn**，而方案 §7.2 头条指标要求 **token·秒**。本轮取法是**保守**的（b0 每轮 prefill 更长 → 换成 token·秒 b0 只会更差）；要正面对上 §7.2 需另加逐请求延迟记录 —— 本轮不做，写进 limitation。
5. `label`（B2）是我按 §7.1 补的臂，**不在原始的两条命令里**；不跑它不影响 A1/A2 判读，只是 2×2 会缺一格。
