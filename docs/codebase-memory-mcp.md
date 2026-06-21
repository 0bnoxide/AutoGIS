# codebase-memory-mcp

Provides a persistent memory graph of this codebase for Claude Code sessions.
Source: https://github.com/DeusData/codebase-memory-mcp

## Status: removed from the repo (local-only now)

This server **used to** be wired into Claude Code on the web via `/.mcp.json`
(server declaration) + `enabledMcpjsonServers` in `/.claude/settings.json`
(trust) + a `session-start.sh` block that downloaded the binary and indexed the
repo into `~/.cache/codebase-memory-mcp/`.

**That web wiring was removed.** Diagnosis: in cloud sessions the binary is
provably healthy (instant stdio handshake, 14 tools advertised, `claude mcp list`
→ Connected), but the harness will not auto-trust a server declared in the
repo's own `.mcp.json`/`settings.json` (a committed file granting itself the
right to run an arbitrary binary). Claude's resolved per-project state showed
`enabledMcpjsonServers=[]` / `hasTrustDialogAccepted=False`, so its tools never
registered into the agent — every web session silently fell back to Grep/Read.
There is no `ENABLE_ALL_PROJECT_MCP_SERVERS` env var to force it, and the value
of a *persistent* graph is wasted in an ephemeral container that re-indexes on
every cold start. So the server now lives at **user scope on your own machine**,
where trust is implicit and the graph persists across sessions.

The local install below is the supported path.

---

## Install locally on your machine (macOS/Linux)

### Step 1 — Install the binary

```bash
# Download the binary for your platform from:
# https://github.com/DeusData/codebase-memory-mcp/releases/latest
# Example for macOS arm64:
curl -fsSL https://github.com/DeusData/codebase-memory-mcp/releases/latest/download/codebase-memory-mcp-darwin-arm64-portable.tar.gz \
  | tar -xz -C /usr/local/bin codebase-memory-mcp
chmod +x /usr/local/bin/codebase-memory-mcp
codebase-memory-mcp --version   # verify
```

### Step 2 — Wire it into your local Claude Code

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

### Step 3 — Clean up any leftover cached data (optional)

```bash
rm -rf ~/.cache/codebase-memory-mcp/   # wipes all project indexes
rm -rf ~/.config/codebase-memory-mcp/  # wipes global config
```
