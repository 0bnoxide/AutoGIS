"""Click parameter types that carry UI intent without changing the value.

Every type here validates (or merely annotates) its input and returns the
**original string unchanged**, so each command body keeps receiving exactly
what it receives today -- no body in the repo changes because of this module.
The value added is metadata: ``gui/introspect.py`` reads these types to decide
which control to render (checklist, editable dropdown, calendar), and the CLI
gains a parse-time error instead of a downstream surprise.

Why ``SuggestedChoice`` instead of ``click.Choice``: Choice *restricts*, and
several AutoGIS vocabularies are open in practice. ``KNOWN_MATRICES`` is
``{"GW", "SOIL"}`` but is a figure-spec vocabulary -- config/lab_profiles/
nysdec.yaml maps to ``SED``. ``UNIT_REGISTRY`` deliberately omits ppb/ppm
(units.py:3-7) yet legacy workbooks use them. Tool-name filters must still
match rows in an old run_history.csv written by a since-renamed command.
Restricting any of those would refuse input the CLI accepts today.

Why ``IsoDate`` instead of ``click.DateTime``: DateTime hands the body a
``datetime`` object. All 16 date options in cli.py call
``date.fromisoformat(...)`` on the value, which raises TypeError on a datetime;
one (``estimate-gw-flow-direction``) fails *silently* by writing
"2026-07-01 00:00:00" into a CSV cell. Validating the string and passing it
through keeps every call site working untouched.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Iterable

import click

__all__ = ["CommaList", "IsoDate", "SuggestedChoice"]


class SuggestedChoice(click.ParamType):
    """Offers a known vocabulary to the GUI but accepts ANY value.

    Renders as an *editable* combo box: pick a suggestion or type your own.
    Deliberately performs no validation -- see the module docstring.
    """

    name = "text"  # stays 'text' so nothing downstream re-types it

    def __init__(self, values: Iterable[str]):
        self.choices: tuple[str, ...] = tuple(values)

    def convert(self, value, param, ctx):
        return value

    def get_metavar(self, param, ctx=None):  # pragma: no cover - cosmetic
        return "TEXT"


class CommaList(click.ParamType):
    """A comma-joined subset of a CLOSED vocabulary.

    Keeps the existing CLI contract exactly -- still ``--features a,b`` -- and
    returns the original string, because each consuming body does its own
    ``.split(",")`` with its own strip/dedupe/case rules.
    """

    name = "commalist"

    def __init__(self, vocabulary: Iterable[str], *, case_sensitive: bool = True):
        self.choices: tuple[str, ...] = tuple(vocabulary)
        self.case_sensitive = case_sensitive

    def convert(self, value, param, ctx):
        if value is None or value == "":
            return value  # several options default to ""; blank means "none"
        haystack = (self.choices if self.case_sensitive
                    else tuple(c.casefold() for c in self.choices))
        for element in value.split(","):
            element = element.strip()
            if not element:
                continue  # bodies already tolerate blanks; don't get stricter
            probe = element if self.case_sensitive else element.casefold()
            if probe not in haystack:
                self.fail(
                    f"{element!r} is not one of "
                    f"{', '.join(repr(c) for c in self.choices)}.",
                    param, ctx)
        return value


class IsoDate(click.ParamType):
    """An ISO date, validated but returned as the original string.

    ``allow_time`` mirrors what the consuming body actually parses: most call
    sites use ``date.fromisoformat`` (date only), but ``run-history --since``
    uses ``datetime.fromisoformat`` and must keep accepting a full timestamp.
    """

    name = "isodate"

    def __init__(self, *, allow_time: bool = False):
        self.allow_time = allow_time

    def convert(self, value, param, ctx):
        if value is None or value == "":
            return value
        parser = datetime.fromisoformat if self.allow_time else date.fromisoformat
        try:
            parser(value)
        except (TypeError, ValueError):
            want = ("an ISO date or timestamp (YYYY-MM-DD[THH:MM:SS])"
                    if self.allow_time else "an ISO date (YYYY-MM-DD)")
            self.fail(f"{value!r} is not {want}.", param, ctx)
        return value
