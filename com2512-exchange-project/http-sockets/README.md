# Assignment — HTTP over a raw socket

In this assignment you write an HTTP echo server and an HTTP client using
nothing but TCP sockets, and then watch your own requests go past in Wireshark.

The reason for doing it the hard way is that `requests.post(url, data=...)`
hides the thing we actually want to look at. HTTP is a text protocol carried
over a byte stream, and a byte stream has no message boundaries in it, so HTTP
has to invent its own out of carriage returns, a blank line, and a header that
says how long the body is. Every bug you hit in this assignment will be a
framing bug of one kind or another, and framing is a problem that comes back at
every layer of this course. You met it on the wire with `bframe`; this is the
same problem written in ASCII.

Hand in your `server.py`, your `client.py`, a packet capture, and some
screenshots. There is no report.

## What you have been given

`sockets_demo.py` shows the socket calls themselves, in plain TCP with no HTTP
anywhere in it. Read it first. The `starter` folder has skeletons for the server
and the client with the work marked out, and a `check.py` that tests your server
as you go. `WIRESHARK.md` explains how to capture your own traffic, and is worth
reading before you start capturing rather than after.

You need Python 3.10 or newer, and nothing else. Work in a copy of `starter`.

## See the sockets work first

```bash
python3 sockets_demo.py listen          # in one terminal
python3 sockets_demo.py send "hello"    # in another
```

That is plain TCP, both halves, about forty lines each, and between them they
use every socket call the rest of the assignment needs.

The one idea to take away from it is this: **a call to `recv()` is not the same
as receiving a message.** It hands back whatever bytes have turned up so far,
which might be all of them, or might be three of them. So you read in a loop.
Nearly every bug in this assignment turns out to be a version of forgetting
that.

## Write the server

Work through the six marked sections in `server.py`. Each one says what it needs
to do.

In order, you need to parse the `Content-Length` header out of a block of
headers; read exactly one complete request off a connection, which means reading
until you see the blank line and then reading precisely as many body bytes as
the header promised; build a response; route the request, so that a `GET` on
`/echo` lists the query parameters, a `POST` on `/echo` hands the body straight
back, and anything else returns a 404; open the listening socket and accept
connections in a loop; and echo every request you receive to standard output
exactly as it arrived.

Listen on `127.0.0.1:8080`. Port 8080 rather than 80 because anything below 1024
needs root, and because Wireshark will recognise 8080 as HTTP without being told.

Two requirements are worth drawing out, because they are where most submissions
lose marks.

The first is that **`Content-Length` counts bytes, not characters.** The string
`£` is one character but two bytes in UTF-8, and `check.py` will send you one to
find out whether you noticed.

The second is that **your server must not fall over.** A truncated request, a
missing or non-numeric `Content-Length`, or a client that connects and then says
nothing at all must not produce a traceback.

Check your work as you go:

```bash
cd starter && python3 check.py
```

It sends raw HTTP over a socket itself, so it works before you have written any
client at all.

## Write the client

Three marked sections this time: build the request bytes by hand, with proper
carriage returns and a blank line before the body; open the connection, send
everything, and read the reply until the far end closes; and print what came
back without interpreting it.

It needs to manage both a `GET` with a query string and a `POST` with a body:

```bash
python3 client.py --path '/echo?name=ada&unit=7'
python3 client.py -X POST --data 'hello from COM2512' --path /echo
```

Then check that something other than your own code can talk to your server,
because a protocol that only one implementation understands is not really a
protocol:

```bash
curl -v -X POST -d 'curl says hi' http://127.0.0.1:8080/echo
```

You may use `socket`, `urllib.parse`, `argparse` and `sys`. You may not use
`requests`, `http.client`, `http.server` or `socketserver` in either file, since
they would do the assignment for you.

## Capture it

The procedure is in `WIRESHARK.md`, including the business about choosing the
right interface, which is the thing that wastes the most time. Capturing on your
Ethernet or wireless adapter while talking to `127.0.0.1` shows you an empty
window, quite correctly.

Capture one `GET` and one `POST`, and save the result as `capture.pcapng` — we
open the file itself, so screenshots alone are not enough. Then take five
screenshots, with the relevant part marked or circled: the packet list showing a
complete exchange including the three-way handshake; the expanded HTTP tree for
your `GET`, showing where the query parameters sit; the same for your `POST`,
showing where the body sits; a **Follow → TCP Stream** window for either one;
and your server's terminal output echoing both requests.

The second and third of those are the point of the whole exercise. The same
information appears in two different places on the wire depending on which verb
you used, and that difference has consequences for what gets written into logs.

## What to hand in

A folder named after your student id, containing `server.py`, `client.py`,
`capture.pcapng` and a `screenshots` folder.

Capture on loopback only, or on a network you own. Not campus wireless, not a
shared lab segment, and not anywhere else you might pick up other people's
traffic — there is a note at the end of `WIRESHARK.md` about why this matters
rather more than it might appear to.

## If it will not work

If you get `Address already in use`, your previous server is still shutting down
and you have not set `SO_REUSEADDR`; either set it or wait about a minute.

If your client hangs after sending, either the `Content-Length` you sent is
larger than the body you actually sent, so the server is still waiting for the
rest of it, or your header-reading loop never found the blank line and is still
going.

If a browser renders your page but keeps spinning, your `Content-Length` is
missing or too small and it is waiting for the remainder. If the response body
comes back truncated, you counted characters instead of bytes.

If Wireshark shows you nothing at all on port 8080, you are capturing on the
wrong interface. If it shows TCP but no HTTP, either use **Decode As** to tell
it the port is HTTP, or check that you clicked on a packet that actually has a
payload — a bare acknowledgement contains no HTTP and nothing is wrong. And if
everything is labelled `[TCP segment of a reassembled PDU]`, that is normal:
Wireshark shows the assembled message on the last segment of the group.

## If you finish early

None of this is marked, but it is where the protocol starts to get interesting.

Try sending `\n` line endings instead of `\r\n` and see whether your server
copes, whether `curl` does, and whether a real server does. Try leaving out the
`Host` header. Try sending a `Content-Length` of 5 with a twenty-byte body, and
then one of 50 with the same body: one of them stalls and the other leaves
fifteen bytes sitting unread in the stream, which on a connection that stayed
open would become the beginning of the next request — and that is request
smuggling, in miniature.

After that, try serving two clients at once with threads, then with `selectors`
and a single thread; implement `Connection: keep-alive` and watch the handshake
you stop paying for; and time a hundred requests with it on and off, explaining
the difference in round trips rather than milliseconds.
