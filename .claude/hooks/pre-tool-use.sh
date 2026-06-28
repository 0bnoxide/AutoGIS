#!/usr/bin/env bash
# PreToolUse coordination hook — delegates to the Python decision logic.
# Fails open: hook_check.py always exits 0 (allow) on any internal error.
exec python "$CLAUDE_PROJECT_DIR/.claude/coordination/hook_check.py"
