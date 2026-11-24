#!/usr/bin/env python3
"""Fail-closed monitor of Farmland's Google Drawing. Never infer bus departure from a static label."""
import datetime as dt
import hashlib
import json
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "gold-bus-status.json"
ID = "1rHhGYA0CAlhuiehJv55gSRYgtuLkDf8TAT2e2rHBbtc"
URL = f"https://docs.google.com/drawings/d/{ID}/export/svg"
NY = ZoneInfo("America/New_York")
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


def schedule_for(now):
    d = now.date().isoformat()
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
    category, bell = schedule_for(now)
    d = now.date().isoformat()
    data = {
        "school": "Farmland Elementary",
        "bus": "Gold 1330",
        "date": d,
        "checked_at": now.isoformat(timespec="seconds"),
        "schedule": category,
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
    DEST.write_text(json.dumps(data, indent=2) + "\\n", encoding="utf-8")
    print(json.dumps({"checked_at": data["checked_at"], "schedule": category, "source_health": data["source_health"]}))


if __name__ == "__main__":
    run()
