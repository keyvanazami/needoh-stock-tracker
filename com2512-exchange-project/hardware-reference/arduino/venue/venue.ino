// venue.ino -- the exchange: matching engine + market data publisher.
// Station id 0x01 (lowest on the bus, so the venue wins arbitration -- see note below).
//
// WIRING: D4 to the shared bus, common ground, ONE 4.7k pull-up on the bus.
//
// A note on the id: giving the venue the lowest id means it always wins a
// contested slot. That is convenient and it is also exactly the unfairness
// students must confront in Phase 6. Leave it until then.

#include <BStack.h>
#include <book.h>

#define VENUE_ID 0x01

BStack bus;
Book   book;
uint16_t last_bid = 0, last_ask = 0;
uint32_t orders = 0, trades = 0;

void publishQuote() {
  BFrame q{};
  q.src = VENUE_ID; q.dst = BF_BROADCAST; q.type = BF_T_QUOTE; q.len = 8;
  uint16_t bb = book.best_bid(), ba = book.best_ask();
  uint16_t bq = book.bid_qty(),  aq = book.ask_qty();
  q.payload[0] = 0x00;                    // symbol index 0
  q.payload[1] = 0x01;                    // quote message version
  q.payload[2] = (uint8_t)(bb >> 8); q.payload[3] = (uint8_t)bb;
  q.payload[4] = (uint8_t)(bq >> 8); q.payload[5] = (uint8_t)bq;
  q.payload[6] = (uint8_t)(ba >> 8); q.payload[7] = (uint8_t)ba;
  bus.send(&q);
}

void publishTrade(const Fill& f) {
  BFrame t{};
  t.src = VENUE_ID; t.dst = BF_BROADCAST; t.type = BF_T_TRADE; t.len = 6;
  t.payload[0] = f.buy_firm; t.payload[1] = f.sell_firm;
  t.payload[2] = (uint8_t)(f.px >> 8);  t.payload[3] = (uint8_t)f.px;
  t.payload[4] = (uint8_t)(f.qty >> 8); t.payload[5] = (uint8_t)f.qty;
  bus.send(&t);
}

void setup() {
  bus.begin(VENUE_ID);
  Serial.begin(115200);
  Serial.println(F("venue up, id 0x01"));
}

void loop() {
  BFrame f{};
  if (bus.poll(&f)) {
    if (f.type == BF_T_ORDER && f.len >= 6) {
      Order o;
      o.firm = f.src;
      o.side = f.payload[0];
      o.id   = f.payload[1];
      o.px   = (uint16_t)(f.payload[2] << 8 | f.payload[3]);
      o.qty  = (uint16_t)(f.payload[4] << 8 | f.payload[5]);
      orders++;

      Fill fills[4];
      uint8_t n = book.submit(o, fills, 4);
      for (uint8_t i = 0; i < n; i++) { publishTrade(fills[i]); trades++; }

      // acknowledge the order back to the sending firm
      BFrame ack{};
      ack.src = VENUE_ID; ack.dst = f.src; ack.type = BF_T_ACK; ack.len = 2;
      ack.payload[0] = o.id; ack.payload[1] = n;
      bus.send(&ack);

      // publish a new quote only when the top of book actually moved
      if (book.best_bid() != last_bid || book.best_ask() != last_ask) {
        last_bid = book.best_bid(); last_ask = book.best_ask();
        publishQuote();
      }
    }
  }

  static uint32_t t0 = 0;
  if (millis() - t0 > 5000) {                 // heartbeat quote and stats
    t0 = millis();
    publishQuote();
    Serial.print(F("orders ")); Serial.print(orders);
    Serial.print(F(" trades ")); Serial.print(trades);
    Serial.print(F(" bid ")); Serial.print(book.best_bid());
    Serial.print(F(" ask ")); Serial.print(book.best_ask());
    Serial.print(F(" collisions ")); Serial.print(bus.collisions);
    Serial.print(F(" stuck ")); Serial.println(bus.stuck);   // >0 = bus jammed dominant
  }
}
