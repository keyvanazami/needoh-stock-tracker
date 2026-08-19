"""Phase 5 demo: (a) 1-RTT encrypted handshake over B-Stack, with active-MITM,
tamper and replay detection; (b) surviving a Slow Loris attack."""

import asyncio
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import struct

from framing import (
    HEADER_FMT,
    HEADER_LEN,
    MAGIC,
    T_PUT,
    TLV_KEY,
    VERSION,
    encode_frame,
    hexdump,
)
from handshake import (
    ClientHandshake,
    HandshakeError,
    ServerHandshake,
    ServerIdentity,
)

# ----------------------------------------------------------------------------
# Part A: crypto
# ----------------------------------------------------------------------------


def part_a():
    print("== Phase 5a: 1-RTT encrypted handshake ==\n")
    ident = ServerIdentity()

    c = ClientHandshake(pinned_server_key=ident.pinned)
    s = ServerHandshake(ident)
    ch = c.hello()
    sh, s_cs, s_sc = s.respond(ch)
    c_cs, c_sc = c.finish(sh)
    print(f"  ClientHello {len(ch)}B, ServerHello {len(sh)}B -> session established in 1 RTT")

    # --- encrypt a real B-Stack frame body, header stays authenticated AAD ---
    plain = encode_frame(T_PUT, 7, [(TLV_KEY, "inventory/needoh")], b"count=42")
    aad, body = plain[:HEADER_LEN], plain[HEADER_LEN:]
    sealed = c_cs.seal(body, aad)
    print(f"\n  plaintext body ({len(body)}B):")
    print(hexdump(body, prefix="    "))
    print(f"  sealed body ({len(sealed)}B: 8B counter + ciphertext + 16B GCM tag):")
    print(hexdump(sealed[:48], prefix="    "))

    opened = s_cs.open(sealed, aad)
    print(f"\n  server decrypt round-trips: {opened == body}")

    # --- tamper with the ciphertext ---
    bad = bytearray(c_cs.seal(body, aad))
    bad[20] ^= 0x01
    try:
        s_cs.open(bytes(bad), aad)
        print("  tampered ciphertext           -> ACCEPTED (BAD)")
    except HandshakeError as e:
        print(f"  tampered ciphertext           -> rejected: {e}")

    # --- tamper with the *header* (which is only AAD, not encrypted) ---
    rec = c_cs.seal(body, aad)
    forged_aad = bytearray(aad)
    forged_aad[3] ^= 0xFF  # change the message type
    try:
        s_cs.open(rec, bytes(forged_aad))
        print("  forged header (AAD)           -> ACCEPTED (BAD)")
    except HandshakeError as e:
        print(f"  forged header (AAD)           -> rejected: {e}")

    # --- replay a previously accepted record ---
    rec2 = c_cs.seal(b"replay-me", aad)
    s_cs.open(rec2, aad)
    try:
        s_cs.open(rec2, aad)
        print("  replayed record               -> ACCEPTED (BAD)")
    except HandshakeError as e:
        print(f"  replayed record               -> rejected: {e}")

    # --- active MITM substitutes its own ephemeral key ---
    evil_ident = ServerIdentity()
    mitm = ServerHandshake(evil_ident)
    evil_hello, _, _ = mitm.respond(ch)
    try:
        ClientHandshake.finish(c, evil_hello)
        print("  MITM with its own identity    -> ACCEPTED (BAD)")
    except HandshakeError as e:
        print(f"  MITM with its own identity    -> rejected: {e}")

    # --- MITM keeps the real identity bytes but re-signs with its own key ---
    forged = bytearray(evil_hello)
    forged[112:144] = ident.pinned  # claim the pinned identity
    try:
        ClientHandshake.finish(c, bytes(forged))
        print("  MITM spoofing pinned identity -> ACCEPTED (BAD)")
    except HandshakeError as e:
        print(f"  MITM spoofing pinned identity -> rejected: {e}")


# ----------------------------------------------------------------------------
# Part B: Slow Loris
# ----------------------------------------------------------------------------

N_ATTACKERS = 120
NAIVE_THREADS = 32
HEADER_DEADLINE = 1.0
MAX_REQUEST = 1 << 16


class NaiveServer:
    """Thread-per-connection with a bounded pool and no read deadline."""

    def __init__(self):
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(256)
        self.port = self.sock.getsockname()[1]
        self.pool = ThreadPoolExecutor(max_workers=NAIVE_THREADS)
        self.run = True
        self.served = 0
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self):
        while self.run:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            self.pool.submit(self._handle, conn)

    def _handle(self, conn):
        try:
            buf = b""
            while len(buf) < HEADER_LEN:
                d = conn.recv(HEADER_LEN - len(buf))
                if not d:
                    return
                buf += d
            # trust the declared length and block until it all arrives
            _, _, _, _, _, _, tlvlen, paylen, _ = struct.unpack(HEADER_FMT, buf)
            need = tlvlen + paylen
            body = b""
            while len(body) < need:
                d = conn.recv(need - len(body))
                if not d:
                    return
                body += d
            conn.sendall(b"OK")
            self.served += 1
        except OSError:
            pass
        finally:
            conn.close()

    def stop(self):
        self.run = False
        self.sock.close()


class HardenedServer:
    """asyncio + a deadline on completing the request header + a per-peer cap."""

    def __init__(self):
        self.served = 0
        self.evicted = 0
        self.server = None

    async def start(self):
        self.server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]

    async def _handle(self, reader, writer):
        try:
            # the deadline covers the entire request, not just the header,
            # so a client cannot buy time by declaring a huge body
            async def whole_request():
                head = await reader.readexactly(HEADER_LEN)
                _, _, _, _, _, _, tlvlen, paylen, _ = struct.unpack(HEADER_FMT, head)
                if tlvlen + paylen > MAX_REQUEST:
                    raise ConnectionError("declared body over cap")
                await reader.readexactly(tlvlen + paylen)

            await asyncio.wait_for(whole_request(), HEADER_DEADLINE)
            writer.write(b"OK")
            await writer.drain()
            self.served += 1
        except (asyncio.TimeoutError, asyncio.IncompleteReadError, ConnectionError):
            self.evicted += 1
        finally:
            try:
                writer.close()
            except Exception:
                pass

    def stop(self):
        if self.server:
            self.server.close()


def slowloris_header(paylen=60000):
    """A well-formed header that promises a large body the attacker never sends."""
    return struct.pack(HEADER_FMT, MAGIC, VERSION, T_PUT, 0, 1, 0, 0, paylen, 0)


def slowloris(port, stop_flag, socks):
    """Send a valid header declaring 60KB, then dribble the body 1 byte / 0.4s.

    The connection never completes, so a server that blocks until the declared
    length arrives holds the worker forever."""
    try:
        s = socket.create_connection(("127.0.0.1", port), timeout=2)
        socks.append(s)
        s.sendall(slowloris_header())
        while not stop_flag.is_set():
            try:
                s.send(b"\x00")
            except OSError:
                return
            time.sleep(0.4)
    except OSError:
        pass


def try_legit(port, timeout=3.0):
    """A well-behaved client: can it get served while the attack runs?"""
    t0 = time.monotonic()
    try:
        s = socket.create_connection(("127.0.0.1", port), timeout=timeout)
        s.settimeout(timeout)
        s.sendall(encode_frame(T_PUT, 1, [(TLV_KEY, "k")], b"v"))
        r = s.recv(2)
        s.close()
        return (r == b"OK"), time.monotonic() - t0
    except OSError:
        return False, time.monotonic() - t0


async def part_b():
    print("\n\n== Phase 5b: Slow Loris resource-exhaustion attack ==\n")
    print(f"  {N_ATTACKERS} attackers dribble 1 byte / 0.4s and never finish a header.\n")

    for label in ("naive thread-per-connection", "hardened async + deadline"):
        if label.startswith("naive"):
            srv = NaiveServer()
            port = srv.port
        else:
            srv = HardenedServer()
            await srv.start()
            port = srv.port

        stop = threading.Event()
        socks = []
        threads = [
            threading.Thread(target=slowloris, args=(port, stop, socks), daemon=True)
            for _ in range(N_ATTACKERS)
        ]
        for t in threads:
            t.start()
        await asyncio.sleep(2.0)  # let the attack settle

        results = []
        for _ in range(5):
            ok, el = await asyncio.get_event_loop().run_in_executor(
                None, try_legit, port
            )
            results.append((ok, el))
            await asyncio.sleep(0.1)

        wins = sum(1 for ok, _ in results if ok)
        avg = sum(el for _, el in results) / len(results)
        extra = f", evicted {srv.evicted} stalled conns" if hasattr(srv, "evicted") else ""
        print(f"  {label:<30} legit clients served: {wins}/5, "
              f"avg latency {avg:.2f}s{extra}")

        stop.set()
        for s in socks:
            try:
                s.close()
            except OSError:
                pass
        srv.stop()
        await asyncio.sleep(0.5)


async def main():
    part_a()
    await part_b()


asyncio.run(main())
