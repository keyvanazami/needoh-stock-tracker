# XCHG/1 — the Phase 1 wire protocol

Everything you need to write a client, in any language. There is no client code
in this kit on purpose: the spec is the deliverable, and you implement it.

Phase 1 is **UDP only**. Reliability is Phase 2 — see
[What Phase 1 leaves out](#what-phase-1-leaves-out).

## Transport

One UDP socket. The server listens on **9001** by default and replies to the
source address of whatever it received, so your client needs no fixed port —
bind to 0 and let the OS pick.

All multi-byte fields are **big-endian** (network byte order). All strings are
ASCII.

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

**The header is 10 bytes, so a datagram is exactly `12 + PAYLEN` bytes.**

UDP already preserves message boundaries, so unlike a TCP protocol there is no
length-prefix framing here — one `recvfrom` gives you exactly one packet.
`PAYLEN` is still carried so a receiver can tell a truncated datagram from a
complete one, and so you can find where the CRC starts.

Keep datagrams well under the ~1500-byte path MTU. Nothing in Phase 1 comes
close: the largest message is 37 bytes.

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

Check your implementation against these before anything else — if these are
wrong, nothing else will work:

| input | CRC |
|---|---|
| `"123456789"` | `0x29B1` |
| `""` | `0xFFFF` |
| `"A"` | `0xB915` |
| `"AAPL"` | `0x3182` |

UDP has its own 16-bit checksum, and it is optional on IPv4 and weak where it is
used. The application-layer CRC is what actually tells you a packet arrived
intact — and it is what you will need on the radio link, where there is no UDP
at all.

## Validation order (normative)

A receiver checks, in this order, stopping at the first failure:

1. datagram is at least 12 bytes → else `E_LENGTH`
2. `MAGIC == 0x5843` → else `E_MAGIC`
3. `VER == 1` → else `E_VERSION`
4. `PAYLEN <= 512` and `12 + PAYLEN == datagram length` → else `E_LENGTH`
5. CRC matches → else `E_CRC`
6. then, and only then, the payload may be read

The order is normative because the acceptance vectors include packets that fail
more than one check: a conforming implementation reports the **earliest**
failure. Nothing in a packet is trustworthy until step 5 passes — including its
`SESSION` and `SEQ`.

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

- Send `HELLO` with `SESSION = 0`. The `WELCOME` tells you your id; put it in
  every later packet. Wrong id → `E_SESSION`. No `HELLO` first → `E_NOHELLO`.
- **Send `PING` at least every 5000 ms.** After 15000 ms of silence the server
  reaps your session and cancels your resting orders. Any packet counts as
  liveness, but `PING` is the one that costs nothing.
- A second `HELLO` from the same address and port keeps your existing session
  and just updates the team name.
- Rate limit: **200 packets/second** per session, then `E_RATE`. A tight send
  loop with no delay will hit this.
- At most **64 resting orders** per session.

## Symbols and units

| id | ticker | starting mid |
|---|---|---|
| 1 | AAPL | 300 |
| 2 | MSFT | 420 |
| 3 | NVDA | 880 |
| 4 | TSLA | 250 |

Take the authoritative table from `WELCOME`, not from here.

**Prices are `uint16`, in cents.** `300` means $3.00. Quantities are `uint16`.
These are the same widths the hardware frame uses, so a QUOTE payload here is
byte-identical to a QUOTE on the AVR wire — which is why the radio budget in
`hardware-reference/vectors/acceptance.txt` is quoted in whole bytes per update.

## Message catalog

### You send

**`0x40 HELLO`** — payload `1 + n` bytes

| off | size | field |
|---|---|---|
| 0 | 1 | team name length, 1..24 |
| 1 | n | team name, ASCII |

**`0x50 SUBSCRIBE`** — payload exactly 2 bytes

| off | size | field |
|---|---|---|
| 0 | 2 | symbol id, or `0` for every symbol |

You are subscribed to everything by default; use this to narrow.

**`0x20 ORDER`** — payload exactly 11 bytes

| off | size | field |
|---|---|---|
| 0 | 4 | client order id — yours, echoed back in the ACK |
| 4 | 2 | symbol id |
| 6 | 1 | side: `0x42` `'B'` buy, `0x53` `'S'` sell |
| 7 | 2 | limit price, cents |
| 9 | 2 | quantity |

Limit orders only. A buy at or above the best ask trades immediately; anything
left over rests in the book.

**`0x21 CANCEL`** — payload exactly 8 bytes

| off | size | field |
|---|---|---|
| 0 | 4 | client order id for this cancel |
| 4 | 4 | the server order id you got in the ACK |

**`0x60 PING`** — payload exactly 8 bytes, opaque. The server copies them into
the `PONG`, so put a timestamp there and you get an RTT for free.

**`0x42 BYE`** — no payload. Cancels your resting orders and drops the session.

### You receive

**`0x41 WELCOME`** — payload `7 + 6*NSYM` bytes

| off | size | field |
|---|---|---|
| 0 | 2 | your session id |
| 2 | 2 | heartbeat interval, ms |
| 4 | 2 | session TTL, ms |
| 6 | 1 | NSYM |
| 7 | 6 each | symbol id (2) + ticker (4 ASCII, space-padded) |

**`0x10 QUOTE`** — payload 10 bytes. Top of book, sent on every change.

| off | size | field |
|---|---|---|
| 0 | 2 | symbol id |
| 2 | 2 | best bid price (`0` = no bid) |
| 4 | 2 | quantity at best bid |
| 6 | 2 | best ask price (`0` = no ask) |
| 8 | 2 | quantity at best ask |

**`0x12 TRADE`** — payload 11 bytes. Broadcast to every subscriber.

| off | size | field |
|---|---|---|
| 0 | 2 | symbol id |
| 2 | 2 | price |
| 4 | 2 | quantity |
| 6 | 1 | aggressor side, `'B'` or `'S'` |
| 7 | 4 | trade id |

**`0x30 ACK`** — payload 14 bytes. One per ORDER and per CANCEL.

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

**`0x61 PONG`** — payload 8 bytes, your PING's bytes unchanged.

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

A packet that fails to decode still gets an ERROR back, addressed to whoever
sent it — but with `SESSION` and `SEQ` of `0`, because neither field could be
trusted.

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

Run the server with `--loss 0.2 --dup 0.1 --delay 50` and watch what happens to
a client that assumes a reply always arrives. The `SEQ` field is how you measure
it: the server's packets to you carry their own increasing `SEQ`, so a gap means
a datagram died in the kernel, and a repeat means you got a duplicate. The UI
shows you the same accounting from the server's side, for your stream.

Retransmission, acknowledgement, windowing and ordered delivery are Phase 2,
where you will build R-UDP on top of exactly this envelope.
