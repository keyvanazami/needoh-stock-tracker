package com.com2512.xchg;

/**
 * CRC-16/CCITT-FALSE: poly 0x1021, init 0xFFFF, no reflection, no final xor.
 *
 * The same CRC the hardware phase uses (see hardware-reference/lib/bframe.h),
 * so a student's Phase 1 implementation carries straight over to the AVR work.
 * Canonical check value: crc16("123456789") == 0x29B1.
 */
public final class Crc16 {
    private Crc16() {}

    public static int compute(byte[] data, int off, int len) {
        int crc = 0xFFFF;
        for (int i = off; i < off + len; i++) {
            crc ^= (data[i] & 0xFF) << 8;
            for (int bit = 0; bit < 8; bit++) {
                crc = ((crc & 0x8000) != 0) ? ((crc << 1) ^ 0x1021) : (crc << 1);
                crc &= 0xFFFF;
            }
        }
        return crc;
    }

    public static int compute(byte[] data) {
        return compute(data, 0, data.length);
    }

    /** Check values from hardware-reference/vectors/acceptance.txt. */
    public static boolean selfTest(StringBuilder out) {
        Object[][] cases = {
            {"123456789", 0x29B1}, {"", 0xFFFF}, {"A", 0xB915}, {"AAPL", 0x3182},
        };
        boolean ok = true;
        for (Object[] c : cases) {
            String s = (String) c[0];
            int want = (Integer) c[1];
            int got = compute(s.getBytes(java.nio.charset.StandardCharsets.US_ASCII));
            boolean pass = got == want;
            ok &= pass;
            out.append(String.format("  crc16(%-11s) = 0x%04X  want 0x%04X  %s%n",
                    "\"" + s + "\"", got, want, pass ? "ok" : "MISMATCH"));
        }
        return ok;
    }
}
