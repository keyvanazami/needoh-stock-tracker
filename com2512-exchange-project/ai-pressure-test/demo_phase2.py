"""Phase 2 demo: the Phase 1 app protocol, unmodified, over Go-Back-N R-UDP,
through an emulator that loses / corrupts / delays / duplicates datagrams."""

import asyncio

from app import Client, Store, serve_session
from framing import TLV_STATUS
from netem import LinkProfile, NetemProxy
from rudp import RudpConn, UdpChannel


def st(r):
    return int(r.gets(TLV_STATUS, "0"))


async def run_profile(label, profile):
    store = Store()

    # --- server: UDP socket + R-UDP + the same serve_session() from Phase 1 ---
    srv_ch = await UdpChannel.create()
    srv_addr = srv_ch.sockname
    srv_conn = RudpConn(srv_ch, name="server")
    srv_task = asyncio.create_task(serve_session(srv_conn, srv_conn, store, 1))

    # --- the abusive middle ---
    proxy = await NetemProxy.create(srv_addr, profile)

    # --- client ---
    cli_ch = await UdpChannel.create(peer=proxy.sockname)
    cli_conn = RudpConn(cli_ch, name="client")
    c = Client(cli_conn, cli_conn)

    ok = True
    try:
        ok &= st(await asyncio.wait_for(c.helo(), 15)) == 210
        ok &= st(await asyncio.wait_for(c.auth("alice", "s3cr3t"), 15)) == 220
        ok &= st(await asyncio.wait_for(c.lock("inventory/needoh"), 15)) == 230
        # a payload big enough to span many GBN segments
        blob = b"NEEDOH-GROOVY-GLOB;" * 400  # ~7.6 KB -> ~15 segments
        ok &= st(await asyncio.wait_for(c.put("inventory/needoh", blob), 20)) == 240
        g = await asyncio.wait_for(c.get("inventory/needoh"), 20)
        ok &= st(g) == 241 and g.payload == blob
        ok &= st(await asyncio.wait_for(c.commit(), 15)) == 250
        verdict = "PASS" if ok else "WRONG-RESULT"
    except asyncio.TimeoutError:
        verdict = "DEADLOCK/TIMEOUT"
    except Exception as e:
        verdict = f"ERROR {type(e).__name__}: {e}"

    print(f"  {label:<34} {verdict}")
    print(f"      link      : {profile}")
    print(f"      emulator  : {proxy.stats}")
    print(f"      client GBN: {cli_conn.stats}")
    print(f"      server GBN: {srv_conn.stats}")

    cli_conn.close()
    srv_conn.close()
    srv_task.cancel()
    cli_ch.close()
    srv_ch.close()
    proxy.close()
    await asyncio.sleep(0.05)
    return verdict == "PASS"


async def main():
    print("== Phase 2: app protocol over Go-Back-N R-UDP through a hostile link ==\n")
    profiles = [
        ("clean link", LinkProfile(seed=1)),
        ("10% loss", LinkProfile(loss=0.10, seed=2)),
        ("20% loss + 10% corruption", LinkProfile(loss=0.20, corrupt=0.10, seed=3)),
        ("30% loss + jitter + dup", LinkProfile(loss=0.30, dup=0.05, delay=(0.001, 0.020), seed=4)),
        ("40% loss + 20% corrupt + jitter", LinkProfile(loss=0.40, corrupt=0.20,
                                                       delay=(0.001, 0.015), seed=5)),
    ]
    results = []
    for label, p in profiles:
        results.append(await run_profile(label, p))
        print()
    print(f"  {sum(results)}/{len(results)} profiles completed the full transaction")


asyncio.run(main())
