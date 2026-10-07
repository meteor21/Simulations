from __future__ import annotations
import hashlib
import json
import re
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

UTC = timezone.utc

def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")

def dt(value: str | date | datetime, *, end_of_day: bool = True) -> datetime:
    """Date-only availability is conservatively interpreted as end of that UTC day."""
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, date) or (isinstance(value, str) and len(value) == 10):
        result = datetime.fromisoformat(str(value)[:10]).replace(tzinfo=UTC)
        if end_of_day:
            result += timedelta(hours=23, minutes=59, seconds=59)
    elif isinstance(value, str):
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise TypeError(f"Expected ISO date/datetime, received {type(value).__name__}")
    if result.tzinfo is None:
        raise ValueError("Datetime strings must include a timezone; date-only strings are UTC.")
    return result.astimezone(UTC)

def iso(value) -> str:
    return dt(value).isoformat(timespec="seconds")

def dumps(value) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)

def digest(value) -> str:
    text = value if isinstance(value, str) else dumps(value)
    return hashlib.sha256(text.encode()).hexdigest()

def normal(text: str) -> str:
    return re.sub(r"\W+", " ", text.casefold(), flags=re.UNICODE).strip()

def host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().removeprefix("www.")

def canonical_url(url: str) -> str:
    p = urlsplit(url)
    if p.scheme not in ("https", "http") or not p.hostname or p.username or p.password:
        raise ValueError("Only public HTTP(S) article URLs without credentials are accepted.")
    query = [(k,v) for k,v in parse_qsl(p.query, keep_blank_values=True)
             if not k.lower().startswith("utm_") and k.lower() not in {"fbclid","gclid"}]
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path or "/", urlencode(query), ""))

def allowed_host(url: str, allowed: list[str] | tuple[str, ...]) -> bool:
    h = host(url)
    return any(h == d or h.endswith("." + d) for d in allowed)

def months(start: str, end: str):
    """Adjacent closed datetime windows; boundary duplication is removed by URL/version IDs."""
    a, stop = dt(start, end_of_day=False), dt(end)
    if a >= stop:
        raise ValueError("start must precede end")
    while a < stop:
        b = datetime(a.year + (a.month == 12), a.month % 12 + 1, 1, tzinfo=UTC)
        b = min(b, stop)
        yield a.isoformat(timespec="seconds"), b.isoformat(timespec="seconds")
        a = b

def finite_number(value, low=None, high=None) -> float:
    import math
    x = float(value)
    if not math.isfinite(x) or (low is not None and x < low) or (high is not None and x > high):
        raise ValueError(f"Invalid numeric value {value!r}; expected [{low}, {high}]")
    return x
