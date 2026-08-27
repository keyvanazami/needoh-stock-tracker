import sys, pathlib, unittest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from exchange.book import BUY, SELL, Book, Order


def o(firm, side, px, qty, coid=1):
    return Order(firm=firm, side=side, px=px, qty=qty, coid=coid)


class TestPriority(unittest.TestCase):
    def test_best_price_first(self):
        b = Book()
        b.submit(o(1, BUY, 100, 10)); b.submit(o(2, BUY, 102, 5))
        self.assertEqual(b.best_bid(), 102)

    def test_time_priority_at_equal_price(self):
        b = Book()
        b.submit(o(7, BUY, 100, 5)); b.submit(o(8, BUY, 100, 5))
        fills = b.submit(o(9, SELL, 100, 5))
        self.assertEqual(fills[0].buy_firm, 7, "earlier order must fill first")

    def test_resting_price_wins(self):
        """The passive side keeps its price -- the aggressor gets improvement."""
        b = Book()
        b.submit(o(1, BUY, 102, 5))
        fills = b.submit(o(2, SELL, 100, 5))
        self.assertEqual(fills[0].px, 102)


class TestMatching(unittest.TestCase):
    def test_partial_fill_rests_remainder(self):
        b = Book()
        b.submit(o(1, BUY, 100, 4))
        fills = b.submit(o(2, SELL, 100, 10))
        self.assertEqual(sum(f.qty for f in fills), 4)
        self.assertEqual(b.best_ask(), 100)
        self.assertEqual(b.qty_at(SELL, 100), 6)

    def test_sweeps_multiple_levels(self):
        b = Book()
        b.submit(o(1, SELL, 100, 3)); b.submit(o(2, SELL, 101, 3)); b.submit(o(3, SELL, 102, 3))
        fills = b.submit(o(9, BUY, 102, 9))
        self.assertEqual([f.px for f in fills], [100, 101, 102])
        self.assertIsNone(b.best_ask())

    def test_wide_spread_does_not_cross(self):
        b = Book()
        b.submit(o(1, BUY, 95, 5)); b.submit(o(2, SELL, 105, 5))
        self.assertEqual((b.best_bid(), b.best_ask()), (95, 105))
        self.assertEqual(b.trade_count, 0)

    def test_cancel_removes_from_book(self):
        b = Book()
        b.submit(o(1, BUY, 100, 5, coid=42))
        self.assertTrue(b.cancel(1, 42))
        self.assertIsNone(b.best_bid())
        self.assertFalse(b.cancel(1, 42), "second cancel must fail")

    def test_cancel_is_per_firm(self):
        b = Book()
        b.submit(o(1, BUY, 100, 5, coid=42))
        self.assertFalse(b.cancel(2, 42), "a firm must not cancel another's order")

    def test_rejects_nonpositive(self):
        b = Book()
        for bad in (o(1, BUY, 0, 5), o(1, BUY, 100, 0), o(1, BUY, -5, 5)):
            with self.assertRaises(ValueError):
                b.submit(bad)

    def test_conservation_of_quantity(self):
        """Nothing is created or destroyed: traded + resting == submitted."""
        import random
        rng = random.Random(11)
        b = Book()
        submitted = traded = 0
        for i in range(400):
            q = rng.randrange(1, 9)
            submitted += q
            traded += sum(f.qty for f in
                          b.submit(o(rng.randrange(1, 5), rng.randrange(2),
                                     100 + rng.randrange(-6, 7), q, i)))
        resting = sum(x.qty for x in b.bids) + sum(x.qty for x in b.asks)
        self.assertEqual(submitted, traded * 2 + resting,
                         "each fill consumes quantity from both sides")


if __name__ == "__main__":
    unittest.main(verbosity=2)
