#!/usr/bin/env python3
"""Offline tests for Gold Bus tracker: no live school data required."""
import datetime as dt
from io import BytesIO
from pathlib import Path
from zoneinfo import ZoneInfo
from PIL import Image
import sys
sys.path.insert(0, str(Path(__file__).parent))
import poll_gold_bus as m

def run():
    ny = ZoneInfo("America/New_York")
    def at(day, hour=13):
        return dt.datetime.fromisoformat(day + f"T{hour:02d}:00:00").replace(tzinfo=ny)
    assert m.schedule_for(at("2026-11-25")) == ("early_release", "13:20")
    assert m.schedule_for(at("2026-11-26")) == ("closed", None)
    assert m.schedule_for(at("2026-12-23")) == ("early_release", "13:20")
    assert m.schedule_for(at("2026-12-28")) == ("closed", None)
    assert m.schedule_for(at("2026-11-30", 15)) == ("regular", "15:50")
    assert m.schedule_for(at("2026-11-25"), {"2026-11-25": {"category": "early_release"}}) == ("early_release", "13:20")
    # Synthetic board image to test that the Gold tile is in the expected column.
    im = Image.new("RGB", (1500, 1165), (205, 213, 225))
    for zone, x in [("last_call", 1120), ("buses_arrived", 650), ("staging", 200)]:
        pic = im.copy()
        for yy in range(460, 545):
            for xx in range(x, x + 180):
                pic.putpixel((xx, yy), (178, 150, 14))
        out = BytesIO(); pic.save(out, format="PNG")
        assert m.detect_gold_column(out.getvalue()) == zone, (zone, m.detect_gold_column(out.getvalue()))
    out = BytesIO(); im.save(out, format="PNG")
    assert m.detect_gold_column(out.getvalue()) is None
    print("Gold Bus schedule and image positioning: 9 checks passed")

if __name__ == "__main__":
    run()
