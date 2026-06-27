#!/bin/bash
# SessionStart hook for Claude Code — runs in both local and remote sessions.
# Always: refresh the codebase-memory knowledge graph (no-op if binary absent).
# Always: install headroom context-compression tool and project deps.
set -euo pipefail

# --- Refresh codebase-memory knowledge graph (local binary; skipped if absent) ---
# Indexing is incremental (~50ms no-op when nothing changed). The repo path is
# the canonical checkout (not $CLAUDE_PROJECT_DIR) so worktree sessions still
# refresh the one registered project; forward slashes required by the JSON arg.
CBM="/c/Users/ichbi/AppData/Local/Programs/codebase-memory-mcp/codebase-memory-mcp.exe"
[ -x "$CBM" ] && "$CBM" cli index_repository \
  '{"repo_path":"C:/Users/ichbi/AutoGIS","mode":"full"}' >/dev/null 2>&1 || true

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
