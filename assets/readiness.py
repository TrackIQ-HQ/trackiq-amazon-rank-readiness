#!/usr/bin/env python
"""Rank readiness engine: will a bought rank survive the spend coming off.

    python readiness.py --asin B0XXXXXXXX \
        --sqp week1.json [--sqp week2.json ...] \
        [--rank rank.json] [--paid paid.json] [--context ctx.json] \
        [--brand "acme" --brand "acme labs"] [--json out.json]

Reads saved TrackIQ pulls and writes a verdict per keyword. No network calls,
so a run is reproducible from its inputs and can be re-run after the fact.
See assets/pulling-data.md for the exact calls that produce each file.

THE QUESTION
------------
Advertising or seeding can buy an organic position on almost any term. The
position only survives the money stopping if the listing then converts organic
shoppers at least as well as the market does on that same search. So every
verdict here turns on one measurement: our conversion against the market's, on
the same query, in the weeks we can actually read.

Four answers, each naming an action:
    FUND  out-converts the market and paid already returns above breakeven
    SEED  out-converts the market but clicks cost more than they return
    TEST  not enough readable weeks to tell; buy a small read first
    NO-GO converts below the market, so a bought position slides back

WHY THE RULES ARE SHAPED THIS WAY
---------------------------------
Each constant below cost a wrong answer to find. assets/method.md has the
full account; the short version is in the comments beside each one.
"""
import argparse, json, os, re, statistics, sys

# ---------------------------------------------------------------- thresholds

MIN_CLICKS = 10        # a week with fewer clicks cannot carry a conversion rate:
                       # a one-click week reports 100% and would top every list
MIN_READS = 2          # one readable week is an anecdote. A term resting on a
                       # single 10-click week is a TEST, never a FUND
RECENT_WEEKS = 3       # the verdict reads the recent window, not all history
PARITY_BAND = 0.10     # within 10% of the market is parity, not a win or a loss
MIN_MARKET_BUYS = 100  # below this the prize cannot repay the work
MIN_IMPRESSIONS = 100  # below this a weekly click-through rate is noise
CONSIDERED = 0.50      # our CTR must reach this share of the market's, or the
                       # shoppers on that query are not considering us at all
NOGO_MIN_POOL = 50000  # a trap smaller than this is not a temptation worth listing
HEAVY_SPEND = 1000.0   # already a material paid investment over the window
BREAKEVEN_ROAS = 1.0

FUND = "FUND: increase advertising"
SEED = "SEED: do not buy clicks"
TEST = "TEST: buy a read first"
NOGO = "NO-GO: the rank will not hold"
NONE = "NO ACTION"
VERDICT_ORDER = (FUND, SEED, TEST, NOGO, NONE)

# Queries that are in the account's report but are not this product's market.
# Extend per brand with --junk; these are the ones that show up for everyone.
JUNK_DEFAULT = ("￼",)          # the U+FFFC glyph Amazon emits for an empty query


def f(v):
    """Tolerant cast. Search query reporting returns every asin_* field and most
    rates as STRINGS while market totals arrive as bare numbers, and the split
    is not perfectly clean, so never assume a type from which side it came."""
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def money(n):
    return "$" + format(int(round(n)), ",")


class Config:
    def __init__(self, brand_tokens=(), junk=()):
        toks = [re.escape(t.strip().lower()) for t in brand_tokens if t.strip()]
        self.brand_re = re.compile("|".join(toks)) if toks else None
        self.junk = tuple(JUNK_DEFAULT) + tuple(j.strip().lower() for j in junk if j.strip())

    def branded(self, kw):
        """A ranking campaign is never funded on our own brand name, and branded
        terms dominate most tracked sets while sitting at rank 1, so left in
        they crowd out everything worth spending on."""
        return bool(self.brand_re and self.brand_re.search(kw.lower()))

    def is_junk(self, q):
        q = (q or "").strip().lower()
        return (not q) or any(j in q for j in self.junk)


# -------------------------------------------------------------------- inputs

def load_sqp(paths, asin, cfg):
    """{query: {week_end: row}} for one ASIN, plus the weeks seen, oldest first.

    Search query reporting is WEEKLY and never aggregated across weeks, and it
    is ingested with gaps, so the weeks are not necessarily consecutive. Pass
    one file per week; the engine sorts them."""
    out, weeks = {}, set()
    for p in paths:
        with open(p, encoding="utf-8") as fh:
            doc = json.load(fh)
        for r in doc.get("rows", []):
            if r.get("asin") != asin or cfg.is_junk(r.get("query")):
                continue
            wk = r.get("week_end")
            weeks.add(wk)
            out.setdefault(r["query"].strip().lower(), {})[wk] = r
    return out, sorted(weeks)


def load_ranks(path):
    """{keyword: (median, low, high, readings)} from a keyword-rank pull.

    Two things to get right. Every (keyword, ASIN) usually returns TWICE, once
    per SKU including a `..._FBM` row carrying an identical rank, so dedupe on
    (keyword, date) or every band doubles its sample. And a rank is read as a
    BAND, not a day: a single term swings several places between consecutive
    days, wider than most week-over-week moves anyone quotes, so one day cannot
    carry a verdict."""
    if not path:
        return {}
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    seen = {}
    for r in doc.get("rows", []):
        rank = r.get("organic_rank")
        if rank is None or not r.get("keyword"):
            continue
        seen.setdefault(r["keyword"].strip().lower(), {})[r.get("tracked_date")] = rank
    return {k: (statistics.median(v.values()), min(v.values()), max(v.values()), len(v))
            for k, v in seen.items() if v}


def load_paid(path):
    """{query: row} of what advertising already pays for this term.

    Scoping a search-terms pull by ASIN returns terms triggered for ad groups
    CONTAINING that ASIN, so where an ad group holds several products the
    orders and spend are not purely this listing's. Cost per click and return
    are reliable; treat the revenue as approximate."""
    if not path:
        return {}
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    rows = {r["query"].strip().lower(): r for r in doc.get("rows", []) if r.get("query")}
    return rows


def load_context(path):
    """Optional listing facts the search query report does not carry: label,
    price, rating, reviews, days of cover, Buy Box state. Everything here is
    presentational or a gate; the verdicts stand without it."""
    if not path:
        return {}
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


# ------------------------------------------------------------------ the test

def hold_test(weeks_for_query, weeks):
    """Does the listing out-convert the market on this term NOW.

    Returns (verdict, reads, hold) where verdict is:
        "clear"  out-converts in the recent window -> a push can hold
        "parity" inside the parity band -> holds its ground, wins nothing
        False    loses now -> a bought position slides back
        None     fewer than MIN_READS readable weeks -> unknown

    RECENT, not all-time, and this is the rule that matters most here. A term
    can turn: one real series read 0.74, 0.68, 1.02, 0.82 and 0.88 of the
    market's conversion over five weeks and then 1.30 and 1.16 in the two most
    recent. Requiring every readable week to win called that a trap on seven
    weeks of data while calling it fundable on two, so the rule got worse as
    the evidence got better, which is how you know a rule is wrong.

    MEDIAN of the window, not its minimum, for the same reason a rank is read
    as a band: weekly conversion on a few dozen clicks is noisy enough that one
    soft week should not veto a verdict.
    """
    reads, ratios = [], []
    for wk in weeks:
        r = weeks_for_query.get(wk)
        if not r:
            continue
        clicks, ours, mkt = (f(r.get("asin_clicks")), f(r.get("asin_cvr")),
                             f(r.get("market_cvr")))
        if not clicks or clicks < MIN_CLICKS or not mkt:
            continue
        reads.append((wk, ours or 0, mkt, int(clicks)))
        ratios.append((ours or 0) / mkt)

    if len(reads) < MIN_READS:
        return None, reads, {"ratio": None, "word": None, "trend": None,
                             "weeks": len(reads)}

    recent = sorted(ratios[-RECENT_WEEKS:])
    n = len(recent)
    mid = recent[n // 2] if n % 2 else (recent[n // 2 - 1] + recent[n // 2]) / 2
    verdict = ("clear" if mid >= 1 + PARITY_BAND
               else "parity" if mid >= 1 - PARITY_BAND else False)

    word = trend = None
    if len(ratios) >= MIN_READS + 2:
        earlier = ratios[:-RECENT_WEEKS]
        if earlier:
            a = sum(earlier) / len(earlier)
            b = sum(ratios[-RECENT_WEEKS:]) / len(ratios[-RECENT_WEEKS:])
            word = ("improving" if b >= a * 1.15
                    else "deteriorating" if b <= a * 0.87 else "holding steady")
            trend = "%s, %.2fx of the market earlier against %.2fx now" % (word, a, b)
    return verdict, reads, {"ratio": mid, "word": word, "trend": trend,
                            "weeks": len(reads)}


def considered(weeks_for_query, weeks):
    """Do shoppers searching this term click us at all, against the market's own
    rate on the same query. Returns the median ratio, or None if unreadable.

    This is what separates a term from a term-shaped accident. An ad group
    picks up queries the product has no business on, and those queries can
    carry enormous market volume: a report can show a product against 'fresh
    produce' or 'hot sauce' with millions of dollars of annual purchases
    behind them. Ranked by pool alone they dominate the shortlist. But the
    click-through on them runs a tenth of the market's, which is the shoppers
    themselves saying this is not the product they came for, so there is no
    position there worth buying at any price.

    Deliberately not a word list. A banned-terms list has to be rewritten for
    every brand and still misses the next oddity; the relative click-through
    is measured, and it travels.
    """
    ratios = []
    for wk in weeks:
        r = weeks_for_query.get(wk)
        if not r:
            continue
        imp, ours, mkt = (f(r.get("asin_impressions")), f(r.get("asin_ctr")),
                          f(r.get("market_ctr")))
        if not imp or imp < MIN_IMPRESSIONS or not mkt:
            continue
        ratios.append((ours or 0) / mkt)
    return statistics.median(ratios) if ratios else None


def assess(asin, sqp_paths, rank_path=None, paid_path=None, context_path=None,
           brand_tokens=(), junk=()):
    cfg = Config(brand_tokens, junk)
    sqp, weeks = load_sqp(sqp_paths, asin, cfg)
    ranks = load_ranks(rank_path)
    paid = load_paid(paid_path)
    ctx = load_context(context_path)
    asp = f(ctx.get("price"))

    rows = []
    for q, wks in sqp.items():
        latest = wks.get(weeks[-1]) if weeks else None
        if latest is None:
            latest = max(wks.values(), key=lambda x: f(x.get("market_purchases")) or 0)
        mp = f(latest.get("market_purchases")) or 0
        ap = f(latest.get("asin_purchases")) or 0
        share = (ap / mp) if mp else None
        held, reads, hold = hold_test(wks, weeks)
        rk = ranks.get(q)
        p = paid.get(q)
        spend = f(p.get("spend")) if p else None
        roas = f(p.get("roas")) if p else None

        # THE POOL, not a projected capture. Sizing a term by projecting it to
        # some share it might reach needs a rank-to-share curve, and fitting
        # one from a handful of non-consecutive weeks produces numbers that
        # look authoritative and are not. What is measured is the query's
        # annual value at our own price and the slice we hold of it; a reader
        # sizes the prize from that without anyone inventing an elasticity.
        pool = None
        if mp and asp:
            annual = mp * asp * 52
            pool = {"annual": annual, "ours": annual * (share or 0),
                    "per_5pts": annual * 0.05, "weekly_buys": mp}

        # Order matters: the traps carry the biggest pools, so they are tested
        # before anything that might wave them through on volume.
        ctr_ratio = considered(wks, weeks)
        best_impressions = max([f(r.get("asin_impressions")) or 0
                                for r in wks.values()] or [0])

        if cfg.branded(q):
            verdict, why = NONE, "our own brand name; a ranking campaign is not the lever"
        elif ctr_ratio is not None and ctr_ratio < CONSIDERED:
            verdict = NONE
            why = ("shoppers here click us at %.2fx the market's rate, so this query is "
                   "not our market however large its pool" % ctr_ratio)
        elif best_impressions < MIN_IMPRESSIONS:
            # No impressions means no position to read, and a term we are
            # barely shown on is a different and much larger decision than
            # testing a position we already hold. These arrive with enormous
            # pools attached because an ad group wandered into them, so left
            # in they lead the shortlist on volume alone.
            verdict = NONE
            why = ("we take %d impressions a week at best, so there is no position here "
                   "to read yet" % int(best_impressions))
        elif held is False:
            verdict, why = NOGO, ("we convert below the market here, so a bought position "
                                  "slides back as soon as the money stops")
        elif held is None:
            if mp >= MIN_MARKET_BUYS:
                verdict = TEST
                why = ("%d market purchases a week and fewer than %d readable weeks, so "
                       "whether we out-convert is still unknown; a small deliberate spend "
                       "answers it" % (mp, MIN_READS))
            else:
                verdict = NONE
                why = "only %d market purchases a week, and not readable either" % mp
        elif mp < MIN_MARKET_BUYS:
            verdict, why = NONE, ("only %d market purchases a week, so the prize cannot "
                                  "repay the work" % mp)
        elif spend and spend >= HEAVY_SPEND:
            verdict = NONE
            why = ("already carrying %s of paid spend at %.2fx; this is not an unworked "
                   "term" % (money(spend), roas or 0))
        elif held == "parity":
            verdict, why = NONE, ("we match the market's conversion rather than beat it, so "
                                  "a bought rank holds its ground but earns no advantage")
        elif roas is not None and roas < BREAKEVEN_ROAS:
            verdict = SEED
            why = ("out-converts the market but paid returns only %.2fx at %s a click, so "
                   "buy the rank with seeding and reviews rather than clicks"
                   % (roas, "$%.2f" % (f(p.get("cpc")) or 0)))
        else:
            verdict = FUND
            why = ("out-converts the market in the recent weeks and paid returns %s"
                   % ("%.2fx" % roas if roas else "nothing spent here yet"))

        rows.append({
            "kw": q, "verdict": verdict, "why": why,
            "market_buys": mp, "our_buys": ap, "share": share, "pool": pool,
            "ctr_ratio": ctr_ratio,
            "ratio": hold["ratio"], "trend": hold["trend"],
            "trend_word": hold["word"], "weeks_readable": hold["weeks"],
            "reads": reads,
            "rank": rk, "spend": spend, "roas": roas,
            "cpc": f(p.get("cpc")) if p else None,
            "acos": f(p.get("acos")) if p else None,
            "impression_share": f(latest.get("impression_share")),
        })

    rows.sort(key=lambda r: (VERDICT_ORDER.index(r["verdict"]), -r["market_buys"]))
    return {"asin": asin, "weeks": weeks, "rows": rows,
            "label": ctx.get("label") or asin, "asp": asp,
            "rating": ctx.get("rating"), "reviews": ctx.get("reviews"),
            "cover": f(ctx.get("cover")), "day": ctx.get("day"),
            "buy_box_suppressed": ctx.get("buy_box_suppressed"),
            "marketplace": ctx.get("marketplace")}


# ------------------------------------------------------------------- report

def report(res):
    print("RANK READINESS  %s  %s" % (res["label"], res["asin"]))
    bits = []
    if res["asp"]:
        bits.append("$%.2f" % res["asp"])
    if res["rating"]:
        bits.append("rated %s on %s reviews"
                    % (res["rating"], format(int(res["reviews"] or 0), ",")))
    if res["cover"] is not None:
        bits.append("%.0f days of cover" % res["cover"])
    if bits:
        print(", ".join(bits))
    if res["buy_box_suppressed"]:
        print("\n!! Buy Box is suppressed. Sponsored Products cannot serve without it, so "
              "no\n   amount of spend can rank this listing until that is resolved.")
    print("search query weeks: %s" % (", ".join(res["weeks"]) or "none"))
    print("Will the rank hold once the spend stops?")

    groups = {v: [r for r in res["rows"] if r["verdict"] == v] for v in VERDICT_ORDER}
    groups[NOGO] = [r for r in groups[NOGO]
                    if (r["pool"] or {}).get("annual", 0) >= NOGO_MIN_POOL][:6]
    for v in VERDICT_ORDER:
        rows = groups[v]
        if not rows:
            continue
        if v == NONE:
            print("\n%s  %d terms: already funded, at parity, our own brand, or too small."
                  % (v, len(rows)))
            continue
        print("\n" + "=" * 76)
        print("%s   (%d)" % (v, len(rows)))
        print("=" * 76)
        print("%-30s %6s %12s %7s  %s"
              % ("keyword", "rank", "pool/yr", "ours", "vs market"))
        for r in rows:
            rk = "%d" % r["rank"][0] if r["rank"] else "n/t"
            pool = money(r["pool"]["annual"]) if r["pool"] else "n/a"
            ratio = ("%.2fx" % r["ratio"]) if r["ratio"] is not None else "unread"
            print("%-30s %6s %12s %6.1f%%  %s"
                  % (r["kw"][:30], rk, pool, (r["share"] or 0) * 100, ratio))
            if r["pool"] and v != NOGO:
                print("%38s we hold %s; every 5 points of share is %s a year"
                      % ("", money(r["pool"]["ours"]), money(r["pool"]["per_5pts"])))
            if r.get("trend"):
                print("%38s %s" % ("", r["trend"]))
    print("\nPool is the query's weekly market purchases at our own price, annualised.")
    print("It is measured: no share gain is assumed anywhere.")
    return 0


def selfcheck():
    cfg = Config(["acme", "acme labs"], ["gift card"])
    assert cfg.branded("acme widget") and cfg.branded("ACME Labs 500")
    assert not cfg.branded("blue widget")
    assert cfg.is_junk("￼widget") and cfg.is_junk("") and cfg.is_junk("gift card 50")
    assert not cfg.is_junk("blue widget")
    assert Config().branded("anything") is False, "no brand tokens means nothing is branded"

    def series(*pairs):
        wk = ["w%02d" % i for i in range(len(pairs))]
        return ({w: {"asin_clicks": "60", "asin_cvr": str(o), "market_cvr": str(m)}
                 for w, (o, m) in zip(wk, pairs)}, wk)

    # a term that TURNED: five losing weeks then two clear wins. Judging every
    # week called this a trap; judging the recent window calls it fundable
    v, reads, hold = hold_test(*series((15.4, 20.8), (13.8, 20.2), (18.2, 17.9),
                                       (14.5, 17.7), (15.6, 17.8), (22.8, 17.5),
                                       (24.1, 20.7)))
    assert v == "clear" and hold["word"] == "improving", (v, hold)
    assert abs(hold["ratio"] - 1.164) < 0.01, hold["ratio"]

    # the mirror: strong history, losing now
    v2, _, h2 = hold_test(*series((24.0, 19.0), (25.0, 19.5), (23.0, 19.0),
                                  (14.0, 20.0), (13.0, 20.5), (12.0, 21.0)))
    assert v2 is False and h2["word"] == "deteriorating", (v2, h2)

    # hovering at parity is neither a win nor a loss
    assert hold_test(*series((23.1, 21.3), (23.0, 22.2), (21.4, 19.6), (20.8, 19.5),
                             (20.2, 18.6), (24.0, 19.4), (18.8, 19.1)))[0] == "parity"
    # a category head we lose every week stays a trap
    assert hold_test(*series((27.3, 43.0), (26.0, 41.4), (22.0, 40.6),
                             (16.3, 38.9), (23.8, 39.4)))[0] is False
    # one readable week is unknown, and a thin week is not readable at all
    one = {"w0": {"asin_clicks": "10", "asin_cvr": "30.0", "market_cvr": "23.5"}}
    v3, r3, h3 = hold_test(one, ["w0"])
    assert v3 is None and len(r3) == 1 and h3["ratio"] is None
    thin = {"w0": {"asin_clicks": "3", "asin_cvr": "100.0", "market_cvr": "20.0"}}
    assert hold_test(thin, ["w0"])[0] is None

    # rank pulls duplicate every (keyword, ASIN) across SKUs; the band must not
    # double-count the FBM twin
    import tempfile
    rows = [{"keyword": "blue widget", "organic_rank": 12, "tracked_date": "2026-09-01"},
            {"keyword": "blue widget", "organic_rank": 12, "tracked_date": "2026-09-01"},
            {"keyword": "blue widget", "organic_rank": 20, "tracked_date": "2026-09-02"},
            {"keyword": "blue widget", "organic_rank": 16, "tracked_date": "2026-09-03"},
            {"keyword": "no rank", "organic_rank": None, "tracked_date": "2026-09-01"}]
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                     encoding="utf-8") as fh:
        json.dump({"rows": rows}, fh)
        tmp = fh.name
    band = load_ranks(tmp)
    assert band["blue widget"] == (16, 12, 20, 3), band
    assert "no rank" not in band
    os.unlink(tmp)

    # the consideration filter: a huge pool we are shown on but never clicked
    # for is not our market. These are 'outdoor wedding decor' and 'christmas lights'
    # shaped rows, which topped the shortlist by pool before this existed.
    def ctr(*triples):
        wk = ["w%02d" % i for i in range(len(triples))]
        return ({w: {"asin_impressions": str(i), "asin_ctr": str(o),
                     "market_ctr": str(m)} for w, (i, o, m) in zip(wk, triples)}, wk)
    assert considered(*ctr((2062, 0.16, 1.34), (1900, 0.20, 1.40))) < CONSIDERED
    assert considered(*ctr((2183, 1.85, 1.51), (2000, 1.90, 1.55))) > 1.0
    # too few impressions to read is None, which must not be mistaken for a low
    # ratio and silently drop a term
    assert considered(*ctr((12, 0.0, 1.5))) is None

    assert f("0.6369") == 0.6369 and f(31523) == 31523.0
    assert f(None) is None and f("") is None and f("n/a") is None
    print("selfcheck OK")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--asin")
    ap.add_argument("--sqp", action="append", default=[])
    ap.add_argument("--rank")
    ap.add_argument("--paid")
    ap.add_argument("--context")
    ap.add_argument("--brand", action="append", default=[])
    ap.add_argument("--junk", action="append", default=[])
    ap.add_argument("--json")
    ap.add_argument("--selfcheck", action="store_true")
    a = ap.parse_args()
    if a.selfcheck:
        selfcheck()
        sys.exit(0)
    if not (a.asin and a.sqp):
        ap.error("need --asin and at least one --sqp file")
    res = assess(a.asin, a.sqp, a.rank, a.paid, a.context, a.brand, a.junk)
    if a.json:
        with open(a.json, "w", encoding="utf-8") as fh:
            json.dump(res, fh, indent=1)
        print("wrote", a.json)
    sys.exit(report(res))
