import autogis.core.common.report_html as rh


def test_text_context_escaping_renders_script_inert():
    out = rh.table(["A"], [["<script>alert(1)</script>"]])
    assert "<script>alert(1)" not in out
    assert "&lt;script&gt;" in out


def test_attribute_context_escaping_cannot_break_out():
    # A caption/src containing a double-quote must not escape the attribute.
    out = rh.photo_grid([('data:image/jpeg;base64,AAA" onerror="x', 'cap"tion')])
    assert 'onerror="x' not in out
    assert "&quot;" in out


def test_badge_applies_tone_class_and_falls_back_on_bad_tone():
    assert 'class="badge tone-bad"' in rh.badge("EXCEED", "bad")
    assert 'class="badge tone-neutral"' in rh.badge("x", "nonsense")


def test_kpi_row_and_table_structure():
    assert 'class="kpi-row"' in rh.kpi_row([("Wells", 5, "neutral")])
    t = rh.table(["H1", "H2"], [["a", "b"]], tone_of=lambda i, j: "bad" if j == 1 else None)
    assert "<th>H1</th>" in t and "<td>a</td>" in t and 'class="tone-bad"' in t


def test_render_document_is_self_contained():
    doc = rh.render_document(
        title="T", subtitle="S", meta={"Site": "X"},
        sections=[rh.section("Sec", "<p>body</p>")], generated="2026-07-11",
    )
    assert doc.startswith("<!doctype html>")
    assert "<style>" in doc and ".report" in doc          # CSS inlined
    assert "http://" not in doc and "https://" not in doc  # no external refs
    assert 'src="http' not in doc and 'href="http' not in doc


def test_render_document_is_deterministic():
    kw = dict(title="T", sections=[rh.section("S", "<p>x</p>")], generated="2026-07-11")
    assert rh.render_document(**kw) == rh.render_document(**kw)
