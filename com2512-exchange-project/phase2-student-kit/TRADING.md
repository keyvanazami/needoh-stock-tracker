# A short introduction to trading

This phase assumes no prior knowledge of financial markets. If you already know
what a bid-ask spread is you can skip this and go straight to `ALGO.md`.
Otherwise, read this once. It explains the dozen or so words you will meet in
the rest of the kit, and none of it is complicated.

## What an exchange actually does

An exchange is a matching engine. People send it offers to buy and offers to
sell, and when a buyer is willing to pay at least what a seller is asking for,
the exchange matches them and a **trade** happens. That is the whole job. It
does not own anything, it does not decide what things are worth, and it has no
opinion about whether you are making a good decision.

The four things being traded here are called **symbols**, and they have tickers
like AAPL and MSFT borrowed from real companies. They are not real; they are
just four things whose prices move.

## The order book

Everything waiting to be matched sits in the **order book**. It has two sides.

The **bid** side holds everyone who wants to buy, sorted so that the highest
price is at the top. The **ask** side — also called the **offer** side — holds
everyone who wants to sell, sorted so that the lowest price is at the top. The
best bid and the best ask together are called the **top of book**, and they are
what the exchange sends you in a `QUOTE` message.

The highest anyone will pay is always lower than the lowest anyone will accept,
because if that stopped being true the two would have matched and the orders
would be gone. So there is always a gap between the best bid and the best ask,
and that gap is called the **spread**.

Halfway between them is the **mid price**, or just the mid. Nobody is actually
trading at the mid — it is a convenient single number for "roughly what this is
worth right now", and it is what the strategy in this phase pays attention to.

A worked example, using numbers you will actually see. If the best bid is 299
and the best ask is 301, then the spread is 2 cents and the mid is 300. You can
sell immediately at 299 or buy immediately at 301, but you cannot do either at
300.

## The spread is a cost, and this matters

Look at those numbers again. If you buy at 301 and immediately sell at 299, you
have lost 2 cents a share and nothing happened in between. That is not a fee and
nobody charged you: it is simply that buying and selling happen at different
prices.

The exchange's spread is 2 cents by default, so that is what a round trip costs
you per share. The test data printed by `--algo-vectors` uses a wider spread of
4 cents, which is why the numbers there look different from the ones on your
screen; it does not change anything about how the rule works.

This is the single most important idea in the phase. Every time you buy and
later sell, you pay the spread, so the price has to move in your favour by more
than the spread before you have actually made anything. A strategy that trades
constantly without an edge does not break even — it bleeds.

## Orders

An order says what you want to do: buy or sell, which symbol, how many shares,
and at what price. The price is a **limit**, meaning the worst price you are
willing to accept. A buy limit of 302 means "buy, but pay no more than 302". A
sell limit of 298 means "sell, but accept no less than 298". There is no way to
say "just trade at whatever the price is" — every order here has a limit.

What happens next depends on your price. If your buy limit is at or above the
best ask, there is somebody on the other side you can trade with right now, and
you trade immediately. An order priced to do that is called **marketable**, and
doing it is called **crossing the spread**, because you have reached over the
gap to the other side.

If your price is not good enough to match anything, your order joins the book
and waits. An order sitting in the book like that is **resting**. It stays there
until somebody trades with it, you cancel it, or your session disappears.

When your order trades, that is a **fill**. If only some of it trades — you
wanted 10 shares but only 4 were available at your price — that is a **partial
fill**, and the other 6 rest in the book waiting. Partial fills are a common
source of bugs, because it is easy to write code that assumes an order either
happened or did not.

Of the two sides of any trade, the one that was already resting in the book is
the **passive** side, and the one that arrived and crossed the spread to hit it
is the **aggressor**. The trade happens at the resting order's price: the
passive side set the terms and the aggressor accepted them. That is why, if you
send a buy with a limit of 600 into a book whose best ask is 302, you pay 302
and not 600. Your limit is the worst you will accept, not what you offer to pay.

## Positions, cash, and what you are worth

How much of a symbol you hold is your **position**. Holding some is being
**long**. Holding a negative amount — having sold things you never owned — is
being **short**, and it is not allowed here: you can only sell what you actually
have. In this phase you start with 200 shares of each symbol and a million cents
of cash, which is ten thousand pounds.

**Settlement** is the moment the exchange actually moves the money and the
shares. In real markets this happens a day or two after the trade; here it
happens instantly, as part of the trade itself.

To say how you are doing, you need a single number combining cash and shares,
and the usual one is **mark to market**: value every share you hold at the
current price, and add your cash. If you hold 200 AAPL at 300 and have 10,000
pounds, you are worth 10,000 + 600 = 10,600 pounds. **P&L** — profit and loss —
is simply that number compared against what you started with. It goes up when
your trades were good and down when they were not, and it is what the
leaderboard ranks you by.

## The market maker

There is a bot built into the exchange called a **market maker**. It constantly
posts both a bid and an ask on every symbol, so that there is always somebody to
trade with even when nobody else is connected.

Real markets have these too, and the deal is the same: the market maker is
willing to take the other side of your trade whenever you want, and in exchange
it collects the spread from everybody who crosses it. It is where your orders
will mostly end up going, especially early on.

## This is a simplified world

Worth saying plainly. There are no fees, no taxes, no borrowing, no dividends,
no auctions at the open and close, no hidden orders, and nobody is trying to
work out what you are doing and trade ahead of you. The prices are generated by
a formula rather than by anybody's opinion about anything.

None of that changes the mechanics you are learning, which are real: books,
spreads, limits, fills, positions and settlement all work this way. But do not
leave this module thinking you now know how to trade.
