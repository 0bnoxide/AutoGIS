Query the codebase-memory indexed graph before falling back to manual search.

> Local-only: the codebase-memory MCP server is no longer wired into the repo
> (see `docs/codebase-memory-mcp.md`). These `mcp__codebase-memory-mcp__*` tools
> exist only if you've installed the server at user scope on your machine. If
> they're unavailable (e.g. web/cloud sessions), use Grep / Glob / Read instead.

## Steps

1. **Check index freshness** — call `mcp__codebase-memory-mcp__index_status`. If the
   index is stale or missing, run `mcp__codebase-memory-mcp__detect_changes` then
   `mcp__codebase-memory-mcp__index_repository` before querying.

2. **Choose the right tool for the question:**

   | Question type | Tool |
   |---|---|
   | Find a symbol, module, or concept | `mcp__codebase-memory-mcp__search_graph` |
   | Find code by keyword or pattern | `mcp__codebase-memory-mcp__search_code` |
   | How does A call / depend on B? | `mcp__codebase-memory-mcp__trace_path` |
   | Layer / module overview | `mcp__codebase-memory-mcp__get_architecture` |
   | Fetch a specific snippet | `mcp__codebase-memory-mcp__get_code_snippet` |

3. **Use graph results to answer the question directly.** Only open files with Read
   or Grep if you need line-level content the graph result doesn't include.

4. **If the graph misses something**, note it — the index may need a refresh or the
   concept may not be indexed yet. Fall back to Grep/Glob and flag the gap.

## Usage

Invoked as `/graph [optional: describe what you're looking for]`.

If an argument is provided, start with the most relevant graph tool for that query.
If no argument is provided, check index status and report what's indexed.
