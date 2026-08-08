"""The header block every report document prints.

Carried on the payload rather than read from the URL by the client, so a
document can never print a period its figures do not cover: the header and the
numbers come from the same response.
"""

from datetime import date, datetime


def report_meta(start: date, end: date, generated_at: datetime) -> dict:
    return {
        "range": {"from": start.isoformat(), "to": end.isoformat()},
        "generated_at": generated_at,
    }
