"""Drive one client against the exchange and report what the transport cost.

    python -m client.bench --host 10.0.0.4 --transport tcp --firm 0x21
    python -m client.bench --host 10.0.0.4 --transport all --orders 200

The point is the comparison table, not any single number. Run all three under
`--impair clean` and the differences are mostly bytes; run them again while the
instructor is holding `wifi-busy` or `lossy` and the differences become fills.
"""

from __future__ import annotations

import argparse
import random
import statistics
import sys
import time
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from client.reference import CLIENTS


def run(transport, host, ports, firm, orders, ticker, seed):
    cls = CLIENTS[transport]
    port = ports[transport]
    c = cls(host, port, firm, name=f"bench-{transport}")
    rng = random.Random(seed)
    time.sleep(0.2)
    c.poll(0.2)

    rtts, acked, sent = [], 0, 0
    t_start = time.perf_counter()
    for i in range(orders):
        side = rng.randrange(2)
        px = 10000 + rng.randrange(-40, 41)
        qty = rng.randrange(1, 6)
        t0 = time.perf_counter()
        if transport == "rest":
            r = c.order(ticker, side, px, qty, i + 1)
            rtts.append((time.perf_counter() - t0) * 1000)
            acked += r.get("type") == "ACK"
        else:
            before = c.acks
            c.order(ticker, side, px, qty, i + 1)
            deadline = time.perf_counter() + 4.0
            while c.acks == before and time.perf_counter() < deadline:
                c.poll(0.01)
            if c.acks > before:
                rtts.append((time.perf_counter() - t0) * 1000)
                acked += 1
        sent += 1
        c.poll(0.0)
    # let late market data land
    for _ in range(10):
        c.poll(0.05)
    elapsed = time.perf_counter() - t_start

    row = {
        "transport": transport,
        "orders_sent": sent,
        "acked": acked,
        # On UDP this is real message loss. On TCP it is an order whose ACK had
        # not arrived before the deadline -- late, not lost.
        "unacked_%": round(100 * (sent - acked) / sent, 1) if sent else 0,
        "rtt_p50_ms": round(statistics.median(rtts), 2) if rtts else None,
        "rtt_p95_ms": round(sorted(rtts)[int(len(rtts) * 0.95)], 2) if len(rtts) > 20 else None,
        "quotes": c.quotes,
        "trades": c.trades,
        "orders_per_s": round(sent / elapsed, 1) if elapsed else 0,
    }
    if transport == "udp":
        row["md_gaps"] = c.gaps
        row["bad_frames"] = c.bad
    if transport == "rest":
        row["http_requests"] = c.http_requests
        row["http_resp_bytes"] = c.http_bytes
    c.close()
    return row


def main(argv=None):
    p = argparse.ArgumentParser(prog="client.bench")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--tcp", type=int, default=7001)
    p.add_argument("--udp", type=int, default=7002)
    p.add_argument("--http", type=int, default=7003)
    p.add_argument("--transport", default="all", choices=["tcp", "udp", "rest", "all"])
    p.add_argument("--firm", default="0x21")
    p.add_argument("--orders", type=int, default=100)
    p.add_argument("--ticker", default="NDOH")
    p.add_argument("--seed", type=int, default=1)
    a = p.parse_args(argv)

    ports = {"tcp": a.tcp, "udp": a.udp, "rest": a.http}
    firm = int(a.firm, 0)
    which = ["tcp", "udp", "rest"] if a.transport == "all" else [a.transport]

    rows = []
    for i, t in enumerate(which):
        try:
            rows.append(run(t, a.host, ports, firm + i, a.orders, a.ticker, a.seed))
        except OSError as e:
            rows.append({"transport": t, "error": str(e)})

    cols = ["transport", "orders_sent", "acked", "unacked_%", "rtt_p50_ms",
            "rtt_p95_ms", "orders_per_s", "quotes", "trades",
            "md_gaps", "http_requests"]
    widths = {c: max(len(c), *(len(str(r.get(c, "-"))) for r in rows)) for c in cols}
    print("  " + "  ".join(c.ljust(widths[c]) for c in cols))
    for r in rows:
        if "error" in r:
            print(f"  {r['transport']:<10} ERROR: {r['error']}")
            continue
        print("  " + "  ".join(str(r.get(c, "-")).ljust(widths[c]) for c in cols))
    return 0


if __name__ == "__main__":
    sys.exit(main())
