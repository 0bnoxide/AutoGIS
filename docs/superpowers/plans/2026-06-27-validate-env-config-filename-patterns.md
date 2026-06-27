# ValidateEnvConfig — Filename Pattern Validation (Phase 1.1 completion)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** Complete Phase 1.1 by adding `output_filename_pattern` validation to `config_validation.py:validate_figure_spec()`. The figure spec has an `output_filename_pattern` field that can contain format tokens like `{SiteID}_{EventDate}`. Validate that the pattern: (a) is a non-empty string, (b) contains only safe characters (alphanumeric, `_`, `-`, `.`, `{`, `}`, `/`), and (c) has balanced braces.

**Architecture:** Single function addition to `autogis/core/common/config_validation.py`. No new files.

## Global Constraints

- Branch: `feat/gdb-schema-upgrade` (already active; this item lands on the same branch)
- All code arcpy-free.
- Existing `validate_figure_spec()` tests must continue to pass.
- Run tests with `python -m pytest -q` from repo root.
- Commit after task completion.

---

### Task 1: Add failing test

**File:** `tests/common/test_config_validation.py` (already exists — append)

- [ ] **Step 1: Append tests**

```python
# Append to tests/common/test_config_validation.py

from autogis.core.common.config_validation import validate_figure_spec

_FIGURE_BASE = {
    "figure_spec_id": "FS-001",
    "site_id": "H281",
    "map_type": "GW_ANALYTICAL",
    "matrix": "GW",
    "output_filename_pattern": "{SiteID}_{EventDate}",
}

def test_valid_filename_pattern_passes():
    recs = validate_figure_spec(_FIGURE_BASE)
    cats = [r.category for r in recs]
    assert "invalid_filename_pattern" not in cats

def test_empty_filename_pattern_errors():
    spec = {**_FIGURE_BASE, "output_filename_pattern": ""}
    recs = validate_figure_spec(spec)
    assert any(r.category == "invalid_filename_pattern" for r in recs)

def test_unsafe_chars_in_pattern_errors():
    spec = {**_FIGURE_BASE, "output_filename_pattern": "{SiteID}; rm -rf /"}
    recs = validate_figure_spec(spec)
    assert any(r.category == "invalid_filename_pattern" for r in recs)

def test_unbalanced_braces_in_pattern_errors():
    spec = {**_FIGURE_BASE, "output_filename_pattern": "{SiteID_EventDate"}
    recs = validate_figure_spec(spec)
    assert any(r.category == "invalid_filename_pattern" for r in recs)

def test_missing_filename_pattern_is_warned():
    spec = {k: v for k, v in _FIGURE_BASE.items() if k != "output_filename_pattern"}
    recs = validate_figure_spec(spec)
    # WARNING not ERROR — optional field, not all figure specs have it
    warn = [r for r in recs if r.category == "missing_filename_pattern"]
    assert len(warn) == 1
    assert warn[0].severity == "WARNING"
```

- [ ] **Step 2: Run to confirm failure**

```
python -m pytest tests/common/test_config_validation.py -k "filename_pattern" -v
```

Expected: 5 failures.

---

### Task 2: Implement in config_validation.py

**File:** `autogis/core/common/config_validation.py`

- [ ] **Step 1: Add `_SAFE_PATTERN` regex near top of file (after imports)**

```python
import re as _re

_SAFE_PATTERN = _re.compile(r'^[A-Za-z0-9_.{}/\-]+$')
```

- [ ] **Step 2: Add helper**

```python
def _validate_filename_pattern(pattern: str, context: str) -> List[QARecord]:
    out: List[QARecord] = []
    if not pattern:
        return [_rec(SEV_ERROR, "invalid_filename_pattern",
                     f"{context}: output_filename_pattern is empty",
                     action="Set a non-empty filename pattern")]
    if not _SAFE_PATTERN.match(pattern):
        return [_rec(SEV_ERROR, "invalid_filename_pattern",
                     f"{context}: output_filename_pattern contains unsafe characters: {pattern!r}",
                     action="Use only alphanumeric, _, -, ., {, }, / characters")]
    if pattern.count("{") != pattern.count("}"):
        return [_rec(SEV_ERROR, "invalid_filename_pattern",
                     f"{context}: output_filename_pattern has unbalanced braces: {pattern!r}")]
    return out
```

- [ ] **Step 3: Add call inside `validate_figure_spec()`**

After the `_require()` call, add:

```python
    pat = data.get("output_filename_pattern")
    if pat is None:
        out.append(_rec(SEV_WARNING, "missing_filename_pattern",
                        f"{context}: output_filename_pattern not set",
                        action="Add output_filename_pattern to figure spec"))
    else:
        out.extend(_validate_filename_pattern(pat, context))
```

- [ ] **Step 4: Run tests**

```
python -m pytest tests/common/test_config_validation.py -k "filename_pattern" -v
```

Expected: 5 PASS.

- [ ] **Step 5: Full suite**

```
python -m pytest -q
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add autogis/core/common/config_validation.py tests/common/test_config_validation.py
git commit -m "feat(config_validation): add output_filename_pattern check to validate_figure_spec"
```
