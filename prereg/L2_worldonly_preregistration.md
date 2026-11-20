# L2 预注册 —— `worldonly` 臂（墓碑里只留 world）
> ℹ️ **2026-10-05 目录整理**：本档只同步了内部引用路径（预注册档统一进 `week1/prereg/`、结果判读档统一进 `week1/results/`）；**判据、数字、结论一字未改**。

> 立此存照：2026-09-19。**判据、阈值与我的预测全部写在跑之前**，跑完不许改（改了就作废重跑）。
> 被回答的问题：`paper/严审稿人意见_2026-09-19.md` 的 **F2**。

## 0. 一句话

`ours` = 丢弃 + 墓碑(**world + advice/strategy/reset**)；`worldonly` = 丢弃 + 墓碑(**只有 world**)。
两个臂**只有墓碑文本不同**：丢弃逻辑、计数器状态、沙盒、种子、轮数上限全部逐位一致。

## 1. 为什么要跑（F2 原文）

审稿人核了 `e5_loop.py` 后指出：墓碑里除了世界事实，还有**规则注入的行为指令** ——
每累计 5 次失败**无条件**追加一句「停下来：先用 list_dir 把仓库结构完整列一遍，再选最小的可行步骤，
不要继续猜路径」。而 §6.2 把全文结论重述为「真正改变 agent 行为的是**关于世界的那一行字**」。
在 `world` 与那句指令从未分开消融之前，这个结论**没有证据**。

## 2. 臂与实现（已完成的代码改动）

- `--mode worldonly`：走**与 ours 同一条**丢弃分支（`del msgs[ckpt:]` + 追加墓碑）；
- 差别只在墓碑文本：`advice=`（同一调用失败 ≥2 次）、`strategy=`（同类失败达阈值）、
  `reset=`（每 5 次失败无条件）**三个字段都不再写入**；
- **计数器照常推进**（`seen` / `fails_total` 在两条臂里都更新）—— 否则两臂状态不一致，消融不干净；
- 墓碑仍保留 `act / target / err / n / world`。**口径先写死**：`n` 是本轨迹自己的失败计数读数
  （事实侧），不是行为指令，所以两个臂都留。若审稿人认为 `n` 也算提示，那是另一个消融，不在本轮。
- 离线自检：`python week1/tools/test_modes.py` → **30/30 PASS**，其中 6 条是本次新增：
  两臂消息结构逐位一致 / ours 墓碑含 `advice` 与 `reset` / worldonly 三者皆无 / worldonly 仍含 `act,world,n` /
  两臂墓碑文本确实不同。（跑之前的绿灯，不代表真机结果。）

## 3. 判据（先写死，N=20，**三臂同批**）

参照点必须来自**同一批**：`ARMS="b0 ours worldonly"`，禁用历史批次的 b0/ours（E6 §4b 已证
temperature=0 下 b0 自己两批之间就会变）。

二项噪声：N=20、p≈0.5 时 **1 SE ≈ 11 pp**。

| 分支 | 条件（worldonly 成功数 /20） | 判决 | 论文动作 |
|---|---|---|---|
| **A · world 足够** | **≥ 8**，且与同批 ours 相差 ≤ 15 pp | world 字段**独立**承载效果 | §6.2 可升级为本文的机制发现；F2 消解，把本批作为新证据写进补充材料 |
| **B · 共同承载** | **4 – 7** | world 必要但**不充分**，规则提示另贡献一部分 | §6.2 改写为「两部分都有贡献」并报出精确数字；不重写全文 |
| **C · 指令才是关键** | **≤ 3**（= label 15% / b0 5% 档） | 机制实为**规则触发的进展重置通道**，墓碑只是载体 | 按 F2 预案重写 §2.4 / §6.2 / 摘要 / 结论，承认 world **必要而非充分**（2–3 天写作） |

阈值依据（E10 同批七臂实测）：b0 = 5%（1/20）、label = 15%（3/20）、rollback = 0%（0/20）、
ours = 55%（11/20）。8/20 = 40% 是「相对 55% 不超过 1.4 SE」；3/20 = 15% 是「塌到 label/b0 档」。

**副判据（只记录，单独不成结论）**：
- 每轮足迹与每轮重算：worldonly 应与 ours 同量级（约 600–750 / 50–90），
  **不应**像 rollback 那样冻结在 5,708–5,807；
- `dup`（字面重复）：worldonly 不应回到 rollback 的 ~360；
- 工具失败极差。

## 4. 实现自检（跑完**先过这个**再看正确率）

| # | 检查 | 期望 |
|---|---|---|
| 1 | SUMMARY 里 `mode=worldonly` 的条数 | = 20 |
| 2 | 逐文件 `grep -c 'advice=' ab_worldonly_s*.log` | 全为 0 |
| 3 | 逐文件 `grep -c 'reset=' ab_worldonly_s*.log` | 全为 0 |
| 4 | 逐文件 `grep -c 'world=' ab_worldonly_s*.log` | > 0 |
| 5 | **反证**：`grep -c 'advice=' ab_ours_s*.log` | > 0（否则说明这批的 ours 也没发 advice，消融没意义） |
| 6 | 消息结构一致（离线已验，见 §2） | 同一脚本下两臂 msgs 逐位一致 |

任一条不过 → **先查实现，别解读正确率**，也别拿这批数改论文。

## 5. 我的预判（写死；错了要在结果文件里写「我错在哪」）

- 预测 worldonly **8–12/20**（落在分支 B）。理由：`reset` 是在模型卡住时**明确说**
  「停下来、先 list_dir、不要继续猜路径」的行为指令，很可能承担了一部分推进作用；
  而 `world` 的作用是不让模型字面重发（把 0/20 的 rollback 拉起来）。
- 预测 worldonly 的足迹与 ours **同量级、不冻结**。
- **证伪条件**：若 worldonly ≥ ours（分支 A），说明我给 `reset` 的权重过高 →
  必须在结果文件里如实写出错因，而不是把预测悄悄改掉。
- 另一侧的证伪：若 worldonly ≈ rollback（0–1/20）**且**足迹像 rollback 一样冻结，
  则"world 字段足以打破字面重复"这一说法也被推翻 → 分支 C。

## 6. 跑法（服务器 `~/eb_probe/`；本脚本**不起服务、不动显卡**）

```bash
# 0) 先备份旧日志 —— run_ablations.sh 会覆盖同名 ab_*.log
cd ~/eb_probe && mkdir -p e10_logs && cp -n ab_*.log ablations_summary.txt pareto.csv e10_logs/ 2>/dev/null

# 1) 服务（若没在跑；45 秒就绪）。CUDA_VISIBLE_DEVICES 必须显式给，先 nvidia-smi 挑空闲卡。
#    脚本内部已经 export PYTHONNOUSERSITE=1（不设会因 ncclCommResume 起不来），不用重复给。
CUDA_VISIBLE_DEVICES=1 nohup bash serve_qwen3_18201.sh > serve.log 2>&1 &
curl -sf http://127.0.0.1:18201/health && echo READY

# 2) 一批跑完三臂（seed 外层、臂内层）：60 次 ≈ 3 分钟
NSEED=20 NTRUNC=0 ARMS="b0 ours worldonly" SUMMARY=l2_worldonly_summary.txt \
  bash run_ablations.sh 2>&1 | tee l2_worldonly.log

# 3) 先自检，再看正确率
python check_ablations.py l2_worldonly_summary.txt
for f in ab_worldonly_s*.log; do printf "%s advice=%s reset=%s\n" "$f" "$(grep -c 'advice=' $f)" "$(grep -c 'reset=' $f)"; done
python summarize.py l2_worldonly_summary.txt --ref ours --csv pareto_worldonly.csv
```

⚠️ **`SUMMARY=` 必须改**：它的默认值是 `ablations_summary.txt`，而脚本第 41 行是 `: > "$SUMMARY"` ——
会用默认值**清空 E10 的原始数据**。

⚠️ 跑完把 `l2_worldonly_summary.txt`（+ `pareto_worldonly.csv`）拉回本地判读：
`scp <server-alias>:~/eb_probe/l2_worldonly_summary.txt D:\task\erro_back\week1\out\`

## 7. 冻结清单（跑之前算好，跑完复核）

| 文件 | SHA-256 前 16 位 | 说明 |
|---|---|---|
| `e5_loop.py`（**L2 版**，含 worldonly） | **843243FF0ECCD290** | 本次唯一改动的文件 |
| `summarize.py` | 71778466DD1C7266 | 与 A1/A2 冻结版一致 |
| `run_ablations.sh` | FF3A011828455CBB | 与 A1/A2 冻结版一致（本次未改） |
| `check_ablations.py` | EA7F84C9D2D0CCFA | 自检门，未改 |

历史版本（**论文里报哈希时三个版本都要说清**）：A1/A2 冻结版 `e5_loop.py = 7006ED537A8DB647`、
E11 版 `= D487A8DD9729A73B`、L2 版 `= 843243FF0ECCD290`。每次都是**增量式**加分支，
五个旧 mode 逐行未动 —— 这一点每次都要在补充材料里如实声明，不隐瞒。

## 8. 结果出来之后

- 我写 `week1/results/L2_worldonly_结果.md`：主表 / 判据判定 / **我的预测错了、错在哪** / 对论文的直接影响；
- 论文按分支 A/B/C 改 §6.2（分支 C 还要动 §2.4 / 摘要 / 结论）；
- 补充材料 Appendix A 增第二段披露（新哈希 + 只加一个 mode）；
- `paper/ERROR-BACK_artifact.zip` 重建（`python week1/mkartifact.py`）。
