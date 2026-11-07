# What Phase 2 adds to the protocol

Everything in `PROTOCOL.md` still holds. The envelope is the same, the checksum
is the same, and the order in which a receiver validates a packet is the same.
This document only describes what is new.

It uses a handful of trading terms — resting orders, fills, positions, short
selling — which are all explained in `TRADING.md` if they are new to you.

## You have an account now

When your session connects, the exchange gives you some money and some stock to
trade with — by default a million cents, which is ten thousand pounds, and two
hundred shares of each of the four symbols. Both are checked every time you send
an order. A buy you cannot pay for is rejected with reason **8**, and a sell of
stock you do not hold is rejected with reason **9**. There is no short selling
and no credit: you can only sell what you actually have, and only buy what you
can actually pay for.

The part that catches people out is that **resting orders reserve**. When the
exchange accepts a buy order that does not fill immediately, it sets the cash
aside there and then, not when the order eventually trades. The same goes for a
resting sell and the shares it would deliver. Cancel the order, or let your
session expire, and the reservation comes back to you. If your client does not
account for this, its idea of your free cash will steadily run ahead of the
exchange's and you will start collecting rejections with reason 8 for orders you
are certain you can afford.

Settlement happens immediately, as part of the trade itself — there is no
overnight clearing and no settlement period. It also only happens while both
sides are connected, since a session that goes away has its resting orders
cancelled, which leaves nothing of it in the book for anyone to trade against.

None of this is saved anywhere. Your account exists for as long as your session
does, and no longer.

## The `ACCOUNT` message, type `0x44`

The exchange sends you this when you connect and then again whenever your
balances could have moved: a fill, an order accepted, an order cancelled, or an
order rejected.

| offset | size | field |
|---|---|---|
| 0 | 4 | free cash, in cents |
| 4 | 4 | cash reserved by your resting buy orders |
| 8 | 1 | number of symbols that follow |
| 9 | 10 each | symbol id (2 bytes), shares free (4), shares reserved by resting sells (4) |

Your actual holding in a symbol is the free shares plus the reserved ones, and
your actual cash is likewise the free cash plus the reserved cash. The split
tells you how much of each is currently spoken for.

This is the exchange's authoritative view of your account. You should still keep
your own, and compare the two — the moments when they disagree are the
interesting ones, and showing that they agree at the end of a difficult run is
part of what you hand in.

## Retries are recognised by `clOrdId`

The client order id, which has been sitting in the `ORDER` message since Phase 1
doing nothing but getting echoed back to you, finally has a job.

The exchange remembers the last **512** client order ids it has seen from your
session. If an order arrives carrying an id it has already answered, it treats
that as a retry rather than a new order: nothing reaches the book, and it sends
back the **original acknowledgement, byte for byte**. That is what makes it safe
to resend an order you are unsure about, provided you resend it unchanged.

You can tell which happened by looking at the order id in the reply. If it is
the same one you saw before, the exchange recognised your retry and the order
was booked exactly once. If it is a new one, the exchange thought you were
placing a second order, and you have now traded twice.

Two things to be careful about. Client order ids have to be unique within your
session, so reusing one for a genuinely new order will simply get you the old
acknowledgement back. And the exchange only remembers 512 of them, so a retry
that arrives after another 512 orders have gone by is no longer recognisable as
a retry — a small version of a real problem, which is that guarantees of this
kind always have a window, and outside it you are on your own.

Finally, do not confuse `clOrdId` with the `SEQ` field in the envelope. `SEQ`
counts datagrams and should keep increasing on everything you send, retries
included. `clOrdId` identifies an order, and must stay the same across every
retry of that order. They are doing two different jobs.
