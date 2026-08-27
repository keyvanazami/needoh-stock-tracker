"""Run the exchange.  python -m exchange [--host 0.0.0.0] [--tcp 7001] ...

Bind address matters in class. The default 0.0.0.0 accepts connections from
the network; 127.0.0.1 accepts only from this machine. If students cannot
reach you, that is the first thing to check, ahead of the firewall.
"""

from __future__ import annotations

import argparse
import asyncio
import socket
import sys

from .impair import Impairer, PRESETS
from .server import Exchange, HttpGateway, TcpGateway, UdpGateway


def local_ips() -> list[str]:
    """Best-effort list of addresses students can actually dial."""
    ips = set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("192.0.2.1", 9))          # TEST-NET-1: no packet is sent
        ips.add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    return sorted(i for i in ips if not i.startswith("127."))


async def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="exchange", description="XCHG classroom exchange")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--tcp", type=int, default=7001)
    p.add_argument("--udp", type=int, default=7002)
    p.add_argument("--http", type=int, default=7003)
    p.add_argument("--tickers", default="NDOH")
    p.add_argument("--impair", default="clean", choices=sorted(PRESETS),
                   help="starting impairment on every gateway")
    a = p.parse_args(argv)

    ex = Exchange(tuple(t.strip() for t in a.tickers.split(",") if t.strip()))
    # tcp and rest run over TCP: stream mode, so loss becomes latency.
    # udp is a datagram gateway: loss, duplication and reordering are real.
    imps = {n: Impairer(n, seed=1234 + i, stream=(n != "udp"))
            for i, n in enumerate(("tcp", "udp", "rest"))}
    for i in imps.values():
        i.cfg = type(i.cfg)(**vars(PRESETS[a.impair]))

    tcp = TcpGateway(ex, imps["tcp"])
    udp = UdpGateway(ex, imps["udp"])
    http = HttpGateway(ex, imps["rest"], imps)

    loop = asyncio.get_running_loop()
    tcp_srv = await asyncio.start_server(tcp.handle, a.host, a.tcp)
    http_srv = await asyncio.start_server(http.handle, a.host, a.http)
    await loop.create_datagram_endpoint(lambda: udp, local_addr=(a.host, a.udp))

    ips = local_ips() or ["<no non-loopback address found>"]
    print(f"XCHG up   tickers={','.join(ex.books)}   impairment={a.impair}")
    print(f"  TCP   {a.host}:{a.tcp}    binary frames, market data pushed")
    print(f"  UDP   {a.host}:{a.udp}    binary frames, unreliable, pushed")
    print(f"  HTTP  {a.host}:{a.http}    JSON REST, market data polled")
    print("\n  students should dial:")
    for ip in ips:
        print(f"    {ip}   tcp {a.tcp} / udp {a.udp} / http {a.http}")
    print(f"\n  live stats:  curl http://{ips[0]}:{a.http}/stats")
    print(f"  impair   :  curl -X POST http://{ips[0]}:{a.http}/admin/impair "
          f"-d '{{\"gateway\":\"all\",\"preset\":\"wifi-busy\"}}'")
    print(f"  presets  :  {', '.join(sorted(PRESETS))}\n")

    async with tcp_srv, http_srv:
        await asyncio.Event().wait()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        print("\nXCHG down")
