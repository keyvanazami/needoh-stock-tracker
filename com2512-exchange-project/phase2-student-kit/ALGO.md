# The Phase 2 strategy

Everyone trades the same way on purpose. The point of this phase is the system
you build around the strategy, not the strategy itself, so the rule below is
fixed and the constants are not yours to tune.

```
WINDOW = 20      mids in the moving average
BAND   = 2       cents away from the average before you act
SIZE   = 10      shares per order
```

On every `QUOTE` for a symbol:

```
if bid == 0 or ask == 0:        do nothing      one-sided book
mid = (bid + ask) / 2                           integer division
append mid to that symbol's window, keep the last WINDOW
if the window is not full:      do nothing      still warming up
sma = sum(window) / WINDOW                      integer division
if   mid < sma - BAND:          BUY  SIZE at ask
elif mid > sma + BAND:          SELL SIZE at bid
else:                           do nothing
```

Each symbol keeps its own window. Both divisions **floor** — use integer
arithmetic throughout and the result is identical in any language. Floating
point is the usual reason two implementations disagree.

Orders are marketable limits: a BUY at the current ask and a SELL at the current
bid cross the spread and fill immediately.

Before you send, check you can afford it. A BUY you have no cash for and a SELL
of stock you do not hold are both rejected, and rejects count against you.

## Check yourself before you trade

```bash
java -jar xchg-server.jar --algo-vectors
```

That prints a fixed quote sequence and, beside it, the decision a correct
implementation makes at each tick — the same idea as the CRC check values in
Phase 1. Feed those quotes to your strategy and compare column by column. A
correct implementation produces **5 BUY and 6 SELL decisions across the 34
quotes**. A different total means you have diverged, and integer division is
nearly always the culprit.

Do this first. Debugging a strategy and a network client at the same time is
miserable, and the vectors take it off the table.

## Why it makes money

The market maker's mid follows a slow cycle with noise on top, so a price well
below its own recent average does tend to come back. That is a deliberately
synthetic world: it exists so that the strategy has a real edge, which in turn
means that **missing market data costs you money**. Against a pure random walk
the same rule would simply pay the spread forever, and the highest-scoring
client would be the one that traded least — which would teach you nothing.

So the edge is there to be captured. How much of it you actually capture depends
on your client, and that is the part being assessed.
