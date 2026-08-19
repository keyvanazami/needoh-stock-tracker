"""B-Stack Binary Framing Format (BSBFF/1).

Wire layout, all multi-byte fields big-endian (network order):

    0                   1                   2                   3
    0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
   +-------+-------+-------+-------+-------+-------+-------+-------+
   |    MAGIC 0xB57C       |  VER  | TYPE  | FLAGS |   SEQ (hi)    |
   +-------+-------+-------+-------+-------+-------+-------+-------+
   |     SEQ (lo)  | NTLV  |    TLVLEN     |    PAYLEN     | CKSUM |
   +-------+-------+-------+-------+-------+-------+-------+-------+
   |  TLV block (TLVLEN bytes, NTLV entries)  ...                  |
   +---------------------------------------------------------------+
   |  Payload (PAYLEN bytes) ...                                   |
   +---------------------------------------------------------------+

Fixed header is 15 bytes. Each TLV entry is: TYPE(1) LEN(2, BE) VALUE(LEN).

CKSUM is a 1-byte XOR of every byte of the frame with the CKSUM field itself
taken as 0x00 -- i.e. header(cksum=0) ^ tlv_block ^ payload, folded by XOR.
"""

from __future__ import annotations

import struct
from functools import reduce

MAGIC = 0xB57C
VERSION = 1

HEADER_FMT = "!HBBBIBHHB"
HEADER_LEN = struct.calcsize(HEADER_FMT)  # 15
assert HEADER_LEN == 15, HEADER_LEN

# ---- message types (bespoke, non-standard on purpose) ----
T_HELO = 0x01
T_AUTH = 0x02
T_TOKEN = 0x03
T_LOCK = 0x04
T_PUT = 0x05
T_GET = 0x06
T_COMMIT = 0x07
T_ABORT = 0x08
T_BYE = 0x09
T_RESP = 0x80

# ---- TLV tags ----
TLV_USER = 0x11
TLV_SECRET = 0x12
TLV_TOKEN = 0x13
TLV_KEY = 0x14
TLV_TXN = 0x15
TLV_STATUS = 0x16
TLV_REASON = 0x17

# ---- flags ----
F_MORE = 0x01
F_ENC = 0x02

MAX_TLV_BLOCK = 0xFFFF
MAX_PAYLOAD = 0xFFFF


class FrameError(Exception):
    """Malformed frame. Never fatal to the process -- callers decide."""


def xor_checksum(*chunks: bytes) -> int:
    return reduce(lambda a, b: a ^ b, (byte for c in chunks for byte in c), 0)


def encode_tlvs(tlvs) -> tuple[bytes, int]:
    """tlvs: sequence of (tag, value_bytes) or a dict. Returns (block, count)."""
    if isinstance(tlvs, dict):
        items = list(tlvs.items())
    else:
        items = list(tlvs or [])
    out = bytearray()
    for tag, val in items:
        if isinstance(val, str):
            val = val.encode("utf-8")
        if len(val) > 0xFFFF:
            raise FrameError(f"TLV {tag:#04x} value too long: {len(val)}")
        out += struct.pack("!BH", tag & 0xFF, len(val))
        out += val
    if len(out) > MAX_TLV_BLOCK:
        raise FrameError("TLV block too long")
    return bytes(out), len(items)


def decode_tlvs(block: bytes, expected_count: int) -> list[tuple[int, bytes]]:
    out = []
    off = 0
    n = len(block)
    while off < n:
        if off + 3 > n:
            raise FrameError("truncated TLV header")
        tag, ln = struct.unpack_from("!BH", block, off)
        off += 3
        if off + ln > n:
            raise FrameError("truncated TLV value")
        out.append((tag, block[off : off + ln]))
        off += ln
    if expected_count is not None and len(out) != expected_count:
        raise FrameError(f"NTLV={expected_count} but parsed {len(out)} TLVs")
    return out


def encode_frame(mtype: int, seq: int, tlvs=None, payload: bytes = b"", flags: int = 0) -> bytes:
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    tlv_block, ntlv = encode_tlvs(tlvs)
    if ntlv > 0xFF:
        raise FrameError("too many TLVs")
    if len(payload) > MAX_PAYLOAD:
        raise FrameError("payload too long")
    head_nock = struct.pack(
        HEADER_FMT,
        MAGIC,
        VERSION,
        mtype & 0xFF,
        flags & 0xFF,
        seq & 0xFFFFFFFF,
        ntlv,
        len(tlv_block),
        len(payload),
        0,
    )
    ck = xor_checksum(head_nock, tlv_block, payload)
    head = head_nock[:-1] + bytes([ck])
    return head + tlv_block + payload


class Frame:
    __slots__ = ("mtype", "flags", "seq", "tlvs", "payload")

    def __init__(self, mtype, flags, seq, tlvs, payload):
        self.mtype = mtype
        self.flags = flags
        self.seq = seq
        self.tlvs = tlvs
        self.payload = payload

    def get(self, tag: int, default=None):
        for t, v in self.tlvs:
            if t == tag:
                return v
        return default

    def gets(self, tag: int, default=None):
        v = self.get(tag)
        return default if v is None else v.decode("utf-8", "replace")

    def __repr__(self):
        tags = ",".join(f"{t:#04x}" for t, _ in self.tlvs)
        return (
            f"<Frame type={self.mtype:#04x} seq={self.seq} flags={self.flags:#04x} "
            f"tlvs=[{tags}] payload={len(self.payload)}B>"
        )


def decode_frame(buf: bytes) -> Frame:
    """Decode one complete frame from bytes. Raises FrameError."""
    if len(buf) < HEADER_LEN:
        raise FrameError("short header")
    magic, ver, mtype, flags, seq, ntlv, tlvlen, paylen, ck = struct.unpack_from(HEADER_FMT, buf, 0)
    if magic != MAGIC:
        raise FrameError(f"bad magic {magic:#06x}")
    if ver != VERSION:
        raise FrameError(f"bad version {ver}")
    need = HEADER_LEN + tlvlen + paylen
    if len(buf) < need:
        raise FrameError("truncated frame body")
    head_nock = buf[: HEADER_LEN - 1] + b"\x00"
    tlv_block = buf[HEADER_LEN : HEADER_LEN + tlvlen]
    payload = buf[HEADER_LEN + tlvlen : need]
    calc = xor_checksum(head_nock, tlv_block, payload)
    if calc != ck:
        raise FrameError(f"checksum mismatch: got {ck:#04x} want {calc:#04x}")
    return Frame(mtype, flags, seq, decode_tlvs(tlv_block, ntlv), payload)


async def read_frame(reader) -> Frame:
    """Read exactly one frame off an asyncio-style reader with readexactly()."""
    head = await reader.readexactly(HEADER_LEN)
    magic, ver, mtype, flags, seq, ntlv, tlvlen, paylen, ck = struct.unpack(HEADER_FMT, head)
    if magic != MAGIC:
        raise FrameError(f"bad magic {magic:#06x}")
    if ver != VERSION:
        raise FrameError(f"bad version {ver}")
    body = await reader.readexactly(tlvlen + paylen) if (tlvlen + paylen) else b""
    return decode_frame(head + body)


def hexdump(data: bytes, width: int = 16, prefix: str = "") -> str:
    lines = []
    for off in range(0, len(data), width):
        chunk = data[off : off + width]
        hexpart = " ".join(f"{b:02x}" for b in chunk)
        hexpart += "   " * (width - len(chunk))
        asc = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"{prefix}{off:04x}  {hexpart}  |{asc}|")
    return "\n".join(lines)
