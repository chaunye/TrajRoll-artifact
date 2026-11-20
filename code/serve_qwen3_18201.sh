#!/usr/bin/env bash
# week1/serve_qwen3_18201.sh —— 起 EB 实验用的 vLLM（与 2026-09-18 那批消融实际在跑的配置一致）
#
# 为什么要有这个文件：服务器上原有的 ~/eb_probe/serve.flags 与 vllm.pid 都是 **9-17 的旧档**
#   （--max-model-len 11520 --num-gpu-blocks-override 750 --enable-auto-tool-choice ...），
#   与 2026-09-18 13:58:26 起的那次启动（pid 3199384）参数**不符** —— 照旧档重启会起成错的配置。
#
# 用法（服务器 ~/eb_probe/）：
#   CUDA_VISIBLE_DEVICES=1 bash serve_qwen3_18201.sh                          # 前台
#   CUDA_VISIBLE_DEVICES=1 nohup bash serve_qwen3_18201.sh > serve.log 2>&1 &  # 脱离终端，登出不会死
#
# 关键约束（改之前先读）：
#   * CUDA_VISIBLE_DEVICES 必须显式给，且只挑**空闲**卡（先 nvidia-smi）。0 常被别人占。
#   * **不要**给 --max-model-len → 取模型自带 40960，这是 E9 回放能装下长轨迹的前提。
#   * --enable-prefix-caching 与 --enable-prompt-tokens-details 缺一不可：
#     前者是本方案立论的前提；后者没有的话 usage.prompt_tokens_details.cached_tokens 直接缺失
#     （且命中为 0 时 vLLM 也会省略该字段 —— 别把它当"缓存没生效"）。
#   * --gpu-memory-utilization 0.90：0.55 装不下 40960 的 KV。
set -euo pipefail

MODEL="${MODEL:-/home/ws/.cache/modelscope/Qwen/Qwen3-4B}"
NAME="${NAME:-Qwen3-4B}"
PORT="${PORT:-18201}"
UTIL="${UTIL:-0.90}"
VLLM="${VLLM:-$HOME/miniconda3/envs/qwen_clean/bin/vllm}"
# MAXLEN 留空 = 不传 --max-model-len（= 现状，取模型自带 40960）。
# 只在第二模型显存装不下 40960 的 KV 时才设（L3 预注册 §2：longtail 任务 prompt < 10k，
# 降窗口不影响该批有效性；E9 回放则绝不可降）。
MAXLEN="${MAXLEN:-}"
MLEN_FLAG=()
[ -n "$MAXLEN" ] && MLEN_FLAG=(--max-model-len "$MAXLEN")

# ★★ 必须设！★★ 服务器上 python3.10 的 user-site 里有一个**坏掉的 torch**（2026-09-18 18:04 装 sglang 时带进来的），
#   它在 sys.path 里排在 qwen_clean 的 site-packages **之前** → 不设这个变量，`import torch` 会报
#   `libtorch_cuda.so: undefined symbol: ncclCommResume`，vLLM 直接起不来（已实测）。
#   设了之后走 env 自带的 torch 2.10.0+cu128，vLLM 0.18.1 正常。
export PYTHONNOUSERSITE=1

# 这台机器上 flashinfer 版本与 vLLM 期望不一致，不设会报错
export FLASHINFER_DISABLE_VERSION_CHECK=1

echo ">>> vLLM: model=$MODEL port=$PORT util=$UTIL cuda=${CUDA_VISIBLE_DEVICES:-<未指定>}"
nvidia-smi --query-gpu=index,memory.used,memory.total --format=csv,noheader 2>/dev/null | sed 's/^/    /'

exec "$VLLM" serve "$MODEL" \
  --served-model-name "$NAME" \
  --port "$PORT" \
  --gpu-memory-utilization "$UTIL" \
  "${MLEN_FLAG[@]}" \
  --enable-prefix-caching \
  --enable-prompt-tokens-details

# 起完自检：
#   curl -sf http://127.0.0.1:$PORT/health && echo READY
#   curl -s  http://127.0.0.1:$PORT/v1/models | head -c 300     # 确认 max_model_len=40960
