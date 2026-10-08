# Assignment — HTTP over a raw socket

Write an HTTP echo server and an HTTP client using nothing but TCP sockets, then
capture your own requests in Wireshark.

HTTP is a text protocol over a byte stream, and a byte stream has no message
boundaries — so HTTP invents its own out of CRLFs, a blank line and
`Content-Length`. You will not see that from behind `requests.post()`. You see it
by writing the bytes.

**Submit:** your `server.py`, your `client.py`, `capture.pcapng`, and `screenshots/`.
No report.

## Files

| | |
|---|---|
| `sockets_demo.py` | the socket calls, in plain TCP, no HTTP. Read this first |
| `starter/server.py` | skeleton, 6 TODOs |
| `starter/client.py` | skeleton, 3 TODOs |
| `starter/check.py` | tests your server; run it as you work |
| `WIRESHARK.md` | capture procedure and the loopback trap — read before capturing |

Python 3.10+. Nothing to install. Work in a copy of `starter/`.

## 1. See the sockets work

```bash
python3 sockets_demo.py listen          # terminal 1
python3 sockets_demo.py send "hello"    # terminal 2
```

Plain TCP, both halves, about 40 lines each. Every call you need for the
assignment is in there: `socket`, `setsockopt`, `bind`, `listen`, `accept`,
`recv`, `sendall`, `connect`, `close`.

The one idea to take from it: **`recv()` is not "receive a message."** It returns
whatever bytes have arrived — maybe all of them, maybe three. So you loop. Nearly
every bug in this assignment is a version of forgetting that.

## 2. Build the server — 6 TODOs

In `server.py`. Each TODO's docstring states the requirement.

| | |
|---|---|
| 1 | `content_length()` — parse the header; 0 if missing or not a number |
| 2 | `recv_request()` — read headers to the blank line, then exactly `Content-Length` body bytes |
| 3 | `build_response()` — status line, headers, blank line, body |
| 4 | `handle()` — route: `GET /echo?...` lists the query params, `POST /echo` echoes the body, anything else `404` |
| 5 | `serve()` — the listening socket and the accept loop |
| 6 | echo each request to stdout, complete and unmodified |

Listen on `127.0.0.1:8080`. Port 8080 rather than 80 because ports below 1024 need
root, and Wireshark dissects 8080 as HTTP by default.

Two requirements worth calling out, because they are where implementations usually go wrong:

- **`Content-Length` is a byte count, not a character count.** `len('£')` is 1;
  it is 2 bytes in UTF-8. `check.py` POSTs you a `£`.
- **Your server must not crash.** A truncated request, a missing or non-numeric
  `Content-Length`, or a client that connects and sends nothing must not produce
  a traceback.

Check your work:

```bash
cd starter && python3 check.py        # 10 checks
```

It sends raw HTTP itself, so it works before your client exists. It does not
check your client, capture or screenshots.

## 3. Build the client — 3 TODOs

In `client.py`.

| | |
|---|---|
| 1 | `build_request()` — request line, `Host`, `Content-Type`/`Content-Length` when there's a body, CRLFs throughout |
| 2 | `send_request()` — connect, `sendall`, read until EOF |
| 3 | print the raw response |

It must do a GET with a query string and a POST with a body:

```bash
python3 client.py --path '/echo?name=ada&unit=7'
python3 client.py -X POST --data 'hello from COM2512' --path /echo
python3 client.py -X POST --form name=ada --form unit=7 --path /echo
```

Then prove it interoperates — a protocol only one implementation speaks is not a
protocol:

```bash
curl -v -X POST -d 'curl says hi' http://127.0.0.1:8080/echo   # curl -> your server
```

Only `socket`, `urllib.parse`, `argparse`, `sys`. No `requests`, `http.client`,
`http.server` or `socketserver` in either file — they'd do the assignment for you.

## 4. Capture it — screenshots

Procedure and the loopback-interface trap are in [`WIRESHARK.md`](WIRESHARK.md).
Read it first; capturing on `eth0` while talking to `127.0.0.1` shows an empty
window, correctly.

Capture one `GET /echo?...` and one `POST /echo`. Save `capture.pcapng` — the real
file, we open it. Then screenshot, with the relevant part annotated or circled:

1. The packet list for a full exchange, with the **three-way handshake** visible.
2. The expanded **HTTP tree for your GET** — show where the query parameters sit.
3. The expanded **HTTP tree for your POST** — show where the body sits.
4. **Follow → TCP Stream** for either one.
5. Your server's **terminal output** echoing both requests.

Screenshots 2 and 3 are the point of the whole exercise: the same data, in two
different places on the wire, with different consequences for what gets logged.

## Submit

```
<your-id>-http-sockets/
  server.py
  client.py
  capture.pcapng
  screenshots/
```

Capture on loopback only, or a link you own — never campus Wi-Fi or a shared lab
segment. See the note at the end of `WIRESHARK.md`.

## Gotchas

| symptom | cause |
|---|---|
| `Errno 98 Address already in use` | missing `SO_REUSEADDR`, or wait ~60s for `TIME_WAIT` |
| Client hangs after sending | `Content-Length` too large, or your header loop never found the blank line |
| Browser renders but keeps spinning | `Content-Length` short or missing |
| Response body truncated | you counted characters, not bytes |
| Wireshark shows nothing on 8080 | wrong interface — loopback is not your Ethernet or Wi-Fi adapter |
| TCP packets but no HTTP | **Decode As → HTTP**, or you clicked a packet with no payload |
| `[TCP segment of a reassembled PDU]` | normal — the assembled message shows on the last segment |

## If you finish early

Try these — nothing to submit, but they are where the protocol gets interesting.

- Send `\n` instead of `\r\n`. Does your server cope? Does `curl`? Does a real server?
- Drop the `Host` header. Yours answers how? A production server?
- Send `Content-Length: 5` with a 20-byte body, then `50` with a 20-byte body. One
  stalls; the other leaves 15 unread bytes in the stream. On a keep-alive
  connection those bytes become the start of the *next* request — which is request
  smuggling, in miniature.
- Serve two clients at once with `threading`, then with `selectors` and one thread.
- Implement `Connection: keep-alive` and watch the handshake you stop paying for.
