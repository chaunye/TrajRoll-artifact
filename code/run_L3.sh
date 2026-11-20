#!/usr/bin/env bash
# L3：第二个模型重跑主批七臂（判据见 L3_第二模型_预注册.md §3，跑完不许改）
#
# 与冻结的 run_ablations.sh 的全部差别：--model 与 --base-url 参数化（那边写死
# Qwen3-4B / 18201，冻结文件不能动）。循环结构、seed 顺序、SUMMARY 格式逐字对齐。
#
# 用法（服务器 ~/eb_probe/，第二个模型的 vLLM 已在 $PORT 上起着）：
#   MODEL2=Qwen3-8B PORT=18202 bash run_L3.sh 2>&1 | tee l3_qwen3_8b.log
# 本脚本不起服务、不动显卡。
set -uo pipefail
cd "$HOME/eb_probe"

PY="${PY:-$HOME/miniconda3/envs/qwen_clean/bin/python}"
PORT="${PORT:-18202}"
BASE="http://127.0.0.1:$PORT"
MODEL2="${MODEL2:-Qwen3-8B}"

NSEED="${NSEED:-20}"                     # b0/ours/rollback/label 各跑 seed 1..NSEED
NTRUNC="${NTRUNC:-20}"                   # truncate 三档（正式批口径 = NSEED）
ARMS="${ARMS:-b0 ours rollback label}"
TNS="${TNS:-4 8 16}"
PAD="${PAD:-3000}"
TURNS="${TURNS:-20}"
SUMMARY="${SUMMARY:-l3_qwen3_8b_summary.txt}"

# ---------------- 预检 ----------------
[ -f e5_loop.py ] && [ -f summarize.py ] || { echo "[x] 缺 e5_loop.py / summarize.py"; exit 2; }
curl -sf -o /dev/null "$BASE/health" || { echo "[x] $BASE/health 不通 —— 先起第二个模型（预注册 §5 第 1 步）"; exit 3; }
curl -s "$BASE/v1/models" | grep -o '"id":"[^"]*"' | head -3 | sed 's/^/    /'
echo ">>> 服务就绪 $BASE（model=$MODEL2）"

N_ARM=$(echo $ARMS | wc -w)
N_TN=$(echo $TNS | wc -w)
n_run=$(( NSEED * N_ARM + NTRUNC * N_TN ))
echo ">>> 计划 $n_run 次运行：MODEL2=$MODEL2 NSEED=$NSEED NTRUNC=$NTRUNC ARMS=[$ARMS] TNS=[$TNS]"
: > "$SUMMARY"

T0=$SECONDS
i=0
run() {   # run <mode> <seed> [wn]
  local mode="$1" seed="$2" wn="${3:-}"
  local name="${mode}${wn:+_n$wn}"
  i=$(( i + 1 ))
  curl -sf -o /dev/null "$BASE/health" || { echo "[x] 第 $i 跑前服务掉了；已有 SUMMARY 保留在 $SUMMARY"; exit 4; }
  local t=$SECONDS
  "$PY" e5_loop.py --base-url "$BASE" --model "$MODEL2" --mode "$mode" ${wn:+--truncate-n "$wn"} \
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
"$PY" summarize.py "$SUMMARY" --ref b0 --csv pareto_l3.csv
echo
echo ">>> 先过自检门再看正确率：python check_ablations.py $SUMMARY"
echo ">>> 判读判据：L3_第二模型_预注册.md §3（H1/H2 为主，只看方向与秩序）"
