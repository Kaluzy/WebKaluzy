#!/usr/bin/env python3
"""Fail-closed monitor of Farmland's Google Drawing. Never infer bus departure from a static label."""
import datetime as dt
import hashlib
import json
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from zoneinfo import ZoneInfo
import re

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "gold-bus-status.json"
ID = "1rHhGYA0CAlhuiehJv55gSRYgtuLkDf8TAT2e2rHBbtc"
URL = f"https://docs.google.com/drawings/d/{ID}/export/svg"
NY = ZoneInfo("America/New_York")
CALENDAR_URL = "https://ww2.montgomeryschoolsmd.org/calendar/download.aspx?file=MCPS_SchoolYearCalendar_Subscription"
CALENDAR_DEST = ROOT / "school-calendar-status.json"

def read_official_calendar():
    """Download published MCPS iCalendar data, parse event days in America/New_York."""
    req = Request(CALENDAR_URL, headers={"User-Agent": "FamilyWallSchoolCalendar/1.0"})
    with urlopen(req, timeout=18) as response:
        raw = response.read(1_500_001)
    if len(raw) > 1_500_000:
        raise ValueError("Calendar larger than safe bound")
    text = raw.decode("utf-8-sig", errors="replace").replace("\\r\\n", "\\n")
    if "BEGIN:VCALENDAR" not in text or "BEGIN:VEVENT" not in text:
        raise ValueError("Unexpected MCPS calendar format")
    unfolded = re.sub(r"\\n[ \\t]", "", text)
    events = {}
    for part in unfolded.split("BEGIN:VEVENT")[1:]:
        block = part.split("END:VEVENT", 1)[0]
        fields = dict((line.split(":", 1)[0].split(";", 1)[0], line.split(":", 1)[1])
                      for line in block.splitlines() if ":" in line)
        begin = fields.get("DTSTART", "")
        summary = fields.get("SUMMARY", "").replace("\\\\,", ",").strip()
        if not re.match(r"^\\d{8}", begin):
            continue
        if len(begin) >= 16 and begin.endswith("Z"):
            date = (dt.datetime.strptime(begin[:15], "%Y%m%dT%H%M%S")
                    .replace(tzinfo=dt.timezone.utc).astimezone(NY).date().isoformat())
        else:
            date = dt.datetime.strptime(begin[:8], "%Y%m%d").date().isoformat()
        lower = summary.lower()
        category = None
        if "early release" in lower or "early dismissal" in lower:
            category = "early_release"
        elif ("no school" in lower or "non-instructional" in lower
              or "schools and offices closed" in lower
              or "winter break" in lower or "spring break" in lower
              or "systemwide closure" in lower):
            category = "closed"
        if category:
            events[date] = {"category": category, "event": summary}
    if not events:
        raise ValueError("MCPS calendar contained no classified school events")
    return events

EARLY = {
    "2026-11-23", "2026-11-24", "2026-11-25", "2026-12-23",
    "2027-02-26", "2027-06-11"
}
CLOSED = [
    ("2026-11-26", "2026-11-27", "Thanksgiving"),
    ("2026-12-24", "2027-01-01", "Winter break"),
    ("2027-01-18", "2027-01-18", "MLK Day"),
    ("2027-01-25", "2027-01-25", "Grading day"),
    ("2027-02-15", "2027-02-15", "Presidents Day"),
    ("2027-03-09", "2027-03-09", "Staff development"),
    ("2027-03-26", "2027-04-02", "Spring break"),
    ("2027-04-12", "2027-04-12", "Grading day"),
    ("2027-05-31", "2027-05-31", "Memorial Day"),
]
POSSIBLE_MAKEUP = {"2027-04-22", "2027-05-17"}


def schedule_for(now, live_events=None):
    d = now.date().isoformat()
    if live_events and d in live_events:
        category = live_events[d]["category"]
        return (category, "13:20" if category == "early_release" else None)
    if now.weekday() >= 5:
        return ("weekend", None)
    for a, b, label in CLOSED:
        if a <= d <= b:
            return ("closed", None)
    if d in POSSIBLE_MAKEUP:
        return ("verify_makeup", None)
    if d in EARLY:
        return ("early_release", "13:20")
    return ("regular", "15:50")


def run():
    now = dt.datetime.now(NY)
    official_events = None
    calendar_health = "official_calendar_unavailable"
    try:
        official_events = read_official_calendar()
        calendar_health = "official_calendar_verified"
        upcoming = {key: value for key, value in sorted(official_events.items())
                    if now.date().isoformat() <= key <= (now.date()+dt.timedelta(days=60)).isoformat()}
        calendar_payload = {
            "source": CALENDAR_URL, "fetched_at": now.isoformat(timespec="seconds"),
            "calendar_health": calendar_health,
            "days": upcoming
        }
        CALENDAR_DEST.write_text(json.dumps(calendar_payload, indent=2) + "\\n", encoding="utf-8")
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
        print("Official calendar fetch unavailable:", type(exc).__name__, flush=True)
    category, bell = schedule_for(now, official_events)
    d = now.date().isoformat()
    data = {
        "school": "Farmland Elementary",
        "bus": "Gold 1330",
        "date": d,
        "checked_at": now.isoformat(timespec="seconds"),
        "schedule": category,
        "calendar_health": calendar_health,
        "dismissal_time": bell,
        "status": "not_confirmed",
        "departure_at": None,
        "estimated_stop_window": None,
        "source": "FES Bus Dismissal Google Drawing",
        "source_url": f"https://docs.google.com/drawings/d/{ID}/edit",
        "source_health": "not_checked",
        "source_hash": None,
        "notice": "No verified Gold Bus departure. Board labels alone do not establish departure or child boarding.",
    }
    # Start exactly ten minutes before the official dismissal bell.
    low, high = (dt.time(13, 10), dt.time(15, 0)) if category == "early_release" else (dt.time(15, 40), dt.time(17, 30))
    if category in ("regular", "early_release") and low <= now.time() <= high:
        try:
            req = Request(URL, headers={"User-Agent": "FarmlandGoldBusMonitor/1.0", "Accept": "image/svg+xml"})
            with urlopen(req, timeout=18) as response:
                raw = response.read(5_000_001)
                mime = response.headers.get("Content-Type", "").lower()
            if len(raw) > 5_000_000:
                data["source_health"] = "oversize"
            elif b"<svg" in raw[:2000] and ("svg" in mime or raw.lstrip().startswith(b"<?xml")):
                data["source_health"] = "drawing_export_accessible"
                data["source_hash"] = hashlib.sha256(raw).hexdigest()
                data["notice"] = "Drawing export accessible. No validated machine-readable departure signal; status remains unconfirmed."
            else:
                data["source_health"] = "not_machine_readable"
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            data["source_health"] = "source_unavailable"
            data["notice"] = "Automatic export unavailable. Check the school's drawing and ParentSquare. No bus movement inferred."
            print("Source unavailable:", type(exc).__name__, flush=True)
    elif category in ("closed", "weekend"):
        data["source_health"] = "skipped_school_closed"
        data["notice"] = "No normal school bus service scheduled; check MCPS for emergency changes."
    elif category == "verify_makeup":
        data["source_health"] = "calendar_verification_required"
        data["notice"] = "Possible make-up day. Confirm actual school calendar before relying on dismissal schedule."
    else:
        data["source_health"] = "outside_monitor_window"
    data["monitor_start"] = "13:10" if category == "early_release" else ("15:40" if category == "regular" else None)
    data["monitoring_phase"] = ("monitoring" if category in ("early_release", "regular") and low <= now.time() <= high
                                else "closed" if category in ("closed", "weekend")
                                else "outside_window")
    data["board_stage"] = "unverified"
    data["board_stage_at"] = None
    data["departure_confirmation_source"] = None
    data["stop_arrival_observed_at"] = None
    # The drawing is not a GPS feed. Publishing a changed SVG hash does not mean the Gold bus moved.
    # A board stage requires validated, position-aware detection of the actual Gold 1330 tile.
    # A departure requires an explicit school departure notice or other reliable source.
    DEST.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"checked_at": data["checked_at"], "schedule": category, "source_health": data["source_health"]}))


if __name__ == "__main__":
    run()
