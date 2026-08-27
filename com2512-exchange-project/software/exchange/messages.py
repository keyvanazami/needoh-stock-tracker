"""Payload codecs. The same eight messages in two encodings.

Binary (TCP/UDP gateways) and JSON (REST gateway) carry identical semantics,
so a student can implement any one transport and still trade against everyone
else. Keeping both live is the assignment's central comparison: the binary
ORDER is 28 bytes on the wire, the REST equivalent is roughly 300 once you
count the request line, headers and JSON punctuation. Both are correct. One
of them is why exchanges do not speak REST.
"""

from __future__ import annotations

import json
import struct

from .wire import (BUY, SELL, F_NONE, Frame, T_ACK, T_CANCEL, T_HEARTBEAT,
                   T_HELLO, T_ORDER, T_QUOTE, T_REJECT, T_TRADE, WireError)

TICKER = struct.Struct("!4s")

_ORDER = struct.Struct("!4sBIHI")        # ticker side px qty coid
_CANCEL = struct.Struct("!4sI")          # ticker coid
_ACK = struct.Struct("!IBHH")            # coid status filled resting
_QUOTE = struct.Struct("!4sIHIHI")       # ticker bid bidqty ask askqty seq
_TRADE = struct.Struct("!4sIHHHI")       # ticker px qty buy_firm sell_firm seq
_HELLO = struct.Struct("!H16s")          # firm name

ACK_OK, ACK_PARTIAL, ACK_FILLED, ACK_CANCELLED = 0, 1, 2, 3
ACK_NAMES = {ACK_OK: "resting", ACK_PARTIAL: "partial",
             ACK_FILLED: "filled", ACK_CANCELLED: "cancelled"}

NO_PRICE = 0xFFFFFFFF        # "no bid" / "no offer" on an empty side


def _tk(s: str) -> bytes:
    return s.encode()[:4].ljust(4, b"\0")


def _untk(b: bytes) -> str:
    return b.rstrip(b"\0").decode(errors="replace")


# --- binary ---------------------------------------------------------------
def enc_order(ticker, side, px, qty, coid, firm=0, seq=0) -> Frame:
    return Frame(T_ORDER, firm, seq, F_NONE, _ORDER.pack(_tk(ticker), side, px, qty, coid))


def dec_order(f: Frame) -> dict:
    tk, side, px, qty, coid = _ORDER.unpack(f.payload)
    return {"ticker": _untk(tk), "side": side, "px": px, "qty": qty, "coid": coid}


def enc_cancel(ticker, coid, firm=0, seq=0) -> Frame:
    return Frame(T_CANCEL, firm, seq, F_NONE, _CANCEL.pack(_tk(ticker), coid))


def dec_cancel(f: Frame) -> dict:
    tk, coid = _CANCEL.unpack(f.payload)
    return {"ticker": _untk(tk), "coid": coid}


def enc_ack(coid, status, filled, resting, firm=0, seq=0) -> Frame:
    return Frame(T_ACK, firm, seq, F_NONE, _ACK.pack(coid, status, filled, resting))


def dec_ack(f: Frame) -> dict:
    coid, status, filled, resting = _ACK.unpack(f.payload)
    return {"coid": coid, "status": status, "status_name": ACK_NAMES.get(status, "?"),
            "filled": filled, "resting": resting}


def enc_quote(ticker, bid, bid_qty, ask, ask_qty, seq) -> Frame:
    return Frame(T_QUOTE, 0, seq, F_NONE, _QUOTE.pack(
        _tk(ticker), NO_PRICE if bid is None else bid, bid_qty,
        NO_PRICE if ask is None else ask, ask_qty, seq))


def dec_quote(f: Frame) -> dict:
    tk, bid, bq, ask, aq, seq = _QUOTE.unpack(f.payload)
    return {"ticker": _untk(tk),
            "bid": None if bid == NO_PRICE else bid, "bid_qty": bq,
            "ask": None if ask == NO_PRICE else ask, "ask_qty": aq, "seq": seq}


def enc_trade(ticker, px, qty, buy_firm, sell_firm, seq) -> Frame:
    return Frame(T_TRADE, 0, seq, F_NONE,
                 _TRADE.pack(_tk(ticker), px, qty, buy_firm, sell_firm, seq))


def dec_trade(f: Frame) -> dict:
    tk, px, qty, bf, sf, seq = _TRADE.unpack(f.payload)
    return {"ticker": _untk(tk), "px": px, "qty": qty,
            "buy_firm": bf, "sell_firm": sf, "seq": seq}


def enc_hello(firm, name) -> Frame:
    return Frame(T_HELLO, firm, 0, F_NONE, _HELLO.pack(firm, name.encode()[:16].ljust(16, b"\0")))


def dec_hello(f: Frame) -> dict:
    firm, name = _HELLO.unpack(f.payload)
    return {"firm": firm, "name": name.rstrip(b"\0").decode(errors="replace")}


def enc_reject(reason: str, firm=0, seq=0) -> Frame:
    return Frame(T_REJECT, firm, seq, F_NONE, reason.encode()[:255])


def dec_reject(f: Frame) -> dict:
    return {"reason": f.payload.decode(errors="replace")}


DECODERS = {T_ORDER: dec_order, T_CANCEL: dec_cancel, T_ACK: dec_ack,
            T_QUOTE: dec_quote, T_TRADE: dec_trade, T_HELLO: dec_hello,
            T_REJECT: dec_reject, T_HEARTBEAT: lambda f: {}}


def decode_payload(f: Frame) -> dict:
    fn = DECODERS.get(f.type)
    if fn is None:
        raise WireError(f"no decoder for type 0x{f.type:02X}")
    try:
        return fn(f)
    except struct.error as e:
        raise WireError(f"malformed {f.name} payload: {e}") from e


# --- JSON (REST gateway) --------------------------------------------------
def to_json(f: Frame) -> str:
    d = decode_payload(f)
    d["type"] = f.name
    if f.firm:
        d["firm"] = f.firm
    return json.dumps(d)
