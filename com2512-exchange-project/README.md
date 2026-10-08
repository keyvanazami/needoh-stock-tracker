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
A standalone HTTP lab: students write an echo server and a client on raw TCP sockets
(port 8080), echo requests to stdout, and capture their own GET and POST exchanges in
Wireshark. Needs no exchange hardware and no network access.

    cd http-sockets/sample && python3 selftest.py    # 4/4, proves the reference code runs

| path | what it is |
|---|---|
| `README.md`    | the handout: five graded parts, 100 marks |
| `WIRESHARK.md` | capture procedure, the loopback-interface trap, display filters |
| `RUBRIC.md`    | mark breakdown and deductions |
| `sample/echo_server.py` | reference listen socket: framing, `SO_REUSEADDR`, partial `recv` |
| `sample/http_client.py` | reference send socket: requests assembled byte by byte |
| `sample/selftest.py`    | end-to-end check of both, on an ephemeral port |

The graded deliverable extends the sample rather than reusing it: routing, a `404`, and
correct `Content-Length` for non-ASCII bodies. Part 4 has students break framing on
purpose — a short `Content-Length` leaves unread bytes in the stream, which is request
smuggling in miniature.

## Key numbers

| quantity | value | why it matters |
|---|---|---|
| CSMA `a` on a lab bench | ~3×10⁻⁶ | efficiency 0.99998 — collisions never happen without the repeater |
| time-dilation factor K | 16.1× | makes the lab a scale model of Chicago–NJ |
| spool setting | 71.5 ms | derived from K, not chosen |
| radio byte budget @ 10 Hz | 12.5 B/update | forces a compressed top-of-book format |
| SRAM budget | 1,644 / 2,048 B | ~80%, real headroom but no slack |
