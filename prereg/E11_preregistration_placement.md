# E11 预注册 —— 放置位置消融（判据在**看到任何数据之前**写死）

> 冻结时间：2026-09-18
> 目的：把「**保留信息放在哪里，决定恢复是不是免费的**」从论证变成**实测**。
> 这是本文改写后的**核心主张**（见 `新颖性核查_2026-09-18.md` §4.4）。

---

## 0. 要回答的问题

回滚式恢复的**服务层代价**由什么决定？

已知（E10 实测）：从**队首**丢 → 每轮重算 ×5.3。
未知：把保留信息写进 **system prompt 并替换**（RIR 的放置方式）要付多少？

## 1. 三个臂（唯一变量 = 保留信息放哪）

| 臂 | `--mode` | 保留信息放在哪 | 相当于 |
|---|---|---|---|
| **A** | `ours` | 作为**最后一条消息**追加，system prompt 全程冻结 | 本文 |
| **B** | `sysend` | 写进 system prompt 的**末尾**并整体替换 | **RIR 的放置方式，且是它的最优位置** |
| **C** | `syshead` | 写进 system prompt 的**开头**并整体替换 | 最差位置 |

**三个臂的其他一切完全相同**：同一个 `base = SYS + runtag`、同样 `del msgs[ckpt:]` 丢弃失败分支、
同样的墓碑内容、同样的参数（`--scenario longtail --error-padding 3000 --max-turns 20`）。
**只有「那块累积信息放在哪」在变。**

（`build_sys(base, mem, where)` 保证 mem 为空时三个臂的 system **逐字节相同**。）

## 2. 主终点与判据（写死）

**主终点**：`prefill / turns` —— 每轮**真正重算**的 token 数（vLLM 实测，非估算）。
**次终点**：`integral`（KV-时间积分）、`correct`（成功率，exploratory）。

### H1（方向）—— 必须成立

    prefill/turn(ours)  <  prefill/turn(sysend)  ≤  prefill/turn(syshead)

**机制预期**：

- `ours`：system prompt 冻结、墓碑追加在末尾 → 前缀逐字节不变 → **近乎全命中**（E10 实测 65 token/轮）；
- `sysend`：记忆块位于**对话之前** → 链式块哈希断在记忆块 → **其后（任务 + 整段对话）全部重算**；
- `syshead`：记忆块在 system prompt **开头** → 连 system prompt 本身都不命中 → 重算量最大。

### H2（量级）—— 决定这条主张有多硬

    prefill/turn(sysend)  ≥  3 × prefill/turn(ours)

- **成立** → 「放置位置决定代价」被量化，且 **sysend 是 RIR 能拿到的最好位置，所以这是其代价的下界**；
- **不成立（< 3×）** → 说明链式哈希在 vLLM 里的断点效应比预期弱，**主张必须收窄成「方向一致但量级温和」**。

### 预测值（先写下来，跑完对）

| 臂 | 预测 prefill/turn | 依据 |
|---|---|---|
| ours | **约 65** | E10 实测 |
| sysend | **约 300~600** | 重算 ≈ 总 prompt − 记忆块之前的稳定前导 |
| syshead | **约 600~700** | 重算 ≈ 整个 prompt |

## 3. 实现自检（不过就不解读）

| # | 自检 | 期望 |
|---|---|---|
| 1 | `sysend` / `syshead` 的最终消息数 **少于** `ours` | 墓碑不占消息位 → `msgs_ours − msgs_sys = 失败次数` |
| 2 | log 里出现 `(sysend：保留信息进 system prompt 的末尾，块 N 行…)` | 三个臂的行为分支确实不同 |
| 3 | `ours` 的 system prompt 长度**恒定** | 它不该被改写 |
| 4 | 三臂的 `base`（`SYS + runtag`）逐字节相同 | `build_sys` 在 `mem` 为空时返回原 base（已单测） |

## 4. 复现步骤（可粘贴）

```bash
# 0) 服务器上起 vLLM —— ★ 必须带 PYTHONNOUSERSITE=1（见 HANDOFF §2 的 user-site 污染）
cd ~/eb_probe
PYTHONNOUSERSITE=1 CUDA_VISIBLE_DEVICES=<空闲卡> FLASHINFER_DISABLE_VERSION_CHECK=1 \
  setsid nohup ~/miniconda3/envs/qwen_clean/bin/vllm serve ~/.cache/modelscope/Qwen/Qwen3-4B \
  --served-model-name Qwen3-4B --port 18201 --gpu-memory-utilization 0.90 \
  --enable-prefix-caching --enable-prompt-tokens-details > serve.log 2>&1 < /dev/null &
until curl -sf -o /dev/null http://127.0.0.1:18201/health; do sleep 5; done; echo READY

# 1) 把新版 e5_loop.py 传上去（本地 → 服务器）
#    scp D:\task\erro_back\week1\e5_loop.py <server-alias>:~/eb_probe/

# 2) 跑三个臂（复用冻结的 run_ablations.sh，靠环境变量切换 —— 不用改冻结文件）
cd ~/eb_probe
NSEED=20 NTRUNC=0 ARMS="ours sysend syshead" SUMMARY=place_summary.txt \
  bash run_ablations.sh 2>&1 | tee place.log     # 60 次运行，约 8~10 分钟

# 3) 汇总
~/miniconda3/envs/qwen_clean/bin/python summarize.py place_summary.txt --ref ours
```

## 5. 本轮**不**声称什么

- **不声称「复现了 RIR」**：它的提示词模板与工具 schema 未公开（附录在 arXiv 各版本缺失），
  我们只量化**它所依赖的那个设计轴**。
- **不声称三个臂的任务成功率可比**：system prompt 变了，模型行为必然分叉。
  成功率只作 exploratory 报告。
- **`sysend` 不是 RIR 的真实实现**，而是**其放置方式的最优情形** → 测出的是其代价的**下界**。

## 6. 冻结记录

| 项 | 值 |
|---|---|
| `e5_loop.py`（E11 版） | `D487A8DD9729A73B` |
| `e5_loop.py`（A1/A2 批用过的旧版） | `7006ED537A8DB647` |
| `run_ablations.sh`（未改，用环境变量切换） | `FF3A011828455CBB` |

**关于哈希变化**：E11 是在旧版上**纯追加** —— 只加了 `build_sys` 辅助函数、`--mode` 的两个取值、
一行初始化、和一个失败分支的 `elif`。**旧版五个模式（b0/ours/rollback/label/truncate）的代码路径逐行未动**，
A1/A2 批的结果仍然对应旧哈希。这一点必须在论文里写明。

**离线自检已过**：`py_compile` 通过；`build_sys` 三条单测通过；
`--provider script` 下三个臂全流程跑通（sys 臂 18 条消息 vs ours 20 条，与「墓碑不占消息位」一致）。
