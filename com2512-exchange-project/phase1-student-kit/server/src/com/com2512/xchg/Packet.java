package com.com2512.xchg;

import java.nio.charset.StandardCharsets;

/**
 * XCHG/1 wire format — the single source of truth for the protocol.
 *
 * Envelope, all multi-byte fields big-endian (network order):
 *
 *    0                   1
 *    0 1 2 3 4 5 6 7 8 9 0 1
 *   +-------+---+---+-------+-------+-------+
 *   | MAGIC |VER|TYP|  SESS |  SEQ  | PAYLEN|
 *   +-------+---+---+-------+-------+-------+
 *   |  PAYLOAD (PAYLEN bytes) ...           |
 *   +---------------------------------------+
 *   |  CRC16                                |
 *   +-------+
 *
 * Header is 10 bytes; CRC16 is 2 bytes over header+payload. A datagram is
 * therefore exactly 12 + PAYLEN bytes, and UDP already told us where it ends —
 * which is why there is no length-prefix framing here, unlike a TCP protocol.
 * PAYLEN is still present so a receiver can reject a truncated datagram.
 */
public final class Packet {

    public static final int MAGIC = 0x5843;     // 'X','C'
    public static final int VERSION = 1;
    public static final int HEADER_LEN = 10;
    public static final int CRC_LEN = 2;
    public static final int OVERHEAD = HEADER_LEN + CRC_LEN;   // 12
    public static final int MAX_PAYLOAD = 512;
    public static final int MAX_DATAGRAM = OVERHEAD + MAX_PAYLOAD;

    // ---- message types. QUOTE/ORDER/TRADE/ACK/HELLO reuse the hardware
    // ---- frame's numbering (hardware-reference/lib/bframe.h) on purpose.
    public static final int T_QUOTE     = 0x10;
    public static final int T_TRADE     = 0x12;
    public static final int T_ORDER     = 0x20;
    public static final int T_CANCEL    = 0x21;
    public static final int T_ACK       = 0x30;
    public static final int T_HELLO     = 0x40;
    public static final int T_WELCOME   = 0x41;
    public static final int T_BYE       = 0x42;
    public static final int T_SUBSCRIBE = 0x50;
    public static final int T_PING      = 0x60;
    public static final int T_PONG      = 0x61;
    public static final int T_ERROR     = 0x7F;

    // ---- sides: ASCII so they are readable in a hexdump
    public static final int SIDE_BUY  = 0x42;   // 'B'
    public static final int SIDE_SELL = 0x53;   // 'S'

    // ---- ACK status
    public static final int ST_RESTING   = 0;
    public static final int ST_PARTIAL   = 1;
    public static final int ST_FILLED    = 2;
    public static final int ST_REJECTED  = 3;
    public static final int ST_CANCELLED = 4;

    // ---- ACK reject reasons
    public static final int R_NONE           = 0;
    public static final int R_UNKNOWN_SYMBOL = 1;
    public static final int R_BAD_SIDE       = 2;
    public static final int R_ZERO_QTY       = 3;
    public static final int R_ZERO_PRICE     = 4;
    public static final int R_TOO_MANY       = 5;
    public static final int R_UNKNOWN_ORDER  = 6;
    public static final int R_NOT_YOUR_ORDER = 7;

    // ---- ERROR codes
    public static final int E_MAGIC   = 0x01;
    public static final int E_VERSION = 0x02;
    public static final int E_CRC     = 0x03;
    public static final int E_LENGTH  = 0x04;
    public static final int E_TYPE    = 0x05;
    public static final int E_SESSION = 0x06;
    public static final int E_PAYLOAD = 0x07;
    public static final int E_NOHELLO = 0x08;
    public static final int E_RATE    = 0x09;

    public static String typeName(int t) {
        switch (t) {
            case T_QUOTE: return "QUOTE";
            case T_TRADE: return "TRADE";
            case T_ORDER: return "ORDER";
            case T_CANCEL: return "CANCEL";
            case T_ACK: return "ACK";
            case T_HELLO: return "HELLO";
            case T_WELCOME: return "WELCOME";
            case T_BYE: return "BYE";
            case T_SUBSCRIBE: return "SUBSCRIBE";
            case T_PING: return "PING";
            case T_PONG: return "PONG";
            case T_ERROR: return "ERROR";
            default: return String.format("0x%02X", t);
        }
    }

    public static String errorName(int code) {
        switch (code) {
            case E_MAGIC: return "E_MAGIC";
            case E_VERSION: return "E_VERSION";
            case E_CRC: return "E_CRC";
            case E_LENGTH: return "E_LENGTH";
            case E_TYPE: return "E_TYPE";
            case E_SESSION: return "E_SESSION";
            case E_PAYLOAD: return "E_PAYLOAD";
            case E_NOHELLO: return "E_NOHELLO";
            case E_RATE: return "E_RATE";
            default: return String.format("0x%02X", code);
        }
    }

    public static String statusName(int s) {
        switch (s) {
            case ST_RESTING: return "RESTING";
            case ST_PARTIAL: return "PARTIAL";
            case ST_FILLED: return "FILLED";
            case ST_REJECTED: return "REJECTED";
            case ST_CANCELLED: return "CANCELLED";
            default: return String.valueOf(s);
        }
    }

    public static String reasonName(int r) {
        switch (r) {
            case R_NONE: return "-";
            case R_UNKNOWN_SYMBOL: return "unknown symbol";
            case R_BAD_SIDE: return "bad side";
            case R_ZERO_QTY: return "zero qty";
            case R_ZERO_PRICE: return "zero price";
            case R_TOO_MANY: return "too many resting orders";
            case R_UNKNOWN_ORDER: return "unknown order id";
            case R_NOT_YOUR_ORDER: return "not your order";
            default: return String.valueOf(r);
        }
    }

    // ---- decoded form -----------------------------------------------------

    public final int type, session, seq;
    public final byte[] payload;

    public Packet(int type, int session, int seq, byte[] payload) {
        this.type = type;
        this.session = session;
        this.seq = seq;
        this.payload = payload;
    }

    /** Thrown by decode(); carries the ERROR code the server should reply with. */
    public static final class BadPacket extends Exception {
        private static final long serialVersionUID = 1L;
        public final int code;
        public BadPacket(int code, String msg) { super(msg); this.code = code; }
    }

    public static byte[] encode(int type, int session, int seq, byte[] payload) {
        if (payload == null) payload = new byte[0];
        if (payload.length > MAX_PAYLOAD)
            throw new IllegalArgumentException("payload too long: " + payload.length);
        byte[] out = new byte[OVERHEAD + payload.length];
        putU16(out, 0, MAGIC);
        out[2] = (byte) VERSION;
        out[3] = (byte) type;
        putU16(out, 4, session);
        putU16(out, 6, seq);
        putU16(out, 8, payload.length);
        System.arraycopy(payload, 0, out, HEADER_LEN, payload.length);
        int crc = Crc16.compute(out, 0, HEADER_LEN + payload.length);
        putU16(out, HEADER_LEN + payload.length, crc);
        return out;
    }

    /**
     * Decode one datagram. Checks are ordered deliberately: magic, version,
     * declared length against the datagram we actually received, then CRC.
     * Nothing in the packet is trusted until the CRC passes.
     */
    public static Packet decode(byte[] buf, int len) throws BadPacket {
        if (len < OVERHEAD)
            throw new BadPacket(E_LENGTH, "datagram is " + len + " bytes, minimum is " + OVERHEAD);
        int magic = getU16(buf, 0);
        if (magic != MAGIC)
            throw new BadPacket(E_MAGIC, String.format("magic 0x%04X, expected 0x%04X", magic, MAGIC));
        int ver = buf[2] & 0xFF;
        if (ver != VERSION)
            throw new BadPacket(E_VERSION, "version " + ver + ", this server speaks " + VERSION);
        int paylen = getU16(buf, 8);
        if (paylen > MAX_PAYLOAD)
            throw new BadPacket(E_LENGTH, "PAYLEN " + paylen + " exceeds max " + MAX_PAYLOAD);
        if (OVERHEAD + paylen != len)
            throw new BadPacket(E_LENGTH, "PAYLEN " + paylen + " implies a " + (OVERHEAD + paylen)
                    + "-byte datagram, but " + len + " bytes arrived");
        int want = Crc16.compute(buf, 0, HEADER_LEN + paylen);
        int got = getU16(buf, HEADER_LEN + paylen);
        if (want != got)
            throw new BadPacket(E_CRC, String.format("CRC 0x%04X, computed 0x%04X", got, want));
        byte[] payload = new byte[paylen];
        System.arraycopy(buf, HEADER_LEN, payload, 0, paylen);
        return new Packet(buf[3] & 0xFF, getU16(buf, 4), getU16(buf, 6), payload);
    }

    // ---- payload builders -------------------------------------------------

    public static byte[] quotePayload(int sym, int bidPx, int bidQty, int askPx, int askQty) {
        byte[] p = new byte[10];
        putU16(p, 0, sym); putU16(p, 2, bidPx); putU16(p, 4, bidQty);
        putU16(p, 6, askPx); putU16(p, 8, askQty);
        return p;
    }

    public static byte[] tradePayload(int sym, int px, int qty, int aggrSide, long tradeId) {
        byte[] p = new byte[11];
        putU16(p, 0, sym); putU16(p, 2, px); putU16(p, 4, qty);
        p[6] = (byte) aggrSide;
        putU32(p, 7, tradeId);
        return p;
    }

    public static byte[] ackPayload(long clOrdId, long orderId, int status, int reason,
                                    int filledQty, int restQty) {
        byte[] p = new byte[14];
        putU32(p, 0, clOrdId); putU32(p, 4, orderId);
        p[8] = (byte) status; p[9] = (byte) reason;
        putU16(p, 10, filledQty); putU16(p, 12, restQty);
        return p;
    }

    public static byte[] errorPayload(int code, int echoSeq, String reason) {
        byte[] r = reason.getBytes(StandardCharsets.US_ASCII);
        if (r.length > 200) r = java.util.Arrays.copyOf(r, 200);
        byte[] p = new byte[4 + r.length];
        p[0] = (byte) code;
        putU16(p, 1, echoSeq);
        p[3] = (byte) r.length;
        System.arraycopy(r, 0, p, 4, r.length);
        return p;
    }

    // ---- primitives -------------------------------------------------------

    public static void putU16(byte[] b, int off, int v) {
        b[off] = (byte) ((v >>> 8) & 0xFF);
        b[off + 1] = (byte) (v & 0xFF);
    }

    public static void putU32(byte[] b, int off, long v) {
        b[off] = (byte) ((v >>> 24) & 0xFF);
        b[off + 1] = (byte) ((v >>> 16) & 0xFF);
        b[off + 2] = (byte) ((v >>> 8) & 0xFF);
        b[off + 3] = (byte) (v & 0xFF);
    }

    public static int getU16(byte[] b, int off) {
        return ((b[off] & 0xFF) << 8) | (b[off + 1] & 0xFF);
    }

    public static long getU32(byte[] b, int off) {
        return ((long) (b[off] & 0xFF) << 24) | ((long) (b[off + 1] & 0xFF) << 16)
             | ((long) (b[off + 2] & 0xFF) << 8) | (b[off + 3] & 0xFF);
    }

    public static String hex(byte[] b, int off, int len) {
        StringBuilder sb = new StringBuilder(len * 3);
        for (int i = off; i < off + len; i++) {
            if (sb.length() > 0) sb.append(' ');
            sb.append(String.format("%02X", b[i] & 0xFF));
        }
        return sb.toString();
    }

    public static String hex(byte[] b) { return hex(b, 0, b.length); }
}
