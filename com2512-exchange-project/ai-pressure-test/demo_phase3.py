"""Phase 3 demo: Phase 1 protocol over Phase 2 R-UDP over a multi-hop overlay mesh,
surviving the death of the router it was using mid-transaction.

Topology (link costs in brackets):

        C(1) --[1]-- R1(2) --[1]-- R2(3) --[1]-- R3(5) --[1]-- S(6)
                       \                          /
                        \--[3]-- R4(4) --[1]-----/

Primary path is C-R1-R2-R3-S (cost 4). Kill R2 and traffic must re-route via
R4 (cost 6) with no help from the application layer.
"""

import asyncio

from app import Client, Store, serve_session
from framing import TLV_STATUS
from mesh import MeshChannel, RoutingNode, wait_for_convergence
from rudp import RudpConn

C, R1, R2, R4, R3, S = 1, 2, 3, 4, 5, 6
NAMES = {1: "C", 2: "R1", 3: "R2", 4: "R4", 5: "R3", 6: "S"}


def st(r):
    return int(r.gets(TLV_STATUS, "0"))


def link(a, b, cost=1):
    a.add_link(b.id, b.sockname, cost)
    b.add_link(a.id, a.sockname, cost)


async def main():
    print("== Phase 3: overlay routed mesh, distance-vector, live link failure ==\n")

    nodes = {}
    for nid in (C, R1, R2, R4, R3, S):
        nodes[nid] = await RoutingNode.create(nid, NAMES[nid])
    c, r1, r2, r4, r3, s = (nodes[i] for i in (C, R1, R2, R4, R3, S))

    link(c, r1, 1)
    link(r1, r2, 1)
    link(r1, r4, 3)
    link(r2, r3, 1)
    link(r4, r3, 1)
    link(r3, s, 1)

    for n in nodes.values():
        n.start()

    converged = await wait_for_convergence(list(nodes.values()), list(nodes), timeout=6)
    print(f"DV converged: {converged}")
    for nid in (C, R1, R2, R4, R3, S):
        print(f"  {NAMES[nid]:<3} {nodes[nid].route_str()}")

    hop, cost = c.table[S]
    print(f"\n  C's route to S: next hop {NAMES[hop]}, cost {cost} (expect via R1, cost 4)")

    # --- app stack rides the mesh ---
    store = Store()
    srv_conn = RudpConn(MeshChannel(s, C), name="server")
    srv_task = asyncio.create_task(serve_session(srv_conn, srv_conn, store, 1))
    cli_conn = RudpConn(MeshChannel(c, S), name="client")
    cli = Client(cli_conn, cli_conn)

    print("\n  transaction over the healthy mesh:")
    print("    HELO   ->", st(await asyncio.wait_for(cli.helo(), 10)))
    print("    AUTH   ->", st(await asyncio.wait_for(cli.auth("alice", "s3cr3t"), 10)))
    print("    LOCK   ->", st(await asyncio.wait_for(cli.lock("k"), 10)))
    print("    PUT    ->", st(await asyncio.wait_for(cli.put("k", b"before-failure"), 10)))
    print("    COMMIT ->", st(await asyncio.wait_for(cli.commit(), 10)))
    print(f"    R2 forwarded {r2.forwarded} pkts, R4 forwarded {r4.forwarded} pkts")

    # --- kill the router in the middle of a live transaction ---
    print("\n  *** killing R2 during an in-flight transaction ***")
    await asyncio.wait_for(cli.lock("k2"), 10)
    blob = b"AFTER-FAILURE-PAYLOAD;" * 300  # ~6.6 KB, many GBN segments

    snap = {}

    async def kill_soon():
        await asyncio.sleep(0.05)
        snap["r2"], snap["r4"] = r2.forwarded, r4.forwarded
        r2.stop()

    killer = asyncio.create_task(kill_soon())
    put_status = st(await asyncio.wait_for(cli.put("k2", blob), 30))
    await killer
    r2_before, r4_before = snap["r2"], snap["r4"]
    print(f"    PUT across the failure -> {put_status} (want 240)")

    # wait for the *cost* to settle, not merely for entries to exist
    async def wait_cost(node, dest, want, timeout=8.0):
        loop = asyncio.get_event_loop()
        end = loop.time() + timeout
        while loop.time() < end:
            if node.table.get(dest, (None, None))[1] == want:
                return True
            await asyncio.sleep(0.05)
        return False

    reconv = await wait_cost(c, S, 6)
    hop2, cost2 = c.table.get(S, (None, None))
    print(f"    re-converged: {reconv}; C's route to S now next hop "
          f"{NAMES.get(hop2)}, cost {cost2} (expect via R1, cost 6)")

    g = await asyncio.wait_for(cli.get("k2"), 20)
    print(f"    GET after reroute -> {st(g)}, {len(g.payload)}B, intact={g.payload == blob}")
    print("    COMMIT ->", st(await asyncio.wait_for(cli.commit(), 20)))

    print(f"\n    R2 forwarded {r2.forwarded - r2_before} pkts after death (want 0)")
    print(f"    R4 forwarded {r4.forwarded - r4_before} pkts after death (want > 0)")
    print(f"    routing recomputes: " + ", ".join(
        f"{NAMES[n]}={nodes[n].recomputes}" for n in (C, R1, R4, R3, S)))
    print(f"    client GBN: {cli_conn.stats}")

    cli_conn.close()
    srv_conn.close()
    srv_task.cancel()
    for n in nodes.values():
        n.close()
    await asyncio.sleep(0.05)


asyncio.run(main())
