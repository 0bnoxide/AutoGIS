# AI-Assisted Tools + LLM Seam Design

**Date:** 2026-06-28
**Reviewed:** 2026-08-01
**Status:** DEFERRED — gate reviewed; owner chose not to reopen implementation
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

## 2026-08-01 gate-review addendum

This addendum records a repository-backed Codex review, an independent Claude
review with repository access, and the owner's decision to **keep the §11 gate
closed**. It refines the future design; it does not authorize implementation or
turn these tools into a pickable backlog. Where it conflicts with the original
2026 sketch retained below, this addendum controls.

### Reopening threshold

Reconsider the group only when a concrete workflow demonstrates that the
deterministic tools are insufficient, for example:

- a real workbook that `propose_parser_profile` handles poorly; or
- staff need a plain-language QA product that the existing deterministic
  `QACollector.write_markdown()` report does not provide.

Convenience alone does not justify API-key handling, external data egress,
provenance storage, model-cost controls, and an additional CI install matrix.

### Verified repository baseline

- None of the four tools has code, CLI/capability registration, an `ai` extra,
  a provider adapter, a dedicated issue, or an active PR.
- `AIDraftParserProfile` has the strongest future tracer-bullet seam:
  `WorkbookInspectionReport`, `propose_parser_profile`, inspection JSON output,
  `validate_parser_profile`, and `envmon draft-parser-profile` already exist.
  An AI path should refine that deterministic draft, not replace it.
- `AIExplainQAReport` has detailed `QACollector.write_csv()` records, while
  `write_json_summary()` contains counts rather than record detail. A future ADR
  must define the bounded/redacted input contract and explain the value beyond
  `write_markdown()` before this tool proceeds. The default candidate is bounded,
  redacted CSV records, not the counts-only JSON summary.
- `AIDraftFigureSpec` must validate through the current
  `validate_figure_spec()` / `FigureSpec` seam.
- `AIMapReviewChecklist` has no unified `export_meta`, export manifest, or
  `MapReviewFacts` artifact. Missing title/layer/collision/pass-fail facts must
  first become a deterministic, base-install feature. Once those facts exist,
  reconsider whether an LLM adds value over a template renderer.

### Required design refresh if the gate reopens

1. **Packaging:** keep one distribution and add `pip install "autogis[ai]"`.
   Commands remain discoverable without the extra and fail before network work
   with the exact install hint. A separate `autogis-ai` package is not justified
   while the tools consume internal AutoGIS contracts and share its release
   cadence.
2. **Boundary:** keep one injected `LLMClient` protocol in core and one lazy
   Anthropic adapter. No provider framework, model tool calls, database writes,
   or module-level SDK import. The model ID is configurable and its default is
   verified against current provider documentation when implementation begins.
3. **Current response semantics:** use schema-constrained structured output for
   structured drafts when the selected API supports it, then run the existing
   domain validator. Treat refusal and token-limit/truncation stop reasons as
   hard failures before reading or writing content; do not accept a repair of a
   truncated response, and do not depend on removed assistant-prefill behavior.
4. **Data egress:** define a per-tool, per-field allowlist. Workbook/sheet names,
   headers, units, nonnumeric tokens, QA messages, site names, and coordinates
   may identify clients and are not safe merely because they are called
   metadata. Workbook cells and other untrusted strings are prompt-injection
   inputs; model output remains an untrusted draft.
5. **Validation and fallback:** never write a structured AI artifact unless it
   passes its deterministic validator. Parser drafting falls back to the valid
   deterministic draft when the AI path fails. AI output cannot feed an import,
   render, or other pipeline action until a human has reviewed it.
6. **Provenance and writes:** write a sidecar containing model and request IDs,
   token counts, temperature/effort where applicable, timestamp, prompt hash,
   and input-file hashes. Default to refusing overwrite.
7. **Tests:** retain fake-client, no-network tests and add malformed output,
   refusal, truncation, prompt-injection, validation-failure, deterministic-
   fallback, and base-install-without-`[ai]` coverage.
8. **CLI:** an `autogis envmon ai ...` subgroup is the preferred future shape,
   with consistently named `draft-*` commands. This intentionally supersedes
   the flat command sketch below and must be recorded in the reopening ADR and
   `runtime/capabilities.py`. Deterministic `MapReviewFacts` stays outside it.

Later improvements, only after the seam proves useful, are a machine-readable
diff from the deterministic parser baseline, distinct CLI exit codes for
dependency/auth/network/validation failures, golden prompt snapshots, an
explicit no-socket CI assertion, and optional cost/token reporting.

### Deferred implementation order

If a later owner decision reopens the gate:

1. reopening/design ADR plus the shared seam and install boundary;
2. `AIDraftParserProfile` tracer bullet;
3. `AIExplainQAReport` after its input/value decision;
4. `AIDraftFigureSpec`; and
5. deterministic `MapReviewFacts`, followed by a fresh YAGNI decision on
   `AIMapReviewChecklist`.

---

## The blocking dependency: the LLM seam

**Chosen:** A single injected `LLMClient` protocol in `core/common/llm.py`. Core
tools depend on the protocol, never on a concrete SDK — exactly the
injected-`gis` discipline the AGOL tools use (`publish.py`). The concrete
implementation wraps the official **Anthropic SDK** (`anthropic`). The model is
configured at the CLI/adapter seam where credentials live; its default is chosen
from current provider documentation when implementation begins, not frozen here.
Tests inject a fake client returning canned completions — no network, no key, CI-safe.

```python
# core/common/llm.py
class LLMClient(Protocol):
    def complete(self, *, system: str, user: str, max_tokens: int = 4096) -> str: ...

# adapters/llm_anthropic.py  (only place that imports `anthropic`)
def anthropic_client(*, model: str) -> LLMClient: ...
```

`anthropic` is an **optional dependency** (a `[project.optional-dependencies] ai`
extra); `core/common/llm.py` defines only the protocol and imports nothing, so the
arcpy-free / arcgis-free import invariant (ADR-0002) extends to the AI deps too.

**Guardrail (applies to every §11 tool):** the LLM output is always a *draft* that a
human reviews; the deterministic tool performs the real action. AI-drafted parser
profiles are imported by `result_parser`, not the LLM; AI explanations summarize a QA
report the deterministic QA framework produced; AI figure specs are validated by
`validate_figure_spec` before use. This mirrors the existing DRAFT-banner discipline
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
AIFigureSpecResult`. The draft is run through `validate_figure_spec` before any use —
an invalid AI spec is a QA error, never silently accepted.

### 11.4 AIMapReviewChecklist

Given map-export metadata + QA results, generates a review checklist (missing
title/date, empty layers, too many callout collisions, unresolved QA, contour review
status, missing analytical key, unmatched wells). `build_review_checklist(*,
export_meta, qa_rows, llm) -> list[str]`. The required unified export metadata
does not exist yet; build deterministic map-review facts before revisiting this
LLM wrapper.

---

## CLI Commands

Historical flat-command sketch; the reviewed future direction is the `envmon ai`
subgroup in the controlling addendum above.

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
5. `draft_figure_spec` output is routed through `validate_figure_spec`; an invalid draft → QA error.
6. `build_review_checklist` includes a line for each failing input category.
7. CLI command raises a clean error (not a traceback) when the `ai` extra is absent.
