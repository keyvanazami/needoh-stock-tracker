# Phase 2 — teacher copy

Students build a trading client. Everyone runs the strategy in `ALGO.md`, so
the variable is the quality of their system, not their trading idea.

## Running it

```bash
java -jar xchg-server.jar --mm-interval 1000
```

One instance for the room. Everyone on the same server and the same `--link`
setting, so conditions are identical and only their code differs.

```bash
--cash 1000000       starting cash in cents (default: 10,000.00)
--inventory 200      starting shares of each symbol
--journal run.csv    every order and trade, by session, for marking
--no-dedup           stop recognising retries, to demonstrate what it was doing
--algo-vectors       the strategy's acceptance vectors
```

The market maker's re-quote interval is the pacing knob. At 1000ms any competent
client in any language reacts in time, so the exercise does not quietly become a
latency contest that punishes whoever chose Python. Lower it only if you want
that pressure.

## Two findings worth knowing before you set the marking

**P&L does not police correctness.** We measured a client that invents a new
`clOrdId` on every retry against one that retries properly, under
`--link flaky-acks`: the careless client booked roughly twice the volume and
finished about 50% ahead (+7250 against +4690), because the strategy is
profitable and it did twice as much trading. Mark on the scorecard, not the
leaderboard. The Deduped column is the honest signal: a correct client retrying
over a lossy link shows hundreds, a careless one shows zero.

The handout makes this the lesson rather than hiding it, which is the most
transferable thing in the phase.

**P&L does reward attention.** Over four seeds, a client dropping 60% of its
market data earned consistently less than an attentive one (around 3,900 against
5,300–6,900). So the leaderboard is meaningful for participation even though it
is useless for correctness.

## Why the prices move the way they do

The maker's mid follows a slow cycle plus noise rather than a random walk. This
is deliberate and it took a few attempts to get right:

- Against a **random walk**, the strategy has no edge and just pays the spread.
  A client that traded less scored higher — the exact opposite of the intent.
- Publishing a **QUOTE on every book change** was worse still. The quote rate
  then depends on how much you trade, so a busy client's 20-sample average spans
  less wall-clock time than a quiet one's, and its view is worse. A client
  dropping 60% of its data beat an attentive one on all five seeds.

Market data is now a steady periodic feed on the maker tick, and the mid has a
real cycle to capture. If you change either, re-run the attention check before
you use it with a class, or the incentives may silently invert again.

## What to look for when marking

| | |
|---|---|
| strategy matches `--algo-vectors` | they implemented the rule, not their own |
| Deduped > 0 under `flaky-acks` | retries are idempotent |
| their position equals `ACCOUNT` | they can say what they own |
| Rejects and Funds columns near zero | their accounting tracks the exchange's |
| Gaps near zero | they are reading the socket, not blocking |

P&L is the headline and the motivator. The five rows above are the grade.
