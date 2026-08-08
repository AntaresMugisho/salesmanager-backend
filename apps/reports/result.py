"""The compte de résultat.

Deliberately thin: every figure on this document is already computed and
unit-tested in `apps.finance.aggregate`. Recomputing any of it here would
create a second arithmetic that could drift from /finances.
"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from apps.finance.aggregate import build_expense_breakdown, summarise
from apps.reports.meta import report_meta


def build_result_report(
    facts: dict, tz: ZoneInfo, start: date, end: date, generated_at: datetime
) -> dict:
    return {
        "meta": report_meta(start, end, generated_at),
        "summary": summarise(facts, tz, start, end),
        "expenses": build_expense_breakdown(facts, tz, start, end),
    }
