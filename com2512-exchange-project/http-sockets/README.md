# Assignment — HTTP over a raw socket

**Application layer lab. Standalone: no exchange hardware, no network access required.**

You will write an HTTP echo server and an HTTP client using nothing but TCP sockets,
then watch your own bytes go past in Wireshark. By the end you should be able to read
an HTTP request the way you read a frame diagram — because you will have typed every
field of one yourself.

Working reference code is in `sample/`. It is yours to read, run and borrow from. The
graded deliverable is your own extension of it, plus a capture and a short report.

- Time: one 3-hour lab plus roughly 3 hours of write-up
- Submit: a single archive, structure given under [What to submit](#what-to-submit)
- Marks: 100, broken down in [`RUBRIC.md`](RUBRIC.md)

## Why bother, when `requests` is one line

Because `requests.post(url, data=...)` hides the thing being examined. HTTP is a text
protocol over a byte stream, and a byte stream has no message boundaries — so HTTP has
to invent its own, out of CRLFs, a blank line and `Content-Length`. Every bug in this
lab is a framing bug, and framing is the problem that recurs at every layer of this
course. You met it in `bframe` on the wire; this is the same problem in ASCII.

## Setup

Python 3.10 or newer, and Wireshark with permission to capture. Nothing to install.

```bash
cd sample
python3 selftest.py        # expect: 4/4 passed
```

If that fails, fix it before the lab — you want to be debugging HTTP, not your toolchain.

We use **port 8080** throughout. Ports below 1024 are privileged, so binding 80 needs
root; 8080 needs nothing and Wireshark dissects it as HTTP by default.

## Part 0 — Run the reference code (ungraded, do it first)

Two terminals. Server in the first:

```bash
python3 sample/echo_server.py --show-crlf
```

Client in the second:

```bash
python3 sample/http_client.py --path '/hello?name=ada'
python3 sample/http_client.py -X POST --data 'hello from COM2512'
python3 sample/http_client.py -X POST --form name=ada --form unit=7 --raw
```

Then point a browser at <http://127.0.0.1:8080/> and watch what a real user agent
sends — note how many headers it volunteers that your client does not.

The `--show-crlf` flag prints line endings literally. Look at the server output and
find: the request line, the header block, the blank line, the body. That shape is the
whole protocol.

## Part 1 — Your server (25 marks)

Write `server.py`. Start from `sample/echo_server.py` if you like, but it must grow
beyond a pure echo:

1. **Listen** on `127.0.0.1:8080` with `SO_REUSEADDR` set.
2. **Echo the request to stdout** — complete and unmodified, headers and body.
3. **Route on method and target:**
   | request | response |
   |---|---|
   | `GET /echo?...` | `200`, body lists each query parameter as `key=value`, one per line |
   | `POST /echo` | `200`, body is the request body verbatim |
   | anything else | `404 Not Found` with a short text body |
4. **Frame correctly.** Read headers until the blank line, then exactly
   `Content-Length` bytes of body. Your `Content-Length` on the way out must be the
   byte length of the body — not the character count. These differ the moment someone
   POSTs a `£` or an emoji, and you will be tested with one.
5. **Survive a sequence of clients.** Serving one request then exiting is not enough;
   `accept()` in a loop.
6. **Never crash on a malformed request.** No traceback on a truncated request, a
   missing `Content-Length`, a non-numeric one, or a client that connects and sends
   nothing. Respond `400` or close cleanly — your choice, but say which in the report.

Use only the standard library: `socket`, and `urllib.parse` for query decoding.
`http.server`, `http.client`, `socketserver`, `requests`, Flask and friends are out.

## Part 2 — Your client (10 marks)

Write `client.py` that builds request bytes by hand and can send both a `GET` with a
query string and a `POST` with a body. It must set `Host` (HTTP/1.1 requires it),
set `Content-Type` and `Content-Length` when there is a body, print the raw response,
and use `sendall`, not `send`.

Prove it interoperates: your client against your server, and also

```bash
curl -v -X POST -d 'curl says hi' http://127.0.0.1:8080/echo
```

against your server. A protocol only one implementation speaks is not a protocol.

## Part 3 — Capture it in Wireshark (30 marks)

Full procedure, including the loopback trap that catches most people, is in
[`WIRESHARK.md`](WIRESHARK.md). Read it before you start capturing.

Capture one `GET /echo?...` and one `POST /echo` exchange. Save as `capture.pcapng`
— the real file, not only screenshots; we open it.

From the capture, report:

1. The **TCP three-way handshake**. Give the three packet numbers and the flags.
2. The packet carrying your **GET**, and the one carrying the response.
3. The packet carrying your **POST**, and the one carrying the response.
4. **Where the data lives.** For the GET, where in the packet do your parameters
   appear? For the POST? Quote the actual bytes from Wireshark.
5. **Overhead.** For each exchange: bytes of HTTP header vs bytes of body. Then
   total bytes on the wire for one complete request/response including handshake and
   teardown. What fraction of the conversation is payload?
6. The **connection teardown** — which side sends `FIN` first, and why is it that side?

Include annotated screenshots: the packet list showing a full exchange, the expanded
HTTP tree for both the GET and the POST, and one **Follow → TCP Stream** window.

## Part 4 — Break it on purpose (20 marks)

Four experiments. For each: predict first, then run it, then explain the gap between
prediction and result. The prediction being wrong costs nothing; not writing one down
costs marks.

| # | Change in your **client** | Record |
|---|---|---|
| 1 | Send `\n` line endings instead of `\r\n` | Does your server cope? Does `curl`'s? Does a real server — try a site you own, or `example.com` |
| 2 | Omit the `Host` header | What does your server do, and what does a production server answer? |
| 3 | Send `Content-Length: 5` with a 20-byte body, then `Content-Length: 50` with a 20-byte body | Which one stalls and why; which one leaves 15 unread bytes sitting in the stream; and, if the connection were kept alive instead of closed, what those leftover bytes would do to the request that followed |
| 4 | POST a string with a non-ASCII character (`£`, `é`, an emoji) | `len(string)` vs `len(string.encode('utf-8'))`, and whether your server's `Content-Length` was right |

Experiment 3 is the important one. It is the HTTP form of a desynchronised receiver,
and it is why request smuggling exists as a vulnerability class.

## Part 5 — Report (15 marks)

`report.md` or a PDF, around 1,200 words, covering Parts 3 and 4 and answering:

1. TCP gives you a reliable ordered byte stream. Why does HTTP still need
   `Content-Length`? What does TCP not tell the receiver?
2. You read your own POST body in cleartext in Wireshark. Does HTTPS change what is
   visible, and what remains visible even with TLS?
3. Your GET parameters appear in the request line. List two places that request line
   gets recorded that the POST body does not. What follows for designing a login form?
4. One `recv()` call is not one message. Show the line of your server that handles
   this and explain what breaks without it.
5. Two clients connect at once. What does your single-threaded server do to the
   second one, and what would you change?

## What to submit

```
<your-id>-http-sockets/
  server.py
  client.py
  capture.pcapng
  report.md
  screenshots/
  transcripts/     server + client terminal output for both GET and POST
```

Do not submit a capture of someone else's traffic, and do not capture on a shared or
campus network — loopback only, or a link you own. See the note at the end of
[`WIRESHARK.md`](WIRESHARK.md).

## Common failure modes

| symptom | cause |
|---|---|
| `OSError: [Errno 98] Address already in use` | previous server in `TIME_WAIT`; set `SO_REUSEADDR`, or wait ~60 s |
| Client hangs forever after sending | `Content-Length` too large, or server waiting for a body that already arrived — your header loop never terminated |
| Browser shows the page but spins forever | missing or short `Content-Length`; browser is waiting for the rest |
| Response body truncated | `Content-Length` counted characters, not bytes |
| Wireshark shows nothing on 8080 | capturing on the wrong interface — loopback is not your Ethernet or Wi-Fi adapter |
| Wireshark shows TCP but no HTTP | **Decode As → HTTP**, or you are looking at a packet with no payload |
| Everything is `[TCP segment of a reassembled PDU]` | normal; the dissector shows the assembled message on the last segment |

## Stretch (no marks, more interesting)

- Serve concurrent clients with `threading`, then with `selectors` and one thread.
- Implement `Connection: keep-alive`: two requests, one TCP connection. Watch the
  handshake you no longer pay for.
- Add `Transfer-Encoding: chunked` and see how the body gets framed without a length.
- Serve a real file with a correct `Content-Type` and a `404` for a missing path.
- Time 100 sequential requests with keep-alive on and off. Explain the difference in
  terms of RTTs, not milliseconds.
