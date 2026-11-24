# Farmland Gold Bus 1330 — scheduled tracker

## Deployed files
- `.github/workflows/gold-bus-monitor.yml` — weekday scheduled check (~5-minute minimum, GitHub Actions can be late).
- `family-wall/scripts/poll_gold_bus.py` — official MCPS iCal calendar parser and Google Drawing PNG position check.
- `family-wall/scripts/test_gold_bus.py` — offline calendar and image classification checks.
- `family-wall/gold-bus-status.json` — public status API for dashboard.
- `family-wall/school-calendar-status.json` — generated at first successful official calendar fetch.
- `family-wall/gold-bus.html` — dashboard, manual confirmations, browser notifications, trip-history median.

## Timing (America/New_York)
- Regular school day: 3:50 PM bell, watch begins 3:40 PM.
- Early release: 1:20 PM bell, watch begins 1:10 PM.
- Closed/weekends: no dismissal monitoring.
- Verified example: Wed, Nov 25, 2026 is **early release**, so start at 1:10 PM.

The cron runs at minutes 02, 07, 12, 17, etc., 16:00–23:59 UTC on weekdays, and the Python script gates attempts to the appropriate local-time interval.

## What is confirmed, what isn't
**Verified from published sources:** Gold = bus 1330 on the FES Google Drawing; MCPS school day / early release calendar; default dismissal 3:50 PM / 1:20 PM. Official MCPS calendar source:
https://ww2.montgomeryschoolsmd.org/calendar/download.aspx?file=MCPS_SchoolYearCalendar_Subscription

**Experimental:** PNG extraction from the Google Drawing (may require Google sign-in), visual recognition of a Gold-colored tile within a particular board column, and interpreting its placement. The script requires two consecutive matching scans and ignores initial static placement for stage-change push alerts. A column is *not* a bus departure or a child-boarding confirmation.

**Not yet connected:** Automatically parsing Gold Bus departure emails and sending an actual authenticated departure event to the dashboard. A school departure email must not be inferred from SVG/PNG updates.

**Not GPS:** A bus-stop arrival estimate is 10–15 minutes after an independently confirmed school departure. Parents can record the actual arrival time in their own browser to improve the local-only median after 3 complete trips. Don't publish a child's home address, bus stop, or precise route in this public repository.

## Android push (optional, requires setup)
This is **not enabled until the owner configures it**:
1. Install the ntfy Android app (https://ntfy.sh) and subscribe to a long, private, randomly generated topic name at least 24 characters long. Treat the topic as a password; never post it in issues or public files.
2. In GitHub repository settings, go to **Secrets and variables → Actions → New repository secret**.
3. Set name `GOLD_BUS_NTFY_TOPIC`, value = the same long topic string (topic characters: letters, numbers, hyphen, underscore).
4. Workflow sends pre-dismissal notices and *validated board transition* events to that topic. It does not yet send automatic departure or arrival alerts, because no source is connected for those events.
5. Confirm the repository allows GitHub Actions workflow scheduling and write access. The GitHub workflow may be delayed at busy times.
6. Check [Actions](https://github.com/Kaluzy/WebKaluzy/actions/workflows/gold-bus-monitor.yml) and `gold-bus-status.json` for evidence of a completed run.

Without this secret, the website can show live status from published JSON and notify only while the page is open; it cannot deliver reliable background push notifications.

## Next engineering task
Integrate ParentSquare/Gmail Gold Bus departure notifications with a private, authenticated source, and correlate timestamped board transitions with confirmed school departures. Once the feed is available, calculate ETAs automatically and emit arrival-window push alerts. Do not claim reliable real-time tracking until this path is validated on an actual school day.
