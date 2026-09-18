# Pulling the data

Every call below is a TrackIQ Amazon Ads MCP tool. Save each response to a file
and pass the paths to the scripts; nothing here calls the network, so a run is
reproducible and can be re-run months later against the same inputs.

## Contents

- [Before anything: confirm the account](#before-anything-confirm-the-account)
- [1. Search query performance — required](#1-search-query-performance--required)
- [2. Keyword rank — optional](#2-keyword-rank--optional)
- [3. Paid search terms — optional](#3-paid-search-terms--optional)
- [4. The context file — you write it](#4-the-context-file--you-write-it)
- [Quirks that produce wrong answers](#quirks-that-produce-wrong-answers)

## Before anything: confirm the account

```
set_context(question="<the user's actual question>")   # required first, fails closed
list_marketplaces()                                    # assert the brand and account
```

Where several TrackIQ connectors are attached they expose identical tool names,
and the `mcp__<uuid>__` prefixes are per-session — the one that was right
yesterday may be a different brand today. Assert on the marketplace response,
not on the server ID. The dangerous failure is not an error: a tool that
defaults its account scope returns another brand's numbers, which will render
and ship without anything firing.

## 1. Search query performance — required

One call **per week**. The report is weekly (Sunday to Saturday) and is never
aggregated across weeks; a call pins to the latest week overlapping the range.

```
get_search_query_performance(
    account_id=<id>, by_product=True, asin="B0XXXXXXXX",
    start_date="2026-09-06", end_date="2026-09-12", limit=200)
```

Save each week to its own file and pass them all with repeated `--sqp`.

**Find the weeks that exist.** Ingestion is irregular: adjacent weeks are
routinely missing. Probing one week at a time is slow, so use the pinning
behaviour instead — a wide range returns the latest week at or before its end
date, which lets you walk backwards:

```
get_search_query_performance(account_id=<id>, start_date="2026-02-01",
    end_date="2026-08-01", by_product=False, query_contains="<a live term>",
    limit=1)          # -> tells you the newest week at or before 2026-08-01
```

Repeat with the end date just before each week you find. A handful of calls maps
months of coverage.

**How many weeks.** As many as exist, and at minimum four. Two weeks will
produce verdicts and will not support them: the engine judges the recent window
precisely because terms turn, and it needs history behind that window to say
whether a term is improving or decaying. One real series ran five losing weeks
then two clear wins — on two weeks of data that term looks simply good, and on
seven it is visibly a term that turned.

## 2. Keyword rank — optional

```
get_keyword_rank(account_id=<id>, asin="B0XXXXXXXX",
    start_date="<~7 days back>", end_date="<today>",
    only_ranked=True, limit=500)
```

Pass `limit=500`: a single ASIN can return well over 100 rows for one day, and
the default silently truncates the tail.

Only keywords configured in a rank project are tracked, so a term with no rank
is not necessarily unranked — it may simply not be watched. The engine prints
`n/t` for those rather than implying a bad position. A high-value term that is
not tracked is itself worth reporting: nobody can see it move.

## 3. Paid search terms — optional

```
get_search_terms(account_id=<id>, ad_type="sp", asin="B0XXXXXXXX",
    start_date="<28 days back>", end_date="<today>",
    sort="orders DESC", limit=400)
```

This is what separates FUND from SEED: a term the listing out-converts but
where clicks return under breakeven is a seeding job, not a bidding one.

Scoping by ASIN returns terms triggered for ad groups **containing** that ASIN,
so where an ad group holds several products the orders and spend are not purely
this listing's. Cost per click and return are reliable; treat revenue as
approximate and say so if you quote it. The pull is also capped by `limit` and
sorted by orders, so a term reported as unspent may simply sit below the cut.

## 4. The context file — you write it

Small JSON of the listing facts the search query report does not carry. All
optional; the verdicts stand without it, but the report is thinner and the two
hard gates go unstated.

```json
{
  "label": "String Lights 48ft",
  "marketplace": "Amazon US",
  "day": "2026-09-15",
  "price": 13.24,
  "rating": 4.6,
  "reviews": 6229,
  "cover": 34,
  "buy_box_suppressed": false
}
```

- `price` drives every "query worth" figure. Without it no pool is computed.
- `cover` is days of stock including inbound. Under 45 the report warns, because
  a push that lands before replenishment buys a stockout rather than a position.
- `buy_box_suppressed` — Sponsored Products cannot serve without the Buy Box, so
  a suppressed listing cannot be ranked at any price. Set it to `true` only on
  evidence: a public price feed reading null is a prompt to check, not proof.
  The confirmation is **spend** — a genuinely suppressed listing's campaigns go
  to zero impressions, because the ads cannot serve. Conversion collapses
  whether a listing is suppressed or has merely come off promotion, so
  conversion alone proves nothing.

Sources: `get_inventory_snapshot` for cover (use `on_hand` plus `inbound`;
`reserved` is healthy stock, not stranded), `get_bsr` for price, and a public
product-data source for rating, reviews and Buy Box.

## Quirks that produce wrong answers

**Every `asin_*` field and most rates arrive as strings** while market totals
are bare numbers, and the split is not perfectly clean. Cast everything
tolerantly; the scripts do.

**`impression_share` is already a percentage.** `2.1343` means 2.13%, not 213%.
Reading it as a fraction makes every share figure wrong by 100x and silently
disables any threshold set against it.

**`asin_cvr` of 100% is almost always one click.** Hence the ten-click floor on
any week that contributes to a verdict.

**`asin_cvr` is `null` on zero-click rows but `"0.0000"` elsewhere** — different
meanings, and treating null as zero fabricates a losing week.

**The ingestion carries roughly 100 query rows per ASIN per week.** `offset`
past that returns empty, so it is the depth of the data rather than a cap you
can page through. A tracked term absent from it is unproven, never a negative.

**Junk queries.** The report contains the U+FFFC glyph as an empty query, and ad
groups wander into queries the product has no business on. The engine filters
these on measured behaviour rather than a word list — if shoppers on a query
click at under half the market's rate, or the listing takes under 100
impressions a week there, it is not that product's market whatever the pool
says. Where something still slips through, add it with `--junk`.

**Search query reporting lags.** Expect the newest available week to be one to
three weeks behind today. Say which weeks were read; the report prints them.
