# COM2512 Phase 2 — a trading client

In Phase 1 you got bytes onto the wire. Now you build something that uses them:
a client that listens to market data, decides, trades, and keeps track of its
own money.

Everybody runs the same strategy, written out in [`ALGO.md`](ALGO.md). Nobody is
competing on the trading idea. What differs between you is the quality of the
system around it, and that is what the leaderboard will end up measuring.

**Submit:** your client source and screenshots. No write-up.

## What's new since Phase 1

You have an account. The exchange gives you cash and stock when you connect,
tells you your balances in a new `ACCOUNT` message, and checks every order
against them. It also now recognises a retried order by its `clOrdId` instead of
booking it twice. The wire details are in
[`PROTOCOL-PHASE2.md`](PROTOCOL-PHASE2.md); the envelope, the CRC and everything
else from `PROTOCOL.md` are unchanged, so your Phase 1 encoder still works.

## 1. Get the strategy right first

```bash
java -jar xchg-server.jar --algo-vectors
```

Feed those quotes to your strategy implementation and check its decisions match
the printed ones, before you connect to anything. You should see 5 BUY and 6
SELL decisions over the 34 quotes. It is much easier to debug a strategy on its
own than to debug a strategy and a socket at the same time.

## 2. Trade

Connect, subscribe, and run the strategy on every `QUOTE` that arrives. When it
says BUY or SELL, send the order and handle the `ACK`.

Keep your own running tally of cash and of each position, updating it as fills
come in. The exchange pushes you an `ACCOUNT` message as well — treat that as
the truth, compare it against your own numbers, and notice when the two drift
apart. Drift means you have mishandled something, usually a partial fill or a
reservation.

Watch yourself appear on the leaderboard in the UI as you go.

## 3. Then make it survive a bad link

```bash
java -jar xchg-server.jar --link flaky-acks
```

Your orders reach the book, but a lot of the `ACK`s do not come back. Resend
anything you have not heard about — **with the same `clOrdId`**, so the exchange
recognises it as the order you already sent rather than booking a second one.
Measure your round trip with `PING` and set your timeout from that, backing off
when retries keep failing. A tight retry loop will hit the 200 packets per
second limit.

You can tell which happened from the `ACK`: the same `orderId` coming back means
the exchange recognised your retry, a new one means you just traded twice.

## 4. The uncomfortable bit

Run the same test with a client that invents a fresh `clOrdId` for every retry,
and look at the leaderboard.

It will probably be **ahead of you**. We measured it: the careless client booked
roughly twice the volume and finished about 50% better off, because the strategy
makes money and doing twice as much of it makes twice as much money — right up
until the market turns, or you run out of cash, or somebody asks what you
actually own.

This is the point of the exercise. **P&L is not a correctness metric.** A
trading system that cannot say what it owns is broken whether or not it happens
to be up today, and real firms have discovered this expensively. The leaderboard
is there to make you care; it is not what you are marked on.

## Submit

```
<your-id>-phase2/
  <your client source>
  README.md          one paragraph: language, how to run it
  screenshots/
```

Four screenshots:

1. Your strategy's decisions beside `--algo-vectors`, matching.
2. The leaderboard with you on it, after a clean run.
3. A clean run of `--link flaky-acks`: your Deduped count above zero, which is
   the exchange telling you your retries were recognised.
4. Your client's own cash and positions next to the exchange's `ACCOUNT`
   figures, agreeing exactly, at the end of that run.

Screenshot 4 is the one that matters most. Anyone can make money by accident.

## When it goes wrong

| symptom | what's probably happening |
|---|---|
| decisions don't match `--algo-vectors` | floating point somewhere; both divisions floor |
| nothing happens for the first 20 quotes | correct — the window is still filling |
| rejects with reason 8 | your free cash is less than you think; resting buys reserve theirs |
| rejects with reason 9 | you are selling stock a resting sell has already set aside |
| Deduped stays 0 under `flaky-acks` | your retries carry a new `clOrdId` each time |
| your position drifts from `ACCOUNT` | partial fills, or counting an order as filled when it only rested |
| `E_RATE` | retrying too fast, no backoff |
| session disappears mid-run | you stopped sending `PING` |
