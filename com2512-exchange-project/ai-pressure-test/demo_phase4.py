"""Phase 4 demo: CSMA/CD contention on a shared medium + AIMD congestion control
with an ASCII cwnd sawtooth (the "analyzer graph" the rubric asks for)."""

import asyncio
import time

from csma import SLOT, SharedMedium, TokenRing
from netem import LinkProfile, NetemProxy
from rudp import RudpConn, UdpChannel


async def csma_run(n_stations, frames_each, seed=7):
    medium = SharedMedium(seed=seed)
    for i in range(n_stations):
        medium.attach(i, lambda src, d: None)

    async def station(i):
        for _ in range(frames_each):
            await medium.transmit(i, b"x" * 64, duration=SLOT)

    t0 = time.monotonic()
    await asyncio.gather(*(station(i) for i in range(n_stations)))
    el = time.monotonic() - t0
    offered = n_stations * frames_each
    util = medium.stats.busy_time / el if el else 0
    return medium.stats, el, offered, util


async def token_run(n_stations, frames_each):
    ring = TokenRing(range(n_stations))

    async def station(i):
        for _ in range(frames_each):
            await ring.transmit(i, b"x" * 64, duration=SLOT)

    t0 = time.monotonic()
    await asyncio.gather(*(station(i) for i in range(n_stations)))
    el = time.monotonic() - t0
    return ring.stats, el


def sawtooth(trace, height=14, width=76):
    """Render cwnd over time as an ASCII graph."""
    if not trace:
        return "  (no trace)"
    t0 = trace[0][0]
    span = max(trace[-1][0] - t0, 1e-6)
    peak = max(c for _, c, _ in trace)
    grid = [[" "] * width for _ in range(height)]
    for t, c, why in trace:
        x = min(width - 1, int((t - t0) / span * (width - 1)))
        y = height - 1 - min(height - 1, int(c / peak * (height - 1)))
        grid[y][x] = "!" if why == "loss" else "*"
    lines = []
    for i, row in enumerate(grid):
        label = f"{peak * (height - 1 - i) / (height - 1):5.1f} |"
        lines.append("  " + label + "".join(row))
    lines.append("  " + " " * 6 + "+" + "-" * (width - 1))
    lines.append("  " + " " * 7 + f"0s{' ' * (width - 12)}{span:.2f}s")
    lines.append("        (* = ACK-driven growth, ! = loss -> multiplicative decrease)")
    return "\n".join(lines)


async def aimd_run(loss, seed):
    srv_ch = await UdpChannel.create()
    srv_conn = RudpConn(srv_ch, name="sink", window=64)

    async def sink():
        try:
            while True:
                await srv_conn.readexactly(1024)
        except Exception:
            pass

    sink_task = asyncio.create_task(sink())
    proxy = await NetemProxy.create(srv_ch.sockname, LinkProfile(loss=loss, seed=seed))
    cli_ch = await UdpChannel.create(peer=proxy.sockname)
    cli = RudpConn(cli_ch, name="src", window=64, cc=True)

    payload = b"Z" * (200 * 1024)  # 200 KB
    t0 = time.monotonic()
    cli.write(payload)
    ok = await cli.flush(timeout=40)
    el = time.monotonic() - t0
    goodput = len(payload) / el / 1024

    result = (ok, el, goodput, cli.stats, list(cli.cwnd_trace), max(c for _, c, _ in cli.cwnd_trace))
    cli.close()
    srv_conn.close()
    sink_task.cancel()
    cli_ch.close()
    srv_ch.close()
    proxy.close()
    await asyncio.sleep(0.05)
    return result


async def main():
    print("== Phase 4a: CSMA/CD collision domain vs token passing ==\n")
    print(f"  {'stations':<10}{'frames':<9}{'collisions':<12}{'backoff-slots':<15}"
          f"{'elapsed':<10}{'utilisation'}")
    for n in (2, 5, 10, 20):
        stats, el, offered, util = await csma_run(n, 20)
        print(f"  {n:<10}{offered:<9}{stats.collisions:<12}{stats.backoff_slots:<15}"
              f"{el:<10.3f}{util:.0%}")
    print("\n  same offered load on a token ring (collision-free):")
    for n in (2, 10, 20):
        stats, el = await token_run(n, 20)
        print(f"  {n:<10}{n*20:<9}{stats.collisions:<12}{'-':<15}{el:<10.3f}"
              f"{stats.busy_time/el:.0%}")

    print("\n\n== Phase 4b: AIMD congestion control over a lossy link ==\n")
    for loss, seed in ((0.02, 11), (0.08, 12)):
        ok, el, goodput, stats, trace, peak = await aimd_run(loss, seed)
        print(f"  link loss {loss:.0%}: transferred 200KB in {el:.2f}s "
              f"({goodput:.0f} KB/s), peak cwnd {peak:.1f} segs, complete={ok}")
        print(f"    {stats}")
        print(sawtooth(trace))
        print()


asyncio.run(main())
