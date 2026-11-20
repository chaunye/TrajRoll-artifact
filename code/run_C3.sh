#!/usr/bin/env bash
# C 类解禁三实验（判据见 week1/prereg/预注册_C类解禁三实验_2026-10-03.md，**跑完不许改判据**）
#   E12 安慰剂阶梯（5 臂 × 20 = 100 次，temp 0，≈8–10 min）
#   E13 采样复核（3 臂 × 20 = 60 次，temp 0.7，≈6–8 min）
#   E14 TTFT 微基准（3 臂 × 20 单流 + 同批 4 路并发，--stream，≈12–15 min）
#
# 与冻结的 run_ablations.sh / run_L3.sh 的全部差别：新增 e12/e13/e14 三个阶段函数与
# --temperature/--stream 传参；循环结构、seed 外层臂内层交错、SUMMARY 格式逐字对齐。
# 本脚本不起服务、不动显卡、不装任何东西。
#
# 用法（服务器 ~/eb_probe/，Qwen3-4B 的 vLLM 已在 $PORT 上起着；跑前 nvidia-smi 确认空闲卡）：
#   PORT=18201 bash run_C3.sh all      # 三批连跑（≈30 min）
#   PORT=18201 bash run_C3.sh e12      # 只跑 E12
#   PORT=18201 bash run_C3.sh e13      # 只跑 E13
#   PORT=18201 bash run_C3.sh e14      # 只跑 E14（阶段1 + 阶段2）
set -uo pipefail
cd "$HOME/eb_probe"

PY="${PY:-$HOME/miniconda3/envs/qwen_clean/bin/python}"
PORT="${PORT:-18201}"
BASE="http://127.0.0.1:$PORT"
MODEL="${MODEL:-Qwen3-4B}"
NSEED="${NSEED:-20}"
PAD="${PAD:-3000}"
TURNS="${TURNS:-20}"
WHICH="${1:-all}"

# ---------------- 预检 ----------------
[ -f e5_loop.py ] && [ -f summarize.py ] || { echo "[x] 缺 e5_loop.py / summarize.py"; exit 2; }
h=$(sha256sum e5_loop.py | cut -c1-16)
[ "$h" = "B94A3B41131496DB" ] || echo "[!] e5_loop.py 哈希 $h ≠ 预注册 §0 的 B94A3B41131496DB —— 先核对版本再跑"
curl -sf -o /dev/null "$BASE/health" || { echo "[x] $BASE/health 不通 —— 先起服务（§2 环境）"; exit 3; }
echo ">>> 服务就绪 $BASE（model=$MODEL，e5_loop.py=$h）"

i=0; T0=$SECONDS
run() {   # run <summary> <mode> <seed> <temp> <stream:0/1> [truncate-n]
  local sum="$1" mode="$2" seed="$3" temp="$4" stream="$5" wn="${6:-}"
  local name="${mode}${wn:+_n$wn}_t${temp/./p}"
  i=$(( i + 1 ))
  curl -sf -o /dev/null "$BASE/health" || { echo "[x] 第 $i 跑前服务掉了；SUMMARY 保留在 $sum"; exit 4; }
  local t=$SECONDS
  "$PY" e5_loop.py --base-url "$BASE" --model "$MODEL" --mode "$mode" ${wn:+--truncate-n "$wn"} \
      --temperature "$temp" $([ "$stream" = 1 ] && echo --stream) \
      --scenario longtail --error-padding "$PAD" --max-turns "$TURNS" --seed "$seed" \
      --sandbox "./ab_sandbox_${name}_s${seed}" --out "ab_${name}_s${seed}.csv" > "ab_${name}_s${seed}.log" 2>&1
  grep "^SUMMARY" "ab_${name}_s${seed}.log" >> "$sum"
  grep "^TTFT_SUMMARY" "ab_${name}_s${seed}.log" >> "${sum%.txt}_ttft.txt" || true
  printf "  [%3d] %-18s seed=%-3s %4ds\n" "$i" "$name" "$seed" "$((SECONDS - t))"
}

# ---------------- E12 安慰剂阶梯 ----------------
e12() {
  local sum="e12_placebo_summary.txt"; : > "$sum"; : > "${sum%.txt}_ttft.txt"
  echo "=== E12 安慰剂阶梯（5 臂 × $NSEED = $((NSEED*5)) 次，temp 0）==="
  for s in $(seq 1 "$NSEED"); do
    for m in b0 generic placebo worldonly ours; do run "$sum" "$m" "$s" 0 0; done
  done
  got=$(grep -c "^SUMMARY" "$sum")
  [ "$got" -ne $((NSEED*5)) ] && echo "[!] SUMMARY 只有 $got / $((NSEED*5)) —— 先 tail ab_*_t0_s*.log 查，别解读"
  echo ">>> 用时 $((SECONDS - T0))s；汇总："
  "$PY" summarize.py "$sum" --ref b0 --csv pareto_e12.csv
  echo ">>> 判读判据：预注册 §1（placebo / generic vs worldonly，Fisher 双边 + 15pp 方向带）"
}

# ---------------- E13 采样复核 ----------------
e13() {
  local sum="e13_sampling_summary.txt"; : > "$sum"; : > "${sum%.txt}_ttft.txt"
  echo "=== E13 采样复核（3 臂 × $NSEED = $((NSEED*3)) 次，temp 0.7）==="
  for s in $(seq 1 "$NSEED"); do
    for m in b0 rollback ours; do run "$sum" "$m" "$s" 0.7 0; done
  done
  got=$(grep -c "^SUMMARY" "$sum")
  [ "$got" -ne $((NSEED*3)) ] && echo "[!] SUMMARY 只有 $got / $((NSEED*3)) —— 先查日志再解读"
  echo ">>> 用时 $((SECONDS - T0))s；汇总："
  "$PY" summarize.py "$sum" --ref b0 --csv pareto_e13.csv
  echo ">>> 判读判据：预注册 §2（rollback@0.7 vs ours / b0，全在本批内比）"
}

# ---------------- E14 阶段1：单流 TTFT ----------------
e14seq() {
  # 10-04 修正：run() 把 TTFT_SUMMARY 落在 "${sum%.txt}_ttft.txt"（即 e14_ttft_summary_ttft.txt），
  # 原来截断/统计的 e14_ttft.txt 从未被写过 → 首批误报「TTFT 0/60」；数据当时在
  # e14_ttft_summary_ttft.txt 与 ab_*_t0_s*.log 里，未丢（并发批的收集是写死同名，所以本来就对）。
  local sum="e14_ttft_summary.txt"; : > "$sum"; : > "${sum%.txt}_ttft.txt"
  echo "=== E14 阶段1：单流 TTFT（3 臂 × $NSEED，--stream，temp 0）==="
  for s in $(seq 1 "$NSEED"); do
    for m in ours sysend truncate; do
      if [ "$m" = "truncate" ]; then run "$sum" "$m" "$s" 0 1 4; else run "$sum" "$m" "$s" 0 1; fi
    done
  done
  got=$(grep -c "^SUMMARY" "$sum")
  [ "$got" -ne $((NSEED*3)) ] && echo "[!] SUMMARY 只有 $got / $((NSEED*3)) —— 先查日志"
  got=$(grep -c "^TTFT_SUMMARY" "${sum%.txt}_ttft.txt")
  [ "$got" -ne $((NSEED*3)) ] && echo "[!] TTFT_SUMMARY 只有 $got / $((NSEED*3)) —— include_usage 可能没生效（预注册 §3 备选路径）"
  echo ">>> 汇总："
  "$PY" summarize.py "$sum" --ref ours --csv pareto_e14.csv
  echo ">>> TTFT 行数 $(grep -c '^TTFT_SUMMARY' "${sum%.txt}_ttft.txt")；判读判据：预注册 §3（V1 排序 / V3 相关）"
}

# ---------------- E14 阶段2：4 路并发 ----------------
e14par() {
  local sum="e14_ttft_4way_summary.txt"; : > "$sum"; : > e14_ttft_4way.txt
  rm -f ab_4w_*.log ab_4w_*.csv
  echo "=== E14 阶段2：4 路并发（seeds 1–20 拆 4 份同时跑，共享前缀缓存）==="
  local pids=()
  for w in 0 1 2 3; do
    (
      for s in $(seq $((w*5+1)) $((w*5+5))); do
        for m in ours sysend truncate; do
          if [ "$m" = "truncate" ]; then
            "$PY" e5_loop.py --base-url "$BASE" --model "$MODEL" --mode "$m" --truncate-n 4 \
                --temperature 0 --stream \
                --scenario longtail --error-padding "$PAD" --max-turns "$TURNS" --seed "$s" \
                --sandbox "./ab_sandbox_4w_${m}n4_s${s}" --out "ab_4w_${m}n4_s${s}.csv" \
                > "ab_4w_${m}n4_s${s}.log" 2>&1
          else
            "$PY" e5_loop.py --base-url "$BASE" --model "$MODEL" --mode "$m" \
                --temperature 0 --stream \
                --scenario longtail --error-padding "$PAD" --max-turns "$TURNS" --seed "$s" \
                --sandbox "./ab_sandbox_4w_${m}_s${s}" --out "ab_4w_${m}_s${s}.csv" \
                > "ab_4w_${m}_s${s}.log" 2>&1
          fi
        done
      done
    ) & pids+=($!)
  done
  wait
  cat ab_4w_*.log | grep "^SUMMARY" >> "$sum" || true
  cat ab_4w_*.log | grep "^TTFT_SUMMARY" >> e14_ttft_4way.txt || true
  echo ">>> 并发批 SUMMARY $(grep -c '^SUMMARY' "$sum") 条、TTFT $(grep -c '^TTFT_SUMMARY' e14_ttft_4way.txt) 条"
  echo ">>> 判读判据：预注册 §3（V2：4-way 下排序是否保持）"
}

case "$WHICH" in
  e12) e12 ;;
  e13) e13 ;;
  e14) e14seq; e14par ;;
  all) e12; echo; e13; echo; e14seq; e14par ;;
  *) echo "用法: bash run_C3.sh [all|e12|e13|e14]"; exit 1 ;;
esac

echo
echo ">>> 全部用时 $((SECONDS - T0))s"
echo ">>> 自检门（预注册 §4，先过门再解读）："
echo "    python check_ablations.py e12_placebo_summary.txt"
echo "    python check_ablations.py e13_sampling_summary.txt"
echo "    python check_ablations.py e14_ttft_summary.txt"
echo ">>> 跑完把 6 个 summary/ttft 文件 + pareto_e1*.csv 拷回本机 week1/out/，判读交 AI"
