#include "manchester.h"

// each input byte -> two output bytes, each holding 4 encoded bit-pairs
size_t mn_encode(const uint8_t* in, size_t len, uint8_t* out, size_t out_cap) {
  if (out_cap < len * 2) return 0;
  size_t o = 0;
  for (size_t i = 0; i < len; i++) {
    for (int half = 1; half >= 0; half--) {          // high nibble first
      uint8_t acc = 0;
      for (int k = 3; k >= 0; k--) {                 // 4 source bits -> 8 line bits
        uint8_t bit = (in[i] >> (half * 4 + k)) & 1;
        // 0 -> 10, 1 -> 01
        acc = (uint8_t)((acc << 2) | (bit ? 0x1 : 0x2));
      }
      out[o++] = acc;
    }
  }
  return o;
}

size_t mn_decode(const uint8_t* in, size_t len, uint8_t* out, size_t out_cap) {
  if (len % 2) return 0;
  if (out_cap < len / 2) return 0;
  size_t o = 0;
  for (size_t i = 0; i < len; i += 2) {
    uint8_t val = 0;
    for (int b = 0; b < 2; b++) {
      uint8_t enc = in[i + b];
      for (int k = 3; k >= 0; k--) {
        uint8_t sym = (enc >> (k * 2)) & 0x3;
        if (sym == 0x0 || sym == 0x3) return 0;      // no mid-bit transition: invalid
        val = (uint8_t)((val << 1) | (sym == 0x1 ? 1 : 0));
      }
    }
    out[o++] = val;
  }
  return o;
}
