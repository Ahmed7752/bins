# bins

Bin collection reminders, as a calendar feed and a one-glance web page.
No app, no App Store, no server at home.

Collections are on **Friday**, on a fixed four-week cycle:

| Week | Bin | Goes in |
|------|-----|---------|
| 1 | 🔵 Blue | Paper and card |
| 2 | ⚫ Black | Non-recyclable waste |
| 3 | 🟤 Brown | Glass bottles, jars, tins, cans, foil, plastic and cartons |
| 4 | ⚫ Black | Non-recyclable waste |

Black is every second Friday; blue and brown alternate on the Fridays between.
Bins go out before **07:00**, so the reminders fire at **18:00 the evening before**.

## What gets published

GitHub Actions builds `site/` and deploys it to Pages:

- **`bins.ics`** — the calendar feed. Three years of collections, each with two
  alarms (6pm the night before, 6am on the day as a backup).
- **`index.html`** — the "next bin" page. Add it to your iPhone home screen and
  it behaves like an app.

## Subscribing

**iPhone** — Settings → Calendar → Accounts → Add Account → Other →
**Add Subscribed Calendar**, and paste the `bins.ics` URL.

> Make sure **Remove Alarms** is **off**. Leave it on and iOS strips the
> notifications, giving you a silent calendar entry and no reminder.

**Echo** — subscribe a Google Calendar to the same URL (Other calendars → From
URL), link that Google account in the Alexa app, then add a Routine for 6pm
Thursday that reads out tomorrow's events.

## How it stays right

`data/schedule.json` holds the cycle as a **stable rule** — three anchor dates
and their intervals. It was verified against the council's published 12-month
calendar: every one of the 26 collections in the second half matched the rule
exactly, and the council states the same cadence in words on the property page.

`scripts/scrape.py` runs twice a week and compares the council's *next
collection* dates against that rule. It deliberately **does not** rebase the
rule when they disagree, because a one-off bank-holiday shift must never
permanently rotate the whole cycle. Instead it records an override for that
single date and opens an issue.

If the same disagreement shows up week after week, the rounds have genuinely
changed and the anchors in `data/schedule.json` need updating by hand.

Because the feed is enumerated three years ahead, it keeps working even if the
scraper breaks or the scheduled workflow stops running.

## Running it locally

```bash
pip install -r requirements.txt
python -m playwright install chromium

python scripts/scrape.py     # check the council site (optional)
python scripts/generate.py   # build site/
```

## Privacy

The published site identifies the property only by its council point ID. The
street address and postcode appear nowhere in this repository or in anything
it deploys.
