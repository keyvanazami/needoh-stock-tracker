"""The XCHG binary wire protocol -- shared by the TCP and UDP gateways.

    +--------+-----+------+-------+--------+--------+--------+---------+-------+
    | MAGIC  | VER | TYPE | FLAGS |  SEQ   |  FIRM  |  LEN   | payload | CRC16 |
    |   2    |  1  |  1   |   1   |   4    |   2    |   2    |   LEN   |   2   |
    +--------+-----+------+-------+--------+--------+--------+---------+-------+
     13-byte header, big-endian, + 2-byte trailer = 15 bytes of overhead.

Why a length prefix and a CRC when TCP already gives you both?

  * The length prefix is not redundant. TCP is a BYTE STREAM: it guarantees
    order and delivery, not message boundaries. A 40-byte order can arrive as
    40 one-byte reads, or glued to the next order in a single read. Students
    who forget this write a client that works on localhost and fails in class,
    because loopback happens to deliver each write intact. This is the single
    most common bug in the whole assignment and it is worth failing once.

  * The CRC is redundant on TCP and essential on UDP, which is exactly the
    point: the same message on two transports needs different guarantees from
    the layer above. Keeping one frame format across both makes the difference
    measurable instead of theoretical.

CRC-16/CCITT-FALSE, the same polynomial the hardware version used, so the
check constant crc16(b"123456789") == 0x29B1 still holds.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

MAGIC = b"BX"
VERSION = 1
HEADER = struct.Struct("!2sBBBIHH")
HEADER_LEN = HEADER.size          # 13
TRAILER_LEN = 2
OVERHEAD = HEADER_LEN + TRAILER_LEN
MAX_PAYLOAD = 1024

# --- message types ---------------------------------------------------------
T_HELLO = 0x01
T_ORDER = 0x10
T_CANCEL = 0x11
T_ACK = 0x20
T_REJECT = 0x21
T_QUOTE = 0x30
T_TRADE = 0x31
T_HEARTBEAT = 0x40

TYPE_NAMES = {
    T_HELLO: "HELLO", T_ORDER: "ORDER", T_CANCEL: "CANCEL", T_ACK: "ACK",
    T_REJECT: "REJECT", T_QUOTE: "QUOTE", T_TRADE: "TRADE",
    T_HEARTBEAT: "HEARTBEAT",
}

# --- flags -----------------------------------------------------------------
F_NONE = 0x00
F_REPLAY = 0x01        # this message is a retransmission (UDP recovery)

BUY, SELL = 0, 1
SIDE_NAMES = {BUY: "BUY", SELL: "SELL"}


class WireError(Exception):
    pass


def crc16(data: bytes, crc: int = 0xFFFF) -> int:
    """CRC-16/CCITT-FALSE. poly 0x1021, init 0xFFFF, no reflection, no xorout."""
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


@dataclass
class Frame:
    type: int
    firm: int = 0
    seq: int = 0
    flags: int = F_NONE
    payload: bytes = b""

    @property
    def name(self) -> str:
        return TYPE_NAMES.get(self.type, f"0x{self.type:02X}")

    def encode(self) -> bytes:
        if len(self.payload) > MAX_PAYLOAD:
            raise WireError(f"payload {len(self.payload)} exceeds {MAX_PAYLOAD}")
        head = HEADER.pack(MAGIC, VERSION, self.type, self.flags,
                           self.seq & 0xFFFFFFFF, self.firm & 0xFFFF, len(self.payload))
        body = head + self.payload
        return body + struct.pack("!H", crc16(body))


def decode(buf: bytes) -> Frame:
    """Decode one complete frame. Raises WireError on anything malformed."""
    if len(buf) < OVERHEAD:
        raise WireError(f"runt frame: {len(buf)} bytes, minimum {OVERHEAD}")
    magic, ver, typ, flags, seq, firm, length = HEADER.unpack_from(buf)
    if magic != MAGIC:
        raise WireError(f"bad magic {magic!r}")
    if ver != VERSION:
        raise WireError(f"unsupported version {ver}")
    if len(buf) != HEADER_LEN + length + TRAILER_LEN:
        raise WireError(
            f"length field says {length}, buffer holds "
            f"{len(buf) - OVERHEAD} payload bytes")
    (got,) = struct.unpack("!H", buf[-TRAILER_LEN:])
    want = crc16(buf[:-TRAILER_LEN])
    if got != want:
        raise WireError(f"CRC mismatch: frame carries {got:04X}, computed {want:04X}")
    return Frame(type=typ, firm=firm, seq=seq, flags=flags,
                 payload=buf[HEADER_LEN:HEADER_LEN + length])


def frame_length(head: bytes) -> int:
    """Total on-wire length of the frame whose header starts `head`.

    Lets a stream reader ask "how many more bytes do I need?" after reading
    exactly HEADER_LEN bytes -- the core of handling TCP's lack of message
    boundaries."""
    if len(head) < HEADER_LEN:
        raise WireError("need a full header to compute frame length")
    _, _, _, _, _, _, length = HEADER.unpack_from(head)
    return HEADER_LEN + length + TRAILER_LEN


class StreamParser:
    """Reassembles frames from an arbitrarily-chopped TCP byte stream.

    Students write their own version of this; it is the reference to check
    against. Feed it whatever recv() returned, get back whole frames."""

    def __init__(self) -> None:
        self.buf = bytearray()
        self.frames_ok = 0
        self.crc_errors = 0
        self.resyncs = 0

    def feed(self, data: bytes) -> list[Frame]:
        self.buf += data
        out: list[Frame] = []
        while True:
            # Resynchronise to the magic. A clean stream never needs this; a
            # stream that just carried a corrupt frame does.
            if len(self.buf) >= 2 and self.buf[:2] != MAGIC:
                idx = self.buf.find(MAGIC, 1)
                if idx < 0:
                    del self.buf[:max(0, len(self.buf) - 1)]
                    return out
                del self.buf[:idx]
                self.resyncs += 1
            if len(self.buf) < HEADER_LEN:
                return out
            need = frame_length(bytes(self.buf[:HEADER_LEN]))
            if need > HEADER_LEN + MAX_PAYLOAD + TRAILER_LEN:
                del self.buf[:2]           # implausible length: not a real header
                self.resyncs += 1
                continue
            if len(self.buf) < need:
                return out
            raw, del_ = bytes(self.buf[:need]), need
            try:
                out.append(decode(raw))
                self.frames_ok += 1
            except WireError:
                self.crc_errors += 1
                del_ = 2                   # skip the magic and hunt for the next
            del self.buf[:del_]
