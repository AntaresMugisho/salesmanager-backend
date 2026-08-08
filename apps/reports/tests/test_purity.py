"""The constraints that keep the builders diffable against the frontend.

Neither of these tests describes a feature. They describe the two properties
that let sub-project 5's and 6's cross-language comparisons exist at all, and
both are the kind of thing an ordinary refactor breaks without noticing.
"""

import pathlib
import re

import pytest

from apps.common.tests.purity import django_imports_of
from apps.reports import meta, profitability, result, sales, stock


class TestThePureModulesImportNoDjango:
    @pytest.mark.parametrize(
        "module",
        [meta, result, sales, profitability, stock],
        ids=["meta", "result", "sales", "profitability", "stock"],
    )
    def test_it(self, module):
        assert django_imports_of(module) == []


def test_no_bare_round_in_the_reports():
    """Money rounds through round_half_up; percentages are not rounded at all.

    Python's round() is banker's rounding and JavaScript's Math.round is
    half-up, so a bare round() here is a wrong cent on a printed document.
    """
    # Derived from the package, not a relative path: a cwd-dependent glob that
    # matches nothing would make this test pass by finding no files.
    app_root = pathlib.Path(result.__file__).parent
    sources = [p for p in app_root.rglob("*.py") if "tests" not in p.parts]
    assert sources, "found no modules to scan"

    offenders = [
        str(path)
        for path in sources
        if re.search(r"(?<![\w.])round\s*\(", path.read_text(encoding="utf-8"))
    ]
    assert offenders == []
