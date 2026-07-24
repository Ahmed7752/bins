"""Check the council site against the stored cycle rule.

The rule in data/schedule.json is deliberately stable. This script does not
rebase it -- it only confirms it, or records a one-off override when the
council has moved a single collection (bank holidays, severe weather).

A genuine permanent change to the rounds shows up as the same disagreement
week after week, which the workflow escalates as an issue rather than
silently rotating the whole calendar.
"""

import json
import pathlib
import re
import sys
from datetime import date, datetime, timedelta

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCHEDULE = ROOT / "data" / "schedule.json"

PROPERTY_URL = (
    "https://wasteservices.sheffield.gov.uk"
    "/recycling-rubbish/property-search/{point_id}/your-collection-days"
)

# The property page renders three cards, one per bin. Each ends with
# "Next collection" followed by a dd/mm/yyyy date.
CARD_RE = re.compile(r"Next collection(\d{2}/\d{2}/\d{4})")


def on_cycle(anchor: date, interval: int, day: date) -> bool:
    """Does `day` fall on the rule's repeating lattice?

    This is the real invariant to test, rather than 'is it the next date I
    expect'. On a collection morning the council has already advanced its
    'next collection' to the following cycle, and a bin whose turn is today
    would otherwise look rescheduled every fortnight.
    """
    return (day - anchor).days % interval == 0


def nearest_on_cycle(anchor: date, interval: int, day: date) -> date:
    """The lattice date closest to `day` -- i.e. the slot it moved out of."""
    steps = round((day - anchor).days / interval)
    return anchor + timedelta(days=steps * interval)


def scrape(point_id: str, timeout_ms: int = 60000) -> dict:
    from playwright.sync_api import sync_playwright

    url = PROPERTY_URL.format(point_id=point_id)
    observed = {}

    with sync_playwright() as p:
        browser = p.chromium.launch()
        # The council site formats its dates client-side, so the browser's
        # timezone decides what they say. Under UTC, a midnight-BST date
        # renders as 23:00 the previous day and every collection reads a day
        # early. Pin to UK time -- CI runners are UTC.
        context = browser.new_context(
            timezone_id="Europe/London",
            locale="en-GB",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            ),
        )
        page = context.new_page()
        page.goto(url, wait_until="networkidle", timeout=timeout_ms)
        # The bin cards are client-rendered; wait for one to appear.
        page.wait_for_selector("h2:text-is('Black Bin')", timeout=timeout_ms)

        for heading in page.query_selector_all("h2"):
            name = (heading.inner_text() or "").strip()
            if not re.fullmatch(r"(Black|Blue|Brown) Bin", name):
                continue
            # Walk up until we find the card that carries "Next collection".
            node = heading
            text = ""
            for _ in range(6):
                node = node.evaluate_handle("e => e.parentElement").as_element()
                if node is None:
                    break
                text = node.inner_text() or ""
                if "Next collection" in text:
                    break
            match = CARD_RE.search(text.replace("\n", ""))
            if match:
                d, m, y = match.group(1).split("/")
                observed[name.split()[0].lower()] = f"{y}-{m}-{d}"

        context.close()
        browser.close()

    if len(observed) < 3:
        raise SystemExit(
            f"Only found {len(observed)} of 3 bins ({sorted(observed)}). "
            "The council site markup has probably changed -- check scrape.py."
        )
    return observed


def main() -> int:
    cfg = json.loads(SCHEDULE.read_text(encoding="utf-8"))
    today = date.today()

    observed = scrape(cfg["propertyId"])
    print(f"Scraped next collections: {observed}")

    disagreements = {}
    for bin_key, spec in cfg["rule"].items():
        anchor = date.fromisoformat(spec["anchor"])
        interval = spec["intervalDays"]
        actual = date.fromisoformat(observed[bin_key])

        if on_cycle(anchor, interval, actual):
            print(f"  OK       {bin_key:6s} next={actual} (on cycle)")
        else:
            slot = nearest_on_cycle(anchor, interval, actual)
            print(f"  DEVIATES {bin_key:6s} slot={slot} site={actual}")
            disagreements[bin_key] = {
                "expected": slot.isoformat(),
                "actual": actual.isoformat(),
                "shiftDays": (actual - slot).days,
            }

    # The council reschedules individual collections, not the whole round at
    # once. Every bin shifting by the same amount is a bug on our side -- a
    # timezone or parsing fault -- so refuse to write it into the calendar.
    shifts = {d["shiftDays"] for d in disagreements.values()}
    systematic = len(disagreements) == len(cfg["rule"]) and len(shifts) == 1

    if systematic:
        shift = shifts.pop()
        print(
            f"::error title=Suspect scrape::All {len(disagreements)} bins shifted by "
            f"{shift:+d} day(s). Treating as a scraper fault, not a reschedule. "
            "No overrides written."
        )
    else:
        for bin_key, d in disagreements.items():
            # Record as a one-off move, leaving the underlying cycle intact.
            cfg["overrides"][d["expected"]] = {
                "bin": bin_key,
                "movedTo": d["actual"],
                "noticedAt": today.isoformat(),
            }

    cfg["lastScrape"] = {
        "checkedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "agrees": not disagreements,
        "observed": observed,
    }
    SCHEDULE.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")

    if systematic:
        return 1

    if disagreements:
        # Surface it to the workflow without failing the build -- the
        # calendar still regenerates, now including the override.
        summary = "; ".join(
            f"{k}: rule said {v['expected']}, site says {v['actual']}"
            for k, v in disagreements.items()
        )
        print(f"::warning title=Collection rescheduled::{summary}")
        pathlib.Path("deviation.txt").write_text(summary, encoding="utf-8")

    return 0


if __name__ == "__main__":
    sys.exit(main())
