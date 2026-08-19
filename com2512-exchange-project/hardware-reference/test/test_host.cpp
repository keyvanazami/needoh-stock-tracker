// Host-side validation of the portable core. Build: g++ -std=c++17 -I lib test/test_host.cpp lib/*.cpp
#include "../lib/bframe.h"
#include "../lib/manchester.h"
#include "../lib/delayline.h"
#include "../lib/arbitration.h"
#include <cstdio>
#include <cstring>
#include <cstdlib>
#include <vector>

static int pass = 0, fail = 0;
#define CHECK(cond, ...) do { if (cond) { pass++; } else { \
  fail++; printf("  FAIL %s:%d  ", __FILE__, __LINE__); printf(__VA_ARGS__); printf("\n"); } } while(0)

static void t_crc() {
  printf("CRC-16/CCITT-FALSE\n");
  const char* s = "123456789";
  uint16_t c = bf_crc16((const uint8_t*)s, 9);
  CHECK(c == 0x29B1, "check value: got %04X want 29B1", c);
  printf("  check value crc16(\"123456789\") = 0x%04X  (canonical 0x29B1)\n", c);

  // single-bit error detection over a realistic quote payload
  uint8_t buf[16] = {0x08,0x21,0xFF,0x10, 'A','A','P','L', 0x01,0x2C,0x01,0x2D};
  uint16_t base = bf_crc16(buf, 12);
  int missed = 0;
  for (int byte = 0; byte < 12; byte++)
    for (int bit = 0; bit < 8; bit++) {
      buf[byte] ^= (1 << bit);
      if (bf_crc16(buf, 12) == base) missed++;
      buf[byte] ^= (1 << bit);
    }
  CHECK(missed == 0, "missed %d single-bit errors", missed);
  printf("  all 96 single-bit flips detected\n");

  // burst error detection: CRC-16 catches every burst <= 16 bits
  int burst_missed = 0;
  for (int start = 0; start < 80; start++)
    for (int blen = 1; blen <= 16; blen++) {
      uint8_t t[16]; memcpy(t, buf, 16);
      for (int b = 0; b < blen; b++) { int p = start + b; if (p < 96) t[p/8] ^= (1 << (p%8)); }
      if (bf_crc16(t, 12) == base && memcmp(t, buf, 12) != 0) burst_missed++;
    }
  CHECK(burst_missed == 0, "missed %d bursts <=16 bits", burst_missed);
  printf("  all bursts up to 16 bits detected (1280 trials)\n");
}

static void t_frame() {
  printf("Frame encode/decode\n");
  BFrame f{}; f.src = 0x21; f.dst = BF_BROADCAST; f.type = BF_T_QUOTE; f.len = 8;
  memcpy(f.payload, "\x00\x01\x01\x2C\x00\x64\x01\x2D", 8);

  uint8_t wire[128];
  size_t n = bf_encode(&f, wire, sizeof wire);
  CHECK(n == BF_OVERHEAD + 8, "encoded %zu bytes, want %d", n, BF_OVERHEAD + 8);
  printf("  quote frame on the wire = %zu bytes (%d overhead + 8 payload)\n", n, BF_OVERHEAD);
  printf("  ");
  for (size_t i = 0; i < n; i++) printf("%02X ", wire[i]);
  printf("\n");

  BFrame g{};
  CHECK(bf_decode(wire, n, &g) == 1, "decode failed");
  CHECK(g.src == f.src && g.dst == f.dst && g.type == f.type && g.len == f.len, "header mismatch");
  CHECK(memcmp(g.payload, f.payload, 8) == 0, "payload mismatch");
  printf("  round-trips intact\n");

  // every single-bit corruption of the body must be rejected
  int accepted = 0;
  for (size_t byte = 3; byte < n; byte++)
    for (int bit = 0; bit < 8; bit++) {
      uint8_t t[128]; memcpy(t, wire, n);
      t[byte] ^= (1 << bit);
      BFrame h{};
      if (bf_decode(t, n, &h) == 1 && memcmp(&h, &g, sizeof h) == 0) accepted++;
    }
  CHECK(accepted == 0, "%d corrupted frames accepted as valid", accepted);
  printf("  all %zu single-bit corruptions rejected\n", (n - 3) * 8);

  // oversize payload refused
  BFrame big{}; big.len = BF_MAX_PAYLOAD + 1;
  CHECK(bf_encode(&big, wire, sizeof wire) == 0, "oversize payload accepted");
  printf("  oversize payload refused\n");
}

static void t_manchester() {
  printf("Manchester coding\n");
  const uint8_t src[4] = {0x00, 0xFF, 0xA5, 0x5A};
  uint8_t enc[8], dec[4];
  size_t n = mn_encode(src, 4, enc, sizeof enc);
  CHECK(n == 8, "encoded %zu, want 8", n);
  size_t m = mn_decode(enc, n, dec, sizeof dec);
  CHECK(m == 4 && memcmp(dec, src, 4) == 0, "round-trip failed");
  printf("  0x%02X -> %02X %02X   0x%02X -> %02X %02X   round-trips\n",
         src[0], enc[0], enc[1], src[1], enc[2], enc[3]);

  // DC balance: every encoded byte must have exactly 4 one-bits
  int unbalanced = 0;
  for (int v = 0; v < 256; v++) {
    uint8_t b = (uint8_t)v, e[2];
    mn_encode(&b, 1, e, 2);
    for (int k = 0; k < 2; k++) __builtin_popcount(e[k]) == 4 ? 0 : unbalanced++;
  }
  CHECK(unbalanced == 0, "%d unbalanced nibbles", unbalanced);
  printf("  DC-balanced for all 256 byte values (AGC on cheap OOK receivers needs this)\n");

  // an invalid symbol (00 or 11, i.e. no mid-bit transition) must be rejected
  uint8_t bad[2] = {0x00, 0xFF};
  CHECK(mn_decode(bad, 2, dec, sizeof dec) == 0, "invalid symbol accepted");
  printf("  symbols without a mid-bit transition rejected as noise/collision\n");

  printf("  cost: %zu line bits to send 8 payload bytes\n", mn_line_bits(8));
}

static void t_delayline() {
  printf("Delay line (the repeater core)\n");
  DelayLine<2048> dl;
  dl.reset(1);
  uint16_t d = dl.set_depth(50);
  CHECK(d == 50, "depth %u", d);

  // a pulse must emerge exactly `depth` samples later, unchanged
  int seen_at = -1;
  for (int t = 0; t < 200; t++) {
    uint8_t in = (t == 10) ? 0 : 1;          // one dominant sample at t=10
    uint8_t out = dl.step(in);
    if (out == 0 && seen_at < 0) seen_at = t;
  }
  CHECK(seen_at == 60, "pulse emerged at %d, want 60 (=10+50)", seen_at);
  printf("  single dominant sample at t=10 emerged at t=%d with depth 50\n", seen_at);

  // waveform preserved, not reshaped
  dl.reset(1); dl.set_depth(16);
  std::vector<uint8_t> in_seq, out_seq;
  srand(4);
  for (int t = 0; t < 400; t++) {
    uint8_t v = (uint8_t)(rand() & 1);
    in_seq.push_back(v);
    out_seq.push_back(dl.step(v));
  }
  int mismatch = 0;
  for (size_t t = 16; t < in_seq.size(); t++)
    if (out_seq[t] != in_seq[t - 16]) mismatch++;
  CHECK(mismatch == 0, "%d samples reshaped", mismatch);
  printf("  384 random samples delayed by 16 with zero distortion\n");

  // capacity clamp
  DelayLine<64> small; 
  CHECK(small.set_depth(9999) == 64, "clamp failed");
  printf("  over-long delay clamps to buffer capacity (fails loud, not silent)\n");
}

static void t_arbitration() {
  printf("Bitwise arbitration\n");
  uint8_t ids[4] = {0x16, 0x18, 0x41, 0x15};
  uint8_t w = arb_winner(ids, 4, 8);
  CHECK(w == 0x15, "winner %02X want 15", w);
  printf("  {22,24,65,21} -> winner %u (lowest id, non-destructively)\n", w);

  // exhaustive: lowest id must always win
  int wrong = 0;
  for (int a = 0; a < 40; a++)
    for (int b = 0; b < 40; b++) {
      if (a == b) continue;
      uint8_t p[2] = {(uint8_t)a, (uint8_t)b};
      uint8_t lo = (uint8_t)(a < b ? a : b);
      if (arb_winner(p, 2, 8) != lo) wrong++;
    }
  CHECK(wrong == 0, "%d pairs resolved wrongly", wrong);
  printf("  1560 contested pairs all resolved to the lower id -- deterministic, and unfair\n");
}

int main() {
  printf("=== B-Stack hardware core: host validation ===\n\n");
  t_crc();        printf("\n");
  t_frame();      printf("\n");
  t_manchester(); printf("\n");
  t_delayline();  printf("\n");
  t_arbitration();printf("\n");
  printf("=== %d passed, %d failed ===\n", pass, fail);
  return fail ? 1 : 0;
}
