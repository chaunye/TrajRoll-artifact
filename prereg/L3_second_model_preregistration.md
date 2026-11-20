# L3 预注册 —— 第二个模型重跑主批七臂
> ℹ️ **2026-10-05 目录整理**：本档只同步了内部引用路径（预注册档统一进 `week1/prereg/`、结果判读档统一进 `week1/results/`）；**判据、数字、结论一字未改**。

> 立此存照：2026-09-22。**判据、阈值与预测全部写在跑之前**，跑完不许改（改了就作废重跑）。
> 被回答的问题：严审意见 §9 L3 与正文 §8 限制 1 ——「单模型（Qwen3-4B）」是这套结论最容易被质疑的一环。
> 本文只写判据与跑法；**实验由用户亲手跑**（HANDOFF §3）。

## 0. 一句话

同一个 `e5_loop.py`（**一行不改**，哈希仍为 `843243FF0ECCD290`）、同一个 longtail 任务族、
同一套七臂与种子方案，只把**推理模型**换成第二个（建议 Qwen3-8B；备选走 API 的 B1 路线）。

## 1. 为什么要跑

- 论文 §8 限制 1 明写「success-rate 结果只在 Qwen3-4B + 单一任务族内成立」；
- 严审 §9 L3：15–20 min 机时就能补掉最便宜的一条致命质疑，「不补说不过去」；
- 判决档位：L3 完成后审稿模拟从「弱收（附条件）」升到「收（不附条件）」。

## 2. 前置条件（都有已知的坑，先看清再动手）

| # | 事 | 状态 / 坑 |
|---|---|---|
| 1 | **模型权重** | 服务器上 `Qwen/Qwen3-8B` 与 `DeepSeek/V2-Lite` 的 HF 目录只有 12 KB 空壳 → **需先下载**（服务器能上 modelscope/HF 镜像）。这是用户决策 + 用户操作 |
| 2 | **显存试跑（先做，5 min）** | Qwen3-8B bf16 权重 ≈ 16 GB，4090 只有 24 GB：40,960 窗口的 KV 大概率装不下 → 用 `UTIL=0.95` 试；仍不行就加 `MAXLEN=16384`。**longtail 沙盒任务的 prompt 全程 < 10k token**（E10 批实测 msgs 恒小），降窗口不影响本批有效性——这与 E9 回放（必须 40,960）不同 |
| 3 | **8B 也是思考型** | `e5_loop.py` 默认 `enable_thinking=False`，对 Qwen3 家族同样适用，无需改 |
| 4 | **引擎** | 仍用 vLLM（`PYTHONNOUSERSITE=1` 必带，见 serve 脚本注释）；SGLang 修好前别碰 |

## 3. 判据（先写死，N=20，**七臂同批、seed 外层**）

与 A1/A2 预注册同构，但**主判据只看方向与秩序，不看量级**（跨模型量级本就不可比）：

| # | 判据 | 通过条件 | 性质 |
|---|---|---|---|
| **H1（主）** | 方向复现 | ours 成功率 > b0，且 Fisher p < 0.05 | 主判据 |
| **H2（主）** | 2×2 秩序复现 | ours > label ≥ b0，且 rollback 为全批最低或次低 | 主判据 |
| H3（副） | 效率结构复现 | ours 每轮足迹 < b0；truncate-4 每轮重算 > ours（比值 ≥ 2×） | 只记录，单独不成结论 |
| H4（副） | 预注册自检门 | `check_ablations.py` 全绿（缺臂则记 SKIP） | 先于一切解读 |

**写死的解读规则**：
- H1+H2 都过 → §8 限制 1 收窄为「两个模型、一个任务族」；论文加一小段（≈5 行）+ 一张小表；
- 只有 H1 过、H2 乱序 → 如实报「方向复现、秩序未复现」，限制 1 不动，论文只加一句方向性证据；
- H1 不过（p ≥ 0.05 或方向反）→ **机制表述必须收窄为「在 Qwen3-4B 上成立」**，L3 结果照写不瞒。

## 4. 我的预测（写死；错了要在结果文件里写「我错在哪」）

- Qwen3-8B 的 b0 会**比 4B 的 5% 高**（模型更强，基线不该那么惨），预测 10–25%；
- ours 仍显著高于 b0（预测差 ≥ 20 pp），但差值**小于** 4B 的 50 pp（天花板效应）；
- rollback 仍接近 0%（确定性解码下的死循环与模型大小无关）。
- 证伪条件：若 8B 上 ours ≈ b0（差 < 10 pp 或 p ≥ 0.05）→ 「机制只在弱模型上有效」这一批评成立，须如实写入。

## 5. 跑法（服务器 `~/eb_probe/`；本预注册不起服务、不动显卡）

```bash
# 0) 备份旧日志（run_L3.sh 的 SUMMARY 是新文件名，但 ab_*.log 会覆盖——它先整体挪走）
cd ~/eb_probe && mkdir -p e10_l2_logs && mv -f ab_*.log ab_*.csv e10_l2_logs/ 2>/dev/null

# 1) 起第二个模型（先 nvidia-smi 挑空闲卡；试跑加 UTIL=0.95，仍不行加 MAXLEN=16384）
MODEL=/path/to/Qwen3-8B NAME=Qwen3-8B PORT=18202 CUDA_VISIBLE_DEVICES=<空闲卡> \
  nohup bash serve_qwen3_18201.sh > serve_8b.log 2>&1 &
curl -sf http://127.0.0.1:18202/health && echo READY

# 2) 七臂整批（seed 外层、臂内层）：140 次 ≈ 15–25 min（8B 约慢一倍）
bash run_L3.sh 2>&1 | tee l3_qwen3_8b.log

# 3) 先自检门，再看正确率（判读按本文 §3）
python check_ablations.py l3_qwen3_8b_summary.txt
python summarize.py l3_qwen3_8b_summary.txt --ref b0 --csv pareto_l3.csv

# 4) 拉回本地判读
# scp <server-alias>:~/eb_probe/l3_qwen3_8b_summary.txt D:\task\erro_back\week1\out\
```

`run_L3.sh` 与冻结的 `run_ablations.sh` 的**全部差别**：`--model` 与 `--base-url` 走环境变量
（后者把 base-url 写死成 18201 且 model 写死 Qwen3-4B，冻结文件不能改，故另起一个——
与 `run_ablations_sglang.sh` 同一先例）。循环结构、seed 顺序、SUMMARY 格式逐字对齐。

## 6. 冻结清单（跑之前算好，跑完复核）

| 文件 | SHA-256 前 16 位 | 说明 |
|---|---|---|
| `e5_loop.py` | `843243FF0ECCD290` | **不改**（= L2 版） |
| `summarize.py` | `71778466DD1C7266` | 不改 |
| `check_ablations.py` | `EA7F84C9D2D0CCFA` | 不改 |
| `run_L3.sh`（新） | 跑前自算并记在这里 → `90AE36FC0C675E86`（2026-09-22 实算） | 本次唯一新文件 |

论文补充材料 Appendix A 若采用本批，需按同样方式增量披露（第三个版本的先例已有两个）。

## 7. 结果出来之后

- 写 `week1/results/L3_结果.md`：主表 / 判据判定 / **预测对错与错因** / 对论文 §8 与 §5.2 的修改量；
- 论文改动按 §3 的解读规则执行（最小 = §8 限制 1 改一行 + §5.2 加半段）；
- 页数红线：当前恰好 10 页，**只能加不超过 8 行**，否则要等价删减。
