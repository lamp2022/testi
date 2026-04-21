#!/usr/bin/env python3
"""
Surftown Booking Monitor
Scrapes https://booking.surftown.de/en/LessonPackage

Schedule:
  - Every hour 08:00-21:00 (daytime hourly scan)
  - 30 minutes before each class found (pre-class alert)

Data logged to surf_bookings.csv with columns:
  timestamp, check_type, lesson_date, lesson_time, category,
  break_type, spots_free, spots_total, instructor, duration_min,
  price, status, raw_title

Usage:
  python surf_monitor.py            # run scheduler (Ctrl+C to stop)
  python surf_monitor.py --once     # single scrape, print + append CSV
  python surf_monitor.py --debug    # single scrape, save HTML for inspection
"""

import argparse
import asyncio
import csv
import json
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.date import DateTrigger
except ImportError:
    print("Missing dependency: pip install apscheduler")
    sys.exit(1)

try:
    from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
except ImportError:
    print("Missing dependency: pip install playwright && playwright install chromium")
    sys.exit(1)

# ── Configuration ─────────────────────────────────────────────────────────────

URL = "https://booking.surftown.de/en/LessonPackage"
TZ = ZoneInfo("Europe/Berlin")
CSV_PATH = Path("surf_bookings.csv")
DEBUG_DIR = Path("debug_html")
DAYTIME_START_H = 8   # 08:00
DAYTIME_END_H = 21    # 21:00 (last check at 20:00)

CATEGORIES = ["progressive", "intermediate", "advanced", "expert"]
BREAK_KEYWORDS = {
    "left": ["left"],
    "right": ["right"],
    "frame": ["frame"],
    "point": ["point break", "pointbreak", "point"],
}

CSV_FIELDS = [
    "timestamp",
    "check_type",
    "lesson_date",
    "lesson_time",
    "category",
    "break_type",
    "spots_free",
    "spots_total",
    "spots_pct_free",
    "instructor",
    "duration_min",
    "price",
    "status",
    "raw_title",
]

# ── Helpers ───────────────────────────────────────────────────────────────────

def notify(title: str, message: str) -> None:
    print(f"\n{'='*60}\n[ALERT] {title}\n        {message}\n{'='*60}")
    try:
        if sys.platform == "darwin":
            os.system(
                f'osascript -e \'display notification "{message}" with title "{title}"\''
            )
        elif sys.platform.startswith("linux"):
            os.system(f'notify-send -u normal "{title}" "{message}"')
    except Exception:
        pass


def classify_category(text: str) -> str:
    t = text.lower()
    # Check longest match first to avoid "progressive" matching in "advanced progressive"
    for cat in ["expert", "advanced", "intermediate", "progressive"]:
        if cat in t:
            return cat
    return "unknown"


def classify_break(text: str) -> str:
    t = text.lower()
    for label, keywords in BREAK_KEYWORDS.items():
        for kw in keywords:
            if kw in t:
                return label
    return "unknown"


def parse_spots(text: str) -> tuple[int | None, int | None]:
    """Return (free, total) from strings like '3/8', '3 of 8', '5 spots left'."""
    # e.g. "3 / 8"
    m = re.search(r"(\d+)\s*/\s*(\d+)", text)
    if m:
        return int(m.group(1)), int(m.group(2))
    # e.g. "3 of 8"
    m = re.search(r"(\d+)\s+of\s+(\d+)", text, re.IGNORECASE)
    if m:
        return int(m.group(1)), int(m.group(2))
    # e.g. "5 spots left"
    m = re.search(r"(\d+)\s+spots?\s+(?:left|free|available|remaining)", text, re.IGNORECASE)
    if m:
        return int(m.group(1)), None
    # e.g. "available: 5"
    m = re.search(r"available[:\s]+(\d+)", text, re.IGNORECASE)
    if m:
        return int(m.group(1)), None
    return None, None


def extract_date(text: str) -> str:
    # DD.MM.YYYY or DD/MM/YYYY
    m = re.search(r"(\d{1,2})[./](\d{1,2})[./](\d{4})", text)
    if m:
        return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    # YYYY-MM-DD
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", text)
    if m:
        return m.group(0)
    return ""


def extract_time(text: str) -> str:
    m = re.search(r"\b(\d{1,2}):(\d{2})\b", text)
    if m:
        return f"{int(m.group(1)):02d}:{m.group(2)}"
    return ""


def pct_free(free, total) -> str:
    try:
        return f"{int(free)/int(total)*100:.0f}%"
    except (TypeError, ZeroDivisionError, ValueError):
        return ""


# ── Scraper ───────────────────────────────────────────────────────────────────

async def scrape(check_type: str = "hourly", debug: bool = False) -> list[dict]:
    now = datetime.now(TZ)
    ts = now.isoformat(timespec="seconds")
    print(f"[{now.strftime('%Y-%m-%d %H:%M')}] Scraping ({check_type}) …")

    # Find installed Chromium — Playwright version pinning sometimes mismatches
    _chromium_candidates = [
        "/opt/pw-browsers/chromium-1194/chrome-linux/chrome",
        "/opt/pw-browsers/chromium-1208/chrome-linux/chrome",
    ]
    _exe = next((c for c in _chromium_candidates if Path(c).exists()), None)

    results = []
    async with async_playwright() as p:
        launch_kwargs: dict = {"headless": True}
        if _exe:
            launch_kwargs["executable_path"] = _exe
        browser = await p.chromium.launch(**launch_kwargs)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="en-US",
            timezone_id="Europe/Berlin",
            viewport={"width": 1280, "height": 900},
            ignore_https_errors=True,
        )
        page = await context.new_page()

        try:
            await page.goto(URL, wait_until="networkidle", timeout=40000)
            # Extra wait for any lazy-loaded JS content
            await page.wait_for_timeout(3000)

            html = await page.content()

            if debug:
                DEBUG_DIR.mkdir(exist_ok=True)
                out = DEBUG_DIR / f"debug_{now.strftime('%Y%m%d_%H%M%S')}.html"
                out.write_text(html, encoding="utf-8")
                print(f"  HTML saved → {out}")

            results = await _parse_page(page, html, check_type, ts)

        except PlaywrightTimeout:
            print("  [WARN] Page timed out.")
        except Exception as exc:
            print(f"  [ERROR] {exc}")
        finally:
            await browser.close()

    return results


async def _parse_page(page, html: str, check_type: str, ts: str) -> list[dict]:
    """Try multiple extraction strategies in order of preference."""

    # 1. JSON-LD / embedded script data
    rows = _try_json_script(html, check_type, ts)
    if rows:
        print(f"  Strategy: JSON script data → {len(rows)} rows")
        return rows

    # 2. DOM card selectors
    card_selectors = [
        ".lesson-card", ".package-card", ".booking-item", ".course-item",
        ".surf-lesson", "[data-lesson]", "[data-package]", "[data-course]",
        ".availability-item", ".slot-item", ".event-item",
        ".fc-event",           # FullCalendar
        ".item",               # generic
    ]
    for sel in card_selectors:
        cards = await page.query_selector_all(sel)
        if cards:
            print(f"  Strategy: DOM selector '{sel}' → {len(cards)} cards")
            rows = await _cards_to_rows(cards, check_type, ts)
            if rows:
                return rows

    # 3. Table rows
    tables = await page.query_selector_all("table")
    if tables:
        rows_all = []
        for table in tables:
            trows = await table.query_selector_all("tr")
            rows_all.extend(await _cards_to_rows(trows, check_type, ts))
        if rows_all:
            print(f"  Strategy: table rows → {len(rows_all)} rows")
            return rows_all

    # 4. Text fallback — scan visible text for lines containing a time
    print("  Strategy: text fallback")
    body = await page.inner_text("body")
    return _text_fallback(body, check_type, ts)


def _try_json_script(html: str, check_type: str, ts: str) -> list[dict]:
    """Look for JSON embedded in <script> tags (Next.js __NEXT_DATA__, etc.)."""
    patterns = [
        r'<script[^>]+type="application/json"[^>]*>(.*?)</script>',
        r'window\.__(?:INITIAL|NEXT|APP)_(?:STATE|DATA)__\s*=\s*({.*?});',
        r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>',
    ]
    for pat in patterns:
        for m in re.finditer(pat, html, re.DOTALL):
            try:
                data = json.loads(m.group(1))
                rows = _flatten_json(data, check_type, ts)
                if rows:
                    return rows
            except (json.JSONDecodeError, KeyError):
                continue
    return []


def _flatten_json(obj, check_type: str, ts: str, depth: int = 0) -> list[dict]:
    """Recursively search a JSON object for lesson-like records."""
    if depth > 8:
        return []
    rows = []
    if isinstance(obj, list):
        for item in obj:
            rows.extend(_flatten_json(item, check_type, ts, depth + 1))
    elif isinstance(obj, dict):
        text = json.dumps(obj)
        # If this dict looks like a lesson record, try to build a row
        if any(k in obj for k in ["date", "time", "startTime", "start_time", "spots", "availability"]):
            row = _dict_to_row(obj, check_type, ts)
            if row:
                rows.append(row)
        else:
            for v in obj.values():
                rows.extend(_flatten_json(v, check_type, ts, depth + 1))
    return rows


def _dict_to_row(d: dict, check_type: str, ts: str) -> dict | None:
    text = json.dumps(d)
    date_val = (
        d.get("date") or d.get("lessonDate") or d.get("lesson_date") or
        d.get("startDate") or d.get("start_date") or ""
    )
    time_val = (
        d.get("time") or d.get("startTime") or d.get("start_time") or
        d.get("lessonTime") or ""
    )
    # Normalize ISO datetime
    if "T" in str(date_val):
        try:
            dt = datetime.fromisoformat(str(date_val).replace("Z", "+00:00"))
            date_val = dt.strftime("%Y-%m-%d")
            if not time_val:
                time_val = dt.strftime("%H:%M")
        except ValueError:
            pass

    spots_free = d.get("spotsAvailable") or d.get("spots_available") or d.get("availableSpots") or d.get("spots") or ""
    spots_total = d.get("spotsTotal") or d.get("spots_total") or d.get("totalSpots") or d.get("capacity") or ""

    if not spots_free:
        free, total = parse_spots(text)
        spots_free = free if free is not None else ""
        spots_total = total if total is not None else ""

    category_raw = str(d.get("category") or d.get("type") or d.get("level") or d.get("name") or d.get("title") or text)
    break_raw = str(d.get("breakType") or d.get("break_type") or d.get("break") or d.get("location") or text)

    return {
        "timestamp": ts,
        "check_type": check_type,
        "lesson_date": str(date_val)[:10] if date_val else extract_date(text),
        "lesson_time": str(time_val)[:5] if time_val else extract_time(text),
        "category": classify_category(category_raw),
        "break_type": classify_break(break_raw),
        "spots_free": spots_free,
        "spots_total": spots_total,
        "spots_pct_free": pct_free(spots_free, spots_total),
        "instructor": d.get("instructor") or d.get("guide") or "",
        "duration_min": d.get("duration") or d.get("durationMinutes") or "",
        "price": d.get("price") or d.get("amount") or "",
        "status": d.get("status") or d.get("bookingStatus") or "",
        "raw_title": category_raw[:200],
    }


async def _cards_to_rows(cards, check_type: str, ts: str) -> list[dict]:
    rows = []
    for card in cards:
        text = (await card.inner_text()).strip()
        if not text or len(text) < 4:
            continue

        # Try data attributes first
        for attr in ["data-lesson", "data-package", "data-course", "data-json"]:
            raw = await card.get_attribute(attr) or ""
            if raw:
                try:
                    d = json.loads(raw)
                    row = _dict_to_row(d, check_type, ts)
                    if row:
                        rows.append(row)
                        break
                except json.JSONDecodeError:
                    pass
        else:
            # Fall back to text parsing
            free, total = parse_spots(text)
            rows.append({
                "timestamp": ts,
                "check_type": check_type,
                "lesson_date": extract_date(text),
                "lesson_time": extract_time(text),
                "category": classify_category(text),
                "break_type": classify_break(text),
                "spots_free": free if free is not None else "",
                "spots_total": total if total is not None else "",
                "spots_pct_free": pct_free(free, total),
                "instructor": "",
                "duration_min": "",
                "price": "",
                "status": "full" if free == 0 else ("available" if free else ""),
                "raw_title": text[:200],
            })
    return rows


def _text_fallback(body: str, check_type: str, ts: str) -> list[dict]:
    rows = []
    for line in body.splitlines():
        line = line.strip()
        if not line or not re.search(r"\d{1,2}:\d{2}", line):
            continue
        free, total = parse_spots(line)
        rows.append({
            "timestamp": ts,
            "check_type": check_type,
            "lesson_date": extract_date(line),
            "lesson_time": extract_time(line),
            "category": classify_category(line),
            "break_type": classify_break(line),
            "spots_free": free if free is not None else "",
            "spots_total": total if total is not None else "",
            "spots_pct_free": pct_free(free, total),
            "instructor": "",
            "duration_min": "",
            "price": "",
            "status": "",
            "raw_title": line[:200],
        })
    return rows


# ── CSV ───────────────────────────────────────────────────────────────────────

def append_csv(rows: list[dict]) -> None:
    is_new = not CSV_PATH.exists()
    with CSV_PATH.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        if is_new:
            w.writeheader()
        w.writerows(rows)
    print(f"  Saved {len(rows)} rows → {CSV_PATH}")


# ── Summary printer ───────────────────────────────────────────────────────────

def print_summary(rows: list[dict]) -> None:
    if not rows:
        print("  No lesson data extracted.")
        return
    # Group by break_type then category for readability
    from itertools import groupby
    sorted_rows = sorted(
        rows,
        key=lambda r: (r.get("break_type", ""), r.get("category", ""), r.get("lesson_time", ""))
    )
    print(f"\n  {'Date':<11} {'Time':<6} {'Category':<14} {'Break':<7} {'Free/Total':<11} {'%Free':<6} Status")
    print("  " + "─" * 65)
    for r in sorted_rows:
        free = r.get("spots_free", "?")
        total = r.get("spots_total", "?")
        print(
            f"  {r.get('lesson_date','?'):<11}"
            f" {r.get('lesson_time','?'):<6}"
            f" {r.get('category','?'):<14}"
            f" {r.get('break_type','?'):<7}"
            f" {str(free)+'/'+str(total):<11}"
            f" {r.get('spots_pct_free',''):<6}"
            f" {r.get('status','')}"
        )
    print()


# ── Scheduler callbacks ───────────────────────────────────────────────────────

async def hourly_job(scheduler: AsyncIOScheduler) -> None:
    now = datetime.now(TZ)
    if not (DAYTIME_START_H <= now.hour < DAYTIME_END_H):
        return  # outside window, scheduler already restricts but guard anyway
    rows = await scrape(check_type="hourly")
    if rows:
        append_csv(rows)
        print_summary(rows)
        _schedule_pre_class_alerts(scheduler, rows)


def _schedule_pre_class_alerts(scheduler: AsyncIOScheduler, rows: list[dict]) -> None:
    now = datetime.now(TZ)
    scheduled = 0
    seen = set()

    for r in rows:
        date_s = r.get("lesson_date", "")
        time_s = r.get("lesson_time", "")
        if not date_s or not time_s:
            continue
        try:
            lesson_dt = datetime.strptime(f"{date_s} {time_s}", "%Y-%m-%d %H:%M").replace(tzinfo=TZ)
        except ValueError:
            continue

        alert_dt = lesson_dt - timedelta(minutes=30)
        if alert_dt <= now:
            continue

        key = f"pre_{lesson_dt.strftime('%Y%m%d_%H%M')}_{r.get('category')}_{r.get('break_type')}"
        if key in seen or scheduler.get_job(key):
            continue
        seen.add(key)

        scheduler.add_job(
            pre_class_job,
            trigger=DateTrigger(run_date=alert_dt, timezone=TZ),
            id=key,
            kwargs={"lesson_info": r},
            misfire_grace_time=300,
            replace_existing=True,
        )
        scheduled += 1

    if scheduled:
        print(f"  Scheduled {scheduled} pre-class check(s).")


async def pre_class_job(lesson_info: dict) -> None:
    rows = await scrape(check_type="pre_class_30min")
    if not rows:
        return
    append_csv(rows)

    target_time = lesson_info.get("lesson_time", "")
    target_cat = lesson_info.get("category", "")
    target_break = lesson_info.get("break_type", "")

    for r in rows:
        if r.get("lesson_time") == target_time and r.get("category") == target_cat:
            free = r.get("spots_free", "?")
            total = r.get("spots_total", "?")
            status = r.get("status", "")
            notify(
                f"Surf class in 30 min — {target_cat.title()} ({target_break})",
                f"{free}/{total} spots free at {target_time}  {status}",
            )
            break
    else:
        notify(
            f"Surf class in 30 min — {target_cat.title()} ({target_break})",
            f"Could not find availability for {target_time}",
        )


# ── Entry point ───────────────────────────────────────────────────────────────

async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Monitor surf lesson availability at Surftown Booking",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--once", action="store_true", help="Single scrape then exit")
    parser.add_argument("--debug", action="store_true", help="Save debug HTML and run once")
    args = parser.parse_args()

    if args.once or args.debug:
        rows = await scrape(check_type="manual", debug=args.debug)
        if rows:
            append_csv(rows)
            print_summary(rows)
        else:
            print(
                "\nNo data extracted. Run with --debug to save the HTML and inspect it.\n"
                "You may need to adapt the selectors in _parse_page() to match the site's DOM.\n"
                f"Debug HTML saved in: {DEBUG_DIR.resolve()}"
            )
        return

    scheduler = AsyncIOScheduler(timezone=TZ)

    # Hourly on the hour, 08:00–20:00 inclusive
    scheduler.add_job(
        hourly_job,
        trigger=CronTrigger(
            hour=f"{DAYTIME_START_H}-{DAYTIME_END_H - 1}",
            minute=0,
            timezone=TZ,
        ),
        id="hourly",
        kwargs={"scheduler": scheduler},
        misfire_grace_time=600,
    )

    scheduler.start()
    print(
        f"\nSurf Monitor running — {URL}\n"
        f"Hourly checks: {DAYTIME_START_H:02d}:00 – {DAYTIME_END_H - 1:02d}:00 ({TZ})\n"
        f"CSV output:    {CSV_PATH.resolve()}\n"
        "Press Ctrl+C to stop.\n"
    )

    # Run immediately on start so you don't wait an hour
    await hourly_job(scheduler)

    try:
        while True:
            await asyncio.sleep(30)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
        print("\nMonitor stopped.")


if __name__ == "__main__":
    asyncio.run(main())
