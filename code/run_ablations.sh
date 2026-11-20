#!/usr/bin/env bash
# A1 + A2：2×2 消融（b0 / B2 label / B3 rollback / ours）+ 滑窗基线（truncate）
# 参数与 E6-d 完全一致：--scenario longtail --error-padding 3000 --max-turns 20
#
# 用法（服务器 ~/eb_probe/，vLLM 已在 $PORT 上起着。本脚本**不起服务、不动显卡**）：
#   NSEED=4 NTRUNC=4 bash run_ablations.sh 2>&1 | tee abl_pilot.log   # 先试水，量单跑耗时
#   bash run_ablations.sh 2>&1 | tee ablations.log                    # 全量
#
# 设计要点（改脚本前先读）：
#   * **seed 外层、arm 内层**：同一批次的各个臂共享批效应。不许拿历史批次的 b0/ours
#     来当对照 —— 实验报告 E6 §4b 已证 temperature=0 下 b0 自己两批之间就会变。
#   * 每个 run 的 system 里带随机 runtag（e5_loop.py 自己加的）→ 跨 run 前缀缓存天然隔离，
#     不需要 /reset_prefix_cache（它在 vLLM 0.18.1 上默认 404，会打一行 [!] 警告，正常）。
#   * 中途别改 e5_loop.py；改了就把整批作废重跑。
set -uo pipefail
cd "$HOME/eb_probe"

PY="${PY:-$HOME/miniconda3/envs/qwen_clean/bin/python}"
PORT="${PORT:-18201}"
BASE="http://127.0.0.1:$PORT"

NSEED="${NSEED:-20}"                     # b0/ours/rollback/label 各跑 seed 1..NSEED
NTRUNC="${NTRUNC:-10}"                   # truncate 三档各跑 seed 1..NTRUNC（与上面同一种子）
ARMS="${ARMS:-b0 ours rollback label}"   # 想省时间：ARMS="b0 ours rollback"
TNS="${TNS:-4 8 16}"
PAD="${PAD:-3000}"
TURNS="${TURNS:-20}"
SUMMARY="${SUMMARY:-ablations_summary.txt}"

# ---------------- 预检 ----------------
[ -f e5_loop.py ] && [ -f summarize.py ] || { echo "[x] 缺 e5_loop.py / summarize.py —— 先 scp 上来"; exit 2; }
grep -q '"rollback"' e5_loop.py || { echo "[x] 服务器上的 e5_loop.py 是旧版（无 rollback/label/truncate）—— 先 scp 新版"; exit 2; }
curl -sf -o /dev/null "$BASE/health" || { echo "[x] $BASE/health 不通 —— 先起 vLLM（HANDOFF §2）。本脚本不起服务"; exit 3; }
echo ">>> 服务就绪 $BASE"

N_ARM=$(echo $ARMS | wc -w)
N_TN=$(echo $TNS | wc -w)
n_run=$(( NSEED * N_ARM + NTRUNC * N_TN ))
echo ">>> 计划 $n_run 次运行：NSEED=$NSEED NTRUNC=$NTRUNC ARMS=[$ARMS] TNS=[$TNS] PAD=$PAD TURNS=$TURNS"
echo ">>> 第一个 run 的 [秒] 就是单跑基准，× $n_run ≈ 总时长"
: > "$SUMMARY"

T0=$SECONDS
i=0
run() {   # run <mode> <seed> [wn]
  local mode="$1" seed="$2" wn="${3:-}"
  local name="${mode}${wn:+_n$wn}"
  i=$((i + 1))
  curl -sf -o /dev/null "$BASE/health" || { echo "[x] 第 $i 跑前服务掉了（已跑 $((i-1)) 次）；已有 SUMMARY 保留在 $SUMMARY"; exit 4; }
  local t=$SECONDS
  "$PY" e5_loop.py --model Qwen3-4B --mode "$mode" ${wn:+--truncate-n "$wn"} \
      --scenario longtail --error-padding "$PAD" --max-turns "$TURNS" --seed "$seed" \
      --sandbox "./ab_sandbox_${name}" --out "ab_${name}_s${seed}.csv" > "ab_${name}_s${seed}.log" 2>&1
  grep "^SUMMARY" "ab_${name}_s${seed}.log" >> "$SUMMARY"
  printf "  [%3d/%3d] %-12s seed=%-3s %4ds\n" "$i" "$n_run" "$name" "$seed" "$((SECONDS - t))"
}

for s in $(seq 1 "$NSEED"); do
  for m in $ARMS; do run "$m" "$s"; done
  if [ "$s" -le "$NTRUNC" ]; then
    for n in $TNS; do run truncate "$s" "$n"; done
  fi
done

echo
got=$(grep -c "^SUMMARY" "$SUMMARY")
if [ "$got" -ne "$n_run" ]; then
  echo "[!] SUMMARY 只有 $got / $n_run 条 —— 有运行没跑到头，先 tail ab_*_s*.log 查（多半是服务掉了）"
fi
echo ">>> 用时 $((SECONDS - T0))s，汇总："
"$PY" summarize.py "$SUMMARY" --ref b0 --csv pareto.csv
echo
echo ">>> 把 $SUMMARY 和 pareto.csv 贴回来判读（判据见 A1A2_预注册.md）"
