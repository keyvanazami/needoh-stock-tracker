"""Price-time priority limit order book and matching engine.

One book per symbol. The rules are the ones a real venue uses, reduced to the
smallest set that still produces arguments in class:

  * Best price wins. Highest bid and lowest ask sit at the top.
  * At equal price, earliest arrival wins. This is why the sequence number is
    assigned on arrival at the gateway and never re-ordered afterwards.
  * An incoming order that crosses executes immediately against resting
    orders, taking each in priority order, at the RESTING order's price --
    the passive side gets the price improvement. Any remainder rests.

That last rule is worth a lecture on its own: it is why sending a marketable
limit order is not the same as sending a market order, and why latency is
worth money -- the resting order that got there first sets the price.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field

BUY, SELL = 0, 1


@dataclass
class Order:
    firm: int
    side: int
    px: int                 # price in cents
    qty: int
    coid: int               # client order id, unique per firm
    seq: int = 0            # arrival sequence, assigned by the gateway
    ticker: str = "NDOH"


@dataclass
class Fill:
    ticker: str
    px: int
    qty: int
    buy_firm: int
    sell_firm: int
    buy_coid: int
    sell_coid: int
    seq: int = 0


class Book:
    def __init__(self, ticker: str = "NDOH") -> None:
        self.ticker = ticker
        self.bids: list[Order] = []      # sorted: px desc, seq asc
        self.asks: list[Order] = []      # sorted: px asc,  seq asc
        self._seq = itertools.count(1)
        self.trade_count = 0
        self.volume = 0

    # --- top of book -------------------------------------------------------
    def best_bid(self) -> int | None:
        return self.bids[0].px if self.bids else None

    def best_ask(self) -> int | None:
        return self.asks[0].px if self.asks else None

    def qty_at(self, side: int, px: int | None) -> int:
        if px is None:
            return 0
        side_list = self.bids if side == BUY else self.asks
        return sum(o.qty for o in side_list if o.px == px)

    def depth(self, levels: int = 5) -> dict:
        def agg(orders, reverse):
            out: dict[int, int] = {}
            for o in orders:
                out[o.px] = out.get(o.px, 0) + o.qty
            return sorted(out.items(), reverse=reverse)[:levels]
        return {"bids": agg(self.bids, True), "asks": agg(self.asks, False)}

    # --- mutation ----------------------------------------------------------
    def submit(self, o: Order) -> list[Fill]:
        """Match `o` against the book, resting any remainder. Returns fills."""
        if o.qty <= 0 or o.px <= 0:
            raise ValueError("price and quantity must both be positive")
        o.seq = next(self._seq)
        o.ticker = self.ticker
        fills: list[Fill] = []
        opposite = self.asks if o.side == BUY else self.bids

        while o.qty > 0 and opposite:
            best = opposite[0]
            crosses = best.px <= o.px if o.side == BUY else best.px >= o.px
            if not crosses:
                break
            traded = min(o.qty, best.qty)
            # the RESTING order's price -- passive side keeps its price
            buy_o, sell_o = (o, best) if o.side == BUY else (best, o)
            fills.append(Fill(self.ticker, best.px, traded,
                              buy_o.firm, sell_o.firm, buy_o.coid, sell_o.coid,
                              next(self._seq)))
            o.qty -= traded
            best.qty -= traded
            self.trade_count += 1
            self.volume += traded
            if best.qty == 0:
                opposite.pop(0)

        if o.qty > 0:
            self._rest(o)
        return fills

    def _rest(self, o: Order) -> None:
        if o.side == BUY:
            self.bids.append(o)
            self.bids.sort(key=lambda x: (-x.px, x.seq))
        else:
            self.asks.append(o)
            self.asks.sort(key=lambda x: (x.px, x.seq))

    def cancel(self, firm: int, coid: int) -> bool:
        for side_list in (self.bids, self.asks):
            for i, o in enumerate(side_list):
                if o.firm == firm and o.coid == coid:
                    side_list.pop(i)
                    return True
        return False

    def snapshot(self) -> dict:
        bb, ba = self.best_bid(), self.best_ask()
        return {
            "ticker": self.ticker,
            "bid": bb, "bid_qty": self.qty_at(BUY, bb),
            "ask": ba, "ask_qty": self.qty_at(SELL, ba),
            "last": None, "trades": self.trade_count, "volume": self.volume,
        }
