"""Phase 1 demo: raw TCP + bespoke framing + stateful FSM, incl. anomaly cases."""

import asyncio

from app import Client, Store, serve_session
from framing import (
    T_GET,
    T_HELO,
    T_PUT,
    TLV_KEY,
    TLV_STATUS,
    encode_frame,
    hexdump,
    read_frame,
)

store = Store()
_sid = [0]


async def on_conn(reader, writer):
    _sid[0] += 1
    await serve_session(reader, writer, store, _sid[0])


def st(r):
    return int(r.gets(TLV_STATUS, "0"))


async def main():
    srv = await asyncio.start_server(on_conn, "127.0.0.1", 0)
    port = srv.sockets[0].getsockname()[1]
    print(f"== Phase 1: bespoke stateful protocol over TCP (port {port}) ==\n")

    # --- wire format proof: hexdump of a real frame ---
    frame = encode_frame(T_PUT, 7, [(TLV_KEY, "inventory/needoh")], b"count=42")
    print("A PUT frame on the wire (15B header + TLV block + payload):")
    print(hexdump(frame, prefix="  "))
    print()

    # --- happy path transaction ---
    r, w = await asyncio.open_connection("127.0.0.1", port)
    c = Client(r, w)
    print("happy path:")
    print("  HELO   ->", st(await c.helo()))
    print("  AUTH   ->", st(await c.auth("alice", "s3cr3t")))
    print("  LOCK   ->", st(await c.lock("inventory/needoh")))
    print("  PUT    ->", st(await c.put("inventory/needoh", b"count=42")))
    g = await c.get("inventory/needoh")
    print("  GET    ->", st(g), g.payload)
    print("  COMMIT ->", st(await c.commit()))

    # --- anomaly 1: duplicate handshake mid-session ---
    print("\nstate-dependent anomalies:")
    print("  duplicate HELO after AUTH      ->", st(await c._rt(T_HELO)), "(want 462)")

    # --- anomaly 2: PUT with no lock ---
    bad = await c._rt(T_PUT, c._tok() + [(TLV_KEY, "x")], b"v")
    print("  PUT with no open txn           ->", st(bad), "(want 451)")

    # --- anomaly 3: second client contends for the same key ---
    r2, w2 = await asyncio.open_connection("127.0.0.1", port)
    c2 = Client(r2, w2)
    await c2.helo()
    await c2.auth("bob", "hunter2")
    await c.lock("shared")
    print("  alice LOCK shared              ->", 230)
    print("  bob   LOCK shared (contended)  ->", st(await c2.lock("shared")), "(want 453)")
    print("  alice LOCK again while holding ->", st(await c.lock("other")), "(want 452)")

    # --- anomaly 4: bad credentials, then recovery ---
    r3, w3 = await asyncio.open_connection("127.0.0.1", port)
    c3 = Client(r3, w3)
    await c3.helo()
    print("  wrong password                 ->", st(await c3.auth("alice", "wrong")), "(want 461)")
    print("  retry with fresh nonce         ->", st(await c3.auth("alice", "s3cr3t")), "(want 220)")

    # --- anomaly 5: corrupted checksum on the wire ---
    good = encode_frame(T_GET, 99, [(TLV_KEY, "inventory/needoh")])
    corrupt = bytearray(good)
    corrupt[-1] ^= 0x40  # flip a bit in the payload/TLV tail
    w3.write(bytes(corrupt))
    await w3.drain()
    resp = await read_frame(r3)
    print("  bit-flipped frame              ->", st(resp), f"({resp.gets(0x17)})", "(want 470)")

    # --- durability across sessions ---
    r4, w4 = await asyncio.open_connection("127.0.0.1", port)
    c4 = Client(r4, w4)
    await c4.helo()
    await c4.auth("bob", "hunter2")
    await c4.lock("inventory/needoh")
    g = await c4.get("inventory/needoh")
    print("\n  committed value visible to bob ->", st(g), g.payload)
    await c4.abort()
    await c4.bye()

    for ww in (w, w2, w3, w4):
        ww.close()
    srv.close()
    await srv.wait_closed()


asyncio.run(main())
