"""End-to-end: all three gateways against one live server and one book.

These are the tests that matter for the assignment, because they assert the
property the whole design rests on -- a REST desk and a UDP desk trade against
each other for real, not against separate copies of the market."""

import json
import socket
import subprocess
import sys
import pathlib
import time
import unittest
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from client.reference import RestClient, TcpClient, UdpClient
from exchange.book import BUY, SELL

TCP, UDP, HTTP = 27401, 27402, 27403
HOST = "127.0.0.1"


def free(port):
    s = socket.socket()
    try:
        s.bind((HOST, port))
        return True
    except OSError:
        return False
    finally:
        s.close()


class Live(unittest.TestCase):
    proc = None

    @classmethod
    def setUpClass(cls):
        cls.proc = subprocess.Popen(
            [sys.executable, "-u", "-m", "exchange", "--host", HOST,
             "--tcp", str(TCP), "--udp", str(UDP), "--http", str(HTTP)],
            cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        for _ in range(100):
            try:
                urllib.request.urlopen(f"http://{HOST}:{HTTP}/health", timeout=0.5)
                return
            except OSError:
                time.sleep(0.1)
        raise RuntimeError("server did not come up:\n" +
                           cls.proc.stdout.read().decode(errors="replace"))

    @classmethod
    def tearDownClass(cls):
        if cls.proc:
            cls.proc.terminate()
            cls.proc.wait(timeout=5)

    def setUp(self):
        self.impair("clean")

    def impair(self, preset, gateway="all"):
        req = urllib.request.Request(
            f"http://{HOST}:{HTTP}/admin/impair", method="POST",
            data=json.dumps({"gateway": gateway, "preset": preset}).encode())
        with urllib.request.urlopen(req, timeout=2) as r:
            return json.load(r)

    def drain(self, c, seconds=0.4):
        out, end = [], time.time() + seconds
        while time.time() < end:
            out += c.poll(0.05)
        return out


class TestGatewayParity(Live):
    def test_tcp_order_acked(self):
        c = TcpClient(HOST, TCP, 0x31)
        self.addCleanup(c.close)
        c.order("NDOH", BUY, 9000, 5, 1)
        acks = [m for m in self.drain(c) if m["type"] == "ACK"]
        self.assertTrue(acks and acks[0]["status_name"] == "resting")
        c.cancel("NDOH", 1)

    def test_udp_order_acked(self):
        c = UdpClient(HOST, UDP, 0x32)
        self.addCleanup(c.close)
        c.order("NDOH", BUY, 9001, 5, 1)
        acks = [m for m in self.drain(c) if m["type"] == "ACK"]
        self.assertTrue(acks and acks[0]["status_name"] == "resting")
        c.cancel("NDOH", 1)

    def test_rest_order_acked(self):
        c = RestClient(HOST, HTTP, 0x33)
        r = c.order("NDOH", BUY, 9002, 5, 1)
        self.assertEqual(r["type"], "ACK")
        c.cancel("NDOH", 1)

    def test_rest_bids_are_filled_by_a_udp_seller(self):
        """The load-bearing test: two transports, one book, a real trade."""
        rest = RestClient(HOST, HTTP, 0x41)
        udp = UdpClient(HOST, UDP, 0x42)
        self.addCleanup(udp.close)
        self.drain(udp, 0.2)

        ack = rest.order("NDOH", BUY, 11000, 7, 1)
        self.assertEqual(ack["status_name"], "resting")

        udp.order("NDOH", SELL, 10900, 7, 1)
        msgs = self.drain(udp, 0.6)
        acks = [m for m in msgs if m["type"] == "ACK"]
        trades = [m for m in msgs if m["type"] == "TRADE"]
        self.assertTrue(acks, "seller got no ACK")
        self.assertEqual(acks[0]["status_name"], "filled")
        self.assertEqual(acks[0]["filled"], 7)
        self.assertTrue(trades, "no trade was published")
        self.assertEqual(trades[0]["px"], 11000, "fills at the resting price")
        self.assertEqual({trades[0]["buy_firm"], trades[0]["sell_firm"]}, {0x41, 0x42})

    def test_tcp_and_rest_see_the_same_book(self):
        tcp = TcpClient(HOST, TCP, 0x51)
        self.addCleanup(tcp.close)
        self.drain(tcp, 0.2)
        tcp.order("NDOH", BUY, 12345, 3, 1)
        self.drain(tcp, 0.4)
        with urllib.request.urlopen(f"http://{HOST}:{HTTP}/quote", timeout=2) as r:
            q = json.load(r)
        self.assertEqual(q["bid"], 12345)
        self.assertEqual(tcp.last_quote["bid"], 12345)
        tcp.cancel("NDOH", 1)


class TestValidation(Live):
    def test_rest_rejects_bad_side(self):
        c = RestClient(HOST, HTTP, 0x61)
        self.assertEqual(c.order("NDOH", 9, 100, 1, 1)["type"], "REJECT")

    def test_rest_rejects_zero_qty(self):
        c = RestClient(HOST, HTTP, 0x62)
        self.assertEqual(c.order("NDOH", BUY, 100, 0, 1)["type"], "REJECT")

    def test_rest_requires_firm_header(self):
        req = urllib.request.Request(f"http://{HOST}:{HTTP}/order", method="POST",
                                     data=b'{"side":0,"px":1,"qty":1,"coid":1}')
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(req, timeout=2)
        self.assertEqual(cm.exception.code, 401)

    def test_unknown_ticker_rejected(self):
        c = RestClient(HOST, HTTP, 0x63)
        self.assertEqual(c.order("ZZZZ", BUY, 100, 1, 1)["type"], "REJECT")

    def test_cancel_of_nothing_is_rejected(self):
        c = RestClient(HOST, HTTP, 0x64)
        self.assertEqual(c.cancel("NDOH", 999999)["type"], "REJECT")


class TestImpairmentLayering(Live):
    """The correction that matters: loss must not delete TCP messages."""

    def test_udp_loses_messages(self):
        self.impair("lossy", "udp")
        c = UdpClient(HOST, UDP, 0x71)
        self.addCleanup(c.close)
        self.drain(c, 0.2)
        for i in range(60):
            c.order("NDOH", BUY, 8000 + i, 1, i + 1)
            self.drain(c, 0.02)
        acks = len([m for m in self.drain(c, 0.5) if m["type"] == "ACK"]) + c.acks
        self.assertLess(acks, 60, "15% loss should cost UDP some ACKs outright")

    def test_tcp_loses_time_not_messages(self):
        self.impair("lossy", "tcp")
        c = TcpClient(HOST, TCP, 0x72)
        self.addCleanup(c.close)
        self.drain(c, 0.2)
        n = 25
        for i in range(n):
            c.order("NDOH", BUY, 7000 + i, 1, i + 1)
        got, end = 0, time.time() + 8.0
        while c.acks < n and time.time() < end:
            c.poll(0.05)
        self.assertEqual(c.acks, n,
                         "TCP must deliver every ACK -- loss becomes latency, "
                         "not lost application messages")

    def test_impairment_is_per_gateway(self):
        r = self.impair("satellite", "udp")
        self.assertIn("280", r["udp"]["impairment"])
        with urllib.request.urlopen(f"http://{HOST}:{HTTP}/admin/impair", timeout=2) as h:
            all_ = json.load(h)
        self.assertEqual(all_["tcp"]["impairment"], "clean")
        self.assertEqual(all_["udp"]["mode"], "datagram (UDP)")
        self.assertEqual(all_["tcp"]["mode"], "stream (TCP)")


if __name__ == "__main__":
    unittest.main(verbosity=2)
