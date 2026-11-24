#!/usr/bin/env python3
"""Fail-closed monitor of Farmland's Google Drawing. Never infer bus departure from a static label."""
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from zoneinfo import ZoneInfo
import re
from io import BytesIO
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "gold-bus-status.json"
ID = "1rHhGYA0CAlhuiehJv55gSRYgtuLkDf8TAT2e2rHBbtc"
URL = f"https://docs.google.com/drawings/d/{ID}/export/png"
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
    text = raw.decode("utf-8-sig", errors="replace").replace("\r\n", "\n")
    if "BEGIN:VCALENDAR" not in text or "BEGIN:VEVENT" not in text:
        raise ValueError("Unexpected MCPS calendar format")
    unfolded = re.sub(r"\n[ \t]", "", text)
    events = {}
    for part in unfolded.split("BEGIN:VEVENT")[1:]:
        block = part.split("END:VEVENT", 1)[0]
        fields = dict((line.split(":", 1)[0].split(";", 1)[0], line.split(":", 1)[1])
                      for line in block.splitlines() if ":" in line)
        begin = fields.get("DTSTART", "")
        summary = fields.get("SUMMARY", "").replace("\\,", ",").strip()
        if not re.match(r"^\d{8}", begin):
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




def push_if_configured(title, message):
    """Optional Android push via a private ntfy topic stored in repository secrets."""
    topic = os.environ.get("GOLD_BUS_NTFY_TOPIC", "").strip()
    if not topic:
        return False
    # URL components are intentionally restricted; never include children's names/stop address.
    if not re.fullmatch(r"[A-Za-z0-9_-]{12,100}", topic):
        print("Invalid push topic configuration")
        return False
    req = Request("https://ntfy.sh/" + topic,
                  data=message.encode("utf-8"),
                  headers={"Title": title, "Priority": "high", "Tags": "school_bus"},
                  method="POST")
    try:
        with urlopen(req, timeout=12) as response:
            return response.status in (200, 201, 202, 204)
    except (HTTPError, URLError, OSError, TimeoutError) as exc:
        print("Push delivery unavailable:", type(exc).__name__, flush=True)
        return False

def detect_gold_column(raw):
    """Color/position observation from the current Gold 1330 school tile.
    Layout-specific, so never infer departure from this detector."""
    im = Image.open(BytesIO(raw)).convert("RGB")
    w, h = im.size
    if not (800 <= w <= 5000 and 500 <= h <= 5000):
        return None
    # Gold tile has a distinctive dark-gold fill (reference: RGB 178,150,14).
    # Ignore the large school bus photograph/header by starting below the header.
    counters = {"staging": 0, "buses_arrived": 0, "last_call": 0}
    for y in range(int(h * .2), int(h * .80), 3):
        for x in range(0, w, 3):
            red, green, blue = im.getpixel((x, y))
            if (140 <= red <= 205 and 115 <= green <= 180 and blue < 60
                and red > green * 1.04 and green > blue * 2.5):
                section = ("staging" if x < w * .37 else
                           "buses_arrived" if x < w * .62 else "last_call")
                counters[section] += 1
    best = max(counters, key=counters.get)
    # Require concentration in one region and enough pixels for a bus tile.
    if counters[best] < max(180, (w * h) // 12000):
        return None
    if counters[best] < sum(counters.values()) * .8:
        return None
    return best


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
        CALENDAR_DEST.write_text(json.dumps(calendar_payload, indent=2) + "\n", encoding="utf-8")
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
        print("Official calendar fetch unavailable:", type(exc).__name__, flush=True)
    category, bell = schedule_for(now, official_events)
    d = now.date().isoformat()
    prior = {}
    if DEST.exists():
        try:
            prior = json.loads(DEST.read_text(encoding="utf-8"))
            if prior.get("date") != d:
                prior = {}
        except (ValueError, OSError):
            prior = {}
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
    data["board_stage"] = "unverified"
    data["board_stage_at"] = None
    data["last_verified_board_stage"] = prior.get("last_verified_board_stage")
    data["board_candidate"] = prior.get("board_candidate")
    data["board_candidate_count"] = prior.get("board_candidate_count", 0)
    if category in ("regular", "early_release") and low <= now.time() <= high:
        try:
            req = Request(URL, headers={"User-Agent": "FarmlandGoldBusMonitor/1.0", "Accept": "image/svg+xml"})
            with urlopen(req, timeout=18) as response:
                raw = response.read(5_000_001)
                mime = response.headers.get("Content-Type", "").lower()
            if len(raw) > 5_000_000:
                data["source_health"] = "oversize"
            elif "image/png" in mime or raw[:8] == b"\x89PNG\r\n\x1a\n":
                data["source_health"] = "board_image_accessible"
                data["source_hash"] = hashlib.sha256(raw).hexdigest()
                candidate = detect_gold_column(raw)
                if candidate:
                    streak = prior.get("board_candidate_count", 0) + 1 if prior.get("board_candidate") == candidate else 1
                    data["board_candidate"] = candidate
                    data["board_candidate_count"] = streak
                    if streak >= 2:
                        data["board_stage"] = candidate
                        data["board_stage_at"] = (prior.get("board_stage_at") if prior.get("board_stage") == candidate
                                                   else now.isoformat(timespec="seconds"))
                        data["notice"] = "Gold tile visually observed in " + candidate.replace("_", " ") + " section on at least two checks; not proof of bus departure."
                    else:
                        data["notice"] = "Potential Gold tile location detected once; awaiting repeat confirmation."
                else:
                    data["notice"] = "Gold tile could not be located reliably. No status confirmed."
                    data["board_candidate"] = None
                    data["board_candidate_count"] = 0
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
    data["departure_confirmation_source"] = None
    data["stop_arrival_observed_at"] = None
    # The drawing is not a GPS feed. Publishing a changed SVG hash does not mean the Gold bus moved.
    # A board stage requires validated, position-aware detection of the actual Gold 1330 tile.
    # A departure requires an explicit school departure notice or other reliable source.
    # Send only meaningful transitions; poll frequency never equals alert frequency.
    if (data.get("board_stage") not in (None, "unverified")
        and prior.get("last_verified_board_stage")
        and data.get("board_stage") != prior.get("last_verified_board_stage")):
        label = {"buses_arrived": "waiting at school", "last_call": "in last call / boarding",
                 "staging": "in staging"}.get(data["board_stage"], "board updated")
        push_if_configured("Gold Bus 1330 — board update",
                           "Gold Bus tile appears " + label + ". Board observation only; departure not confirmed.")
    if data.get("board_stage") not in (None, "unverified"):
        data["last_verified_board_stage"] = data["board_stage"]
    # One pre-dismissal notice when polling within the 10-minute lead time.
    if category in ("regular", "early_release") and bell and prior.get("prebell_notified") != d:
        bell_minutes = (13 * 60 + 20) if category == "early_release" else (15 * 60 + 50)
        now_minutes = now.hour * 60 + now.minute
        if bell_minutes - 10 <= now_minutes < bell_minutes:
            if push_if_configured("Gold Bus 1330 — dismissal soon",
                                  "Farmland dismissal at " + ("1:20 PM (early release)" if category == "early_release" else "3:50 PM") +
                                  ". Gold Bus tracking window has begun."):
                data["prebell_notified"] = d
    if not data.get("prebell_notified"):
        data["prebell_notified"] = prior.get("prebell_notified")
    DEST.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"checked_at": data["checked_at"], "schedule": category, "source_health": data["source_health"]}))


if __name__ == "__main__":
    run()
