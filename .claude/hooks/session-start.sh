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

# --- [PROBE] codebase-memory-mcp for REMOTE sessions only ---------------------
# Tests whether a hook-time USER-SCOPE MCP registration is picked up in cloud
# (the 06-21 attempt used PROJECT scope -> hit the trust wall). Remote-only,
# never runs locally, fully non-fatal, NO indexing (isolates the trust/timing
# variable). Writes /tmp/cbm-probe.log for the probe agent to read back.
if [ "${CLAUDE_CODE_REMOTE:-}" = "true" ]; then
  {
    PLOG=/tmp/cbm-probe.log
    echo "[cbm-probe] start $(date -u +%FT%TZ) CLAUDE_CODE_REMOTE=${CLAUDE_CODE_REMOTE:-}" > "$PLOG"
    RBIN="/usr/local/bin/codebase-memory-mcp"
    if [ ! -x "$RBIN" ]; then
      curl -fsSL --max-time 120 \
        "https://github.com/DeusData/codebase-memory-mcp/releases/latest/download/codebase-memory-mcp-linux-amd64-portable.tar.gz" \
        -o /tmp/cbm.tar.gz \
        && tar -xzf /tmp/cbm.tar.gz -C /usr/local/bin codebase-memory-mcp \
        && chmod +x "$RBIN"
    fi
    echo "[cbm-probe] binary: $(ls -la "$RBIN" 2>&1)" >> "$PLOG"
    # Documented user-scope registration; non-fatal if `claude` is absent.
    claude mcp add --scope user codebase-memory-mcp "$RBIN" >> "$PLOG" 2>&1 \
      || echo "[cbm-probe] 'claude mcp add' failed or unavailable" >> "$PLOG"
    echo "[cbm-probe] --- claude mcp list ---" >> "$PLOG"
    claude mcp list >> "$PLOG" 2>&1 || echo "[cbm-probe] 'claude mcp list' failed" >> "$PLOG"
    echo "[cbm-probe] --- ~/.claude.json mcpServers ---" >> "$PLOG"
    python - >> "$PLOG" 2>&1 <<'PYEOF' || echo "[cbm-probe] config read failed" >> "$PLOG"
import json, os
try:
    d = json.load(open(os.path.expanduser("~/.claude.json")))
    print(json.dumps(d.get("mcpServers", {}), indent=1))
except Exception as e:
    print("ERR", e)
PYEOF
    echo "[cbm-probe] done $(date -u +%FT%TZ)" >> "$PLOG"
  } 1>&2 || true
fi

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"

# --- Start every session from a current pull (so sessions + the subagents and
# worktrees that branch from HEAD develop against up-to-date code). Only on a
# clean 'main' checkout, fast-forward only; fully guarded so a network/auth/
# non-ff failure can't abort the rest of setup under `set -e`. Never pull onto a
# feature branch or worktree. ponytail: ff-only on clean main; nothing fancier.
if [ "$(git -C "$PROJECT_DIR" branch --show-current 2>/dev/null)" = "main" ] \
   && [ -z "$(git -C "$PROJECT_DIR" status --porcelain 2>/dev/null)" ]; then
  git -C "$PROJECT_DIR" pull --ff-only >/dev/null 2>&1 || true
fi

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
