"""Generate the DesignSync preview bundle FROM the render-layer builders, so the
claude.ai/design visual spec cannot drift from the markup the tools emit.

Run:  python docs/design/report-templates/build_bundle.py
Then push with the DesignSync tool (see this file's sibling README / the plan).
"""
from __future__ import annotations

import sys
from pathlib import Path

# Allow running as a plain script from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from autogis.core.common import report_html as rh  # noqa: E402


def _preview(group: str, title: str, body_html: str) -> str:
    css = rh.css()
    return (f'<!-- @dsCard group="{group}" -->\n'
            "<!doctype html>\n"
            f'<html lang="en"><head><meta charset="utf-8"/><title>{title}</title>'
            f'<style>{css}</style></head><body><main class="report" '
            'style="margin:12px auto">'
            f"{body_html}</main></body></html>\n")


def build(out_dir) -> list:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    pages = {
        "kpi_row.html": _preview("Components", "KPI row", rh.kpi_row([
            ("Total wells", 42, "neutral"), ("Never inspected", 3, "warn"),
            ("Needs attention", 1, "bad")])),
        "data_table.html": _preview("Components", "Data table", rh.table(
            ["Location", "Analyte", "Result", "Status"],
            [["MW-1", "Benzene", "5.5", "EXCEED"], ["MW-2", "Benzene", "<1.0", "OK"]],
            tone_of=lambda i, j: ("bad" if i == 0 else "ok") if j == 3 else None)),
        "badges.html": _preview("Components", "Status badges",
            " ".join(rh.badge(t.upper(), t) for t in
                     ["ok", "warn", "bad", "info", "neutral"])),
        "photo_grid.html": _preview("Components", "Photo grid", rh.photo_grid([
            # 1x1 transparent PNG data URI — self-contained placeholder.
            ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1"
             "HAwCAAAAC0lEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==",
             "MW-1 — wellhead")])),
        "report_shell.html": (
            '<!-- @dsCard group="Shell" -->\n' + rh.render_document(
                title="Well Inspection Report — MW-1",
                meta={"Owner": "ACME", "Site": "Demo"},
                sections=[rh.section("Inspection History", rh.table(
                    ["Date", "Condition", "Notes"],
                    [["2026-04-01", "GOOD", "clear"]]))],
                generated="2026-07-11")),
    }
    written = []
    for name, html in pages.items():
        p = out / name
        p.write_text(html, encoding="utf-8")
        written.append(str(p))
    return written


if __name__ == "__main__":
    for p in build(Path(__file__).resolve().parent):
        print("wrote", p)
