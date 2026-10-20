# COM2512 Phase 1 — student kit

Write a client that trades on the exchange over **UDP**. You get a test server
and the exchange UI; you write the client, in whatever language you like.

There is no client code in this kit. [`PROTOCOL.md`](PROTOCOL.md) is the spec,
and the server will check your bytes for you.

**Submit:** your client source, plus screenshots. No write-up.

## Run the server

Needs a JRE 17+. Nothing else to install.

```bash
java -jar xchg-server.jar
```

```
  exchange   UDP  0.0.0.0:9001
  UI         http://localhost:9000/
```

Open the UI. A built-in market maker is already quoting, so the book is live
before you write a line of code — your first order can trade immediately.

Useful modes, all of which exit straight away:

```bash
java -jar xchg-server.jar --vectors          # the test vectors your client must reproduce
java -jar xchg-server.jar --decode "58 43 01 40 ..."   # decode a packet, field by field
java -jar xchg-server.jar --help             # every option
```

## The UI is your debugger

<http://localhost:9000/> shows the order books, the trade tape, every connected
session — and a **packet log**: every datagram the server received or sent, how
it decoded, and why it was rejected if it was. Click a row for the raw bytes.

When your client misbehaves, the answer is almost always on that screen already:
`ORDER payload is 9 bytes, spec says 11` beats guessing. Filter it with
**problems only**, and hit **Freeze** to stop the refresh while you read.

The sessions table also shows gaps, duplicates and late packets in *your*
sequence numbers, as the server sees them.

## Build it in five steps

Each step is visible in the UI, so you always know whether it worked.

1. **CRC first.** Reproduce the four check values in `PROTOCOL.md`. Everything
   downstream depends on this, and a wrong CRC looks like a dead server.
2. **Reproduce the vectors.** Encode the `HELLO` and `ORDER` from
   `--vectors` and compare byte for byte. When they match, your framing is right.
3. **HELLO → WELCOME.** Send it, read your session id and the symbol table out
   of the reply. You should appear in the UI's sessions table.
4. **Trade.** `ORDER` a buy that crosses the market maker's ask, read the `ACK`,
   and watch the print land in the tape. Then rest an order far from the market
   and `CANCEL` it by the order id the ACK gave you.
5. **Stay alive.** `PING` every 5 seconds. Stop, and after 15 seconds the server
   reaps your session and cancels your orders — on purpose. UDP has no
   connection to notice dying, so liveness is something the protocol invents.

Decode the `QUOTE` and `TRADE` broadcasts as they arrive and print them; your
client should show a running top-of-book.

## Then break the link

The server will misbehave on request:

```bash
java -jar xchg-server.jar --loss 0.2 --dup 0.1 --delay 50
```

20% of datagrams vanish in each direction, 10% of replies arrive twice, and
everything is held 50 ms. Point your working client at it.

You are **not** asked to fix this in Phase 1 — you are asked to see it, and to
measure it. Count the gaps in the server's `SEQ` numbers, count the duplicates,
and make your client survive a missing `ACK` without hanging forever. Phase 2 is
where you build reliability on this exact envelope.

Everything is seeded, so `--seed 7` twice gives the same run twice.

## Submit

```
<your-id>-phase1/
  <your client source>
  README.md          one paragraph: language, how to run it
  screenshots/
```

Screenshots, annotated:

1. The UI's **sessions table** with your team connected.
2. The **packet log** showing your HELLO, your ORDER and its ACK.
3. The **trade tape** with a trade your client caused.
4. Your client's own output, decoding QUOTE and TRADE.
5. The same client against `--loss 0.2`, with gaps or duplicates visible.

A Wireshark capture on the loopback interface (`udp.port == 9001`) is worth
taking too: `java -jar xchg-server.jar --decode` and Wireshark's hex pane should
agree about every byte.

## When it does not work

| symptom | cause |
|---|---|
| no reply at all | CRC wrong. Check the four values in `PROTOCOL.md` before anything else |
| `E_MAGIC` | wrong byte order — `0x5843` is big-endian, high byte first |
| `E_LENGTH` | `PAYLEN` disagrees with the bytes you actually sent |
| `E_CRC` | CRC computed over the wrong range: it covers the header *and* payload, not itself |
| `E_PAYLOAD` | payload is not exactly the size the message type requires |
| `E_NOHELLO` | send `HELLO` first; the server keys sessions by address and port |
| `E_SESSION` | you are still sending `SESSION = 0` after WELCOME gave you an id |
| `E_RATE` | over 200 packets/sec — put a sleep in your loop |
| session keeps vanishing | no `PING`; the TTL is 15 seconds |
| orders rejected, reason 1 | symbol id, not ticker text — take the table from `WELCOME` |
| works alone, fails in the lab | two clients on one machine must bind different source ports |

`--decode "<hex>"` settles most arguments in one command.
