// bframe.h -- B-Stack hardware frame format. Portable: builds for AVR and host.
//
//   PREAMBLE 0xAA 0xAA   alternating bits: lets a receiver lock its bit clock
//   SFD      0xD5        start-of-frame delimiter, breaks the preamble pattern
//   LEN      1 byte      payload length, 0..BF_MAX_PAYLOAD
//   SRC      1 byte      station id  (bitwise-arbitration priority: lower wins)
//   DST      1 byte      station id, 0xFF = broadcast
//   TYPE     1 byte      message type
//   PAYLOAD  LEN bytes
//   CRC16    2 bytes     CRC-16/CCITT-FALSE over LEN..PAYLOAD inclusive, big-endian
//
// The CRC deliberately does NOT cover the preamble or SFD: those are physical-layer
// framing, not data, and a receiver that has not yet locked will not have seen them
// identically.
#ifndef BFRAME_H
#define BFRAME_H

#include <stdint.h>
#include <stddef.h>

#define BF_PREAMBLE   0xAA
#define BF_SFD        0xD5
#define BF_BROADCAST  0xFF
#define BF_MAX_PAYLOAD 64
#define BF_HDR_LEN     4          // LEN SRC DST TYPE
#define BF_CRC_LEN     2
#define BF_OVERHEAD   (3 + BF_HDR_LEN + BF_CRC_LEN)   // 2 preamble + SFD + hdr + crc

// message types
enum {
  BF_T_QUOTE  = 0x10,   // top-of-book update  (radio + wire)
  BF_T_BOOK   = 0x11,   // full depth update   (wire only)
  BF_T_TRADE  = 0x12,   // execution print
  BF_T_ORDER  = 0x20,   // new order
  BF_T_CANCEL = 0x21,
  BF_T_ACK    = 0x30,
  BF_T_HELLO  = 0x40    // neighbour discovery
};

struct BFrame {
  uint8_t src, dst, type, len;
  uint8_t payload[BF_MAX_PAYLOAD];
};

// CRC-16/CCITT-FALSE: poly 0x1021, init 0xFFFF, no reflection, no final xor.
// Check value: crc16("123456789") == 0x29B1  (use this to validate your build)
uint16_t bf_crc16(const uint8_t* data, size_t len);
uint16_t bf_crc16_update(uint16_t crc, uint8_t b);

// Serialise f into out (must be >= BF_OVERHEAD + f.len). Returns bytes written, 0 on error.
size_t bf_encode(const BFrame* f, uint8_t* out, size_t out_cap);

// Parse a frame body that starts at LEN (i.e. preamble+SFD already consumed).
// Returns 1 on success, 0 on bad length or CRC mismatch.
int bf_decode_body(const uint8_t* body, size_t body_len, BFrame* out);

// Convenience: find SFD in a raw buffer and decode. Returns 1 on success.
int bf_decode(const uint8_t* raw, size_t raw_len, BFrame* out);

#endif
