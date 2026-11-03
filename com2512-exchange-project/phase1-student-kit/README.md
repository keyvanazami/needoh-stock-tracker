# COM2512 Phase 1 — talking to the exchange over UDP

In this phase you write a program that talks to our exchange server over UDP.
You can write it in whatever language you like, because we are not giving you
any client code — what you get instead is `PROTOCOL.md`, which describes exactly
what the bytes have to look like, and a server that will tell you when you get
them wrong.

When you are finished, hand in your source code and a few screenshots. There is
no report to write.

## Getting started

You need Java 17 or newer to run the server, and nothing else at all. Start it
like this:

```bash
java -jar xchg-server.jar
```

It will tell you that the exchange is listening on UDP port 9001 and that there
is a web page at <http://localhost:9000/>. Open that page now, before you write
anything. There is a market maker built into the server that is already quoting
prices, so the exchange is alive and trading even though nobody has connected to
it yet, and your very first order will be able to trade against it.

Three other things the server can do for you, each of which prints something and
then exits:

```bash
java -jar xchg-server.jar --vectors                    # test data your client must reproduce
java -jar xchg-server.jar --decode "58 43 01 40 ..."   # explain one packet, field by field
java -jar xchg-server.jar --help                       # everything else it accepts
```

## The web page is your debugger

Most of your debugging will happen on that page rather than in your own code.
Alongside the order books and the trades, it shows a complete log of every
datagram the server has received or sent, what it made of each one, and — when
it rejected something — why. If your client is misbehaving, the explanation is
usually already on the screen: something like `ORDER payload is 9 bytes, spec
says 11` will save you an hour of guessing.

There is a filter box for narrowing the log down, a **problems only** checkbox
for hiding everything that worked, and a **Freeze** button that stops the page
refreshing so you can actually read a line before it scrolls away. Clicking any
row shows you the raw bytes of that packet.

The page also keeps count of anything odd it notices in the sequence numbers you
send: gaps where a datagram seems to have gone missing, duplicates, and packets
that arrived later than they should have.

## Building your client

Work through it in roughly this order, because each step is visible on the web
page and you will know immediately whether it worked.

**Start with the checksum.** `PROTOCOL.md` gives four short test values for
CRC-16/CCITT-FALSE. Get those four matching before you open a socket. Everything
else depends on the checksum being right, and the symptom of getting it wrong is
that the server ignores you completely, which looks exactly like the server
being broken or your packets not arriving.

**Then reproduce the test vectors.** Run `--vectors` and you will get a list of
complete datagrams in hex. Build the `HELLO` and the `ORDER` yourself and compare
them byte by byte against those. Once they match, you know your framing is
correct, and you can stop wondering about it.

**Now say hello.** Send a `HELLO` and read the `WELCOME` that comes back; it
carries the session id you must put in every later packet, along with the table
of symbols the exchange trades. You should see yourself appear in the sessions
list on the web page.

**Then trade.** Send an `ORDER` to buy at a price that crosses the market
maker's offer, read the `ACK`, and watch the trade appear in the tape on the web
page. After that, try resting an order well away from the current price and then
cancelling it, using the order id the exchange gave you in the `ACK`.

**Finally, stay alive.** Send a `PING` every five seconds. If you stop, the
server will throw your session away after fifteen seconds and cancel any orders
you had resting. This is deliberate: UDP has no connection that can be noticed
dying, so the only way the exchange can tell whether you are still there is if
you keep saying so.

While all this is going on your client should also be reading the `QUOTE` and
`TRADE` messages that arrive unprompted, and printing them, so that you end up
with a running view of the market.

## Making the network worse

Once your client works, make its life difficult:

```bash
java -jar xchg-server.jar --link lossy
```

A fifth of all datagrams now vanish in each direction. The server can pretend to
be several different kinds of bad connection, and `--link list` will describe
them all — among them `slow`, `busy`, `corrupt` and `flaky-acks`. Whichever you
choose is named across the top of the web page along with what it is doing to
you, and each line of the packet log is tagged with what happened to it.

You are not being asked to fix any of this in Phase 1. You are being asked to
see it happen, and to measure it. Count the gaps in the sequence numbers on the
packets the server sends you, count the duplicates, and make sure that a missing
reply leaves your client waiting sensibly rather than hanging forever. Repairing
the damage is Phase 2, and you will build it on exactly this protocol.

Everything the server does randomly is seeded, so `--seed 7` twice will give you
the same run twice.

## What to hand in

Put your source code in a folder named after your student id, with a short
`README.md` saying what language you wrote it in and how to run it, and a
`screenshots` folder containing five pictures:

the sessions table on the web page with your team connected; the packet log
showing your `HELLO`, your `ORDER` and the `ACK` that came back; the trade tape
containing a trade your client caused; your own client's output as it decodes
quotes and trades; and finally the same client running against `--link lossy`,
with the gaps or duplicates visible.

It is also worth capturing the traffic in Wireshark on the loopback interface
with the filter `udp.port == 9001`, and checking that what Wireshark shows you
agrees with what `--decode` says about the same packet.

## If it will not work

By far the most common problem is that **the server appears to ignore you
entirely**. That is almost always a wrong checksum, so go back and check those
four test values before you look at anything else. The server will not reply to
a packet whose CRC does not match, because it has no reason to believe anything
the packet says.

If you are getting errors back, each one tells you what it objected to.
`E_MAGIC` means your byte order is wrong somewhere — the first two bytes are
`0x5843` with the high byte first. `E_LENGTH` means the length you declared in
the header does not match the number of bytes you actually sent. `E_CRC` usually
means you computed the checksum over the wrong range: it covers the header and
the payload, but not itself. `E_PAYLOAD` means the payload is not exactly the
size that kind of message requires. `E_NOHELLO` means you have not introduced
yourself yet, and `E_SESSION` means you are still sending a session id of zero
after the `WELCOME` gave you a real one.

Two more that surprise people. `E_RATE` means you are sending more than two
hundred packets a second and the server has started refusing them, which usually
means a retry loop with no delay in it. And if your session keeps disappearing
after about fifteen seconds, you have stopped sending `PING`.

If your orders come back rejected with reason 1, you are probably sending the
ticker text where the exchange expects the numeric symbol id; take the id from
the `WELCOME` message rather than guessing. And if everything works alone but
falls apart in the lab, remember that two clients on one machine need different
source ports.

When you cannot work out what is wrong with a particular packet, paste it into
`--decode` and the server will take it apart for you, including telling you
which checksum it was expecting.
