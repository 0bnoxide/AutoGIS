# codebase-memory-mcp

Provides a persistent memory graph of this codebase for Claude Code sessions.
Source: https://github.com/DeusData/codebase-memory-mcp

## How it works in this repo (Claude Code on the web)

Each web session is an ephemeral container — the binary doesn't persist. The
session-start hook (`/.claude/hooks/session-start.sh`) re-downloads the binary
on cold starts; subsequent starts skip the download if the binary is already
present.

The MCP server is declared in `/.mcp.json` and trusted via
`enabledMcpjsonServers` in `/.claude/settings.json`.

Memory databases live in `~/.cache/codebase-memory-mcp/` (outside the repo).
The `.codebase-memory/` directory and `.codebase-memory.json` file are
gitignored so project-local snapshots never land in version history.

---

## Remove from this repo / switch to local install

### Step 1 — Revert repo changes

```bash
# Remove the MCP declaration and .gitignore entries
git revert --no-edit <commit-sha>   # commit that added .mcp.json + hook changes
# — or apply manually:
rm .mcp.json
# In .claude/settings.json: remove the "enabledMcpjsonServers" line
# In .claude/hooks/session-start.sh: remove the codebase-memory-mcp block
# In .gitignore: remove the two .codebase-memory* lines
git add -p && git commit -m "chore: remove codebase-memory-mcp from repo"
git push
```

### Step 2 — Install locally on your machine (macOS/Linux)

```bash
# Download the binary for your platform from:
# https://github.com/DeusData/codebase-memory-mcp/releases/latest
# Example for macOS arm64:
curl -fsSL https://github.com/DeusData/codebase-memory-mcp/releases/latest/download/codebase-memory-mcp-darwin-arm64-portable.tar.gz \
  | tar -xz -C /usr/local/bin codebase-memory-mcp
chmod +x /usr/local/bin/codebase-memory-mcp
codebase-memory-mcp --version   # verify
```

### Step 3 — Wire it into your local Claude Code

Add to `~/.claude/settings.json` (create if it doesn't exist):

```json
{
  "mcpServers": {
    "codebase-memory-mcp": {
      "command": "/usr/local/bin/codebase-memory-mcp",
      "args": []
    }
  }
}
```

This is user-level config — it applies to all your local projects without
touching any repo.

### Step 4 — Clean up cached data (optional)

```bash
rm -rf ~/.cache/codebase-memory-mcp/   # wipes all project indexes
rm -rf ~/.config/codebase-memory-mcp/  # wipes global config
```
