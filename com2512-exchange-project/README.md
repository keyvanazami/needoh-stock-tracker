# COM2512 — the exchange project

Course materials for a physical trading-exchange project spanning all seven units of
COM2512. Unrelated to the NeeDoh tracker in the rest of this repository; it lives on
this branch only, so deleting the branch removes it cleanly.

## What's here

### `hardware-reference/` — the instructor build
Portable C++ that compiles unchanged for AVR and for the host, plus the three Arduino
sketches the course depends on.

    cd hardware-reference && make test     # 19 assertions, no hardware needed

| path | what it is |
|---|---|
| `lib/bframe.*`       | frame format + CRC-16/CCITT-FALSE. Check value `crc16("123456789") == 0x29B1` |
| `lib/manchester.*`   | Manchester line coding for the radio path, with code-violation sync |
| `lib/delayline.h`    | the repeater core: a sampled circular **bit** buffer |
| `lib/arbitration.h`  | wired-AND bitwise arbitration, in software for tests |
| `test/test_host.cpp` | 19 host assertions covering all of the above |
| `vectors/acceptance.txt` | byte-exact vectors a student build must reproduce |
| `arduino/repeater/`  | **build this first** — the calibrated delay instrument |
| `arduino/busnode/`   | a station on the pit: carrier sense, arbitration, backoff |
| `arduino/dualrx/`    | the wire-vs-radio measurement rig (needs no clock sync) |

Two things that are easy to get wrong:

1. **The repeater must delay bits, not frames.** A store-and-forward relay serialises the
   bus and makes collisions impossible — destroying the phenomenon it exists to create.
2. **Run the bus at 2400 baud, not 9600.** At 9600 the sampling ISR has 208 CPU cycles;
   at 2400 it has 833, and the delay range grows from 167 ms to 667 ms.

### `ai-pressure-test/` — the B-Stack evaluation
The earlier "how much of this can AI just do" test: all five phases of the proposed
B-Stack project, implemented from the plan's prose alone and run.

    cd ai-pressure-test && python3 demo_phase1.py   # ... through demo_phase5.py

Phase 5 needs a working `cryptography` (some images ship one missing `_cffi_backend`):
`pip install --target ./pylibs cffi cryptography`, then run with `PYTHONPATH=./pylibs`.

Headline results: Go-Back-N completed full transactions on 5 of 5 link profiles including
40% loss + 20% corruption with no deadlock; the overlay mesh rerouted around a router
killed mid-transfer with 0 packets through the dead node; all five crypto attacks were
rejected. The CSMA/CD emulator reported **zero collisions across three successive
implementations** while appearing to work — which is the finding the whole hardware
design is built around.

### `http-sockets/` — the application-layer assignment
A standalone HTTP lab: students build an echo server and a client on raw TCP sockets
(port 8080), echo requests to stdout, and capture their own GET and POST exchanges in
Wireshark. No exchange hardware, no network access. Deliverables are code and
screenshots — no write-up.

    cd http-sockets && python3 sockets_demo.py listen    # the socket calls, plain TCP
    cd http-sockets/starter && python3 check.py          # grades a student server, 10 checks

| path | what it is |
|---|---|
| `README.md`      | the handout |
| `WIRESHARK.md`   | capture procedure, the loopback-interface trap, display filters |
| `sockets_demo.py`| the six socket calls in plain TCP — no HTTP, nothing to fill in |
| `starter/server.py` | skeleton, 6 TODOs: framing, routing, accept loop |
| `starter/client.py` | skeleton, 3 TODOs: request bytes, connect/send/recv |
| `starter/check.py`  | conformance checks students run as they work |

`check.py` is the marking tool: it sends raw HTTP over a socket so it works before the
student's client exists, and it catches the two failures that otherwise slip through —
a `Content-Length` that counts characters instead of bytes, and a `recv()` loop that
only works because the request happened to arrive in one segment. Validated against a
reference solution (10/10) and against the untouched starter, which fails pointing at
TODO 5.

No reference solution ships in this directory, deliberately.

## Key numbers

| quantity | value | why it matters |
|---|---|---|
| CSMA `a` on a lab bench | ~3×10⁻⁶ | efficiency 0.99998 — collisions never happen without the repeater |
| time-dilation factor K | 16.1× | makes the lab a scale model of Chicago–NJ |
| spool setting | 71.5 ms | derived from K, not chosen |
| radio byte budget @ 10 Hz | 12.5 B/update | forces a compressed top-of-book format |
| SRAM budget | 1,644 / 2,048 B | ~80%, real headroom but no slack |
