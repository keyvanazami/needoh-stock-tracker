import sys, pathlib, unittest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from exchange import messages as M
from exchange.wire import (BUY, Frame, StreamParser, T_ORDER, WireError,
                           crc16, decode)


class TestCrc(unittest.TestCase):
    def test_check_constant(self):
        # CRC-16/CCITT-FALSE is defined by this value; it is the same constant
        # the hardware version had to match.
        self.assertEqual(crc16(b"123456789"), 0x29B1)

    def test_detects_single_bit_flip(self):
        f = M.enc_order("NDOH", BUY, 10000, 5, 1, firm=0x21).encode()
        for bit in range(0, len(f) * 8, 7):
            bad = bytearray(f)
            bad[bit // 8] ^= 1 << (bit % 8)
            with self.assertRaises(WireError):
                decode(bytes(bad))


class TestFraming(unittest.TestCase):
    def test_roundtrip(self):
        f = Frame(T_ORDER, firm=0x21, seq=99, payload=b"abc")
        g = decode(f.encode())
        self.assertEqual((g.type, g.firm, g.seq, g.payload), (T_ORDER, 0x21, 99, b"abc"))

    def test_rejects_truncated(self):
        f = M.enc_order("NDOH", BUY, 1, 1, 1).encode()
        with self.assertRaises(WireError):
            decode(f[:-1])

    def test_rejects_bad_magic(self):
        f = bytearray(M.enc_order("NDOH", BUY, 1, 1, 1).encode())
        f[0] = ord("Z")
        with self.assertRaises(WireError):
            decode(bytes(f))


class TestStreamParser(unittest.TestCase):
    """TCP gives a byte stream, not messages. These are the cases that bite."""

    def setUp(self):
        self.frames = [M.enc_order("NDOH", BUY, 10000 + i, i + 1, i + 1, firm=0x21).encode()
                       for i in range(5)]
        self.blob = b"".join(self.frames)

    def test_one_read_per_frame(self):
        p = StreamParser()
        got = [f for raw in self.frames for f in p.feed(raw)]
        self.assertEqual(len(got), 5)

    def test_all_frames_in_one_read(self):
        p = StreamParser()
        self.assertEqual(len(p.feed(self.blob)), 5)

    def test_one_byte_at_a_time(self):
        p = StreamParser()
        got = [f for i in range(len(self.blob)) for f in p.feed(self.blob[i:i + 1])]
        self.assertEqual(len(got), 5)

    def test_arbitrary_chunking(self):
        for size in (3, 7, 13, 31, 64):
            p = StreamParser()
            got = [f for i in range(0, len(self.blob), size)
                   for f in p.feed(self.blob[i:i + size])]
            self.assertEqual(len(got), 5, f"chunk size {size}")

    def test_recovers_after_corruption(self):
        bad = bytearray(self.blob)
        bad[20] ^= 0xFF                        # damage frame 1
        p = StreamParser()
        got = p.feed(bytes(bad))
        self.assertEqual(p.crc_errors, 1)
        self.assertGreaterEqual(len(got), 3)   # the rest still arrive

    def test_survives_leading_garbage(self):
        p = StreamParser()
        got = p.feed(b"\x00\xff\x11garbage" + self.blob)
        self.assertEqual(len(got), 5)

    def test_implausible_length_does_not_hang(self):
        p = StreamParser()
        p.feed(b"BX\x01\x10\x00\x00\x00\x00\x01\x00\x21\xff\xff")
        self.assertEqual(p.frames_ok, 0)
        self.assertEqual(len(p.feed(self.blob)), 5)


class TestMessages(unittest.TestCase):
    def test_all_types_roundtrip(self):
        cases = [
            M.enc_order("NDOH", BUY, 10250, 5, 7, firm=0x21),
            M.enc_cancel("NDOH", 7, firm=0x21),
            M.enc_ack(7, M.ACK_FILLED, 5, 0, firm=0x21),
            M.enc_quote("NDOH", 10200, 4, 10300, 9, 12),
            M.enc_trade("NDOH", 10250, 5, 0x21, 0x22, 13),
            M.enc_hello(0x21, "Kappa Capital"),
            M.enc_reject("bad price"),
        ]
        for f in cases:
            with self.subTest(f.name):
                self.assertIsInstance(M.decode_payload(decode(f.encode())), dict)

    def test_empty_book_quote_uses_sentinel(self):
        q = M.dec_quote(decode(M.enc_quote("NDOH", None, 0, None, 0, 1).encode()))
        self.assertIsNone(q["bid"])
        self.assertIsNone(q["ask"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
