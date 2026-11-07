# The trading rule

Everyone in the class trades using the rule described here, and the three
numbers in it are fixed. That is deliberate: this phase is about the system you
build around a strategy, not about inventing a better strategy, so we have taken
the trading idea off the table entirely and left you with the engineering.

If the words *bid*, *ask*, *spread* or *mid* are unfamiliar, read `TRADING.md`
first. The rest of this assumes them.

## The idea behind it

The strategy is a **mean reversion** strategy, which is a bet that prices which
have moved unusually far from their recent average tend to come back towards it.

The reasoning, in the abstract, goes like this. A price wanders around for all
sorts of reasons, some of which reflect genuine news about what a thing is worth
and some of which are just noise — a large seller who needed to sell today, a
brief imbalance of buyers and sellers. If a move is noise, it should fade, and
the price should drift back towards where it has been sitting. So when something
looks unusually cheap compared to its own recent history, you buy it, and when
it looks unusually dear, you sell.

Whether that is true of real markets is a long argument and mostly it is not,
which is why real mean-reversion strategies are considerably more careful than
this one. But it is comfortably true of the prices on our exchange, for reasons
explained at the end.

To use the idea you need to answer two questions: what counts as "its recent
average", and how far from it is "unusually far". This rule answers the first
with a **moving average** — the mean of the last twenty mid prices, recomputed
every time a new quote arrives, so it slides along as new data comes in and old
data falls off the end. It answers the second with a fixed threshold of two
cents.

## The rule

Keep a window of the last twenty mid prices for each symbol, separately. When a
new `QUOTE` arrives, work out the mid, add it to that symbol's window, and then
compare the current mid to the average of the window. If the mid is more than
two cents below the average, buy ten shares. If it is more than two cents above,
sell ten. Otherwise do nothing.

Written out exactly:

```
if bid or ask is zero:              do nothing      one side of the book is empty
mid = (bid + ask) / 2                               integer division
append mid to that symbol's window, keeping the last 20
if the window holds fewer than 20:  do nothing      still warming up
sma = sum(window) / 20                              integer division
if   mid < sma - 2:                 BUY  10 at the ask
elif mid > sma + 2:                 SELL 10 at the bid
else:                               do nothing
```

`sma` stands for simple moving average, "simple" meaning every sample in the
window counts equally.

Both of those divisions **floor**, so do all of it in integer arithmetic. This
is the single most common reason two implementations disagree: in floating point
the average drifts a fraction of a cent away from the integer one, and every so
often that fraction is enough to flip a decision.

Note which price you send. Buying, you use the **ask**, because that is the
price somebody is actually willing to sell to you at, and your order fills
immediately. Selling, you use the **bid**. Both are marketable orders that cross
the spread, so you always know straight away whether you traded, which keeps
your client much simpler than it would be if you were resting orders and waiting.

The threshold of two cents is not arbitrary. Because you cross the spread in
both directions, a round trip costs you the spread, so a rule that fired on
every tiny wobble would trade constantly and pay that cost over and over. The
threshold makes the rule wait for a move big enough to be worth paying for.

## A worked example

Run `--algo-vectors` and the server prints a fixed sequence of quotes with the
decision a correct implementation makes beside each one. The interesting part
starts once the window is full:

```
tick    bid    ask    mid    sma   decision
  22    293    297    295    299   BUY  10 @ 297
  23    291    295    293    299   BUY  10 @ 295
  ...
  28    298    302    300    297   SELL 10 @ 298
  29    302    306    304    297   SELL 10 @ 302
```

At tick 22 the mid is 295 while the average is still 299, four cents higher, so
the price counts as cheap and the rule buys — paying 297, the ask, not the mid.
The price keeps falling for a few ticks and the rule keeps buying. Then it turns
and climbs. By tick 28 the mid has reached 300 while the average has fallen to
297, so now it counts as dear and the rule sells at the bid.

Across the whole sequence it buys 50 shares at an average of 294.2 and sells 60
at an average of 304.0 — selling, on average, 9.8 cents a share higher than it
bought. That gap, repeated, is where the money comes from. Note that it sold ten
more shares than it bought, which it could only do because it started with
inventory; this is why you are given 200 shares of each symbol rather than only
cash.

## Why it works here

The market maker's price does not wander at random. It follows a slow cycle with
a little noise on top, so a price that has fallen well below its own recent
average really does tend to come back up, and the rule really does have an edge.

That is artificial and it is worth knowing why we built it that way. The
strategy needs to be genuinely profitable for this exercise to mean anything,
because only then does failing to read your market data properly cost you
something. If prices simply wandered at random, this rule would pay the spread
over and over and slowly lose money, and the highest-scoring client in the room
would be whichever one managed to trade the least — which would teach nobody
anything useful.

So the edge is there. How much of it you actually capture depends on whether
your client reads every quote, places its orders correctly, keeps accurate track
of what it owns, and survives a bad network. That is the part being assessed.

## Check your implementation before you connect

```bash
java -jar xchg-server.jar --algo-vectors
```

Feed those quotes into your strategy and compare its decisions against the
printed ones, line by line. A correct implementation produces **five buys and
six sells across the thirty-four quotes**. If your totals differ, you have
diverged somewhere, and integer division is the first thing to check.

Do this before you write any networking code. Debugging a trading rule and a
UDP client at the same time is thoroughly unpleasant, and half an hour spent
here will save you an evening later.

## Before you send an order

Check you can afford it. A buy you have no cash for, and a sell of shares you do
not hold, are both rejected, and rejections count against you in the marking.
Working out why you have less free cash than you expected is a large part of
this phase, and `PROTOCOL-PHASE2.md` explains the mechanism that usually catches
people out.
