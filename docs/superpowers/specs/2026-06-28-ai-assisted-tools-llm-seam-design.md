# AI-Assisted Tools + LLM Seam Design

**Date:** 2026-06-28
**Status:** DEFERRED — design approved; implementation blocked on the LLM seam below
**Tools:** AIDraftParserProfile (11.1), AIExplainQAReport (11.2), AIDraftFigureSpec (11.3),
AIMapReviewChecklist (11.4)
**Priority:** LOW — deferred per `ROADMAP_STATUS_2026-06-27`; all four need the shared seam first

---

## Why one spec

The four §11 tools are deferred for the same reason: none can be built until the
repo has an **LLM client seam**. They also share the same guardrail (the LLM only
*drafts*; deterministic core code does the real work) and the same arcpy-free,
dependency-injected shape. Specced together so the seam is designed once; each tool
gets its own module + CLI command when the seam lands.

---

## The blocking dependency: the LLM seam

**Chosen:** A single injected `LLMClient` protocol in `core/common/llm.py`. Core
tools depend on the protocol, never on a concrete SDK — exactly the
injected-`gis` discipline the AGOL tools use (`publish.py`). The concrete
implementation wraps the official **Anthropic SDK** (`anthropic`), default model
**`claude-opus-4-8`**, built only in the CLI/adapter seam where credentials live.
Tests inject a fake client returning canned completions — no network, no key, CI-safe.

```python
# core/common/llm.py
class LLMClient(Protocol):
    def complete(self, *, system: str, user: str, max_tokens: int = 4096) -> str: ...

# adapters/llm_anthropic.py  (only place that imports `anthropic`)
def anthropic_client(*, model: str = "claude-opus-4-8") -> LLMClient: ...
```

`anthropic` is an **optional dependency** (a `[project.optional-dependencies] ai`
extra); `core/common/llm.py` defines only the protocol and imports nothing, so the
arcpy-free / arcgis-free import invariant (ADR-0002) extends to the AI deps too.

**Guardrail (applies to every §11 tool):** the LLM output is always a *draft* that a
human reviews; the deterministic tool performs the real action. AI-drafted parser
profiles are imported by `result_parser`, not the LLM; AI explanations summarize a QA
report the deterministic QA framework produced; AI figure specs are validated by
`validate_config` before use. This mirrors the existing DRAFT-banner discipline
(ADR-0011) — AI output carries a `DRAFT_AI_GENERATED` marker and `_TODO` fields.

**Rejected: a provider-agnostic adapter for v1.** One concrete client (Anthropic)
behind the protocol is enough; a second provider can implement the same protocol
later without touching any tool. (ponytail: one implementation now, not a plugin
framework.)

**Rejected: letting the LLM call tools / write the database.** The seam is
text-in / text-out only. No tool-use loop, no DB writes from the model — the
deterministic pipeline owns all side effects.

---

## Architecture

```
autogis/
  core/common/
    llm.py                    ← NEW: LLMClient protocol only (no SDK import)
  core/envmon/
    ai_parser_profile.py      ← NEW (11.1)
    ai_qa_explainer.py        ← NEW (11.2)
    ai_figure_spec.py         ← NEW (11.3)
    ai_map_review.py          ← NEW (11.4)
  adapters/
    llm_anthropic.py          ← NEW: Anthropic SDK wrapper (only SDK import site)
    cli.py                    ← add ai-* commands; build client, inject
tests/envmon/
  test_ai_*.py                ← NEW (fake LLMClient, no network)
```

---

## Per-tool design

### 11.1 AIDraftParserProfile

Consumes the workbook-inspection JSON from `CreateWorkbookParserProfile` (2.1, the
deterministic drafter) plus an example profile, and asks the LLM to propose parser
YAML. Output is a *draft* the human confirms and `result_parser` imports.
`draft_parser_profile_ai(inspection, *, llm, example_profile) -> AIDraftResult` with
`profile`, `confidence_notes`, `fields_needing_confirmation`. Builds on 2.1, does not
replace its deterministic heuristics.

### 11.2 AIExplainQAReport

Turns a machine QA report (`QACollector` output) into a plain-language summary for
non-technical staff. `explain_qa(qa_rows, *, llm) -> str`. Reads the existing QA
CSV/JSON; the numbers come from the deterministic QA, the LLM only narrates. Sibling
of the deterministic `GenerateEventChangeLog` (9.3) — that one is template-based and
CI-deterministic; this one is the LLM-narrated variant.

### 11.3 AIDraftFigureSpec

Drafts a figure-spec YAML from selected analytes + desired map type + an example
style + site config. `draft_figure_spec(*, analytes, map_type, example, llm) ->
AIFigureSpecResult`. The draft is run through `validate_config` (10.2) before any use —
an invalid AI spec is a QA error, never silently accepted.

### 11.4 AIMapReviewChecklist

Given map-export metadata + QA results, generates a review checklist (missing
title/date, empty layers, too many callout collisions, unresolved QA, contour review
status, missing analytical key, unmatched wells). `build_review_checklist(*,
export_meta, qa_rows, llm) -> list[str]`. Consumes outputs that already exist
(export manifest, QA, collisions); the LLM organizes them into a reviewer-facing list.

---

## CLI Commands

```
autogis envmon ai-draft-parser-profile --inspection <insp.json> --example <ex.yaml> --out <draft.yaml>
autogis envmon ai-explain-qa           --qa <qa.csv> --out <summary.md>
autogis envmon ai-draft-figure-spec    --analytes Benzene,MTBE --map-type GW_ANALYTICAL --out <spec.yaml>
autogis envmon ai-map-review           --export-meta <meta.json> --qa <qa.csv> --out <checklist.md>
```

Each requires the `ai` extra (`anthropic` + credentials). Without it the command
fails with a clean "AI features require the `ai` extra and ANTHROPIC_API_KEY" error —
the same clean-guard pattern as the arcpy `_guard`.

---

## Test Strategy

`tests/envmon/test_ai_*.py` — arcpy-free, **no network**, fake `LLMClient`:

1. `core/common/llm.py` imports without `anthropic` installed (protocol only).
2. Each tool calls `llm.complete` exactly once with a system+user prompt built from its inputs.
3. AI parser-profile output carries the `DRAFT_AI_GENERATED` marker.
4. `explain_qa` passes the QA rows into the user prompt; returns the fake completion.
5. `draft_figure_spec` output is routed through `validate_config`; an invalid draft → QA error.
6. `build_review_checklist` includes a line for each failing input category.
7. CLI command raises a clean error (not a traceback) when the `ai` extra is absent.
```
