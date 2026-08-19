#include "bframe.h"

uint16_t bf_crc16_update(uint16_t crc, uint8_t b) {
  crc ^= (uint16_t)b << 8;
  for (uint8_t i = 0; i < 8; i++)
    crc = (crc & 0x8000) ? (uint16_t)((crc << 1) ^ 0x1021) : (uint16_t)(crc << 1);
  return crc;
}

uint16_t bf_crc16(const uint8_t* data, size_t len) {
  uint16_t crc = 0xFFFF;
  for (size_t i = 0; i < len; i++) crc = bf_crc16_update(crc, data[i]);
  return crc;
}

size_t bf_encode(const BFrame* f, uint8_t* out, size_t out_cap) {
  if (!f || !out) return 0;
  if (f->len > BF_MAX_PAYLOAD) return 0;
  size_t need = BF_OVERHEAD + f->len;
  if (out_cap < need) return 0;

  size_t i = 0;
  out[i++] = BF_PREAMBLE;
  out[i++] = BF_PREAMBLE;
  out[i++] = BF_SFD;
  size_t crc_start = i;              // CRC covers LEN..PAYLOAD
  out[i++] = f->len;
  out[i++] = f->src;
  out[i++] = f->dst;
  out[i++] = f->type;
  for (uint8_t k = 0; k < f->len; k++) out[i++] = f->payload[k];
  uint16_t crc = bf_crc16(out + crc_start, i - crc_start);
  out[i++] = (uint8_t)(crc >> 8);
  out[i++] = (uint8_t)(crc & 0xFF);
  return i;
}

int bf_decode_body(const uint8_t* body, size_t body_len, BFrame* out) {
  if (!body || !out) return 0;
  if (body_len < BF_HDR_LEN + BF_CRC_LEN) return 0;
  uint8_t len = body[0];
  if (len > BF_MAX_PAYLOAD) return 0;
  size_t need = (size_t)BF_HDR_LEN + len + BF_CRC_LEN;
  if (body_len < need) return 0;

  uint16_t want = ((uint16_t)body[BF_HDR_LEN + len] << 8) | body[BF_HDR_LEN + len + 1];
  uint16_t got  = bf_crc16(body, BF_HDR_LEN + len);
  if (want != got) return 0;

  out->len  = len;
  out->src  = body[1];
  out->dst  = body[2];
  out->type = body[3];
  for (uint8_t k = 0; k < len; k++) out->payload[k] = body[BF_HDR_LEN + k];
  return 1;
}

int bf_decode(const uint8_t* raw, size_t raw_len, BFrame* out) {
  for (size_t i = 0; i + 1 < raw_len; i++) {
    if (raw[i] == BF_SFD && i > 0 && raw[i-1] == BF_PREAMBLE)
      return bf_decode_body(raw + i + 1, raw_len - i - 1, out);
  }
  return 0;
}
