# The trading rule

Everyone trades the same way on purpose. The point of this phase is the system
you build around the strategy rather than the strategy itself, so the rule below
is fixed, and the three numbers in it are not yours to adjust.

The rule keeps a moving average of the last **twenty** mid prices for each
symbol. When the current mid falls more than **two** cents below that average,
it buys **ten** shares; when the mid rises more than two cents above it, it
sells ten. The rest of the time it does nothing.

In full, for every `QUOTE` that arrives:

```
if bid or ask is zero:          do nothing      one-sided book, not tradeable
mid = (bid + ask) / 2                           integer division
append mid to that symbol's window, keeping the last 20
if the window holds fewer than 20:  do nothing  still warming up
sma = sum(window) / 20                          integer division
if   mid < sma - 2:             BUY  10 at the ask
elif mid > sma + 2:             SELL 10 at the bid
else:                           do nothing
```

Each symbol keeps its own separate window.

Both of those divisions **floor**, so do the whole thing in integer arithmetic
and your answers will be identical to everybody else's. This is the single most
common place for two implementations to disagree: in floating point the moving
average will drift a fraction of a cent away from the integer one, and every so
often that fraction is enough to change a decision.

The orders are marketable limits, which is to say that buying at the current ask
and selling at the current bid both cross the spread and fill straight away.

Before you send anything, check you can afford it. A buy you have no cash for,
and a sell of stock you do not hold, are both rejected, and rejections count
against you.

## Checking your implementation

```bash
java -jar xchg-server.jar --algo-vectors
```

This prints a fixed sequence of quotes with the decision a correct
implementation makes beside each one, in the same spirit as the checksum test
values in Phase 1. Feed those quotes to your strategy and compare the two
columns. A correct implementation produces **five buy and six sell decisions
across the thirty-four quotes**, so if your totals come out differently you have
diverged somewhere, and integer division is where to look first.

## Why the rule makes money

The market maker's price follows a slow cycle with a little noise on top, so a
price that has fallen well below its own recent average does genuinely tend to
come back up.

That is a deliberately artificial world, and it is worth knowing why we built it
that way. The strategy needs a real edge for this exercise to work, because only
then does missing market data actually cost you something. If prices simply
wandered at random, the same rule would pay the spread over and over and slowly
lose money, and the best-scoring client in the room would be whichever one
traded least — which would teach nobody anything.

So the edge is there to be captured. How much of it you actually capture depends
on your client, and that is the part being assessed.
