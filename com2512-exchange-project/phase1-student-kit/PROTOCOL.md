# XCHG/1 — the Phase 1 wire protocol

This document describes everything you need in order to write a client, in
whatever language you like. There is deliberately no client code in this kit:
the description is the thing you are given, and writing the code from it is the
exercise.

Phase 1 is UDP only, and does nothing to recover from a network that loses or
mangles your packets. That comes in Phase 2, and the last section explains what
is being left out and why.

## How it is carried

Everything happens over a single UDP socket. The server listens on port 9001
unless you tell it otherwise, and it replies to whatever address a packet came
from, so your client does not need a fixed port of its own — bind to port 0 and
let the operating system choose one for you.

Every field longer than a byte is big-endian, which is to say network byte
order, high byte first. Every string is ASCII.

## The envelope

Every datagram, in both directions, is one XCHG/1 packet:

```
 0                   1
 0 1 2 3 4 5 6 7 8 9 0 1
+---+---+---+---+---+---+
|MAGIC  |VER|TYP| SESS  |   bytes 0-5
+---+---+---+---+---+---+
|  SEQ  | PAYLEN|           bytes 6-9
+---+---+---+---+
|  PAYLOAD (PAYLEN bytes)  |
+--------------------------+
|  CRC16 (2 bytes)         |
+--------------------------+
```

| off | size | field | notes |
|---|---|---|---|
| 0 | 2 | MAGIC | always `0x5843` (ASCII `XC`) |
| 2 | 1 | VER | always `1` |
| 3 | 1 | TYPE | see the message catalog |
| 4 | 2 | SESSION | `0` until the server gives you one |
| 6 | 2 | SEQ | your own counter, +1 per datagram you send, starts at 1, wraps at 65535 |
| 8 | 2 | PAYLEN | payload length, 0..512 |
| 10 | PAYLEN | PAYLOAD | per message type |
| 10+PAYLEN | 2 | CRC16 | over bytes `0 .. 10+PAYLEN-1` — the header and payload, not itself |

The header is ten bytes long, so a complete datagram always comes to exactly
twelve bytes plus the length of its payload.

It is worth noticing what is *not* here. UDP preserves message boundaries for
you, so a single receive gives you exactly one packet and there is none of the
length-prefix framing a protocol over TCP would need. The length field is still
carried, for two smaller reasons: it lets a receiver tell a truncated datagram
from a complete one, and it is how you find where the checksum starts.

Keep datagrams comfortably below the usual 1500-byte limit on how large a packet
can travel without being fragmented. Nothing in Phase 1 comes close, as the
largest message is thirty-seven bytes.

## CRC-16/CCITT-FALSE

Polynomial `0x1021`, init `0xFFFF`, **no** input/output reflection, **no** final
XOR. This is the same CRC as the hardware phase (`hardware-reference/lib/bframe.h`),
so your implementation carries over.

```
crc = 0xFFFF
for each byte b:
    crc ^= b << 8
    repeat 8 times:
        crc = (crc & 0x8000) ? ((crc << 1) ^ 0x1021) : (crc << 1)
        crc &= 0xFFFF
```

Check your implementation against the four values below before you write
anything else. If these are wrong then nothing else can work, and the symptom —
a server that never replies — looks nothing like a checksum problem.

| input | CRC |
|---|---|
| `"123456789"` | `0x29B1` |
| `""` | `0xFFFF` |
| `"A"` | `0xB915` |
| `"AAPL"` | `0x3182` |

You may wonder why this is here at all, given that UDP carries a checksum of its
own. The answer is that UDP's is optional on IPv4 and weak where it is used, so
this is the one that actually tells you a packet arrived intact. It is also the
one you will need later on the radio link, where there is no UDP to rely on.

## Validation order (normative)

A receiver works through the following checks in order and stops at the first
one that fails:

1. datagram is at least 12 bytes → else `E_LENGTH`
2. `MAGIC == 0x5843` → else `E_MAGIC`
3. `VER == 1` → else `E_VERSION`
4. `PAYLEN <= 512` and `12 + PAYLEN == datagram length` → else `E_LENGTH`
5. CRC matches → else `E_CRC`
6. then, and only then, the payload may be read

The order matters, and is part of the specification rather than an implementation
detail, because some of the test packets fail more than one check at once. A
correct implementation reports the earliest failure, not whichever it happens to
notice first. And nothing in a packet can be trusted until the checksum has
passed — not even the session and sequence numbers, which is why an error about
a packet that failed to decode comes back with both of them set to zero.

## Session lifecycle

UDP has no connections, so a session is something the server invents and you
must maintain.

```
  you                                  server
   |-- HELLO (SESSION=0) -------------->|  assigns a session id
   |<------------------- WELCOME -------|  carries id + symbol table
   |-- SUBSCRIBE / ORDER / CANCEL ----->|  all with SESSION = your id
   |<----------- QUOTE / TRADE / ACK ---|
   |-- PING (every <= 5s) ------------->|  keeps the session alive
   |<------------------- PONG ----------|
   |-- BYE ---------------------------->|  cancels your resting orders
```

You begin by sending a `HELLO` with the session field set to zero. The `WELCOME`
that comes back carries the session id you have been given, and every packet you
send afterwards must contain it; sending the wrong one gets you an `E_SESSION`
error, and sending anything at all before you have said hello gets you
`E_NOHELLO`.

After that you need to keep saying something at least every five seconds, or the
server will decide you have gone away. It gives you fifteen seconds of silence
before it drops your session and cancels any orders you had resting. Any packet
counts as a sign of life, but `PING` is the one that costs nothing, which is why
it exists.

A few limits worth knowing. A second `HELLO` from the same address and port
keeps the session you already had and simply updates your team name. You may
send at most two hundred packets a second before the server starts refusing them
with `E_RATE`, which a retry loop without a delay in it will reach almost
immediately. And you may have at most sixty-four orders resting in the book at
once.

## Symbols and units

| id | ticker | starting mid |
|---|---|---|
| 1 | AAPL | 300 |
| 2 | MSFT | 420 |
| 3 | NVDA | 880 |
| 4 | TSLA | 250 |

Take the authoritative table from `WELCOME`, not from here.

Prices and quantities are both unsigned 16-bit numbers, and prices are in cents,
so a price of 300 means three pounds exactly.

These are the same field widths the hardware frame uses later in the course. A
quote here is byte-for-byte identical to a quote travelling over the radio link
you will build, which is why the radio's budget in the hardware acceptance
vectors can be quoted in whole bytes per update, and why the encoder you write
now is not thrown away when you get there.

## The messages themselves

What follows is reference material: each message, its type byte, and the layout
of its payload. The payload sizes are exact, and the server will reject anything
that is even a byte out with an `E_PAYLOAD` error telling you what it expected.

### Messages you send

**`0x40 HELLO`** — payload `1 + n` bytes

| off | size | field |
|---|---|---|
| 0 | 1 | team name length, 1..24 |
| 1 | n | team name, ASCII |

**`0x50 SUBSCRIBE`** — payload exactly 2 bytes

| off | size | field |
|---|---|---|
| 0 | 2 | symbol id, or `0` for every symbol |

You are subscribed to every symbol already, so you only need this if you want to
narrow that down to one of them.

**`0x20 ORDER`** — payload exactly 11 bytes

| off | size | field |
|---|---|---|
| 0 | 4 | client order id — yours, echoed back in the ACK |
| 4 | 2 | symbol id |
| 6 | 1 | side: `0x42` `'B'` buy, `0x53` `'S'` sell |
| 7 | 2 | limit price, cents |
| 9 | 2 | quantity |

These are limit orders and nothing else — there is no such thing as a market
order here. A buy priced at or above the best offer in the book will trade
straight away, and whatever quantity is left over after that sits in the book
waiting, until it trades, you cancel it, or your session goes away.

**`0x21 CANCEL`** — payload exactly 8 bytes

| off | size | field |
|---|---|---|
| 0 | 4 | client order id for this cancel |
| 4 | 4 | the server order id you got in the ACK |

**`0x60 PING`** — payload exactly 8 bytes, opaque. The server copies them into
the `PONG`, so put a timestamp there and you get an RTT for free.

**`0x42 BYE`** — no payload. Cancels your resting orders and drops the session.

### Messages you receive

**`0x41 WELCOME`** — payload `7 + 6*NSYM` bytes

| off | size | field |
|---|---|---|
| 0 | 2 | your session id |
| 2 | 2 | heartbeat interval, ms |
| 4 | 2 | session TTL, ms |
| 6 | 1 | NSYM |
| 7 | 6 each | symbol id (2) + ticker (4 ASCII, space-padded) |

**`0x10 QUOTE`** — payload 10 bytes. This is the top of the book: the best price
on each side and how much is available there.

Quotes arrive as a steady feed, one per symbol on each tick of the market maker,
rather than being sent every time something in the book changes. That is
deliberate, and it matters if you are averaging prices over time: it means the
rate at which quotes reach you does not depend on how much you happen to be
trading.

| off | size | field |
|---|---|---|
| 0 | 2 | symbol id |
| 2 | 2 | best bid price (`0` = no bid) |
| 4 | 2 | quantity at best bid |
| 6 | 2 | best ask price (`0` = no ask) |
| 8 | 2 | quantity at best ask |

**`0x12 TRADE`** — payload 11 bytes. Sent to everyone subscribed to that symbol
whenever a trade happens, whoever was involved in it.

| off | size | field |
|---|---|---|
| 0 | 2 | symbol id |
| 2 | 2 | price |
| 4 | 2 | quantity |
| 6 | 1 | aggressor side, `'B'` or `'S'` |
| 7 | 4 | trade id |

**`0x30 ACK`** — payload 14 bytes. You get exactly one of these for every order
and every cancellation you send.

| off | size | field |
|---|---|---|
| 0 | 4 | your client order id |
| 4 | 4 | server order id — needed to cancel |
| 8 | 1 | status |
| 9 | 1 | reject reason, `0` unless rejected |
| 10 | 2 | quantity filled |
| 12 | 2 | quantity now resting |

status: `0` RESTING · `1` PARTIAL · `2` FILLED · `3` REJECTED · `4` CANCELLED

reason: `0` none · `1` unknown symbol · `2` bad side · `3` zero quantity ·
`4` zero price · `5` too many resting orders · `6` unknown order id ·
`7` not your order

**`0x61 PONG`** — payload 8 bytes, being whatever eight bytes you put in your
`PING`, handed back untouched.

**`0x7F ERROR`** — payload `4 + n` bytes

| off | size | field |
|---|---|---|
| 0 | 1 | error code |
| 1 | 2 | the SEQ this refers to, `0` if it could not be read |
| 3 | 1 | reason length |
| 4 | n | reason, ASCII — written for a human, do not parse it |

codes: `0x01` E_MAGIC · `0x02` E_VERSION · `0x03` E_CRC · `0x04` E_LENGTH ·
`0x05` E_TYPE · `0x06` E_SESSION · `0x07` E_PAYLOAD · `0x08` E_NOHELLO ·
`0x09` E_RATE

Even a packet that fails to decode at all gets an error back, addressed to
whoever appeared to send it. Both the session and sequence fields in that reply
will be zero, because in a packet that failed its checksum there is no reason to
believe either of them.

## A worked packet

`ORDER`, client order id 1001, buy 50 AAPL at 300, on session 7, sequence 3:

```
58 43 01 20 00 07 00 03 00 0B 00 00 03 E9 00 01 42 01 2C 00 32 D9 5A
^^^^^ ^^ ^^ ^^^^^ ^^^^^ ^^^^^ ^^^^^^^^^^^ ^^^^^ ^^ ^^^^^ ^^^^^ ^^^^^
MAGIC VR TY SESS  SEQ   PAYLEN clOrdId    symbol B price qty   CRC
0x5843 1 ORDER  7     3     11  1001         1   buy  300    50
```

23 bytes: 10 header + 11 payload + 2 CRC.

Get the full set with `java -jar xchg-server.jar --vectors`. They are generated
by the server's own encoder, so the spec and the server cannot drift apart. If
your encoder reproduces those bytes, your framing is right.

Stuck on one packet? The server will decode it for you:

```
java -jar xchg-server.jar --decode "58 43 01 20 00 07 00 03 ..."
```

It prints every field and, on a CRC failure, tells you the CRC it expected.

## What Phase 1 leaves out

Deliberately. UDP gives you no delivery guarantee, no ordering guarantee, and no
duplicate suppression, and **Phase 1 does not ask you to fix any of that** — it
asks you to see it.

Run the server with `--link lossy`, `--link corrupt` or `--link flaky-acks` and
watch what happens to a client that assumes a reply always arrives. The `SEQ`
field is how you measure it: the server's packets to you carry their own
increasing `SEQ`, so a gap means a datagram died and a repeat means you got a
duplicate. The UI shows the same accounting from the server's side, for your
stream.

Note that a **corrupted** packet is a different failure from a lost one. It
arrives, so your socket hands it to you; only the CRC tells you it is rubbish.
Check it before you believe anything in it — including the `SEQ` you are using
to count the others.

Retransmission, acknowledgement, windowing and ordered delivery are Phase 2,
where you will build R-UDP on top of exactly this envelope.
