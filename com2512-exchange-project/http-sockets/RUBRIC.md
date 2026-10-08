# Marking — HTTP over a raw socket

100 marks. Anything using `http.server`, `http.client`, `socketserver`, `requests`,
Flask or an equivalent for the graded parts scores 0 on Parts 1 and 2 — the point of
the exercise is the bytes you write yourself.

## Part 1 — Server (25)

| | marks |
|---|---|
| Listens on 8080 with `SO_REUSEADDR`; accepts in a loop and serves successive clients | 5 |
| Echoes the complete request to stdout, headers and body, unmodified | 4 |
| Header/body split handled correctly: reads to the blank line, then exactly `Content-Length` bytes, looping on partial `recv` | 6 |
| Routing: `GET /echo` parses the query, `POST /echo` returns the body, everything else `404` | 5 |
| Outgoing `Content-Length` is a byte count and is correct for non-ASCII bodies | 3 |
| No traceback on a truncated request, missing or non-numeric `Content-Length`, or a client that sends nothing | 2 |

A server that only works because the request happened to arrive in one `recv()` loses
the 6 framing marks even though it appears to work. We test with a slow client that
sends the headers and the body in separate writes.

## Part 2 — Client (10)

| | marks |
|---|---|
| Builds the request by hand with correct CRLFs and a blank line before the body | 3 |
| Sets `Host`; sets `Content-Type` and `Content-Length` when there is a body | 3 |
| Sends both a GET with a query string and a POST with a body; prints the raw response | 2 |
| Uses `sendall`, and reads the response until EOF rather than assuming one `recv` | 2 |

## Part 3 — Capture (30)

| | marks |
|---|---|
| `capture.pcapng` present, opens cleanly, contains a complete GET and a complete POST exchange | 6 |
| Handshake identified by packet number with correct flags | 4 |
| Request and response packets identified for both methods | 4 |
| Where the data lives: parameters located in the request line for GET, in the body for POST, with bytes quoted from the capture | 6 |
| Overhead figures: header vs body bytes, total conversation bytes, payload fraction — arithmetic shown | 5 |
| Teardown: which side sends `FIN` first, with a correct reason | 3 |
| Screenshots: packet list, expanded HTTP tree for both methods, one Follow-stream window, annotated | 2 |

Full marks on the overhead question require noting that loopback segment sizes make the
ratio unrepresentative of a real link.

## Part 4 — Experiments (20)

5 marks each. For each: a prediction recorded *before* running, the observed result
with evidence, and an explanation of any difference. A correct prediction with no
explanation scores 2; a wrong prediction well explained scores 5.

| | |
|---|---|
| 1 | `\n` instead of `\r\n` — tested against your server and at least one other implementation |
| 2 | Missing `Host` — your server vs a production server |
| 3 | `Content-Length` too small and too large — identifies which stalls, which leaves unread bytes in the stream, and what those bytes would do to a following request on a persistent connection |
| 4 | Non-ASCII body — character count vs byte count, and whether the header was right |

Experiment 3 earns the full 5 only if the answer connects a desynchronised receiver to
why mismatched length headers are a security problem, not only a bug.

## Part 5 — Report (15)

| | marks |
|---|---|
| Q1 Why `Content-Length` when TCP is already reliable and ordered | 3 |
| Q2 What TLS hides and what it still leaks | 3 |
| Q3 Where GET query strings get logged, and the consequence for login forms | 3 |
| Q4 One `recv()` is not one message — cites the student's own line of code | 3 |
| Q5 Concurrent clients: what the single-threaded server does, and the fix | 3 |

Clear prose, readable figures, captioned screenshots. Length is not a grading criterion
and padding is visible.

## Deductions

| | |
|---|---|
| Capture contains third-party traffic, or was taken on a shared network | −20 and referred, per the note in `WIRESHARK.md` |
| `capture.pcapng` missing, screenshots only | −10 |
| Code does not run as submitted, with no instructions explaining why | −10 |
| Submission structure does not match the handout | −3 |
