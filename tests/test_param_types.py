"""Every type here must return the input string UNCHANGED -- that is the whole
point (no command body changes). These tests exist to pin that contract."""
import click
import pytest

from autogis.adapters.param_types import CommaList, IsoDate, SuggestedChoice


def _convert(param_type, value):
    return param_type.convert(value, None, None)


class TestCommaList:
    VOCAB = ("nondetects", "rpd_sheet", "blanks")

    def test_returns_original_string_unchanged(self):
        t = CommaList(self.VOCAB)
        assert _convert(t, "nondetects,rpd_sheet") == "nondetects,rpd_sheet"

    def test_preserves_whitespace_and_order_verbatim(self):
        # The bodies do their own .split(",")/.strip(); we must not pre-chew it.
        t = CommaList(self.VOCAB)
        assert _convert(t, " nondetects , blanks ") == " nondetects , blanks "

    def test_empty_string_is_allowed(self):
        # Several of these options default to "".
        assert _convert(CommaList(self.VOCAB), "") == ""

    def test_unknown_element_fails_and_names_the_legal_values(self):
        t = CommaList(self.VOCAB)
        with pytest.raises(click.BadParameter) as exc:
            _convert(t, "nondetects,typo_feature")
        msg = str(exc.value)
        assert "typo_feature" in msg
        assert "nondetects" in msg and "rpd_sheet" in msg

    def test_case_insensitive_mode_accepts_other_casing(self):
        t = CommaList(("GW", "SOIL"), case_sensitive=False)
        assert _convert(t, "gw,soil") == "gw,soil"  # unchanged, still accepted

    def test_choices_attribute_exposes_vocabulary(self):
        assert CommaList(self.VOCAB).choices == self.VOCAB


class TestSuggestedChoice:
    def test_accepts_a_known_value(self):
        assert _convert(SuggestedChoice(("GW", "SOIL")), "GW") == "GW"

    def test_accepts_an_UNKNOWN_value_unchanged(self):
        # This is the entire reason this type exists instead of click.Choice.
        assert _convert(SuggestedChoice(("GW", "SOIL")), "SED") == "SED"

    def test_choices_attribute_exposes_suggestions(self):
        assert SuggestedChoice(("GW", "SOIL")).choices == ("GW", "SOIL")


class TestIsoDate:
    def test_returns_original_string_unchanged(self):
        assert _convert(IsoDate(), "2026-07-25") == "2026-07-25"

    def test_rejects_a_malformed_date(self):
        with pytest.raises(click.BadParameter):
            _convert(IsoDate(), "25-07-2026")

    def test_date_only_mode_rejects_a_timestamp(self):
        with pytest.raises(click.BadParameter):
            _convert(IsoDate(), "2026-07-25T10:30:00")

    def test_allow_time_mode_accepts_a_timestamp(self):
        # run-history --since calls datetime.fromisoformat today, so narrowing
        # it to date-only would reject a value that works.
        t = IsoDate(allow_time=True)
        assert _convert(t, "2026-07-25T10:30:00") == "2026-07-25T10:30:00"

    def test_allow_time_mode_still_accepts_a_bare_date(self):
        assert _convert(IsoDate(allow_time=True), "2026-07-25") == "2026-07-25"
