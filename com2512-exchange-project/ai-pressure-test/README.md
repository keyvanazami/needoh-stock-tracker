# B-Stack — AI pressure test of the Networking Project plan

All five phases of the "Bespoke Overlay Stack" project, implemented from the
project plan's prose alone (no student input) and verified by running them.

    python3 demo_phase1.py   # bespoke TLV framing + stateful FSM over TCP
    python3 demo_phase2.py   # Go-Back-N R-UDP through a loss/corruption emulator
    python3 demo_phase3.py   # distance-vector overlay mesh, live router failure
    python3 demo_phase4.py   # CSMA/CD contention + AIMD congestion sawtooth
    python3 demo_phase5.py   # X25519/Ed25519 1-RTT handshake + Slow Loris defense
    python3 bench_droop.py   # thread-per-connection vs async throughput droop

Phase 5 needs a working `cryptography` (the stock one in some images is missing
`_cffi_backend`): `pip install --target ./pylibs cffi cryptography` then run with
`PYTHONPATH=./pylibs`.

## Modules

| file            | phase | what it is |
|-----------------|-------|------------|
| `framing.py`    | 1     | BSBFF/1 wire format: 15B header, TLV block, XOR checksum, hexdump |
| `app.py`        | 1     | Stateful KV/transaction protocol, server FSM + client |
| `rudp.py`       | 2,4   | Go-Back-N over a Channel abstraction, Internet checksum, AIMD |
| `netem.py`      | 2     | Emulator proxy: loss, corruption, delay, duplication (seeded) |
| `mesh.py`       | 3     | Overlay routing node, distance-vector w/ poisoned reverse |
| `csma.py`       | 4     | Shared medium w/ carrier sense, collision detect, backoff; token ring |
| `handshake.py`  | 5     | 1-RTT ECDH + Ed25519 transcript signature, AEAD record layer |

## Notes on what was hard

The three CSMA models in `csma.py` git history are the interesting part: the
first two ran cleanly and reported zero collisions. See the comments in
`SharedMedium.__init__` for the two traps.
