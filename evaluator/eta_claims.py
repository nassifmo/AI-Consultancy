"""Read explicit ETA claims in the supported customer-facing text formats."""

from datetime import UTC, datetime, timedelta
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


ETA_MENTION = re.compile(
    r"\b(?:ETA|arrival estimate|estimated (?:time of )?arrival|estimate for (?:destination )?arrival)\b",
    re.IGNORECASE,
)
STATUS_ONLY = re.compile(
    r"(?:the |your )?(?:vessel|ship|shipment|container)(?: [\w-]+\d[\w-]*)? "
    r"(?:(?:has|is|was)(?: already| currently)? )?"
    r"(?:departed|booked|loaded|discharged|released|unloaded|gated in|gated out)[.!]?",
    re.IGNORECASE,
)
ETA_UNAVAILABLE = re.compile(
    r"(?:(?:the )?(?:ETA|arrival estimate)(?: is |:\s*)(?:unknown|unavailable|not (?:yet )?available)"
    r"|no (?:confirmed |current )?(?:ETA|arrival estimate) (?:is )?(?:available|known)"
    r"|(?:I|we) (?:cannot|can't) (?:confirm|provide|verify) (?:the |an )?(?:ETA|arrival estimate))[.!]?",
    re.IGNORECASE,
)
CLAIM_PREFIX = re.compile(r"\s*(?:(?:is|was|moved to|changed to|of|on)\b\s*)?[:=]?\s*", re.IGNORECASE)
ISO_TIME = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?P<seconds>:\d{2})?(?:Z|[+-]\d{2}:\d{2})(?![\w:])")
WRITTEN_TIME = re.compile(
    r"(?P<day>\d{1,2})\s+(?P<month>[A-Za-z]+)\s+(?:(?P<year>\d{4})\s+)?(?:arrival estimate\s+)?(?:at\s+)?"
    r"(?P<hour>\d{1,2}):(?P<minute>\d{2})\s+(?P<zone>UTC|local time)\b",
    re.IGNORECASE,
)
DATE_BEFORE = re.compile(r"\b\d{1,2}\s+[A-Za-z]+\s+(?:\d{4}\s+)?$")
CLOCK_TIME = re.compile(r"(?<![\d:])\d{1,2}:\d{2}(?::\d{2})?(?![\d:])")
SENTENCE_TEXT = re.compile(r"[^.!?\n]+")
AMBIGUOUS_TIMING = re.compile(
    r"\b(?:or|between|before|after|until|around|approximately|unless|if|not|"
    r"as early as|as late as|by)\b|\b\d{1,2}\s*[-–—/]\s*\d{1,2}\s+[A-Za-z]",
    re.IGNORECASE,
)
_FUTURE_ETA_UPDATE = re.compile(
    rf"\b(?:will|(?:we|i)['’]ll)\s+(?:send|share|provide|give|confirm)\b[^.!?]{{0,75}}{ETA_MENTION.pattern}",
    re.IGNORECASE,
)
_ARRIVAL_LOCATION = re.compile(
    r"\b(?:arriv(?:e|al|ing)|due|expected|alongside|dock(?:ing)?|berth(?:ing)?)\s+(?:in|at)\s+"
    r"(?P<place>[^\W\d_][\w '\-]{0,48}?)\s+(?=(?:on|at|between|by)\b|\d)",
    re.IGNORECASE,
)
MONTHS = {name: index for index, month in enumerate(
    ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"), 1
) for name in (month, month[:3])}


def requested_eta_response(message, basis):
    """Distinguish a known omission from wording an assessor still needs to read."""
    if basis in {"sent_message", "ai_quote"}:
        return "provided"
    text = (message or "").strip()
    if basis == "no_eta_in_sent_message" and STATUS_ONLY.fullmatch(text):
        return "omitted"
    if ETA_UNAVAILABLE.fullmatch(text):
        return "declared_unavailable"
    return "unknown"


def conflicting_eta_passage(text, port_name):
    """Reject a release-time promise or an explicitly named different arrival location."""
    if not isinstance(text, str) or _FUTURE_ETA_UPDATE.search(text):
        return True
    return bool(port_name and any(
        not re.search(rf"\b{re.escape(port_name)}\b", place["place"], re.IGNORECASE)
        for place in _ARRIVAL_LOCATION.finditer(text)
    ))


def _written_instant(match, sent, zone_name):
    month = MONTHS.get(match["month"].casefold())
    if month is None:
        return None
    zone = UTC if match["zone"].casefold() == "utc" else ZoneInfo(zone_name) if zone_name else None
    if zone is None:
        return None
    sent_local = sent.astimezone(zone)
    stated_year = match["year"]
    years = [int(stated_year)] if stated_year else range(sent_local.year - 1, sent_local.year + 2)
    candidates = []
    for year in years:
        try:
            local = datetime(year, month, int(match["day"]), int(match["hour"]), int(match["minute"]), tzinfo=zone)
        except ValueError:
            continue
        if local.utcoffset() != local.replace(fold=1).utcoffset():
            continue  # An ambiguous or skipped local clock time needs a confirmed offset.
        if stated_year or abs(local - sent_local) < timedelta(days=183):
            candidates.append(local.astimezone(UTC))
    return candidates[0] if len(candidates) == 1 else None


def _parse_time(timestamp, *, explicit, sent, message, port_name, port_timezone):
    if explicit:
        value = datetime.fromisoformat(timestamp[0]).astimezone(UTC)
        return value, 1 if timestamp["seconds"] else 60
    # Resolve destination-local wording only if the delivered message names the port.
    zone = (port_timezone if port_name and re.search(r"\b" + re.escape(port_name) + r"\b", message, re.IGNORECASE)
            else None)
    value = _written_instant(timestamp, sent, zone)
    return (value, 60) if value is not None else None


def sent_eta(message, sent, port_name, port_timezone):
    """Return the unique, explicit timestamp and how it was obtained."""
    message = message or ""
    mentions = list(ETA_MENTION.finditer(message))
    if not mentions:
        return None, None, "no_eta_in_sent_message"
    values = set()
    for mention in mentions:
        statement = re.split(r"[.!?;\n]", message[:mention.end()])[-1]
        if _FUTURE_ETA_UPDATE.search(statement):
            continue
        start = CLAIM_PREFIX.match(message, mention.end()).end()
        explicit = ISO_TIME.match(message, start)
        written = WRITTEN_TIME.match(message, start)
        if not explicit and not written and mention[0].casefold() == "arrival estimate":
            date_before = DATE_BEFORE.search(message, 0, mention.start())
            if date_before:
                written = WRITTEN_TIME.match(message, date_before.start())
        timestamp = explicit or written
        if timestamp is None or message[timestamp.end():].lstrip()[:1] not in {"", ".", ";", "!", "?"}:
            values.add(None)
            continue
        try:
            values.add(_parse_time(timestamp, explicit=explicit is not None, sent=sent,
                                   message=message, port_name=port_name, port_timezone=port_timezone))
        except (ValueError, OverflowError, ZoneInfoNotFoundError):
            values.add(None)
    if len(values) != 1 or None in values:
        return None, None, "sent_eta_needs_review"
    value, precision = values.pop()
    return value, precision, "sent_message"


def quoted_eta(quote, message, sent, port_name, port_timezone):
    """Verify a time supported by the verbatim passage the interpreter selected."""
    unknown = (None, None, "sent_eta_needs_review")
    if not isinstance(quote, str) or not quote.strip() or not isinstance(message, str):
        return unknown
    start = message.find(quote)
    if start < 0 or not isinstance(sent, datetime) or sent.utcoffset() is None:
        return unknown
    matches = [(match, pattern is ISO_TIME) for pattern in (ISO_TIME, WRITTEN_TIME)
               for match in pattern.finditer(message)]
    if len(matches) != 1:
        return unknown
    timestamp, explicit = matches[0]
    if not start <= timestamp.start() < timestamp.end() <= start + len(quote):
        return unknown
    if timestamp.start() and re.match(r"\w", message[timestamp.start() - 1]):
        return unknown
    if any(not timestamp.start() <= clock.start() < clock.end() <= timestamp.end()
           for clock in CLOCK_TIME.finditer(message)):
        return unknown
    sentence = next((part[0] for part in SENTENCE_TEXT.finditer(message)
                     if part.start() <= timestamp.start() < timestamp.end() <= part.end()), "")
    if not sentence or AMBIGUOUS_TIMING.search(sentence) or conflicting_eta_passage(sentence, port_name):
        return unknown
    suffix = message[timestamp.end():].lstrip()
    if suffix[:1] not in {"", ".", ";", "!", "?", ")", "]"}:
        return unknown
    try:
        parsed = _parse_time(timestamp, explicit=explicit, sent=sent, message=message,
                             port_name=port_name, port_timezone=port_timezone)
    except (ValueError, OverflowError, ZoneInfoNotFoundError):
        return unknown
    return (*parsed, "ai_quote") if parsed is not None else unknown
