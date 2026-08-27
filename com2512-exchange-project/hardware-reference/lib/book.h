// book.h -- a minimal limit order book with price-time priority.
//
// Sized for an ATmega328P: fixed arrays, no allocation, 8 levels per side.
// Prices are integer ticks; quantities are integer lots. Both are uint16_t,
// which is deliberate -- overflow behaviour is something students should reason
// about rather than discover.
#ifndef BOOK_H
#define BOOK_H

#include <stdint.h>

#define SIDE_BUY  0
#define SIDE_SELL 1
#define BOOK_DEPTH 8

struct Order { uint8_t firm, side, id; uint16_t px, qty; };
struct Fill  { uint8_t buy_firm, sell_firm; uint16_t px, qty; };

class Book {
 public:
  Order bids[BOOK_DEPTH], asks[BOOK_DEPTH];
  uint8_t nbid = 0, nask = 0;

  uint16_t best_bid() const { return nbid ? bids[0].px : 0; }
  uint16_t best_ask() const { return nask ? asks[0].px : 0xFFFF; }
  uint16_t bid_qty()  const { return nbid ? bids[0].qty : 0; }
  uint16_t ask_qty()  const { return nask ? asks[0].qty : 0; }

  // Match an incoming order against the resting side, then rest the remainder.
  // Returns the number of fills written to fills[].
  uint8_t submit(Order in, Fill* fills, uint8_t maxf) {
    uint8_t nf = 0;
    if (in.side == SIDE_BUY) {
      while (in.qty && nask && asks[0].px <= in.px && nf < maxf) {
        uint16_t q = in.qty < asks[0].qty ? in.qty : asks[0].qty;
        fills[nf++] = { in.firm, asks[0].firm, asks[0].px, q };
        in.qty -= q; asks[0].qty -= q;
        if (!asks[0].qty) pop(asks, nask);
      }
      if (in.qty) rest(bids, nbid, in, true);
    } else {
      while (in.qty && nbid && bids[0].px >= in.px && nf < maxf) {
        uint16_t q = in.qty < bids[0].qty ? in.qty : bids[0].qty;
        fills[nf++] = { bids[0].firm, in.firm, bids[0].px, q };
        in.qty -= q; bids[0].qty -= q;
        if (!bids[0].qty) pop(bids, nbid);
      }
      if (in.qty) rest(asks, nask, in, false);
    }
    return nf;
  }

 private:
  static void pop(Order* a, uint8_t& n) {
    for (uint8_t i = 1; i < n; i++) a[i-1] = a[i];
    if (n) n--;
  }
  // Insert keeping price priority; equal prices keep arrival (time) order.
  static void rest(Order* a, uint8_t& n, const Order& o, bool desc) {
    if (n >= BOOK_DEPTH) return;                  // book full: drop, do not corrupt
    uint8_t i = 0;
    while (i < n && (desc ? a[i].px >= o.px : a[i].px <= o.px)) i++;
    for (uint8_t k = n; k > i; k--) a[k] = a[k-1];
    a[i] = o; n++;
  }
};

#endif
