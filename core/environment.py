"""
Ambient environment context — local time, timezone, and approximate location.

Injected into the system prompt so the assistant answers time / date / weather /
location questions directly (using tools when live data is needed) instead of
asking the user where or when they are.

Location is derived from the public IP via ip-api.com, cached for a few hours.
Everything degrades gracefully: if the lookup fails we still supply local time.
"""

import time
import threading
from datetime import datetime

import requests
from core.logger import get_logger

log = get_logger("environment")

_LOCATION = None            # cached dict or None
_LOCATION_AT = 0.0
_LOCATION_TTL = 6 * 3600    # refresh at most every 6 hours
_LOCK = threading.Lock()


def _fetch_location():
    try:
        r = requests.get(
            "http://ip-api.com/json/"
            "?fields=status,city,regionName,country,lat,lon,timezone",
            timeout=5,
        )
        d = r.json()
        if d.get("status") == "success":
            return {
                "city":     d.get("city", ""),
                "region":   d.get("regionName", ""),
                "country":  d.get("country", ""),
                "lat":      d.get("lat"),
                "lon":      d.get("lon"),
                "timezone": d.get("timezone", ""),
            }
        log.warning(f"Location lookup non-success: {d.get('message', d)}")
    except Exception as e:
        log.warning(f"Location lookup failed: {e}")
    return None


def get_location(force: bool = False):
    global _LOCATION, _LOCATION_AT
    with _LOCK:
        now = time.time()
        if _LOCATION and not force and (now - _LOCATION_AT) < _LOCATION_TTL:
            return _LOCATION
    loc = _fetch_location()
    if loc:
        with _LOCK:
            _LOCATION = loc
            _LOCATION_AT = time.time()
    return _LOCATION


def prime_async():
    """Warm the location cache in the background so the first query has it."""
    threading.Thread(target=get_location, daemon=True).start()


def local_time_str() -> str:
    now = datetime.now().astimezone()
    tz = now.strftime("%Z") or time.tzname[0]
    off = now.strftime("%z")                       # e.g. +0530
    off_fmt = f"UTC{off[:3]}:{off[3:]}" if len(off) == 5 else "UTC"
    return now.strftime("%A, %B %d, %Y  %I:%M %p") + f" {tz} ({off_fmt})"


def city_str() -> str:
    loc = _LOCATION
    if not loc:
        return ""
    return ", ".join(p for p in (loc.get("city"), loc.get("region"),
                                 loc.get("country")) if p)


def get_environment_for_prompt() -> str:
    lines = [
        "LOCAL ENVIRONMENT (authoritative — use directly; never ask the user "
        "for the current time, date, or their location):",
        f"- Current local time: {local_time_str()}",
    ]
    loc = get_location()
    if loc:
        place = city_str()
        if place:
            lines.append(f"- Approximate location: {place}")
        if loc.get("timezone"):
            lines.append(f"- Timezone: {loc['timezone']}")
        if loc.get("lat") is not None and loc.get("lon") is not None:
            lines.append(f"- Coordinates: {loc['lat']}, {loc['lon']}")
    lines.append(
        "- For weather or 'what's it like outside' questions, use the location "
        "above and fetch live conditions with [SEARCH: weather in <city>]. "
        "For time/date questions, answer from the local time above immediately."
    )
    return "\n".join(lines)
