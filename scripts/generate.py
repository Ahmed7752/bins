"""Build the published site: bins.ics + a glanceable "next bin" page.

Events are enumerated rather than expressed as RRULEs so that one-off
reschedules can be baked in per-date. Three years are emitted, so the feed
keeps working even if the weekly workflow stops running.

Nothing here writes the property address or postcode -- the published output
identifies the property only by its council point ID.
"""

import json
import pathlib
from datetime import date, datetime, timedelta, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCHEDULE = ROOT / "data" / "schedule.json"
SITE = ROOT / "site"

YEARS_AHEAD = 3
REMIND_HOUR = 18  # 6pm the evening before


def build_collections(cfg):
    """Expand the rule into concrete (date, bin_key) pairs, applying overrides."""
    today = date.today()
    horizon = today + timedelta(days=365 * YEARS_AHEAD)
    overrides = cfg.get("overrides", {})
    out = []

    for bin_key, spec in cfg["rule"].items():
        anchor = date.fromisoformat(spec["anchor"])
        step = timedelta(days=spec["intervalDays"])

        d = anchor
        while d < today - timedelta(days=7):
            d += step
        while d <= horizon:
            ov = overrides.get(d.isoformat())
            if ov and ov["bin"] == bin_key:
                out.append((date.fromisoformat(ov["movedTo"]), bin_key, True))
            else:
                out.append((d, bin_key, False))
            d += step

    # An override can land on a date the cycle already covers -- a collection
    # pushed onto the following slot, say. Without this, that bin would be
    # listed twice on the same day. Sorting puts the unmoved entry first, so
    # keeping the first occurrence prefers the genuine scheduled collection.
    out.sort(key=lambda r: (r[0], r[1], r[2]))
    deduped, seen = [], set()
    for collection_day, bin_key, moved in out:
        if (collection_day, bin_key) in seen:
            continue
        seen.add((collection_day, bin_key))
        deduped.append((collection_day, bin_key, moved))
    return deduped


def esc(text: str) -> str:
    return text.replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;")


def fold(line: str) -> str:
    """RFC 5545 says lines wrap at 75 octets; continuations start with a space."""
    raw = line.encode("utf-8")
    if len(raw) <= 75:
        return line
    chunks, cur = [], b""
    for ch in line:
        b = ch.encode("utf-8")
        if len(cur) + len(b) > (75 if not chunks else 74):
            chunks.append(cur)
            cur = b""
        cur += b
    chunks.append(cur)
    return "\r\n ".join(c.decode("utf-8") for c in chunks)


def build_ics(cfg, collections) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//bins//Collection reminders//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:Bins",
        f"X-WR-CALDESC:{esc('Bin collection reminders (' + cfg['council'] + ')')}",
        "REFRESH-INTERVAL;VALUE=DURATION:P1D",
        "X-PUBLISHED-TTL:P1D",
    ]

    for collection_day, bin_key, moved in collections:
        spec = cfg["rule"][bin_key]
        remind = collection_day - timedelta(days=1)
        start = f"{remind:%Y%m%d}T{REMIND_HOUR:02d}0000"
        end = f"{remind:%Y%m%d}T{REMIND_HOUR:02d}1500"

        summary = f"Put out the {spec['label']} bin"
        if moved:
            summary += " (rescheduled)"
        desc = (
            f"{spec['contents']}. {spec['cadence']}. "
            f"Collected {collection_day:%a %d %b} - out before {cfg['putOutBy']}."
        )

        lines += [
            "BEGIN:VEVENT",
            f"UID:{bin_key}-{collection_day:%Y%m%d}@bins-{cfg['propertyId']}",
            f"DTSTAMP:{stamp}",
            f"DTSTART:{start}",
            f"DTEND:{end}",
            fold(f"SUMMARY:{esc(summary)}"),
            fold(f"DESCRIPTION:{esc(desc)}"),
            "BEGIN:VALARM",
            "ACTION:DISPLAY",
            fold(f"DESCRIPTION:{esc(spec['label'] + ' bin goes out tonight')}"),
            "TRIGGER:PT0M",
            "END:VALARM",
            "BEGIN:VALARM",
            "ACTION:DISPLAY",
            fold(f"DESCRIPTION:{esc(spec['label'] + ' bin - collection is this morning')}"),
            "TRIGGER:PT12H",
            "END:VALARM",
            "END:VEVENT",
        ]

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


def build_html(cfg, collections) -> str:
    """A single self-contained page. Picks 'next' client-side so it stays
    correct between rebuilds, and works offline once cached."""
    upcoming = [
        {"date": d.isoformat(), "bin": b, "moved": m}
        for d, b, m in collections
        if d >= date.today() - timedelta(days=1)
    ][:40]

    payload = json.dumps(
        {
            "bins": {
                k: {
                    "label": v["label"],
                    "contents": v["contents"],
                    "colour": v["colour"],
                    "cadence": v["cadence"],
                }
                for k, v in cfg["rule"].items()
            },
            "upcoming": upcoming,
            "putOutBy": cfg["putOutBy"],
            "built": date.today().isoformat(),
        },
        separators=(",", ":"),
    )

    return """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="Bins">
<meta name="theme-color" content="#0f172a">
<title>Bins</title>
<link rel="apple-touch-icon" href="icon.png">
<link rel="icon" href="icon.png">
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{
    font:16px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
    background:#0f172a;color:#f8fafc;min-height:100dvh;
    display:flex;align-items:center;justify-content:center;
    padding:max(1.5rem,env(safe-area-inset-top)) 1.5rem max(1.5rem,env(safe-area-inset-bottom));
    -webkit-font-smoothing:antialiased;
  }
  .card{width:100%;max-width:26rem;text-align:center}
  .eyebrow{
    font-size:.75rem;letter-spacing:.18em;text-transform:uppercase;
    color:#94a3b8;margin-bottom:1.75rem
  }
  .dot{
    width:6.5rem;height:6.5rem;border-radius:50%;margin:0 auto 1.5rem;
    border:3px solid rgba(248,250,252,.25);
    box-shadow:0 0 0 10px rgba(255,255,255,.03),0 18px 40px -12px rgba(0,0,0,.6)
  }
  h1{font-size:clamp(2.75rem,16vw,4rem);font-weight:800;letter-spacing:-.03em;line-height:1}
  .when{font-size:1.35rem;font-weight:600;margin-top:.6rem}
  .countdown{color:#94a3b8;margin-top:.2rem}
  .contents{
    margin-top:1.75rem;padding:1rem 1.15rem;border-radius:.85rem;
    background:rgba(148,163,184,.1);border:1px solid rgba(148,163,184,.16);
    color:#cbd5e1;font-size:.95rem
  }
  .flag{
    margin-top:1rem;padding:.7rem 1rem;border-radius:.6rem;font-size:.9rem;
    background:rgba(220,38,38,.16);border:1px solid rgba(248,113,113,.4);color:#fecaca
  }
  .then{margin-top:2rem;border-top:1px solid rgba(148,163,184,.16);padding-top:1.1rem}
  .row{
    display:flex;align-items:center;gap:.7rem;
    padding:.5rem 0;color:#cbd5e1;font-size:.95rem
  }
  .swatch{
    width:.85rem;height:.85rem;border-radius:50%;flex:0 0 auto;
    border:1px solid rgba(248,250,252,.55);
    box-shadow:0 0 0 2px rgba(148,163,184,.14)
  }
  .row .d{margin-left:auto;color:#94a3b8;font-variant-numeric:tabular-nums}
  footer{margin-top:1.75rem;color:#64748b;font-size:.75rem}
  @media (prefers-color-scheme:light){
    body{background:#f1f5f9;color:#0f172a}
    .eyebrow,.countdown,.row .d,footer{color:#64748b}
    .contents{background:#fff;border-color:#e2e8f0;color:#475569}
    .row{color:#334155}
    .then{border-top-color:#e2e8f0}
  }
</style>
</head>
<body>
<div class="card" id="app">Loading&hellip;</div>
<script id="data" type="application/json">__DATA__</script>
<script>
(function () {
  var D = JSON.parse(document.getElementById('data').textContent);
  var DAY = 86400000;

  function midnight(s) { var p = s.split('-'); return new Date(+p[0], +p[1] - 1, +p[2]); }
  function fmt(d) {
    return d.toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long' });
  }
  function shortFmt(d) {
    return d.toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' });
  }

  var today = new Date(); today.setHours(0, 0, 0, 0);
  var future = D.upcoming.filter(function (c) { return midnight(c.date) >= today; });

  if (!future.length) {
    document.getElementById('app').innerHTML =
      '<p class="eyebrow">No dates left</p><div class="contents">This calendar needs rebuilding \\u2014 ' +
      'the published schedule ran out.</div>';
    return;
  }

  var next = future[0];
  var info = D.bins[next.bin];
  var when = midnight(next.date);
  var days = Math.round((when - today) / DAY);
  var rel = days === 0 ? 'today' : days === 1 ? 'tomorrow' : 'in ' + days + ' days';

  var rest = future.slice(1, 5).map(function (c) {
    var b = D.bins[c.bin];
    return '<div class="row"><span class="swatch" style="background:' + b.colour + '"></span>' +
           b.label.charAt(0) + b.label.slice(1).toLowerCase() + ' bin' +
           '<span class="d">' + shortFmt(midnight(c.date)) + '</span></div>';
  }).join('');

  document.getElementById('app').innerHTML =
    '<p class="eyebrow">Next collection</p>' +
    '<div class="dot" style="background:' + info.colour + '"></div>' +
    '<h1>' + info.label + '</h1>' +
    '<p class="when">' + fmt(when) + '</p>' +
    '<p class="countdown">' + rel + ' \\u00b7 out by ' + D.putOutBy + '</p>' +
    '<div class="contents">' + info.contents + '</div>' +
    (next.moved ? '<div class="flag">Rescheduled \\u2014 this one has moved from its usual date.</div>' : '') +
    '<div class="then">' + rest + '</div>' +
    '<footer>Property ' + '__PID__' + ' \\u00b7 updated ' + D.built + '</footer>';
})();
</script>
</body>
</html>
""".replace("__DATA__", payload).replace("__PID__", cfg["propertyId"])


def build_setup_html(cfg) -> str:
    """Landing page for the QR code: one tap to subscribe, then the two
    steps iOS will not let a link do on your behalf."""
    base = cfg["siteUrl"].rstrip("/")
    feed = f"{base}/bins.ics"
    # webcal:// is what makes iOS hand the feed to Calendar instead of
    # downloading it as a file.
    webcal = "webcal://" + feed.split("://", 1)[1]

    return """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#0f172a">
<title>Set up bin reminders</title>
<link rel="apple-touch-icon" href="../icon.png">
<link rel="icon" href="../icon.png">
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{
    font:16px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
    background:#0f172a;color:#f8fafc;-webkit-font-smoothing:antialiased;
    padding:max(2rem,env(safe-area-inset-top)) 1.25rem max(3rem,env(safe-area-inset-bottom));
  }
  .wrap{max-width:30rem;margin:0 auto}
  h1{font-size:1.75rem;font-weight:800;letter-spacing:-.02em;margin-bottom:.4rem}
  .sub{color:#94a3b8;margin-bottom:2.25rem}
  .btn{
    display:block;text-align:center;text-decoration:none;
    background:#22c55e;color:#052e16;font-weight:700;font-size:1.05rem;
    padding:1.05rem 1rem;border-radius:.8rem;margin:.25rem 0 .5rem;
    box-shadow:0 12px 28px -14px rgba(34,197,94,.9)
  }
  .btn.secondary{background:rgba(148,163,184,.16);color:#f8fafc;box-shadow:none;font-weight:600}
  ol{list-style:none;counter-reset:s}
  li{
    counter-increment:s;position:relative;padding:0 0 1.75rem 3rem;
    border-left:2px solid rgba(148,163,184,.22);margin-left:1rem
  }
  li:last-child{border-left-color:transparent;padding-bottom:0}
  li::before{
    content:counter(s);position:absolute;left:-1.05rem;top:-.15rem;
    width:2.1rem;height:2.1rem;border-radius:50%;
    background:#1e293b;border:2px solid #334155;
    display:grid;place-items:center;font-size:.9rem;font-weight:700;color:#e2e8f0
  }
  h2{font-size:1.05rem;font-weight:700;margin-bottom:.3rem}
  p.note{color:#94a3b8;font-size:.92rem}
  .warn{
    margin-top:.7rem;padding:.8rem .95rem;border-radius:.6rem;font-size:.9rem;
    background:rgba(234,179,8,.14);border:1px solid rgba(250,204,21,.42);color:#fde68a
  }
  code{
    background:rgba(148,163,184,.16);padding:.12rem .4rem;border-radius:.3rem;
    font-size:.86em;word-break:break-all
  }
  footer{margin-top:2.5rem;color:#64748b;font-size:.8rem;text-align:center}
  a{color:#7dd3fc}
  @media (prefers-color-scheme:light){
    body{background:#f1f5f9;color:#0f172a}
    .sub,p.note,footer{color:#64748b}
    li::before{background:#fff;border-color:#cbd5e1;color:#334155}
    li{border-left-color:#e2e8f0}
    .btn.secondary{background:#e2e8f0;color:#0f172a}
    a{color:#0369a1}
  }
</style>
</head>
<body>
<div class="wrap">
  <h1>Bin reminders</h1>
  <p class="sub">Three taps and you will never guess which bin again.</p>

  <ol>
    <li>
      <h2>Add the calendar</h2>
      <p class="note">Opens Calendar and asks you to subscribe. Say yes.</p>
      <a class="btn" href="__WEBCAL__">Subscribe to bin collections</a>
    </li>

    <li>
      <h2>Keep the alarms</h2>
      <p class="note">
        Settings &rarr; Apps &rarr; Calendar &rarr; Accounts &rarr; Subscribed
        Calendars &rarr; Bins.
      </p>
      <div class="warn">
        <strong>Remove Alarms must be OFF.</strong> Leave it on and iOS strips the
        reminders out, so you get a silent calendar entry and no notification &mdash;
        exactly the problem you started with.
      </div>
    </li>

    <li>
      <h2>Put it on the home screen</h2>
      <p class="note">
        Open the page below in <strong>Safari</strong>, then tap Share
        &rarr; <strong>Add to Home Screen</strong>. iOS only allows this by hand
        &mdash; no link or QR code can do it for you.
      </p>
      <a class="btn secondary" href="../">Open the bin page</a>
    </li>
  </ol>

  <footer>
    Feed: <code>__FEED__</code><br>
    Updates itself twice a week.
  </footer>
</div>
</body>
</html>
""".replace("__WEBCAL__", webcal).replace("__FEED__", feed)


def build_qr(url: str, path: pathlib.Path):
    import qrcode

    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=12,
        border=3,
    )
    qr.add_data(url)
    qr.make(fit=True)
    qr.make_image(fill_color="#0f172a", back_color="white").save(path)


def build_icon(path: pathlib.Path):
    """180x180 home-screen icon: a simple bin glyph on the site background."""
    from PIL import Image, ImageDraw

    S = 180
    img = Image.new("RGB", (S, S), "#0f172a")
    d = ImageDraw.Draw(img)
    fg = "#f8fafc"
    # lid
    d.rounded_rectangle([40, 40, 140, 56], radius=6, fill=fg)
    d.rounded_rectangle([76, 28, 104, 42], radius=4, fill=fg)
    # body, tapering
    d.polygon([(52, 64), (128, 64), (119, 148), (61, 148)], fill=fg)
    # ribs
    for x in (76, 90, 104):
        d.line([(x, 78), (x - 1, 134)], fill="#0f172a", width=5)
    img.save(path, "PNG")


def main():
    cfg = json.loads(SCHEDULE.read_text(encoding="utf-8"))
    collections = build_collections(cfg)

    SITE.mkdir(exist_ok=True)
    (SITE / "setup").mkdir(exist_ok=True)
    (SITE / "bins.ics").write_text(build_ics(cfg, collections), encoding="utf-8", newline="")
    (SITE / "index.html").write_text(build_html(cfg, collections), encoding="utf-8")
    (SITE / "setup" / "index.html").write_text(build_setup_html(cfg), encoding="utf-8")
    (SITE / ".nojekyll").write_text("", encoding="utf-8")
    build_icon(SITE / "icon.png")
    build_qr(cfg["siteUrl"].rstrip("/") + "/setup/", SITE / "setup" / "qr.png")

    print(f"Wrote {len(collections)} collections through {collections[-1][0]}")
    for d, b, moved in collections[:6]:
        print(f"  {d:%a %d %b %Y}  {cfg['rule'][b]['label']}{'  (rescheduled)' if moved else ''}")


if __name__ == "__main__":
    main()
