"""Phase 1 scalability challenge: measure "throughput droop" of a greedy
thread-per-connection server against an async event-loop server, same protocol."""

import asyncio
import socket
import threading
import time

from framing import HEADER_LEN, T_GET, T_RESP, TLV_KEY, decode_frame, encode_frame

REQ = encode_frame(T_GET, 1, [(TLV_KEY, "k")], b"")
RESP = encode_frame(T_RESP, 1, [(TLV_KEY, "k")], b"value")


def read_frame_blocking(sock):
    buf = b""
    while len(buf) < HEADER_LEN:
        d = sock.recv(HEADER_LEN - len(buf))
        if not d:
            return None
        buf += d
    import struct

    from framing import HEADER_FMT

    *_, tlvlen, paylen, _ = struct.unpack(HEADER_FMT, buf)
    need = tlvlen + paylen
    body = b""
    while len(body) < need:
        d = sock.recv(need - len(body))
        if not d:
            return None
        body += d
    return decode_frame(buf + body)


class ThreadServer:
    """One OS thread per connection -- the greedy architecture."""

    def __init__(self):
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(512)
        self.port = self.sock.getsockname()[1]
        self.run = True
        self.threads = 0
        self.peak_threads = 0
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self):
        while self.run:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            t = threading.Thread(target=self._handle, args=(conn,), daemon=True)
            self.threads += 1
            self.peak_threads = max(self.peak_threads, self.threads)
            t.start()

    def _handle(self, conn):
        try:
            while True:
                f = read_frame_blocking(conn)
                if f is None:
                    return
                conn.sendall(RESP)
        except OSError:
            pass
        finally:
            self.threads -= 1
            conn.close()

    def stop(self):
        self.run = False
        self.sock.close()


class AsyncServer:
    def __init__(self):
        self.server = None
        self.conns = 0
        self.peak = 0

    async def start(self):
        self.server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]

    async def _handle(self, reader, writer):
        self.conns += 1
        self.peak = max(self.peak, self.conns)
        try:
            while True:
                head = await reader.readexactly(HEADER_LEN)
                import struct

                from framing import HEADER_FMT

                *_, tlvlen, paylen, _ = struct.unpack(HEADER_FMT, head)
                if tlvlen + paylen:
                    await reader.readexactly(tlvlen + paylen)
                writer.write(RESP)
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            self.conns -= 1
            try:
                writer.close()
            except Exception:
                pass

    def stop(self):
        if self.server:
            self.server.close()


def client_worker(port, n_reqs, results, barrier):
    try:
        s = socket.create_connection(("127.0.0.1", port), timeout=10)
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        barrier.wait()
        t0 = time.monotonic()
        for _ in range(n_reqs):
            s.sendall(REQ)
            if read_frame_blocking(s) is None:
                break
        results.append(time.monotonic() - t0)
        s.close()
    except (OSError, threading.BrokenBarrierError):
        pass


def load(port, n_conns, n_reqs=40):
    results = []
    barrier = threading.Barrier(n_conns + 1)
    threads = [
        threading.Thread(target=client_worker, args=(port, n_reqs, results, barrier),
                         daemon=True)
        for _ in range(n_conns)
    ]
    for t in threads:
        t.start()
    try:
        barrier.wait(timeout=30)
    except threading.BrokenBarrierError:
        return 0, 0
    t0 = time.monotonic()
    for t in threads:
        t.join(timeout=60)
    el = time.monotonic() - t0
    done = len(results)
    return (done * n_reqs / el if el else 0), done


async def main():
    print("== Phase 1 scalability: thread-per-connection vs async event loop ==\n")
    levels = [1, 8, 32, 128, 400]

    ts = ThreadServer()
    print(f"  {'conns':<8}{'thread-per-conn req/s':<24}{'async req/s':<16}{'ratio'}")
    thread_results = {}
    for n in levels:
        rps, done = load(ts.port, n)
        thread_results[n] = rps
        await asyncio.sleep(0.3)
    peak_threads = ts.peak_threads
    ts.stop()
    await asyncio.sleep(0.3)

    a = AsyncServer()
    await a.start()
    async_results = {}
    for n in levels:
        rps, done = await asyncio.get_event_loop().run_in_executor(None, load, a.port, n)
        async_results[n] = rps
        await asyncio.sleep(0.3)
    peak_async = a.peak
    a.stop()

    for n in levels:
        t, s = thread_results[n], async_results[n]
        ratio = f"{s / t:.2f}x" if t else "-"
        print(f"  {n:<8}{t:<24,.0f}{s:<16,.0f}{ratio}")

    best = max(thread_results.values())
    worst_high = thread_results[levels[-1]]
    print(f"\n  thread-per-conn peaked at {best:,.0f} req/s and fell to "
          f"{worst_high:,.0f} req/s at {levels[-1]} connections "
          f"({100 * (1 - worst_high / best):.0f}% droop)")
    print(f"  OS threads spawned by the greedy server: {peak_threads} "
          f"(async peak concurrent conns: {peak_async}, 1 thread)")


asyncio.run(main())
