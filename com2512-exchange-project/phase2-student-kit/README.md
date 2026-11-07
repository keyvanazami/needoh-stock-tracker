# COM2512 Phase 2 — writing a trading client

In Phase 1 you got bytes onto the wire. In this phase you build something that
does a job with them: a client that listens to the market, decides whether to
buy or sell, places orders, and keeps track of its own money while it does so.

Everybody trades using exactly the same rule, which is written out in
`ALGO.md`. Nobody is competing on having a cleverer idea about markets. What
will differ between you is how well your client is built, and that is what the
leaderboard ends up measuring.

**If you have never looked at a financial market before, start with
`TRADING.md`.** It is a short read and it explains every term the rest of the
kit uses — what an order book is, what the bid and the ask are, why the gap
between them costs you money, and what it means to hold a position. None of it
is difficult, but the rest of this will be heavy going without it.

Hand in your source code and some screenshots. There is no report.

## What has changed since Phase 1

You now have an account. When you connect, the exchange gives you some cash and
a holding in each symbol, tells you what they are in a new `ACCOUNT` message,
and checks every order you send against them. It has also started recognising
when you resend an order, so that a retry no longer gets booked twice.

`PROTOCOL-PHASE2.md` explains both of those properly. Everything else about the
wire format is unchanged — same envelope, same checksum, same validation rules —
so the encoder you wrote in Phase 1 still works exactly as it did.

## Start with the strategy, on its own

The rule is a mean reversion strategy: it watches each symbol's price against
its own recent average, buys when the price looks unusually cheap, and sells
when it looks unusually dear. `ALGO.md` explains the thinking behind it, walks
through a worked example, and then states it precisely.

Before you connect to anything, implement it and check it against the test
data:

```bash
java -jar xchg-server.jar --algo-vectors
```

That prints a sequence of quotes together with the decision a correct
implementation makes at each one. Feed the same quotes into your own code and
compare. You should end up with five buy decisions and six sell decisions across
the thirty-four quotes; if your totals differ, something in your implementation
has diverged, and the cause is nearly always floating-point arithmetic where the
rule calls for integer division.

Do this first. Debugging a trading strategy and a network client at the same
time is thoroughly unpleasant, and half an hour here will save you an evening
later.

## Then trade with it

Connect as you did in Phase 1, and run your strategy over every `QUOTE` that
arrives. When it tells you to buy or sell, send the order and deal with the
`ACK` that comes back.

While that is going on, keep your own running total of how much cash you have
and how much of each symbol you hold, updating it as fills arrive. The exchange
also pushes you an `ACCOUNT` message whenever your balances change. Treat that
as the truth, compare it against your own figures, and pay attention when the
two stop agreeing — a drift between them means you have mishandled something,
usually a partial fill, or an order that merely rested when you recorded it as
filled.

You should see yourself appear on the leaderboard on the web page as you go.

## Then make it survive a bad connection

```bash
java -jar xchg-server.jar --link flaky-acks
```

Your orders still reach the exchange and still execute, but a lot of the
acknowledgements never make it back to you. Resend anything you have not heard
about — and resend it carrying **the same `clOrdId` as the original**, so that
the exchange recognises it as the order you already sent rather than treating it
as a fresh one.

Work your timeout out from the round trip you actually measure, using `PING`,
rather than picking a number, and back off when retries keep failing. A retry
loop with no delay in it will quickly hit the two-hundred-packets-a-second limit
and start collecting `E_RATE` errors.

You can tell which of the two things happened from the `ACK`. If the order id
that comes back is the one you saw the first time, the exchange recognised your
retry. If it is a new one, you have just bought the same thing twice.

## The uncomfortable part

Now run that same test alongside a client that invents a fresh `clOrdId` every
time it retries, and look at the leaderboard.

The careless client will quite possibly be **ahead of you**. We measured it: it
booked roughly twice as much volume and finished about fifty per cent better
off, for the simple reason that the strategy makes money and doing twice as much
of it makes twice as much money. That holds right up until the market turns, or
it runs out of cash, or somebody asks it what it actually owns.

This is the point of the whole phase, so it is worth sitting with. **Profit is
not a measure of correctness.** A trading system that cannot tell you what it
holds is broken whether or not it happens to be up on the day, and firms have
discovered this at enormous expense. The leaderboard exists to make you care
about getting fills; it is not what you are marked on.

## What to hand in

Put your source in a folder named after your student id, with a short
`README.md` saying what language you used and how to run it, and four
screenshots.

The first should show your strategy's decisions next to the output of
`--algo-vectors`, matching. The second should show the leaderboard with you on
it after a clean run. The third should be a run against `--link flaky-acks` with
your **Deduped** count above zero, which is the exchange confirming that it
recognised your retries. The fourth, and the one that matters most, should show
your client's own idea of its cash and positions next to the exchange's
`ACCOUNT` figures, agreeing exactly, at the end of that run.

Anyone can make money by accident. The fourth screenshot is the one that shows
you built something trustworthy.

## If it will not work

If your decisions do not match `--algo-vectors`, look for floating-point
arithmetic. Both divisions in the rule floor, and doing them in floating point
will give you a different answer every few quotes.

If nothing happens for the first twenty quotes, that is correct — the moving
average needs twenty samples before it will say anything.

Orders rejected with reason 8 mean you have less free cash than you think, which
usually means you have forgotten that a resting buy order sets its cash aside
the moment it is accepted rather than when it fills. Reason 9 is the same
problem on the other side: you are trying to sell shares that a resting sell
order has already spoken for.

If your **Deduped** count stays at zero while you are running against
`flaky-acks`, your retries are going out with a new `clOrdId` each time, and the
exchange is booking every one of them as a new order.

If your position drifts away from the one in `ACCOUNT`, suspect partial fills
first, and then look for places where you count an order as filled when the
`ACK` actually said it was resting.

And as in Phase 1, `E_RATE` means you are retrying too fast, and a session that
vanishes mid-run means you stopped sending `PING`.
