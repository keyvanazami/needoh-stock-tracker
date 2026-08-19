"""Phase 5: simplified 1-RTT crypto negotiation (QUIC-flavoured) for B-Stack.

    Client                                          Server
      |-- ClientHello: eph_pub_C || nonce_C -------->|
      |<- ServerHello: eph_pub_S || nonce_S          |
      |                || Sig_Ed25519(transcript)    |
      |                || identity_pub               |
      |   (client can send encrypted data now: 1 RTT)|

Shared secret  = X25519(eph_C, eph_S)
Traffic keys   = HKDF-SHA256(secret, salt=nonce_C||nonce_S, info="b-stack v1")
                 -> 32B client->server key, 32B server->client key
Record         = AES-256-GCM, 12-byte nonce = 4B fixed || 8B counter,
                 AAD = the plaintext B-Stack header, so header fields are
                 authenticated even though only the body is hidden.

The Ed25519 signature covers the full transcript, so an active MITM that swaps
in its own ephemeral key fails verification. Per-direction counters give replay
detection: a record whose counter has been seen is rejected.
"""

from __future__ import annotations

import os
import struct

from cryptography.exceptions import InvalidSignature, InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, x25519
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

INFO = b"b-stack v1 traffic keys"


class HandshakeError(Exception):
    pass


def _raw_pub(k):
    return k.public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
    )


class ServerIdentity:
    """Long-term Ed25519 key the client pins (stands in for a certificate)."""

    def __init__(self):
        self.sk = ed25519.Ed25519PrivateKey.generate()
        self.pk = self.sk.public_key()

    @property
    def pinned(self) -> bytes:
        return _raw_pub(self.pk)


def _derive(shared: bytes, nonce_c: bytes, nonce_s: bytes):
    okm = HKDF(
        algorithm=hashes.SHA256(), length=64, salt=nonce_c + nonce_s, info=INFO
    ).derive(shared)
    return okm[:32], okm[32:]  # (client->server, server->client)


class Record:
    """AEAD record layer with a per-direction counter (nonce + replay window)."""

    def __init__(self, key: bytes, fixed: bytes, label: str):
        self.aead = AESGCM(key)
        self.fixed = fixed
        self.label = label
        self.send_ctr = 0
        self.seen: set[int] = set()

    def seal(self, plaintext: bytes, aad: bytes = b"") -> bytes:
        ctr = self.send_ctr
        self.send_ctr += 1
        nonce = self.fixed + struct.pack("!Q", ctr)
        ct = self.aead.encrypt(nonce, plaintext, aad)
        return struct.pack("!Q", ctr) + ct

    def open(self, record: bytes, aad: bytes = b"") -> bytes:
        if len(record) < 8:
            raise HandshakeError("short record")
        (ctr,) = struct.unpack("!Q", record[:8])
        if ctr in self.seen:
            raise HandshakeError(f"replay detected on {self.label} (counter {ctr})")
        nonce = self.fixed + struct.pack("!Q", ctr)
        try:
            pt = self.aead.decrypt(nonce, record[8:], aad)
        except InvalidTag:
            raise HandshakeError("AEAD tag mismatch: record tampered or wrong key")
        self.seen.add(ctr)
        return pt


class ClientHandshake:
    def __init__(self, pinned_server_key: bytes):
        self.pinned = pinned_server_key
        self.eph = x25519.X25519PrivateKey.generate()
        self.nonce = os.urandom(16)

    def hello(self) -> bytes:
        return _raw_pub(self.eph.public_key()) + self.nonce

    def finish(self, server_hello: bytes):
        if len(server_hello) != 32 + 16 + 64 + 32:
            raise HandshakeError("malformed ServerHello")
        eph_s, nonce_s = server_hello[:32], server_hello[32:48]
        sig, ident = server_hello[48:112], server_hello[112:144]

        if ident != self.pinned:
            raise HandshakeError("server identity key does not match the pinned key")

        transcript = self.hello() + eph_s + nonce_s
        try:
            ed25519.Ed25519PublicKey.from_public_bytes(ident).verify(sig, transcript)
        except InvalidSignature:
            raise HandshakeError("ServerHello signature invalid (active MITM?)")

        shared = self.eph.exchange(x25519.X25519PublicKey.from_public_bytes(eph_s))
        k_cs, k_sc = _derive(shared, self.nonce, nonce_s)
        return Record(k_cs, b"\x00\x00\x00\x01", "c->s"), Record(
            k_sc, b"\x00\x00\x00\x02", "s->c"
        )


class ServerHandshake:
    def __init__(self, identity: ServerIdentity):
        self.identity = identity
        self.eph = x25519.X25519PrivateKey.generate()
        self.nonce = os.urandom(16)

    def respond(self, client_hello: bytes):
        if len(client_hello) != 48:
            raise HandshakeError("malformed ClientHello")
        eph_c, nonce_c = client_hello[:32], client_hello[32:48]
        transcript = client_hello + _raw_pub(self.eph.public_key()) + self.nonce
        sig = self.identity.sk.sign(transcript)
        hello = _raw_pub(self.eph.public_key()) + self.nonce + sig + self.identity.pinned

        shared = self.eph.exchange(x25519.X25519PublicKey.from_public_bytes(eph_c))
        k_cs, k_sc = _derive(shared, nonce_c, self.nonce)
        return hello, Record(k_cs, b"\x00\x00\x00\x01", "c->s"), Record(
            k_sc, b"\x00\x00\x00\x02", "s->c"
        )
