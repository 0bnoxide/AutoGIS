# headroom-proxy

Context-compression + memory layer for Claude Code sessions on this machine.
Source: https://headroom-docs.vercel.app/docs/ · package `headroom-ai` (PyPI).

Headroom runs as a **local optimization proxy** that Claude Code routes through
via `ANTHROPIC_BASE_URL`. It compresses large tool outputs / history to cut
tokens, and (with `--learn`) extracts failure→recovery patterns from traffic
into personal memory files. Like `codebase-memory-mcp`, it is **machine-local**,
not wired into the repo — the only repo-visible footprint is the `.gitignore`
line this doc's PR adds (see *Deviations → #1072* below).

> **Why this doc exists:** for ~2 weeks headroom was installed by the
> SessionStart hook but never *wired* — no proxy running, no routing, no MCP
> registration. It compressed nothing while paying the install/model-download
> tax every session (verified 2026-07-09: no `proxy.log`, no `memory.db`, MCP
> unregistered). If you re-implement this elsewhere or it breaks, **start from
> the "Prove it's not dead weight" section** — a green install message is not
> proof it's doing anything.

---

## Verified working setup (Windows) — 2026-07-09, headroom-ai 0.27.0

| Thing | Correct value |
|---|---|
| Package | `headroom-ai[proxy,mcp,relevance]` (v0.27.0; installed to `Python314\Lib\site-packages\headroom`). **≥0.27.0 required** — it carries the issue-#1072 fix (see Deviations). |
| Console script | `headroom` → `headroom.cli:main` (on PATH as `headroom.EXE`) |
| Compression mode | **`cache`** — reversible CCR only, no lossy Kompress rewrite (chosen deliberately; see *Two-layer compression*) |
| Proxy | `headroom proxy --mode cache --memory --learn --port 8787`, loopback-only |
| Persistence | **NSSM service `HeadroomProxy`** — auto-start + auto-restart. headroom's own `headroom install apply` is **broken on Windows** — do NOT use it (see *Deviations → install apply*). |
| Where `--learn` lives | the NSSM service's `AppParameters` (`proxy --mode cache --memory --learn --port 8787`) — **permanent**; nothing regenerates it |
| SYSTEM-profile override (critical) | the service runs as LocalSystem, so `AppEnvironmentExtra` sets `USERPROFILE=C:\Users\ichbi`, `HEADROOM_MEMORY_DB_PATH=…\.headroom\memory.db`, `HEADROOM_LOG_FILE=…\.headroom\proxy.log` — else `--learn` scans SYSTEM's empty `~/.claude/projects` and memory lands in the wrong profile (dead weight). |
| MCP server (CCR retrieve) | registered in `~/.claude.json` as `headroom` → `headroom.EXE mcp serve`; tools `mcp__headroom__headroom_retrieve/_compress/_stats` |
| Memory DB | `C:\Users\ichbi\.headroom\memory.db` (local SQLite+HNSW; no Docker) |
| Learn output (personal) | project `CLAUDE.local.md` (gitignored) + `~/.claude/projects/C--Users-ichbi-AutoGIS/memory/MEMORY.md` |
| Routing | `ANTHROPIC_BASE_URL=http://127.0.0.1:8787` set as a **user env var** via `setx` — not via headroom's installer |
| When it takes effect | proxy = live once the service starts; **routing + MCP load at Claude Code startup only** — restart after wiring |

### Two-layer compression — why `cache` mode

The proxy has **two independent compressors**; only one is reversible:

| Layer | What it does | Reversible? |
|---|---|---|
| **CCR** (Compress-Cache-Retrieve) | drops big tool-output blobs → hash marker; stores the **original verbatim**; LLM recovers via `headroom_retrieve` | **Yes** (`cache/compression_store.py`: `retrieve(hash)` returns full original) |
| **Kompress** (token-mode) | ONNX/ModernBERT importance model drops low-value tokens from prose/code in history; signature-tracked, original **not** stored | **No** (lossy) |

`--mode cache` freezes prior turns → CCR-only → fully reversible (lower but real
savings, best provider prefix-cache hits). `--mode token` (default) adds the
lossy Kompress rewrite for more savings. **We chose `cache`** for reversibility.

### The three memory features

| Feature | Enabled by | Where it lives |
|---|---|---|
| **Persistent memory** | `--memory` | local SQLite+HNSW at `~/.headroom/memory.db`; injects `memory_save`/`memory_search` tools + relevant past memories into context |
| **Shared context** | `--memory` (context injection) | cross-session memory injection is live; the inter-agent `SharedContext` library (`from headroom import SharedContext`, `.put/.get`) only fires if multi-agent code calls it — inert in a solo session |
| **Failure learning** | `--learn` (implies `--memory`) | live traffic learner writes fenced blocks to `CLAUDE.local.md` + auto-memory `MEMORY.md` (see Deviations for the write-target details) |

---

## Reproduce the wiring (order matters)

1. **Install package** (the SessionStart hook already does this):
   `pip install --ignore-installed PyJWT "headroom-ai[proxy,mcp,relevance]"`
2. **Register the CCR-retrieve MCP** (user scope): `headroom mcp install --agent claude`
   → writes `headroom` server to `~/.claude.json`. *(Restart Claude Code to load.)*
3. **Land the `.gitignore` line for `CLAUDE.local.md` on `main` first** — see
   *Deviations → #1072* for why this MUST precede enabling `--learn`.
4. **Install the persistent service with NSSM (admin terminal, once).** Do NOT
   use `headroom install apply` — it is broken on Windows (see Deviations). NSSM
   supervises the console proxy properly (reports RUNNING while managing the
   child); bare `sc.exe` cannot.
   ```powershell
   choco install nssm -y ; refreshenv
   $hr = "C:\Users\ichbi\AppData\Local\Programs\Python\Python314\Scripts\headroom.exe"
   nssm install HeadroomProxy $hr proxy --mode cache --memory --learn --port 8787
   nssm set HeadroomProxy AppDirectory "C:\Users\ichbi\.headroom"
   # CRITICAL — SYSTEM service must resolve YOUR profile or --learn is dead weight:
   nssm set HeadroomProxy AppEnvironmentExtra USERPROFILE=C:\Users\ichbi HEADROOM_MEMORY_DB_PATH=C:\Users\ichbi\.headroom\memory.db HEADROOM_LOG_FILE=C:\Users\ichbi\.headroom\proxy.log
   nssm set HeadroomProxy Start SERVICE_AUTO_START
   nssm set HeadroomProxy AppExit Default Restart
   nssm set HeadroomProxy AppRestartDelay 5000
   nssm set HeadroomProxy AppStdout "C:\Users\ichbi\.headroom\service.log"
   nssm set HeadroomProxy AppStderr "C:\Users\ichbi\.headroom\service.log"
   nssm start HeadroomProxy
   ```
   (To run the service **as you** instead of SYSTEM — avoids the profile override
   and SYSTEM-owned files — use `nssm edit HeadroomProxy` → *Log on* tab with your
   Windows password; the `USERPROFILE` line then becomes unnecessary.)
5. **Wire routing (no admin), only after the service is confirmed up**
   (proxy-up-before-routing): `setx ANTHROPIC_BASE_URL "http://127.0.0.1:8787"`.
6. **Restart Claude Code** so routing + the MCP server load.

---

## Prove it's not dead weight (run these, don't trust install messages)

```powershell
nssm status HeadroomProxy             # SERVICE_RUNNING   (Get-Service HeadroomProxy → Running)
Get-NetTCPConnection -LocalPort 8787 -State Listen        # one row = listening
Invoke-RestMethod http://127.0.0.1:8787/readyz | Select ready,@{n='mem';e={$_.checks.memory.enabled}}
Invoke-RestMethod http://127.0.0.1:8787/health | %{ $_.config } | Select memory,learn,mode
headroom doctor                       # proxy ✓ (savings appear after real traffic)
```
Good: `SERVICE_RUNNING`, one listener, `ready:True mem:True`, `memory:True learn:True mode:cache`.
If it won't start: `Get-Content C:\Users\ichbi\.headroom\service.log -Tail 40`.

After the first **routed** request also confirm:
- `~/.headroom/proxy.log` is gaining entries (proxy actually saw traffic),
- `~/.headroom/memory.db` exists (memory wrote),
- tracked `CLAUDE.md` is **untouched**; `CLAUDE.local.md` appears and is
  gitignored (absent from `git status --porcelain`),
- a fenced `<!-- headroom:learn -->` / `<!-- headroom:memory -->` block lands in
  `~/.claude/projects/C--Users-ichbi-AutoGIS/memory/MEMORY.md`.

Dead-weight tells (what we found on 2026-07-09 before fixing): `ANTHROPIC_BASE_URL`
unset, nothing on 8787, no `proxy.log`, no `memory.db`, `claude mcp get headroom`
= "No MCP server named headroom".

---

## Known deviations / gotchas (recognise these fast)

- **#1072 — `--learn` writes `CLAUDE.local.md`, NOT the tracked `CLAUDE.md`.**
  `learn/writer.py:_resolve_context_path` defaults project learnings to
  `CLAUDE.local.md` (personal, gitignored) precisely so it never pollutes the
  team file. **But `CLAUDE.local.md` is not gitignored by default**, so an
  untracked `?? CLAUDE.local.md` in the **main** tree dirties
  `git status --porcelain` and silently blocks SessionStart's clean-only ff-pull
  (`session-start.sh` ends the pull in `|| true`) → **main drift, no signal**.
  Fix = the `.gitignore` line. It must be **merged to `main` and pulled *before*
  `--learn` goes live** — a draft PR protects nothing.
- **`headroom install apply` is broken on Windows — use NSSM.** Both persistence
  presets fail: the `persistent-service` preset builds a malformed `sc.exe`
  command (unquoted `binPath=` with spaces → `sc` rejects `start=`, exit **1639**)
  and the `persistent-task` preset uses `schtasks /SC ONSTART` (needs admin). On
  failure `install apply` **rolls back completely** — no scripts, no routing, no
  service left behind. `--learn` also has no `install apply` flag and no env var,
  so even a working install couldn't enable it. Bare `sc.exe` can't host the
  console proxy either (SCM kills it for not answering service control). **NSSM is
  the working path** — it reports RUNNING while supervising the child. Because
  `--learn` lives in NSSM's `AppParameters`, nothing regenerates/strips it (the
  old "re-apply drops `--learn`" hazard does not apply to the NSSM setup).
- **A SYSTEM-run service needs profile overrides or `--learn` is dead weight.**
  NSSM defaults to LocalSystem, whose `~` is `…\config\systemprofile` — so without
  `AppEnvironmentExtra USERPROFILE=C:\Users\ichbi` the learner scans an empty
  `~/.claude/projects` and finds nothing, and memory writes to the wrong profile.
  Set `USERPROFILE` + `HEADROOM_MEMORY_DB_PATH` + `HEADROOM_LOG_FILE`, or run the
  service as your user (`nssm edit` → *Log on*, needs your Windows password). Auth
  is unaffected either way — the proxy forwards the client's per-request token, so
  SYSTEM never needs your credentials for the API itself.
- **Never paste the `<!-- headroom:learn -->` markers into tracked `CLAUDE.md`.**
  `writer.py:_migrate_legacy_block` will rewrite / `unlink()` `CLAUDE.md`
  out-of-band on `main` if it finds the block there — bypassing the read-only-main
  PreToolUse hook. When curating, promote learnings as **plain unfenced prose**.
- **`skip-worktree` on `CLAUDE.local.md`/`CLAUDE.md` is self-defeating on main.**
  With a local mod + skip-worktree, `porcelain` reads clean so the pull guard
  passes, but `git pull --ff-only` then *aborts* ("would overwrite") — silently,
  forever, via `|| true`. Use `.gitignore`, not `skip-worktree`.
- **Auto-memory co-mingling (accepted).** Learn's memory-category patterns write
  a fenced block into `~/.claude/projects/.../memory/MEMORY.md` — the same
  auto-memory index loaded into every session. No redirect lever exists. It's a
  content-quality tradeoff (machine-extracted noise enters context unreviewed);
  the curation step is the control.
- **Routing-vs-proxy-up window.** `ANTHROPIC_BASE_URL` is global once installed;
  a Claude session that starts while the service is down routes **all** traffic
  (not just learning) to a dead port and can't reach the API. Mitigations:
  `start=auto` + `restart/5000` + `/readyz`. **Fallback:** unset/override
  `ANTHROPIC_BASE_URL` to get Claude working if the proxy is ever down.
- **The SessionStart hook installs headroom but does NOT wire it** (no MCP
  register, no proxy start, no routing). By design the hook only guarantees the
  *package* is present in cloud/remote sessions; wiring (MCP reg, service) is
  machine-local. A fresh clone / remote session therefore gets dead-weight
  headroom again unless separately wired. (Left as-is per owner decision
  2026-07-09 — local-only usage.)

---

## Change log

- **2026-07-09** — Diagnosed 2-week dead-weight install; wired for real:
  registered the `headroom` MCP (`headroom mcp install --agent claude`), stood
  up the proxy in `cache` mode with `--memory --learn`, decided reversible-CCR
  (`cache`) over lossy `token`. Added the `CLAUDE.local.md` / `HEADROOM_MEMORY.md`
  `.gitignore` lines (PR #206) + this doc. Plan cold-reviewed by Fable against the
  0.27.0 source: caught the merge-before-live-learn ordering; dropped a
  self-defeating `skip-worktree` approach.
- **2026-07-09 (same day, superseding update)** — `headroom install apply` proved
  **broken on Windows** (sc.exe `start=`/exit-1639 quoting bug; rolls back). The
  planned `install apply` + `run-headroom.ps1 --learn` patch was **abandoned**;
  replaced with a real **NSSM service `HeadroomProxy`** (`--learn` baked into
  `AppParameters`; SYSTEM-profile overrides via `AppEnvironmentExtra`; auto-start
  + auto-restart). Routing set with `setx ANTHROPIC_BASE_URL`. Verified live:
  `SERVICE_RUNNING`, `readyz` memory healthy, `health` memory+learn true, mode
  cache, memory DB resolved to the user profile. This doc updated to match.
