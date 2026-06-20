#!/bin/bash
# SessionStart hook for Claude Code on the web.
# Installs AutoGIS test deps + the headroom context-compression tool, and points
# headroom's runtime artifacts at $HOME so they never land in the repo tree.
set -euo pipefail

# Only run in Claude Code on the web (remote) sessions.
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"

# Keep stdout clean in synchronous mode: send all install chatter to stderr.
{
  # --- AutoGIS project deps (so the 113-test suite runs in fresh sessions) ---
  pip install --quiet pytest PyYAML click openpyxl
  pip install --quiet --no-deps -e "$PROJECT_DIR"

  # --- headroom (context-compression tool), lean Claude Code set ---
  # PyJWT ships from the system package manager with no RECORD file, so pip
  # cannot uninstall it; --ignore-installed installs the newer one alongside.
  pip install --quiet --ignore-installed PyJWT "headroom-ai[proxy,mcp,relevance]"
  # transformers requires tokenizers <=0.23.0, but 0.23.0 has no final release
  # and litellm/fastembed pull 0.23.1 -> pin the highest compatible final.
  pip install --quiet "tokenizers==0.22.2"
} 1>&2

# --- keep headroom runtime artifacts OUT of the repo ---
mkdir -p "$HOME/.headroom"
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  {
    echo "export HEADROOM_MEMORY_DB_PATH=\"$HOME/.headroom/memory.db\""
    echo "export HEADROOM_LOG_FILE=\"$HOME/.headroom/proxy.log\""
  } >> "$CLAUDE_ENV_FILE"
fi

# --- pre-warm the kompress-base model so the first compression isn't a cold
# ~264MB download. It caches under $HOME/.cache/huggingface, which is baked into
# the web container snapshot after this hook completes. Guarded by a marker so
# warm sessions skip it; non-fatal (falls back to fetch-on-first-use).
if [ ! -f "$HOME/.headroom/.model-prewarmed" ]; then
  if python - 1>&2 <<'PYEOF'
# Use headroom's intended startup eager-preload API to fetch + load the
# kompress-v2-base ONNX model (and ModernBERT tokenizer) deterministically.
from headroom.transforms.kompress_compressor import KompressCompressor
backend = KompressCompressor().preload(allow_download=True)
print(f"kompress model pre-warmed (backend={backend})")
PYEOF
  then
    touch "$HOME/.headroom/.model-prewarmed"
  else
    echo "headroom model pre-warm skipped (will fetch on first use)" >&2
  fi
fi
