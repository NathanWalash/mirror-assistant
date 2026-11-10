#!/usr/bin/env bash
# Run the personality eval against one model: start a throwaway llama-server, ask every
# question in personality/eval/questions.yaml, save results, stop the server.
#
#   scripts/eval.sh <hf-repo:quant> <label> [mirror-eval run options...]
#   scripts/eval.sh mradermacher/Hermes-3-Llama-3.2-3B-abliterated-i1-GGUF:Q4_K_M hermes3
#   scripts/eval.sh mradermacher/Huihui-Qwen3.5-4B-abliterated-GGUF:Q4_K_M qwen35 --no-think
#
# Uses port 8090 (EVAL_PORT) so it doesn't clash with talk.sh on 8080. Extra llama-server
# flags go in LLAMA_ARGS, e.g. LLAMA_ARGS="--reasoning off".
# Then compare runs:  uv run mirror-eval compare personality/eval/results/*.jsonl -o x.html
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ $# -lt 2 ]]; then
  sed -n '2,12p' "$0"
  exit 1
fi
model=$1 label=$2
shift 2
port=${EVAL_PORT:-8090}
url="http://127.0.0.1:$port"
mkdir -p models
log="models/eval-server-$label.log"

if curl -sf "$url/health" >/dev/null; then
  echo "Something is already running on port $port. Stop it or set EVAL_PORT."
  exit 1
fi

# shellcheck disable=SC2086
llama-server -hf "$model" --port "$port" -c 8192 --no-mmproj ${LLAMA_ARGS:-} >"$log" 2>&1 &
server_pid=$!
trap 'kill "$server_pid" 2>/dev/null || true' EXIT

echo "Starting $model on port $port (log: $log)..."
until curl -sf "$url/health" >/dev/null; do
  if ! kill -0 "$server_pid" 2>/dev/null; then
    echo "Model server stopped unexpectedly. Last lines of $log:"
    tail -20 "$log"
    exit 1
  fi
  sleep 1
done

uv run mirror-eval run --url "$url" --label "$label" --model "$model" "$@"
