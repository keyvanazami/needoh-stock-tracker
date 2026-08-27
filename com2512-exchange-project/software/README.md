# XCHG — one exchange, three protocols

A classroom trading venue reachable over **TCP**, **UDP** and **REST**, all
feeding one matching engine. Students build a trading client on whichever
transport they are assigned; on demonstration day every client connects to the
same live server and they trade against each other.

Pure Python 3.9+ standard library. No pip install, no venv required, runs the
same on macOS, Windows and Linux.

```bash
python -m exchange                          # serve on 0.0.0.0:7001/7002/7003
python -m client.bench --host <server-ip>   # measure all three transports
python -m unittest discover -s tests        # 37 tests, no network needed
```

## Why this shape

The protocol is the variable; the market is the constant. Two students who
made different transport choices are, at the end of the session, holding
different positions — and the fill log says which choice cost what. That is
the whole design.

| | TCP `:7001` | UDP `:7002` | REST `:7003` |
|---|---|---|---|
| encoding | binary frames | binary frames | JSON |
| framing | length prefix (**you** must reassemble) | one message per datagram | `Content-Length` |
| ordering | guaranteed | not guaranteed | per request |
| delivery | guaranteed | best effort | guaranteed |
| market data | **pushed** | **pushed** | **polled** |
| bytes per order | 30 | 30 | ~300 |

That last row is not a criticism of REST. It is the reason exchanges do not
speak it, and it is measurable rather than asserted: `client.bench` reports
bytes and request counts per session.

## The wire protocol

```
+--------+-----+------+-------+--------+--------+--------+---------+-------+
| MAGIC  | VER | TYPE | FLAGS |  SEQ   |  FIRM  |  LEN   | payload | CRC16 |
|  "BX"  |  1  |  1   |   1   |   4    |   2    |   2    |   LEN   |   2   |
+--------+-----+------+-------+--------+--------+--------+---------+-------+
```

Big-endian, 15 bytes of overhead. CRC-16/CCITT-FALSE, so
`crc16(b"123456789") == 0x29B1`.

**The length prefix is not redundant on TCP.** TCP is a byte stream: it
guarantees order and delivery, not message boundaries. A 30-byte order can
arrive as 30 one-byte reads, or glued to the next order in a single read.
Localhost usually delivers each write intact, so a client that ignores this
works on the student's laptop and fails in class. `exchange/wire.py:StreamParser`
is the reference; `tests/test_wire.py` has the cases that catch it.

**The CRC is redundant on TCP and essential on UDP** — which is the point.
The same message on two transports needs different guarantees from the layer
above it.

## Messages

`HELLO` `ORDER` `CANCEL` `ACK` `REJECT` `QUOTE` `TRADE` `HEARTBEAT`

Binary layouts in `exchange/messages.py`; the REST gateway carries the same
fields as JSON. Prices are integer cents. Sides are `0 = BUY`, `1 = SELL`.

## Matching rules

1. Best price first.
2. At equal price, earliest arrival first.
3. A crossing order executes at the **resting** order's price — the passive
   side keeps its price and the aggressor takes the improvement.
4. Any remainder rests.

Rule 3 is why latency is worth money: the order that got there first sets the
price. `tests/test_book.py` asserts all four, plus conservation of quantity
over 400 random orders.

## Impairment — the instrument

The instructor degrades the network live, per gateway, from any terminal:

```bash
curl -X POST http://<server>:7003/admin/impair \
     -d '{"gateway":"all","preset":"wifi-busy"}'
curl -X POST http://<server>:7003/admin/impair \
     -d '{"gateway":"udp","delay_ms":40,"loss":0.1,"reorder":0.05}'
curl     http://<server>:7003/admin/impair      # what is set right now
```

Presets: `clean` `campus` `wifi-busy` `lossy` `leo` `satellite` `brutal`.

### The layer this runs at, and why it changes the rules

The impairer sits **above** the transport. For UDP that is exact: the
application message and the datagram are the same thing, so loss, duplication
and reordering are all real.

For TCP it would be wrong, and wrong in a way that looks completely plausible.
Dropping an application message on a TCP gateway does not model a lossy link —
TCP would have retransmitted those bytes and the receiver would have got them,
late. It models *TCP with its reliability removed*, which makes TCP measure
like UDP and hides the entire distinction the assignment exists to teach. It
also corrupts the stream, because you deleted the middle of a frame the
receiver is still counting bytes for.

So the TCP and REST gateways run in **stream mode**: loss becomes a
retransmission timeout with exponential backoff, and duplication and
reordering are not applied at all, because TCP resequences and deduplicates
below the application.

> Under a lossy link, **UDP loses messages and TCP loses time.**

That sentence only shows up in the numbers if the impairment is applied at the
right layer. Measured, 50 orders per transport, `lossy` (15% loss):

```
  transport  orders_sent  acked  unacked_%  rtt_p50_ms  rtt_p95_ms  md_gaps
  tcp        50           50     0.0        5.94        206.87      -
  udp        50           47     6.0        5.96        6.30        13
  rest       50           50     0.0        6.36        207.23      -
```

TCP's median is untouched and its tail explodes. UDP's latency is flat and its
messages are simply gone. Neither is better; they fail differently, and the
students' own fills will show which failure hurt them more.

## Running it in class

```bash
python -m exchange --host 0.0.0.0 --impair clean
```

The banner prints the addresses students should dial. Then:

```bash
curl http://<server>:7003/stats     # every session: bytes, orders, fills
```

**Campus wireless will fight you.** Two things to check before the first
session, because both are common and both look like broken student code:

- **Client isolation.** Most enterprise APs block client-to-client traffic. If
  students cannot reach the server on the campus SSID, the fix is a dedicated
  network — a travel router, a phone hotspot, or an ethernet switch — not a
  change to anything here.
- **Multicast.** Market data is deliberately **unicast fan-out**, not
  multicast, because campus wireless almost always drops multicast. Real
  exchanges multicast; we cannot. The gap between those two facts is worth
  five minutes of lecture on why multicast never made it across the public
  internet.

## Layout

```
exchange/
  wire.py       frame codec + StreamParser (TCP reassembly reference)
  messages.py   the eight messages, binary and JSON
  book.py       price-time priority matching engine
  impair.py     latency / jitter / loss / dup / reorder, layer-aware
  server.py     Exchange + TcpGateway + UdpGateway + HttpGateway
  __main__.py   runner, prints the addresses students should dial
client/
  reference.py  TcpClient, UdpClient, RestClient — identical trading logic
  bench.py      drives any client, reports RTT, loss, gaps, bytes
tests/          37 tests: wire, book, and all three gateways end to end
```

## What students build

Any language — it is a wire protocol, not a Python library. The reference
clients exist to check against, and `bench.py` will drive a student's client
if it exposes `order`, `cancel` and `poll`.
