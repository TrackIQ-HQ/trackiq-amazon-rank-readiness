# Why the rules are what they are

Every threshold in `readiness.py` exists because a simpler version of it
produced a wrong answer on real data. Read the relevant entry before changing a
constant — most of these look arbitrary until you know what they are guarding
against, and several are tempting to "simplify" straight back into the bug.

## Contents

- [The verdict reads the recent window, not all history](#the-verdict-reads-the-recent-window-not-all-history)
- [Median, not minimum](#median-not-minimum)
- [Ten clicks to read a week, two weeks to reach a verdict](#ten-clicks-to-read-a-week-two-weeks-to-reach-a-verdict)
- [Parity is not a loss](#parity-is-not-a-loss)
- [The pool, not a projected capture](#the-pool-not-a-projected-capture)
- [Consideration beats a word list](#consideration-beats-a-word-list)
- [Branded terms are excluded](#branded-terms-are-excluded)
- [Rank is a band](#rank-is-a-band)
- [The traps are listed on purpose](#the-traps-are-listed-on-purpose)

## The verdict reads the recent window, not all history

`RECENT_WEEKS = 3`

The original rule was "out-converts the market in **every** readable week". It
is the obvious rule and it is wrong, because terms turn.

A real series, one term's conversion as a ratio of the market's, oldest first:

```
0.74  0.68  1.02  0.82  0.88  |  1.30  1.16
```

Five losing weeks, then two clear wins. Under "every week must win" that term
was fundable on two weeks of data and a **trap** on seven. A rule that gets
worse as the evidence improves is not a strict rule, it is a broken one.

So the verdict comes from the recent window and the whole series is carried as
trend. The engine reports "improving" or "deteriorating" by comparing the
window against everything before it, which is the thing an operator actually
needs: not just whether a term converts, but which way it is going.

## Median, not minimum

Taking the minimum of the recent window lets one soft week veto a verdict. On
the series above, the window is `0.88, 1.30, 1.16` — the minimum reads 0.88 and
calls it a loss, while the median reads 1.16 and calls it a win. The median is
right here: weekly conversion on a few dozen clicks is noisy enough that a
single reading should not decide anything.

The median separates all three real cases correctly where the minimum did not:

| Series (recent window) | Median | Verdict |
|---|---|---|
| 0.88, 1.30, 1.16 | 1.16 | holds |
| 1.09, 1.24, 0.98 | 1.09 | parity |
| 0.42, 0.47, 0.60 | 0.47 | will not hold |

## Ten clicks to read a week, two weeks to reach a verdict

`MIN_CLICKS = 10`, `MIN_READS = 2`

A one-click week that converts reports a 100% conversion rate, which would top
every ranking ever produced. Ten clicks is the floor for a week to count at all.

Two readable weeks is the floor for a verdict. This one was learned late: a
term was reported as the single best opportunity on a listing on the strength
of **one** week at exactly ten clicks — three orders. Pulling five more weeks
did not strengthen it, because the term never cleared ten clicks again, and
that absence was itself the finding: the listing barely gets clicks there. It
is a term to test, not to fund.

## Parity is not a loss

`PARITY_BAND = 0.10`

A term reading 0.98x of the market has not lost. On the largest query one real
listing had, the series ran 1.09, 1.24 and then 0.98 on nearly 900 clicks — a
0.3 percentage point miss. Calling that a term that cannot hold rank would have
discarded the biggest addressable query on the page; calling it a win would
have overstated it. It is parity: the position holds its ground and earns no
structural advantage, which is a real and distinct answer.

## The pool, not a projected capture

Earlier versions projected each term to the purchase share the listing already
held on comparable terms it ranked top-10 for, and reported the gap as the
prize. The output looked authoritative and was not.

The anchor came to 6.2%, dominated by one high-volume term where the listing
sat at rank 7 with 5.9% share. But position 7 on a huge query takes a small
slice and position 2 takes a large one, so bucketing ranks 1 to 10 together
implied rank barely mattered. It sized a $175,562-a-year query at **$1,864**.

Worse, the anchor was unstable in a way that was invisible: its median moved
from 11.1% to 5.9% the moment the volume floor for membership rose from 20
purchases to 50, because two members were tiny denominators — "11.1%" was three
purchases out of 27. The statistic was an artefact of its own threshold.

Fitting a real rank-to-share curve needs far more data than a handful of
non-consecutive weeks. So the engine reports what is measured: the query's
annual value at the product's own price, and the share held today. A reader
sizes the prize from that without anyone inventing an elasticity.

## Consideration beats a word list

`CONSIDERED = 0.50`, `MIN_IMPRESSIONS = 100`

Ad groups wander into queries the product has no business on, and those queries
can carry enormous market volume. Ranked by pool alone, a patio-lighting
listing's shortlist led with "outdoor wedding decor", "christmas lights",
"party decorations" and "solar garden stakes" —
several million dollars of annual purchases apiece.

The first fix was a word list, which has to be rewritten per brand and still
misses the next oddity. The measured version travels: if shoppers searching a
term click the listing at under half the market's rate, they are saying it is
not the product they came for, so there is no position there worth buying at
any price. And if the listing takes under 100 impressions a week on a term,
there is no position to read at all — that is a much larger decision than
testing a position already held.

Where something still slips through, `--junk` takes brand-specific patterns.
That is config, not a rule, which is the right place for a judgement call.

## Branded terms are excluded

A ranking campaign is never funded on the brand's own name. Branded terms also
dominate most tracked keyword sets and sit at rank 1, so left in they crowd out
every term worth spending on — one listing's shortlist was 21 branded terms
against 26 genuine candidates, and the branded ones sorted to the top on rank.

Pass every variant with `--brand`, including common misspellings, since the
report contains whatever shoppers typed.

## Rank is a band

A single term swings several places between consecutive days — wider, on
measured data, than almost every week-over-week rank move anyone quotes. One
report shipped an open question about a listing's rank "declining" that
evaporated when measured against the band of intervening days instead of one
reference day: the move was flat.

So the engine reads every tracked day in the window and reports the median with
the range, and the report draws the range as a band with the current position
as a dot on it. Quote a move only if it clears that term's own spread.

Two mechanical traps in the rank data. Every (keyword, ASIN) usually returns
**twice**, once per SKU, including an `..._FBM` row with an identical rank — so
dedupe on (keyword, date) or every band doubles its sample. And the number of
tracked terms moves between days: a term appearing today and not last week may
be newly tracked rather than newly ranked, so it is not a placement anyone won.

## The traps are listed on purpose

`NOGO_MIN_POOL = 50000`

The NO-GO block usually holds the largest pools on the page — one listing's
worst term carried $18.4M a year at 0.47x the market's conversion. Dropping
them would leave the reader to rediscover them, and their size is exactly what
makes them tempting. They are listed with their pools and their losing ratios
so the case against them is visible.

Below the floor they stop being a temptation and become noise, so small traps
are counted rather than listed.
