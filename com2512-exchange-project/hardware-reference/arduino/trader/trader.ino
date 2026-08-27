// trader.ino -- a member firm: sends orders, consumes market data.
// Change FIRM_ID per board. Lower ids win contested bus slots.

#include <BStack.h>

#define FIRM_ID  0x21          // 0x21, 0x22, 0x24, 0x41 ... one per trader board
#define VENUE_ID 0x01

BStack bus;
uint8_t next_order_id = 1;
uint16_t last_bid = 0, last_ask = 0;
uint32_t acks = 0, quotes = 0, my_trades = 0;

void sendOrder(uint8_t side, uint16_t px, uint16_t qty) {
  BFrame o{};
  o.src = FIRM_ID; o.dst = VENUE_ID; o.type = BF_T_ORDER; o.len = 6;
  o.payload[0] = side;
  o.payload[1] = next_order_id++;
  o.payload[2] = (uint8_t)(px >> 8);  o.payload[3] = (uint8_t)px;
  o.payload[4] = (uint8_t)(qty >> 8); o.payload[5] = (uint8_t)qty;
  bus.send(&o);
}

void setup() {
  bus.begin(FIRM_ID);
  Serial.begin(115200);
  Serial.print(F("trader up, firm 0x")); Serial.println(FIRM_ID, HEX);
}

void loop() {
  BFrame f{};
  if (bus.poll(&f)) {
    if (f.type == BF_T_QUOTE && f.len >= 8) {
      last_bid = (uint16_t)(f.payload[2] << 8 | f.payload[3]);
      last_ask = (uint16_t)(f.payload[6] << 8 | f.payload[7]);
      quotes++;
    } else if (f.type == BF_T_TRADE && f.len >= 6) {
      if (f.payload[0] == FIRM_ID || f.payload[1] == FIRM_ID) my_trades++;
    } else if (f.type == BF_T_ACK && f.dst == FIRM_ID) {
      acks++;
    }
  }

  // A deliberately simple strategy: quote around the last seen mid.
  static uint32_t t0 = 0;
  if (millis() - t0 > 1500) {
    t0 = millis();
    uint16_t mid = (last_bid && last_ask && last_ask != 0xFFFF)
                 ? (uint16_t)((last_bid + last_ask) / 2) : 300;
    sendOrder(random(2) ? SIDE_BUY : SIDE_SELL,
              (uint16_t)(mid + random(-3, 4)), (uint16_t)random(1, 6));
  }

  static uint32_t t1 = 0;
  if (millis() - t1 > 5000) {
    t1 = millis();
    Serial.print(F("sent ")); Serial.print(bus.sent);
    Serial.print(F(" acks ")); Serial.print(acks);
    Serial.print(F(" quotes ")); Serial.print(quotes);
    Serial.print(F(" myTrades ")); Serial.print(my_trades);
    Serial.print(F(" collisions ")); Serial.print(bus.collisions);
    Serial.print(F(" crcErr ")); Serial.println(bus.rx.crc_errors);
  }
}
