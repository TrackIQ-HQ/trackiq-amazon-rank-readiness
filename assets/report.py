#!/usr/bin/env python
"""Render a rank readiness verdict as a single self-contained HTML page.

    python report.py --asin B0XXXXXXXX --sqp week1.json [--sqp week2.json ...]
        [--rank rank.json] [--paid paid.json] [--context ctx.json]
        [--brand acme] [--assets DIR] [--out page.html]

Takes the same inputs as readiness.py and calls its assess() directly, so the
page and the terminal run cannot disagree. The output is one file with no
external dependencies except a Google Fonts link: it opens from disk, emails,
and publishes as-is.

Layout: masthead, headline, five summary tiles, a diverging chart of
conversion against the market, a square-root-scaled chart of where the money
sits, then one card per keyword grouped by verdict, and a short "how to read
this" panel. Everything is computed here rather than in the browser, so there
is no JavaScript on the page.

Images are optional. Put logo-wordmark-dark.png and marketplace-amazon.png in
an --assets directory to use them; without them the masthead sets the wordmark
in type and shows a marketplace chip, which is a deliberate fallback rather
than a broken image.

The palette is light-only and every colour is painted explicitly, so the page
does not inherit a host theme and looks the same wherever it is opened.
"""
import argparse, base64, html, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import readiness as dm

HERE = os.path.dirname(os.path.abspath(__file__))
# Optional images, resolved next to the script or in --assets. Absent, the
# masthead falls back to the wordmark set in type and a marketplace chip, which
# is the behaviour every user gets until they drop their own PNGs in.
ASSETS = HERE   # overridden by --assets

# from _ds/.../colors_and_type.css
SAGE, SAGE_HOVER = "#17533F", "#123F31"
OLIVE, SAND = "#778867", "#C4A574"
OK, BAD, WARN, INFO = "#2F7A5A", "#C65345", "#D89B35", "#4B8C7A"
INK, SECONDARY, MUTED = "#1F2420", "#586258", "#6E726A"
APP_BG, CARD_BG, SOFT, MUTED_BG = "#FDFBFA", "#FFFFFF", "#F7F5EF", "#F3F1EA"
BORDER, CHROME, CARD_BORDER = "#EEEEEE", "#E6E1D8", "#EFEAE3"
TAUPE = "#B7AA98"
SHADOW = "0 8px 24px rgba(31,36,32,.06)"

# verdict -> (colour, tint, badge, section title, why)
GROUPS = {
    dm.FUND: (OK, "#EEF7F1", "Fund", "Increase advertising",
              "These convert better than the market on their own query, so a position "
              "bought with advertising holds after the spend stops, and paid already "
              "returns above 1.0x here."),
    dm.SEED: (WARN, "#FFF7E6", "Seed", "Seed it, do not buy clicks",
              "This converts better than the market, so a position would hold, but "
              "clicks cost more than they return. Buy the rank with reviews and "
              "seeding instead of CPC."),
    dm.TEST: (INFO, "#EEF7F5", "Read", "Buy a small read first",
              "Real market volume, but not enough search query data yet to tell whether "
              "we out-convert the market. A short, deliberate spend answers it before "
              "any real money goes in."),
    dm.NOGO: (BAD, "#FFF3F1", "Avoid", "Do not push these",
              "We convert below the market here, so a bought position slides back as "
              "soon as the money stops. They are listed because they carry the largest "
              "pools, which is exactly what makes them tempting."),
}
ORDER = (dm.FUND, dm.SEED, dm.TEST, dm.NOGO)
RANK_FLOOR = 60          # the rank rail runs #1 to here, as the design draws it
ROAS_FULL = 2.5          # the roas bar saturates here
ROAS_BREAKEVEN = 1.0


def e(s):
    return html.escape(str(s), quote=True)


def img(path):
    try:
        with open(path, "rb") as fh:
            return "data:image/png;base64," + base64.b64encode(fh.read()).decode()
    except OSError:
        return None


def money(n):
    return "$" + format(int(round(n)), ",")


def compact(n):
    if n >= 1e6:
        return "$%.2fM" % (n / 1e6)
    if n >= 1e3:
        return "$%dK" % round(n / 1e3)
    return "$%d" % round(n)


def worth_w(v, lo=2000.0, hi=2e7):
    """Log width for the money rails, as the design does it."""
    import math
    L = lambda x: math.log10(max(x, 1000.0))
    return max(3.0, ((L(v) - L(lo)) / (L(hi) - L(lo))) * 100)


def diverge(ratio):
    """Bar geometry around a centre line at 50%, clamped at 2.00x. Ported from
    the design: left = min(50, clamped*50), width = |clamped - 1| * 50."""
    c = min(ratio, 2.0)
    return min(50.0, c * 50), abs(c - 1) * 50


# --------------------------------------------------------------- page pieces

def masthead(res, wordmark, amazon):
    mark = ('<img src="%s" alt="TrackIQ" style="height:26px;width:auto;display:block">'
            % wordmark) if wordmark else \
           ('<span style="font-weight:700;font-size:20px;color:%s">{TRACKIQ}</span>' % SAGE)
    badge = ('<img src="%s" alt="Amazon" style="height:20px;width:auto;display:block;'
             'opacity:.85">' % amazon) if amazon else \
            ('<span style="font-size:10px;font-weight:700;letter-spacing:.14em;'
             'text-transform:uppercase;color:%s;border:1px solid %s;border-radius:4px;'
             'padding:3px 7px;white-space:nowrap">%s</span>'
             % (MUTED, CHROME, e(res.get("marketplace") or "Amazon")))
    return (
        '<div style="background:%s;border-bottom:1px solid %s">'
        '<div style="max-width:1180px;margin:0 auto;padding:18px 24px;display:flex;'
        'flex-wrap:wrap;gap:16px 32px;align-items:center;justify-content:space-between">'
        '%s'
        '<div style="display:flex;align-items:center;gap:12px">%s'
        '<div style="display:flex;flex-direction:column;gap:2px;line-height:1.3">'
        '<div style="font-size:13px;font-weight:600;color:%s">%s '
        '<span style="color:%s;font-weight:400;font-family:\'Inter Tight\',Inter,sans-serif">'
        '&middot; %s</span></div>'
        '<div style="font-size:12px;color:%s;font-family:\'Inter Tight\',Inter,sans-serif;'
        'font-feature-settings:\'tnum\' 1">$%.2f &middot; %s stars on %s reviews '
        '%s</div></div></div></div></div>'
        % (MUTED_BG, CHROME, mark, badge, INK, e(res["label"] or ""), MUTED,
           e(res["asin"]), MUTED, res["asp"] or 0, e(res["rating"] or "n/a"),
           format(int(res["reviews"] or 0), ","),
           (" &middot; " + e(res["day"])) if res.get("day") else ""))


def hero(res, skipped):
    cover = res["cover"] or 0
    dots = [(OK, "Buy Box live at <b style=\"color:%s\">$%.2f</b>" % (INK, res["asp"] or 0))]
    dots.append((WARN if cover < 45 else OK,
                 "<b style=\"color:%s\">%.0f days of cover</b> including inbound%s"
                 % (INK, cover,
                    " &mdash; confirm replenishment before a push" if cover < 45 else "")))
    dots.append((TAUPE, "%d further terms funded, at parity, or too small to matter"
                 % skipped))
    bullets = "".join(
        '<div style="display:flex;gap:10px;align-items:flex-start">'
        '<span style="flex:none;margin-top:5px;width:7px;height:7px;border-radius:999px;'
        'background:%s"></span><span style="font-size:13px;line-height:1.45;color:%s">'
        '%s</span></div>' % (c, SECONDARY, t) for c, t in dots)
    return (
        '<div class="hero">'
        '<div><div style="display:flex;align-items:center;gap:10px;margin-bottom:14px">'
        '<span style="display:block;width:26px;height:3px;background:%s"></span>'
        '<span style="font-size:11px;font-weight:700;letter-spacing:.24em;'
        'text-transform:uppercase;color:%s">Rank readiness &middot; one listing</span></div>'
        '<h1 style="margin:0 0 12px;font-size:36px;line-height:1.15;font-weight:600;'
        'letter-spacing:-.02em;color:%s;text-wrap:balance;max-width:24ch">Which keywords '
        'keep the rank after the spend stops</h1>'
        '<p style="margin:0;font-size:15px;line-height:1.6;color:%s;max-width:62ch;'
        'text-wrap:pretty">A keyword only holds a bought position if this listing then '
        'converts organic shoppers at least as well as the market does on that same '
        'search. Every verdict below leads with that ratio, over the most recent %d '
        'weeks of search query data.</p></div>'
        '<div style="background:%s;border:1px solid %s;border-radius:12px;box-shadow:%s;'
        'padding:16px 18px">'
        '<div style="font-size:11px;font-weight:700;letter-spacing:.14em;'
        'text-transform:uppercase;color:%s;margin-bottom:10px">Before you commit</div>'
        '<div style="display:flex;flex-direction:column;gap:9px">%s</div></div></div>'
        % (SAGE, OLIVE, SAGE, SECONDARY, dm.RECENT_WEEKS,
           CARD_BG, BORDER, SHADOW, MUTED, bullets))


def kpis(rows, skipped):
    pool = sum((r["pool"] or {}).get("annual", 0) for r in rows)
    spend = sum(r["spend"] or 0 for r in rows)
    rev = sum((r["spend"] or 0) * (r["roas"] or 0) for r in rows)
    avoid_pool = sum((r["pool"] or {}).get("annual", 0)
                     for r in rows if r["verdict"] == dm.NOGO)
    measured = [r for r in rows if r.get("ratio") is not None]
    beat = [r for r in measured if r["ratio"] >= 1.0]
    unread = [r for r in rows if r.get("ratio") is None]
    slides = [r for r in measured if r["ratio"] < 1.0]

    def tile(label, value, note, colour, top=None, gradient=False):
        if gradient:
            shell = ('background:linear-gradient(135deg,%s,%s);border-radius:10px;'
                     'padding:16px 18px;color:%s;box-shadow:%s' % (SAGE, SAGE_HOVER, APP_BG, SHADOW))
            lab = ('font-size:12px;font-weight:600;letter-spacing:.06em;'
                   'text-transform:uppercase;opacity:.82')
            val = ("font-family:'Inter Tight',Inter,sans-serif;font-weight:600;"
                   "font-size:32px;letter-spacing:-.4px;line-height:1.1;margin-top:8px")
            sub = "font-size:11px;opacity:.78;margin-top:4px"
        else:
            shell = ('background:%s;border:1px solid %s;border-top:4px solid %s;'
                     'border-radius:10px;padding:14px 16px;box-shadow:%s'
                     % (CARD_BG, BORDER, top, SHADOW))
            lab = ('font-size:12px;font-weight:600;letter-spacing:.06em;'
                   'text-transform:uppercase;color:%s' % MUTED)
            val = ("font-family:'Inter Tight',Inter,sans-serif;font-weight:600;"
                   "font-size:32px;letter-spacing:-.4px;line-height:1.1;margin-top:8px;"
                   "color:%s" % colour)
            sub = "font-size:11px;color:%s;margin-top:4px" % MUTED
        return ('<div style="%s"><div style="%s">%s</div><div style="%s">%s</div>'
                '<div style="%s">%s</div></div>' % (shell, lab, e(label), val, value, sub, note))

    share = ("%d%% of the pool sits here" % round(avoid_pool / pool * 100)) if pool else "n/a"
    blended = ("%.2fx blended" % (rev / spend)) if spend else "no spend"
    return ('<div class="kpis">%s%s%s%s%s</div>' % (
        tile("Pool reviewed", compact(pool), "a year across %d terms" % len(rows),
             None, gradient=True),
        tile("Beat the market",
             '%d <span style="font-size:16px;color:%s">of %d</span>'
             % (len(beat), MUTED, len(measured)),
             "readable terms &middot; these hold", OK, top=OK),
        tile("Unread", str(len(unread)), "need a deliberate read", INFO, top=INFO),
        tile("Slides back", str(len(slides)), share, BAD, top=BAD),
        tile("Spend, 28 days", money(spend),
             "on these %d terms &middot; %s" % (len(rows), blended), INK, top=SAND)))


def conversion_chart(rows):
    measured = sorted((r for r in rows if r.get("ratio") is not None),
                      key=lambda r: -r["ratio"])
    if not measured:
        return ""
    unread = sum(1 for r in rows if r.get("ratio") is None)
    lines = []
    for r in measured:
        colour = OK if r["ratio"] >= 1.0 else BAD
        left, width = diverge(r["ratio"])
        lines.append(
            '<div class="cvrow">'
            '<div style="font-size:13px;color:%s;overflow-wrap:break-word;line-height:1.3">'
            '%s</div>'
            '<div style="position:relative;height:22px;background:%s;border-radius:4px">'
            '<div style="position:absolute;top:0;bottom:0;left:50%%;width:1px;background:%s;'
            'opacity:.35"></div>'
            '<div style="position:absolute;top:3px;bottom:3px;border-radius:3px;left:%.2f%%;'
            'width:%.2f%%;background:%s"></div></div>'
            '<div style="text-align:right;font-family:\'Inter Tight\',Inter,sans-serif;'
            'font-feature-settings:\'tnum\' 1;font-weight:600;font-size:15px;color:%s">'
            '%.2fx</div></div>'
            % (INK, e(r["kw"]), SOFT, SAGE, left, width, colour, colour, r["ratio"]))
    note = ("" if not unread else
            '<p style="margin:14px 0 0;font-size:12.5px;color:%s;max-width:80ch">The other '
            '%d terms have no readable ratio yet &mdash; a week only counts once a term takes '
            'ten clicks, and a verdict needs %d such weeks.</p>'
            % (MUTED, unread, dm.MIN_READS))
    return (
        '<div style="margin-top:44px;background:%s;border:1px solid %s;border-radius:12px;'
        'box-shadow:%s;overflow:hidden">'
        '<div style="display:flex;flex-wrap:wrap;gap:8px 20px;align-items:baseline;'
        'justify-content:space-between;padding:16px 20px 14px;border-bottom:1px solid %s">'
        '<div><div style="font-size:16px;font-weight:600;color:%s">Conversion against the '
        'market</div><div style="font-size:12.5px;color:%s;margin-top:2px">Anything left of '
        'the 1.00x line cannot keep a position it did not earn</div></div>'
        '<div style="display:flex;gap:14px;align-items:center;font-size:11.5px;color:%s">'
        '<span style="display:flex;gap:6px;align-items:center"><span style="width:10px;'
        'height:10px;border-radius:2px;background:%s"></span>holds</span>'
        '<span style="display:flex;gap:6px;align-items:center"><span style="width:10px;'
        'height:10px;border-radius:2px;background:%s"></span>slides back</span></div></div>'
        '<div style="padding:18px 20px 20px">%s'
        '<div class="cvrow" style="margin-top:6px;padding-top:10px;border-top:1px solid %s">'
        '<div></div><div style="display:flex;justify-content:space-between;font-size:11px;'
        'color:%s;font-family:\'Inter Tight\',Inter,sans-serif"><span>0.00x</span>'
        '<span>1.00x &mdash; market parity</span><span>2.00x</span></div><div></div></div>'
        '%s</div></div>'
        % (CARD_BG, BORDER, SHADOW, BORDER, INK, MUTED, SECONDARY, OK, BAD,
           "".join(lines), BORDER, MUTED, note))


def worth_chart(rows):
    import math
    ranked = sorted((r for r in rows if r["pool"]),
                    key=lambda r: -r["pool"]["annual"])
    if not ranked:
        return ""
    pool = sum(r["pool"]["annual"] for r in ranked)
    top = ranked[0]
    max_root = math.sqrt(top["pool"]["annual"])
    lines = []
    for r in ranked:
        colour = GROUPS[r["verdict"]][0] if r["verdict"] in GROUPS else TAUPE
        w = max(1.2, (math.sqrt(r["pool"]["annual"]) / max_root) * 100)
        lines.append(
            '<div class="wrow">'
            '<div style="font-size:13px;color:%s;overflow-wrap:break-word;line-height:1.3">'
            '%s</div>'
            '<div style="position:relative;height:16px;border-radius:4px;background:%s;'
            'border:1px solid %s"><div style="position:absolute;top:0;bottom:0;left:0;'
            'border-radius:3px;width:%.2f%%;background:%s"></div></div>'
            '<div style="text-align:right;font-family:\'Inter Tight\',Inter,sans-serif;'
            'font-feature-settings:\'tnum\' 1;font-size:13.5px;color:%s">%s/yr</div>'
            '<div style="text-align:right;font-family:\'Inter Tight\',Inter,sans-serif;'
            'font-feature-settings:\'tnum\' 1;font-size:13px;color:%s">%.1f%% held</div>'
            '</div>'
            % (INK, e(r["kw"]), SOFT, CARD_BORDER, w, colour, INK,
               compact(r["pool"]["annual"]), MUTED, (r["share"] or 0) * 100))
    lead = ""
    if pool:
        lead = ('&mdash; <b style="color:%s">%s</b> alone is %d%% of every dollar reviewed '
                'here%s.' % (INK, e(top["kw"]), round(top["pool"]["annual"] / pool * 100),
                             ", and it is one of the terms that slides back"
                             if top["verdict"] == dm.NOGO else ""))
    return (
        '<div style="margin-top:20px;background:%s;border:1px solid %s;border-radius:12px;'
        'box-shadow:%s;overflow:hidden">'
        '<div style="padding:16px 20px 14px;border-bottom:1px solid %s">'
        '<div style="font-size:16px;font-weight:600;color:%s">Where the money sits, and what '
        'we hold of it</div><div style="font-size:12.5px;color:%s;margin-top:2px">Annualised '
        'market purchases at our own price, on a square-root scale %s</div></div>'
        '<div style="padding:16px 20px 20px">%s</div></div>'
        % (CARD_BG, BORDER, SHADOW, BORDER, INK, MUTED, lead, "".join(lines)))


def term_card(r):
    colour, tint, badge, _, _ = GROUPS[r["verdict"]]
    measured = r.get("ratio") is not None
    fig_colour = MUTED if not measured else (OK if r["ratio"] >= 1.0 else BAD)
    if measured:
        left, width = diverge(r["ratio"])
        fig = "%.2fx" % r["ratio"]
        note = "of the market&rsquo;s conversion"
        bar = ('<div style="position:relative;height:8px;margin-top:11px;border-radius:999px;'
               'background:%s;border:1px solid %s">'
               '<div style="position:absolute;top:-3px;bottom:-3px;left:50%%;width:1px;'
               'background:%s;opacity:.4"></div>'
               '<div style="position:absolute;top:1px;bottom:1px;border-radius:999px;'
               'left:%.2f%%;width:%.2f%%;background:%s"></div></div>'
               % (CARD_BG, CARD_BORDER, SAGE, left, width, fig_colour))
        trend = r.get("trend") or ("%d weeks of data" % r["weeks_readable"])
    else:
        fig, note, bar = "&mdash;", "not enough SQP data", ""
        trend = ("%d week%s clears the ten-click floor &middot; a verdict needs %d"
                 % (r["weeks_readable"], "" if r["weeks_readable"] == 1 else "s",
                    dm.MIN_READS))

    p = r["pool"]
    blocks = []
    if p:
        blocks.append(
            '<div><div style="display:flex;justify-content:space-between;gap:10px;'
            'align-items:baseline"><span style="%s">Query worth</span>'
            '<span style="%s">%s a year</span></div>'
            '<div style="position:relative;height:6px;margin-top:6px;border-radius:999px;'
            'background:%s"><div style="position:absolute;inset:0;border-radius:999px;'
            'width:%.2f%%;background:%s"></div></div>'
            '<div style="font-size:11.5px;color:%s;margin-top:5px">%s purchases a week</div>'
            '</div>'
            % (LBL, VAL, money(p["annual"]), MUTED_BG, worth_w(p["annual"]), OLIVE,
               MUTED, format(int(p["weekly_buys"]), ",")))
        upside = money(p["ours"]) + " a year today"
        if r["verdict"] != dm.NOGO:
            upside += " &middot; every 5 points of share is %s" % money(p["per_5pts"])
        blocks.append(
            '<div style="padding-top:11px;border-top:1px solid %s">'
            '<div style="display:flex;justify-content:space-between;gap:10px;'
            'align-items:baseline"><span style="%s">We hold</span>'
            '<span style="%s">%.1f%%</span></div>'
            '<div style="font-size:11.5px;color:%s;margin-top:5px">%s</div></div>'
            % (CARD_BORDER, LBL, VAL, (r["share"] or 0) * 100, SECONDARY, upside))

    rank_rail = ""
    if r["rank"]:
        cur, lo, hi = r["rank"][0], r["rank"][1], r["rank"][2]
        rank_rail = (
            '<div style="position:relative;height:18px;margin-top:6px">'
            '<div style="position:absolute;top:8px;left:0;right:0;height:3px;'
            'border-radius:999px;background:%s"></div>'
            '<div style="position:absolute;top:7px;height:5px;border-radius:999px;left:%.2f%%;'
            'width:%.2f%%;background:%s"></div>'
            '<div style="position:absolute;top:4px;width:11px;height:11px;margin-left:-5px;'
            'border-radius:999px;background:%s;border:2px solid %s;'
            'box-shadow:0 1px 3px rgba(31,36,32,.3);left:%.2f%%"></div></div>'
            '<div style="display:flex;justify-content:space-between;font-size:11px;color:%s;'
            'font-family:\'Inter Tight\',Inter,sans-serif"><span>#1</span>'
            '<span>ranged #%d to #%d across the week</span><span>#%d</span></div>'
            % (MUTED_BG, min(100.0, lo / RANK_FLOOR * 100),
               max(2.0, (hi - lo) / RANK_FLOOR * 100), SAND, SAGE, CARD_BG,
               min(100.0, cur / RANK_FLOOR * 100), MUTED, lo, hi, RANK_FLOOR))
    blocks.append(
        '<div style="padding-top:11px;border-top:1px solid %s">'
        '<div style="display:flex;justify-content:space-between;gap:10px;align-items:baseline">'
        '<span style="%s">Organic rank</span><span style="%s">%s</span></div>%s</div>'
        % (CARD_BORDER, LBL, VAL,
           ("#%d" % r["rank"][0]) if r["rank"] else "not tracked", rank_rail))

    ad_rail = ""
    if r["spend"]:
        roas = r["roas"] or 0
        ad_rail = (
            '<div style="position:relative;height:6px;margin-top:7px;border-radius:999px;'
            'background:%s"><div style="position:absolute;inset:0;border-radius:999px;'
            'width:%.2f%%;background:%s"></div>'
            '<div style="position:absolute;top:-3px;bottom:-3px;left:%.1f%%;width:1px;'
            'background:%s"></div></div>'
            '<div style="font-size:11.5px;color:%s;margin-top:5px">$%.2f a click &middot; '
            '%.0f%% ACoS &middot; breakeven marked</div>'
            % (MUTED_BG, max(2.0, min(100.0, roas / ROAS_FULL * 100)),
               OK if roas >= ROAS_BREAKEVEN else BAD,
               ROAS_BREAKEVEN / ROAS_FULL * 100, SECONDARY, SECONDARY,
               r["cpc"] or 0, r["acos"] or 0))
    blocks.append(
        '<div style="padding-top:11px;border-top:1px solid %s">'
        '<div style="display:flex;justify-content:space-between;gap:10px;align-items:baseline">'
        '<span style="%s">Ads, 28 days</span><span style="%s">%s</span></div>%s</div>'
        % (CARD_BORDER, LBL, VAL,
           ("%s at %.2fx" % (money(r["spend"]), r["roas"] or 0)) if r["spend"]
           else "no spend", ad_rail))

    return (
        '<article style="background:%s;border:1px solid %s;border-top:4px solid %s;'
        'border-radius:12px;box-shadow:%s;padding:16px 18px 14px;min-width:0">'
        '<div style="display:flex;gap:10px;align-items:flex-start;'
        'justify-content:space-between">'
        '<h3 style="margin:0;font-size:16.5px;font-weight:600;color:%s;line-height:1.3;'
        'overflow-wrap:break-word">%s</h3>'
        '<span style="flex:none;font-size:11px;font-weight:600;padding:3px 9px;'
        'border-radius:999px;background:%s;color:%s;border:1px solid %s;white-space:nowrap">'
        '%s</span></div>'
        '<div style="margin-top:14px;padding:12px 14px;border-radius:10px;background:%s">'
        '<div style="display:flex;align-items:baseline;gap:9px;flex-wrap:wrap">'
        '<span style="font-family:\'Inter Tight\',Inter,sans-serif;font-weight:600;'
        'font-size:30px;line-height:1;font-feature-settings:\'tnum\' 1;color:%s">%s</span>'
        '<span style="font-size:12.5px;color:%s">%s</span></div>%s'
        '<div style="font-size:11.5px;color:%s;margin-top:7px">%s</div></div>'
        '<div style="margin-top:14px;display:flex;flex-direction:column;gap:11px">%s</div>'
        '</article>'
        % (CARD_BG, BORDER, colour, SHADOW, INK, e(r["kw"]), tint, colour, colour,
           e(badge), tint, fig_colour, fig, SECONDARY, note, bar, MUTED, e(trend),
           "".join(blocks)))


LBL = ("font-size:11px;font-weight:600;letter-spacing:.1em;text-transform:uppercase;"
       "color:%s" % MUTED)
VAL = ("font-family:'Inter Tight',Inter,sans-serif;font-feature-settings:'tnum' 1;"
       "font-size:14px;font-weight:600;color:%s" % INK)


def sections(rows):
    out = []
    for v in ORDER:
        items = [r for r in rows if r["verdict"] == v]
        if not items:
            continue
        colour, _, _, title, why = GROUPS[v]
        worth = sum((r["pool"] or {}).get("annual", 0) for r in items)
        out.append(
            '<div style="margin-top:48px">'
            '<div style="display:flex;flex-wrap:wrap;gap:10px 14px;align-items:center;'
            'padding-bottom:10px;border-bottom:3px solid %s">'
            '<span style="display:flex;align-items:center;justify-content:center;'
            'min-width:26px;height:26px;padding:0 8px;border-radius:999px;background:%s;'
            'color:#FFFFFF;font-family:\'Inter Tight\',Inter,sans-serif;font-weight:600;'
            'font-size:14px">%d</span>'
            '<h2 style="margin:0;font-size:21px;font-weight:600;color:%s;'
            'letter-spacing:-.01em">%s</h2>'
            '<span style="margin-left:auto;font-size:12px;'
            'font-family:\'Inter Tight\',Inter,sans-serif;color:%s">%s of pool</span></div>'
            '<p style="margin:12px 0 0;font-size:13.5px;line-height:1.6;color:%s;'
            'max-width:86ch;text-wrap:pretty">%s</p>'
            '<div class="cards">%s</div></div>'
            % (colour, colour, len(items), SAGE, e(title), MUTED, compact(worth),
               SECONDARY, e(why), "".join(term_card(r) for r in items)))
    return "".join(out)


def how_to_read(res):
    panels = [
        ("Weeks are not consecutive",
         "Search query reporting is weekly and arrives with gaps, so the weeks read here "
         "may not sit next to each other."),
        ("The ten-click floor",
         "A week counts only once a term takes ten clicks &mdash; a one-click week reports "
         "a 100% conversion rate."),
        ("Query worth is measured",
         "Weekly market purchases at our own price, annualised. No share gain is assumed "
         "anywhere on this page."),
    ]
    cells = "".join(
        '<div style="background:%s;border:1px solid %s;border-radius:10px;padding:14px 16px">'
        '<div style="font-size:13.5px;font-weight:600;color:%s;margin-bottom:5px">%s</div>'
        '<p style="margin:0;font-size:13px;line-height:1.55;color:%s">%s</p></div>'
        % (SOFT, CHROME, SAGE, e(t), SECONDARY, b) for t, b in panels)
    cover = res["cover"] or 0
    warn = ""
    if cover < 45:
        warn = ('<div style="margin-top:16px;padding:12px 16px;background:#FFF7E6;'
                'border:1px solid %s;border-radius:10px;font-size:13px;color:%s">%.0f days '
                'of cover including inbound. A rank push that lands before replenishment '
                'buys a stockout, not a position.</div>' % (WARN, INK, cover))
    return ('<div style="margin-top:56px;padding-top:26px;border-top:2px solid %s">'
            '<h2 style="margin:0 0 4px;font-size:16px;font-weight:600;color:%s">How to read '
            'this</h2><div class="howto">%s</div>%s</div>' % (SAGE, SAGE, cells, warn))


def render(res):
    wordmark = img(os.path.join(ASSETS, "logo-wordmark-dark.png"))
    amazon = img(os.path.join(ASSETS, "marketplace-amazon.png"))

    shown = [r for r in res["rows"] if r["verdict"] in GROUPS]
    shown = [r for r in shown
             if r["verdict"] != dm.NOGO
             or (r["pool"] or {}).get("annual", 0) >= dm.NOGO_MIN_POOL]
    nogo = [r for r in shown if r["verdict"] == dm.NOGO][:6]
    shown = [r for r in shown if r["verdict"] != dm.NOGO] + nogo
    skipped = len(res["rows"]) - len(shown)

    title = "%s Rank Readiness" % (res["label"] or res["asin"])
    return ("<title>" + e(title) + "</title>\n"
            '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n'
            '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
            'family=Inter:wght@400;500;600;700&family=Inter+Tight:wght@500;600;700'
            '&display=swap">\n'
            "<style>" + CSS + "</style>\n"
            '<div style="background:%s;padding:0 0 64px">%s'
            '<div style="max-width:1180px;margin:0 auto;padding:0 24px">'
            '%s%s%s%s%s%s'
            '<div style="margin-top:44px;padding-top:20px;border-top:1px solid %s;'
            'display:flex;flex-wrap:wrap;gap:14px;align-items:center;'
            'justify-content:space-between">%s'
            '<p style="margin:0;font-size:12px;color:%s">Rank readiness &middot; %s '
            '&middot; %s &middot; %s</p></div></div></div>'
            % (APP_BG, masthead(res, wordmark, amazon),
               hero(res, skipped), kpis(shown, skipped),
               conversion_chart(shown), worth_chart(shown), sections(shown),
               how_to_read(res), CHROME,
               ('<img src="%s" alt="TrackIQ" style="height:20px;width:auto;display:block;'
                'opacity:.75">' % wordmark) if wordmark else "",
               MUTED, e(res["label"] or ""), e(res["asin"]),
               (" &middot; " + e(res["day"])) if res.get("day") else ""))


CSS = """
body{margin:0;background:%(app)s;color:%(ink)s;font-family:Inter,ui-sans-serif,system-ui,
  sans-serif;font-size:14px;-webkit-font-smoothing:antialiased}
a{color:%(sage)s}a:hover{color:%(hover)s}
.hero{display:grid;grid-template-columns:minmax(0,1.35fr) minmax(0,1fr);gap:40px;
  align-items:end;padding:40px 0 28px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(178px,1fr));gap:14px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(310px,1fr));gap:16px;
  margin-top:18px}
.howto{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:14px;
  margin-top:16px}
.cvrow{display:grid;grid-template-columns:minmax(120px,210px) minmax(0,1fr) 92px;gap:14px;
  align-items:center;padding:7px 0}
.wrow{display:grid;grid-template-columns:minmax(120px,230px) minmax(0,1fr) 108px 78px;
  gap:14px;align-items:center;padding:6px 0}
@media (max-width:820px){
  .hero{grid-template-columns:1fr;gap:24px;align-items:start}
  .hero h1{font-size:29px!important}
  .cvrow{grid-template-columns:minmax(0,1fr) 76px}
  .cvrow > div:nth-child(2){grid-column:1 / -1;order:3}
  .wrow{grid-template-columns:minmax(0,1fr) 96px 72px}
  .wrow > div:nth-child(2){grid-column:1 / -1;order:4}
}
@media (max-width:560px){.cards{grid-template-columns:1fr}}
""" % {"app": APP_BG, "ink": INK, "sage": SAGE, "hover": SAGE_HOVER}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--asin", required=True)
    ap.add_argument("--sqp", action="append", default=[])
    ap.add_argument("--rank")
    ap.add_argument("--paid")
    ap.add_argument("--context")
    ap.add_argument("--brand", action="append", default=[])
    ap.add_argument("--junk", action="append", default=[])
    ap.add_argument("--assets")
    ap.add_argument("--out")
    a = ap.parse_args()
    if a.assets:
        ASSETS = a.assets
    if not a.sqp:
        ap.error("need at least one --sqp file")
    res = dm.assess(a.asin, a.sqp, a.rank, a.paid, a.context, a.brand, a.junk)
    out = a.out or os.path.join(os.getcwd(), "rank_readiness_%s.html" % a.asin)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(render(res))
    print("wrote %s (%d bytes)" % (out, os.path.getsize(out)))
