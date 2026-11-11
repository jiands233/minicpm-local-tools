#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ -x "$ROOT_DIR/.local/runtime/ollama" ]; then
  OLLAMA_BIN="$ROOT_DIR/.local/runtime/ollama"
elif command -v ollama >/dev/null 2>&1; then
  OLLAMA_BIN="$(command -v ollama)"
else
  echo '找不到 Ollama。请按 docs/models.md 安装本地运行时。' >&2
  exit 1
fi
export OLLAMA_HOST=127.0.0.1:11434
export OLLAMA_MODELS="$ROOT_DIR/.local/models"
export OLLAMA_NO_CLOUD=1
export OLLAMA_MAX_LOADED_MODELS=1
export OLLAMA_NUM_PARALLEL=1
mkdir -p "$OLLAMA_MODELS"
exec "$OLLAMA_BIN" serve
