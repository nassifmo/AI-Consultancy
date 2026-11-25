from datetime import UTC, datetime

import pytest

from evaluator.eta_claims import quoted_eta


SENT = datetime(2026, 3, 1, 13, tzinfo=UTC)
UNKNOWN = (None, None, "sent_eta_needs_review")


@pytest.mark.parametrize(("message", "quote", "port", "expected"), [
    ("We expect her alongside in Rotterdam on 16 March at 11:00 local time.",
     "alongside in Rotterdam on 16 March at 11:00 local time", "Rotterdam",
     (datetime(2026, 3, 16, 10, tzinfo=UTC), 60, "ai_quote")),
    ("Expect the ship in port on 2026-03-16T11:00:10+01:00.",
     "2026-03-16T11:00:10+01:00", None,
     (datetime(2026, 3, 16, 10, 0, 10, tzinfo=UTC), 1, "ai_quote")),
])
def test_parses_absolute_time_from_verbatim_quote(message, quote, port, expected):
    assert quoted_eta(quote, message, SENT, port, "Europe/Amsterdam") == expected


@pytest.mark.parametrize(("message", "quote"), [
    ("We expect her alongside in Rotterdam on 16 March at 11:00 local time.",
     "16 March at 10:00 local time"),
    ("We expect her alongside on 16 March at 11:00 local time.",
     "16 March at 11:00 local time"),
    ("We expect her alongside Rotterdam on 29 March at 02:30 local time.",
     "29 March at 02:30 local time"),
    ("We expect her alongside on 16 March at 11:00 UTC or 17:00 UTC.",
     "16 March at 11:00 UTC"),
    ("We expect her on 16–17 March at 11:00 UTC.", "17 March at 11:00 UTC"),
    ("We expect her before 16 March at 11:00 UTC.", "16 March at 11:00 UTC"),
    ("We expect her in Rotterdam on 16 March at 11:00 local time UTC.",
     "16 March at 11:00 local time"),
    ("We expect her in port on 16 March at 11:00 UTC if the berth is ready.",
     "16 March at 11:00 UTC"),
    ("We expect her alongside tomorrow morning.", "tomorrow morning"),
    ("We expect her on 16 March at 11:00 UTC.", "16 March at 11:00"),
])
def test_leaves_invalid_clipped_or_ambiguous_times_unknown(message, quote):
    assert quoted_eta(quote, message, SENT, "Rotterdam", "Europe/Amsterdam") == UNKNOWN
