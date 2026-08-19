"""Phase 1: stateful B-Stack application protocol (distributed KV store w/ transactions).

Formal FSM, server side, one instance per connection:

    INIT --HELO--> GREETED --AUTH(ok)--> AUTHED --LOCK--> TXN_OPEN
      |               |                    |  ^              | |
      |               +--AUTH(bad)-------->+  |  COMMIT/ABORT| |
      +--anything else--> DEAD <--BYE------+  +--------------+ |
                                              PUT/GET (in txn)-+

State-dependent anomalies the rubric asks for are handled explicitly:
  * duplicate HELO in GREETED/AUTHED  -> 462 REPEAT-HANDSHAKE, state unchanged
  * PUT/GET outside TXN_OPEN          -> 451 NO-LOCK
  * LOCK while already holding a lock -> 452 LOCK-HELD
  * LOCK on a key another session owns -> 453 LOCK-BUSY
  * verbs after BYE                    -> connection already gone
Status codes are deliberately non-HTTP.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import secrets

from framing import (
    F_ENC,
    T_ABORT,
    T_AUTH,
    T_BYE,
    T_COMMIT,
    T_GET,
    T_HELO,
    T_LOCK,
    T_PUT,
    T_RESP,
    T_TOKEN,
    TLV_KEY,
    TLV_REASON,
    TLV_SECRET,
    TLV_STATUS,
    TLV_TOKEN,
    TLV_TXN,
    TLV_USER,
    FrameError,
    encode_frame,
    read_frame,
)

# --- bespoke status codes (not HTTP, not SMTP) ---
S_GREET = 210
S_AUTHED = 220
S_LOCKED = 230
S_STORED = 240
S_VALUE = 241
S_COMMITTED = 250
S_ABORTED = 251
S_BYE = 290
S_BADSEQ = 450
S_NOLOCK = 451
S_LOCKHELD = 452
S_LOCKBUSY = 453
S_NOAUTH = 460
S_BADAUTH = 461
S_REHELO = 462
S_BADFRAME = 470
S_NOKEY = 471

INIT, GREETED, AUTHED, TXN_OPEN, DEAD = "INIT", "GREETED", "AUTHED", "TXN_OPEN", "DEAD"

USERS = {"alice": "s3cr3t", "bob": "hunter2"}


def _digest(user: str, secret: str, nonce: bytes) -> bytes:
    return hashlib.sha256(nonce + user.encode() + secret.encode()).digest()[:16]


class Store:
    """Shared KV store with per-key locks and per-session write sets."""

    def __init__(self):
        self.data: dict[str, bytes] = {}
        self.locks: dict[str, str] = {}  # key -> owning token

    def lock(self, key: str, token: str) -> int:
        owner = self.locks.get(key)
        if owner is None:
            self.locks[key] = token
            return S_LOCKED
        return S_LOCKHELD if owner == token else S_LOCKBUSY

    def release_all(self, token: str):
        for k in [k for k, v in self.locks.items() if v == token]:
            del self.locks[k]

    def commit(self, writes: dict[str, bytes], token: str):
        self.data.update(writes)
        self.release_all(token)


class Session:
    """Pure-ish FSM: feed it a Frame, get back a response Frame (or None)."""

    def __init__(self, store: Store, sid: int):
        self.store = store
        self.sid = sid
        self.state = INIT
        self.user = None
        self.nonce = None
        self.token = None
        self.txn = None
        self.writes: dict[str, bytes] = {}
        self.seq = 0
        self.transitions: list[tuple[str, int, str]] = []

    def _resp(self, status: int, reason: str = "", tlvs=None, payload=b""):
        self.seq += 1
        base = [(TLV_STATUS, str(status).encode())]
        if reason:
            base.append((TLV_REASON, reason.encode()))
        base.extend(tlvs or [])
        return encode_frame(T_RESP, self.seq, base, payload)

    def handle(self, f):
        prev = self.state
        out = self._dispatch(f)
        self.transitions.append((prev, f.mtype, self.state))
        return out

    def _dispatch(self, f):
        t = f.mtype

        if t == T_HELO:
            if self.state in (GREETED, AUTHED, TXN_OPEN):
                # duplicate handshake: refuse, do NOT reset state
                return self._resp(S_REHELO, "handshake already completed")
            self.nonce = os.urandom(8)
            self.state = GREETED
            return self._resp(S_GREET, "b-stack/1", [(TLV_SECRET, self.nonce)])

        if t == T_AUTH:
            if self.state != GREETED:
                return self._resp(S_BADSEQ, f"AUTH not valid in {self.state}")
            user = f.gets(TLV_USER, "")
            proof = f.get(TLV_SECRET, b"")
            expect = _digest(user, USERS.get(user, "\x00nope"), self.nonce)
            if user not in USERS or not secrets.compare_digest(proof, expect):
                # stay in GREETED; a retry is allowed but the nonce is burned
                self.nonce = os.urandom(8)
                return self._resp(S_BADAUTH, "bad credentials", [(TLV_SECRET, self.nonce)])
            self.user = user
            self.token = secrets.token_hex(8)
            self.state = AUTHED
            return self._resp(S_AUTHED, user, [(TLV_TOKEN, self.token.encode())])

        if t == T_TOKEN:
            if self.state not in (AUTHED, TXN_OPEN):
                return self._resp(S_NOAUTH, "not authenticated")
            return self._resp(S_AUTHED, "token ok", [(TLV_TOKEN, self.token.encode())])

        # everything below requires auth
        if self.state in (INIT, GREETED):
            return self._resp(S_NOAUTH, f"{t:#04x} requires AUTH")
        if f.gets(TLV_TOKEN, "") != self.token:
            return self._resp(S_NOAUTH, "bad or missing session token")

        if t == T_LOCK:
            key = f.gets(TLV_KEY, "")
            if self.state == TXN_OPEN:
                return self._resp(S_LOCKHELD, f"txn {self.txn} already open")
            rc = self.store.lock(key, self.token)
            if rc != S_LOCKED:
                return self._resp(rc, f"key {key!r} locked elsewhere")
            self.txn = secrets.token_hex(4)
            self.writes = {}
            self.state = TXN_OPEN
            return self._resp(S_LOCKED, key, [(TLV_TXN, self.txn.encode())])

        if t in (T_PUT, T_GET):
            if self.state != TXN_OPEN:
                return self._resp(S_NOLOCK, "no open transaction")
            if f.gets(TLV_TXN, "") != self.txn:
                return self._resp(S_BADSEQ, "txn id mismatch")
            key = f.gets(TLV_KEY, "")
            if t == T_PUT:
                self.writes[key] = f.payload
                return self._resp(S_STORED, key)
            val = self.writes.get(key, self.store.data.get(key))
            if val is None:
                return self._resp(S_NOKEY, key)
            return self._resp(S_VALUE, key, [(TLV_KEY, key.encode())], val)

        if t in (T_COMMIT, T_ABORT):
            if self.state != TXN_OPEN:
                return self._resp(S_NOLOCK, "no open transaction")
            n = len(self.writes)
            if t == T_COMMIT:
                self.store.commit(self.writes, self.token)
                status, msg = S_COMMITTED, f"{n} writes"
            else:
                self.store.release_all(self.token)
                status, msg = S_ABORTED, f"{n} discarded"
            self.writes, self.txn, self.state = {}, None, AUTHED
            return self._resp(status, msg)

        if t == T_BYE:
            if self.token:
                self.store.release_all(self.token)
            self.state = DEAD
            return self._resp(S_BYE, "goodbye")

        return self._resp(S_BADFRAME, f"unknown type {t:#04x}")


async def serve_session(reader, writer, store: Store, sid: int, log=None):
    sess = Session(store, sid)
    try:
        while sess.state != DEAD:
            try:
                f = await read_frame(reader)
            except (asyncio.IncompleteReadError, ConnectionResetError, EOFError):
                break
            except FrameError as e:
                # bad checksum / bad magic: answer and resync by dropping the conn
                writer.write(sess._resp(S_BADFRAME, str(e)))
                await _drain(writer)
                break
            resp = sess.handle(f)
            if log is not None:
                log.append((sid, sess.transitions[-1], resp))
            if resp:
                writer.write(resp)
                await _drain(writer)
    finally:
        if sess.token:
            store.release_all(sess.token)
        try:
            writer.close()
        except Exception:
            pass
    return sess


async def _drain(writer):
    d = getattr(writer, "drain", None)
    if d:
        await d()


class Client:
    """Thin request/response client. Works over TCP streams or the R-UDP adapter."""

    def __init__(self, reader, writer):
        self.reader, self.writer = reader, writer
        self.seq = 0
        self.token = None
        self.txn = None

    async def _rt(self, mtype, tlvs=None, payload=b"", flags=0):
        self.seq += 1
        self.writer.write(encode_frame(mtype, self.seq, tlvs, payload, flags))
        await _drain(self.writer)
        return await read_frame(self.reader)

    async def helo(self):
        r = await self._rt(T_HELO)
        self.nonce = r.get(TLV_SECRET, b"")
        return r

    async def auth(self, user, secret):
        proof = _digest(user, secret, self.nonce)
        r = await self._rt(T_AUTH, [(TLV_USER, user), (TLV_SECRET, proof)])
        tok = r.get(TLV_TOKEN)
        if tok:
            self.token = tok.decode()
        else:
            # server burns the nonce on a failed AUTH and issues a fresh one;
            # a retry must use it or it will fail forever.
            fresh = r.get(TLV_SECRET)
            if fresh:
                self.nonce = fresh
        return r

    def _tok(self):
        return [(TLV_TOKEN, (self.token or "").encode())]

    async def lock(self, key):
        r = await self._rt(T_LOCK, self._tok() + [(TLV_KEY, key)])
        tx = r.get(TLV_TXN)
        if tx:
            self.txn = tx.decode()
        return r

    async def put(self, key, val):
        return await self._rt(
            T_PUT, self._tok() + [(TLV_TXN, (self.txn or "").encode()), (TLV_KEY, key)], val
        )

    async def get(self, key):
        return await self._rt(
            T_GET, self._tok() + [(TLV_TXN, (self.txn or "").encode()), (TLV_KEY, key)]
        )

    async def commit(self):
        r = await self._rt(T_COMMIT, self._tok())
        self.txn = None
        return r

    async def abort(self):
        r = await self._rt(T_ABORT, self._tok())
        self.txn = None
        return r

    async def bye(self):
        return await self._rt(T_BYE, self._tok())
