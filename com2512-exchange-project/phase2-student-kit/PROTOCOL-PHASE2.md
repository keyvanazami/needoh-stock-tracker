# XCHG/1 — what Phase 2 adds

Everything in `PROTOCOL.md` still holds: same envelope, same CRC, same
validation order. This is the delta.

## You now have an account

The exchange gives every session cash and stock when it connects — by default
**1,000,000 cents (10,000.00) and 200 shares of each symbol**. Both are checked
at order entry:

- a BUY you cannot pay for is rejected with reason **8**, `not enough cash`
- a SELL of stock you do not hold is rejected with reason **9**, `not enough stock`

There is no short selling and no credit.

**Resting orders reserve.** A resting BUY sets its cash aside and a resting SELL
sets its shares aside, at the moment the order is accepted rather than when it
fills. Cancel it, or let your session expire, and the reservation comes back. If
you do not account for this, your own idea of your free cash will run ahead of
the exchange's and you will start collecting reason 8.

Settlement is immediate and atomic with the trade print — no T+2, no clearing.
It also only happens while both sides are connected, because a session that goes
away has its resting orders cancelled, leaving nothing to trade against.

Nothing is persisted. Your account exists for the life of your session.

## `0x44 ACCOUNT` — server to client

Pushed when you connect and whenever your balances could have moved: a fill, an
order accepted, an order cancelled, a rejection.

| off | size | field |
|---|---|---|
| 0 | 4 | free cash, cents |
| 4 | 4 | cash reserved by your resting buys |
| 8 | 1 | NSYM |
| 9 | 10 each | symbol id (2), shares free (4), shares reserved by resting sells (4) |

Your holding in a symbol is **free + reserved**. Your total cash is
**free + reserved**.

This is the exchange's authoritative view. Track your own position and cash as
well, and compare — the drift between the two is the thing worth noticing, and
it is what you will be asked to show.

## Retries are recognised by `clOrdId`

`clOrdId` finally does something. The exchange remembers the last **512** client
order ids per session, and an `ORDER` carrying an id it has already answered is
treated as a retry: nothing reaches the book, and the **original ACK is replayed
byte for byte**.

So you can resend a lost order safely, provided you resend it unchanged. The
`orderId` in the reply tells you which happened:

- **same `orderId` as before** — recognised as a retry, booked once
- **a new `orderId`** — the exchange thought this was a new order, and you have
  just traded twice

Two things to be careful about. Client order ids must be unique within your
session; reusing one for a genuinely new order gets you the old ACK back. And
the memory is 512 ids deep, so a retry that arrives after 512 further orders is
no longer recognisable as one — a small version of a real problem, which is that
exactly-once guarantees always have a window.

The envelope's `SEQ` is unrelated and should still increase on every datagram
you send, retries included. `SEQ` counts datagrams; `clOrdId` identifies an
order.
