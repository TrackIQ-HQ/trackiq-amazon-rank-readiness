---
name: trackiq-amazon-rank-readiness
description: >-
  Decides which Amazon search terms deserve advertising spend or product
  seeding on a single ASIN, by testing whether a bought organic rank would
  hold once the money stops - the listing's conversion rate against the
  market's on that same query. Returns FUND, SEED, TEST or NO-GO per keyword
  plus a designed HTML report. Use when the user asks which keywords to push,
  where to increase PPC, whether to seed a listing, which terms will keep
  their rank, why a rank slid back after the spend stopped, or to find
  diamond-in-the-rough keywords.
---

# Rank Readiness

## What this answers, and why it is not obvious

Advertising or seeding can buy an organic position on almost any term. Whether
that position **survives the money stopping** is a different question, and it
has one answer: the listing has to convert organic shoppers at least as well as
the market does on that same search. If it converts worse, Amazon hands the slot
back to whoever converts better, and the spend bought a spike rather than a
position.

So every verdict here turns on one measurement — **our conversion rate against
the market's, on the same query, in the weeks we can actually read**. That test
also does the most important negative work, because the biggest-volume terms in
a category are usually the ones a niche product converts worst on. They look
like the obvious targets precisely because they are large.

Four verdicts, each naming an action:

| Verdict | Means | Do |
|---|---|---|
| **FUND** | out-converts the market, and paid already returns above breakeven | increase advertising |
| **SEED** | out-converts the market, but clicks cost more than they return | buy the rank with reviews and seeding, not CPC |
| **TEST** | too few readable weeks to tell | buy a small deliberate read first |
| **NO-GO** | converts below the market | do not push; it will slide back |

## Requires

- The TrackIQ MCP, for `set_context`, `list_marketplaces`,
  `get_search_query_performance`, and optionally `get_keyword_rank` and
  `get_search_terms`. Ask which brand and marketplace before pulling anything.
- **A filesystem.** Inputs are saved pulls read from disk and the report is
  written to disk. This is the one TrackIQ skill that needs it.
- **No third-party API and no network at run time.** A run is reproducible
  from its inputs.
- **Without the MCP:** the same saved exports work — Search Query
  Performance per week is required, keyword rank and paid search terms are
  optional.

## First run

Fill in a copy of `assets/account.example.md` saved as account.md beside the
skill. Every TrackIQ skill reads the same file, so an account already set up
for another TrackIQ report needs nothing added here.

1. **Brand and marketplace** — which account, and which TrackIQ connector
2. **Delivery** — in-chat, file, Slack, n8n or email

## Run it

Four steps. The scripts do the arithmetic; your job is the pulls and the reading.

### 1. Confirm which account you are on

If more than one TrackIQ connector is attached, they expose identical tool
names and nothing in a tool signature says which brand you are holding. The
server IDs are per-session and change between runs, so never pick by ID.

Call `set_context` (required first on each server, it fails closed), then
`list_marketplaces()`, and assert the account and brand name you expect. If no
connected server returns it, stop and say so rather than pulling someone else's
numbers — most tools will happily return another brand's data without erroring.

### 2. Pull the data

`assets/pulling-data.md` has the exact calls, their parameters, and the
quirks that will otherwise cost you a wrong answer. In short:

| File | Call | Required |
|---|---|---|
| one per week | `get_search_query_performance(by_product=True, asin=...)` | **yes** |
| rank | `get_keyword_rank(asin=..., limit=500)` | no |
| paid | `get_search_terms(ad_type="sp", asin=...)` | no |
| context | you write it (price, rating, cover, Buy Box) | no |

Pull **as many weeks as the feed holds**, not one. Two weeks is enough to
produce a verdict and not enough to trust it: a term can turn, and a rule
reading only recent data needs history behind it to say so. The ingestion is
irregular — some weeks simply do not exist — so probe backwards and take what
is there. Responses exceed the inline limit and get saved to a file; that is
the intended path, so read the saved file rather than re-pulling with a smaller
`limit`, which silently truncates.

### 3. Score

```bash
python assets/readiness.py --asin B0XXXXXXXX \
    --sqp week1.json --sqp week2.json --sqp week3.json \
    --rank rank.json --paid paid.json --context ctx.json \
    --brand "acme" --brand "acme labs" \
    --json scored.json
```

`--brand` takes the brand's own name and its common misspellings. Branded terms
sit at rank 1 and dominate most tracked sets, so left in they crowd out every
term worth spending on — and a ranking campaign is never funded on your own
name anyway. `--junk` drops query patterns the ad group wandered into that no
filter catches.

`--selfcheck` runs the engine's assertions, including four real conversion
series that each broke an earlier version of the rules.

### 4. Render

```bash
python assets/report.py --asin B0XXXXXXXX --sqp week1.json ... \
    --context ctx.json --brand "acme" --out report.html
```

One self-contained HTML file, no JavaScript, opens from disk and publishes
as-is. The TrackIQ wordmark ships in `assets/`. An Amazon marketplace mark
is not bundled and is not required — the renderer omits it silently. To add
your own, drop a file named marketplace-amazon.png into a
directory and pass `--assets` to brand it; without them the masthead sets the
wordmark in type, which is a deliberate fallback rather than a broken image.


### Without the scripts

`assets/readiness.py` and `assets/report.py` only do arithmetic and layout.
If the runtime cannot execute Python, the work is still doable by hand:
`assets/method.md` carries every threshold and the reasoning behind it, and
`assets/pulling-data.md` carries the exact pulls. Compute the conversion
ratio per query, apply the four verdicts in the table above, and present the
result as a table. The report is nicer; the decision is identical.

## Reading the output honestly

**Lead with what to do, not with the biggest number.** The NO-GO block usually
holds the largest pools on the page. That is the point of listing it.

**"Query worth" is measured, not projected.** It is the query's weekly market
purchases at the product's own price, annualised, alongside the share held
today. Resist turning that into a forecast: projecting a term to some share it
might reach needs a rank-to-share curve, and fitting one from a handful of
non-consecutive weeks produces numbers that look authoritative and are not. An
earlier version did exactly that and sized a real opportunity at $1,864 a year
when the query was worth $175,000; the error was invisible because the output
looked precise. Give the reader the pool and the current slice and let them
size it.

**A rank is a band, not a number.** A single term swings several places between
consecutive days, wider than most week-over-week moves anyone quotes, so the
report shows the range the term moved across and the engine uses the median.
Quote a move only if it clears that term's own spread.

**Stock and Buy Box gate everything.** Sponsored Products cannot serve without
the Buy Box, so a suppressed listing cannot be ranked at any price — the report
says so at the top when `buy_box_suppressed` is set. And a push that lands
before replenishment buys a stockout rather than a position, so thin cover is
called out. Put both in the context file.

## Delivery

The verdict list goes to the chat first. Delivery is the last step and the
method comes from the Delivery block in account.md — never ask per run.

| Method | What to do | Needs |
|---|---|---|
| `in-chat` | Return the verdict table and the HTML. The default and the fallback. | nothing |
| `file` | Write the report beside the skill, dated. | a filesystem |
| `slack` | Post the FUND and SEED lists as text, then upload the HTML. | a connected Slack tool |
| `n8n` | POST the HTML to the configured webhook, `Content-Type: text/html`. | network access |
| `email` | Hand it to the connected mail tool. | a connected mail tool |

Confirm before the first outward send of a session, fall back to in-chat
loudly when a method is unavailable, and never substitute a different
outward channel.

## What this deliberately does not do

It does not run the campaign, size the seeding drip, or edit the listing. It
decides **where** the spend should point. The next steps it hands you are a
keyword list and a reason.

It also does not name competitors: the search query report carries market
totals as anonymous aggregates and has no competitor ASIN field at all. If
someone asks who they are actually beating, that needs a live search-results
source on top, weighted by this same query set.

## Reference files

- `assets/account.example.md` — the first-run answers, filled in once
- `assets/logo-wordmark-dark.png` — the report wordmark

- `assets/pulling-data.md` — every call with parameters, and the data
  quirks that produce wrong answers if you do not know them. Read this before
  the first pull.
- `assets/method.md` — why each threshold is what it is, each traced to the
  wrong answer that produced it. Read this when a verdict looks wrong, before
  changing a constant.

## Version

`trackiq-amazon-rank-readiness` v1.0.0 (2026-09-18).

If the user asks whether this skill is current, fetch
`https://trackiq.com/skills/registry.json`, compare the `version` field for
`trackiq-amazon-rank-readiness`, and if it is newer, give them the download
link and the one-line changelog. Do not fetch at any other time.
