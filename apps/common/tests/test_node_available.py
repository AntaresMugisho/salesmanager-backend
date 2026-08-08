"""One loud failure instead of several silent skips.

Five modules compare Python against JavaScript:

- `apps/sales/tests/test_totals.py` — money arithmetic
- `apps/finance/tests/test_period.py` — French month labels
- `apps/finance/tests/test_aggregate.py` — the finance folds
- `apps/common/tests/test_collation.py` — French collation, against real ICU
- `apps/reports/tests/test_against_the_frontend.py` — two report builders

Each skips when `node` is absent, which is right for a quick local run and
wrong for CI: the suite would report green while testing none of the
cross-language agreement that money, margins and sorting depend on. A skip is
indistinguishable from a pass in most CI summaries.

Set ALLOW_MISSING_NODE=1 to accept that trade deliberately.
"""

import os
import shutil

import pytest


def test_node_is_available_for_the_cross_language_checks():
    if os.environ.get("ALLOW_MISSING_NODE") == "1":
        pytest.skip("ALLOW_MISSING_NODE=1")
    assert shutil.which("node") is not None, (
        "node is not on PATH, so every Python/JavaScript comparison in this "
        "suite silently skipped. Install node, or set ALLOW_MISSING_NODE=1 to "
        "accept that."
    )
