package com.com2512.xchg;

import java.nio.charset.StandardCharsets;

/**
 * COM2512 Phase 1 exchange test server.
 *
 * Modes:
 *   (default)         run the UDP exchange + the web UI
 *   --selftest        verify the CRC against the course check values
 *   --vectors         print the acceptance vectors students must reproduce
 *   --decode HEX      decode one packet of hex bytes and explain it
 */
public final class Main {

    private static final String VERSION = "xchg-server 1.0 (XCHG/1)";

    public static void main(String[] args) throws Exception {
        int udpPort = 9001, webPort = 9000, mmInterval = 1000, logCap = 400;
        int mmSpread = 4, mmSize = 10;
        long seed = 2512;
        double loss = 0.0, dup = 0.0;
        int delayMs = 0;
        boolean mm = true, verbose = false, noWeb = false;

        for (int i = 0; i < args.length; i++) {
            String a = args[i];
            try {
                switch (a) {
                    case "--help": case "-h": usage(); return;
                    case "--version": System.out.println(VERSION); return;
                    case "--selftest": System.exit(selfTest() ? 0 : 1); return;
                    case "--vectors": vectors(); return;
                    case "--decode": decode(args[++i]); return;
                    case "--udp-port": udpPort = Integer.parseInt(args[++i]); break;
                    case "--web-port": webPort = Integer.parseInt(args[++i]); break;
                    case "--no-web": noWeb = true; break;
                    case "--loss": loss = Double.parseDouble(args[++i]); break;
                    case "--dup": dup = Double.parseDouble(args[++i]); break;
                    case "--delay": delayMs = Integer.parseInt(args[++i]); break;
                    case "--seed": seed = Long.parseLong(args[++i]); break;
                    case "--no-mm": mm = false; break;
                    case "--mm-interval": mmInterval = Integer.parseInt(args[++i]); break;
                    case "--mm-spread": mmSpread = Integer.parseInt(args[++i]); break;
                    case "--mm-size": mmSize = Integer.parseInt(args[++i]); break;
                    case "--log-size": logCap = Integer.parseInt(args[++i]); break;
                    case "--verbose": case "-v": verbose = true; break;
                    default:
                        System.err.println("unknown option: " + a);
                        usage();
                        System.exit(2);
                }
            } catch (ArrayIndexOutOfBoundsException e) {
                System.err.println(a + " needs a value");
                System.exit(2);
            } catch (NumberFormatException e) {
                System.err.println(a + ": not a number: " + args[i]);
                System.exit(2);
            }
        }

        if (loss < 0 || loss > 1 || dup < 0 || dup > 1) {
            System.err.println("--loss and --dup are probabilities between 0 and 1");
            System.exit(2);
        }

        StringBuilder crc = new StringBuilder();
        if (!Crc16.selfTest(crc)) {
            System.err.println("CRC self-test FAILED - refusing to start:");
            System.err.print(crc);
            System.exit(1);
        }

        Exchange exchange = new Exchange(seed, mm, mmSpread, mmSize);
        Server server = new Server(udpPort, exchange, seed, loss, dup, delayMs, logCap, verbose);

        System.out.println(VERSION);
        System.out.println("  exchange   UDP  0.0.0.0:" + udpPort);
        if (!noWeb) {
            WebUi web = new WebUi(webPort, server);
            web.start();
            System.out.println("  UI         http://localhost:" + webPort + "/");
        }
        System.out.printf("  symbols    %s%n", tickerList(exchange));
        System.out.printf("  impairment loss=%.0f%% dup=%.0f%% delay=%dms  (seed %d)%n",
                loss * 100, dup * 100, delayMs, seed);
        System.out.printf("  market maker %s, every %dms%n", mm ? "on" : "off", mmInterval);
        System.out.println("  heartbeat  send PING every " + Server.HEARTBEAT_MS
                + "ms or the session expires after " + Server.SESSION_TTL_MS + "ms");
        System.out.println();
        System.out.println("Send HELLO to begin. Run with --vectors for the test vectors.");

        server.start(mmInterval);
        Runtime.getRuntime().addShutdownHook(new Thread(server::close));
    }

    private static String tickerList(Exchange ex) {
        StringBuilder b = new StringBuilder();
        for (Exchange.Symbol s : ex.symbols()) {
            if (b.length() > 0) b.append("  ");
            b.append(s.id).append('=').append(s.ticker);
        }
        return b.toString();
    }

    private static boolean selfTest() {
        StringBuilder out = new StringBuilder();
        boolean ok = Crc16.selfTest(out);
        System.out.println("CRC-16/CCITT-FALSE against hardware-reference/vectors/acceptance.txt:");
        System.out.print(out);
        System.out.println(ok ? "PASS" : "FAIL");
        return ok;
    }

    /**
     * Prints the acceptance vectors. They are generated by the same encoder the
     * server runs, so the spec and the implementation cannot drift apart.
     */
    private static void vectors() {
        System.out.println("# XCHG/1 acceptance vectors - your client MUST reproduce these exactly.");
        System.out.println("# Generated by the server's own encoder (" + VERSION + ").");
        System.out.println("# Header: MAGIC(2)=0x5843 VER(1)=1 TYPE(1) SESSION(2) SEQ(2) PAYLEN(2)");
        System.out.println("# then PAYLOAD, then CRC16(2) = CRC-16/CCITT-FALSE over header+payload.");
        System.out.println();

        System.out.println("## CRC-16/CCITT-FALSE check values (same CRC as the hardware phase)");
        StringBuilder crc = new StringBuilder();
        Crc16.selfTest(crc);
        System.out.print(crc);
        System.out.println();

        System.out.println("## Client -> server");
        byte[] team = "ada".getBytes(StandardCharsets.US_ASCII);
        byte[] hello = new byte[1 + team.length];
        hello[0] = (byte) team.length;
        System.arraycopy(team, 0, hello, 1, team.length);
        vec("HELLO  team=\"ada\", session 0, seq 1", Packet.T_HELLO, 0, 1, hello);

        byte[] sub = new byte[2];
        Packet.putU16(sub, 0, 1);
        vec("SUBSCRIBE  symbol 1 (AAPL), session 7, seq 2", Packet.T_SUBSCRIBE, 7, 2, sub);

        byte[] order = new byte[11];
        Packet.putU32(order, 0, 1001);          // clOrdId
        Packet.putU16(order, 4, 1);             // symbol AAPL
        order[6] = (byte) Packet.SIDE_BUY;      // 'B'
        Packet.putU16(order, 7, 300);           // price 300 cents
        Packet.putU16(order, 9, 50);            // qty 50
        vec("ORDER  clOrdId=1001 AAPL BUY 50 @ 300, session 7, seq 3", Packet.T_ORDER, 7, 3, order);

        byte[] cancel = new byte[8];
        Packet.putU32(cancel, 0, 1002);
        Packet.putU32(cancel, 4, 42);
        vec("CANCEL  clOrdId=1002 orderId=42, session 7, seq 4", Packet.T_CANCEL, 7, 4, cancel);

        byte[] ping = new byte[]{0, 0, 0, 0, 0, 0, 0x12, 0x34};
        vec("PING  echo=00..1234, session 7, seq 5", Packet.T_PING, 7, 5, ping);

        vec("BYE  no payload, session 7, seq 6", Packet.T_BYE, 7, 6, new byte[0]);

        System.out.println();
        System.out.println("## Server -> client (decode these; you never send them)");
        vec("QUOTE  AAPL bid 299 x100 / ask 301 x100, session 7, seq 11",
                Packet.T_QUOTE, 7, 11, Packet.quotePayload(1, 299, 100, 301, 100));
        vec("TRADE  AAPL 50 @ 300 aggressor BUY tradeId=9, session 7, seq 12",
                Packet.T_TRADE, 7, 12, Packet.tradePayload(1, 300, 50, Packet.SIDE_BUY, 9));
        vec("ACK  clOrdId=1001 orderId=42 FILLED filled=50 resting=0, session 7, seq 13",
                Packet.T_ACK, 7, 13,
                Packet.ackPayload(1001, 42, Packet.ST_FILLED, Packet.R_NONE, 50, 0));
        vec("ACK  clOrdId=1003 REJECTED (unknown symbol), session 7, seq 14",
                Packet.T_ACK, 7, 14,
                Packet.ackPayload(1003, 0, Packet.ST_REJECTED, Packet.R_UNKNOWN_SYMBOL, 0, 0));

        System.out.println();
        System.out.println("## Deliberately malformed - the server must reject these.");
        System.out.println("## Checks run in this order: MAGIC, VER, PAYLEN vs datagram size, CRC.");
        System.out.println("## Order matters: the magic and length vectors below also carry a stale");
        System.out.println("## CRC, but a conforming implementation reports the EARLIER failure.");
        byte[] bad = Packet.encode(Packet.T_PING, 7, 9, ping);
        bad[bad.length - 1] ^= 0x01;
        System.out.printf("  %-74s %s%n", "PING with one CRC bit flipped -> E_CRC", Packet.hex(bad));
        byte[] badMagic = Packet.encode(Packet.T_PING, 7, 9, ping);
        badMagic[0] = 0x58; badMagic[1] = 0x44;
        System.out.printf("  %-74s %s%n", "magic 0x5844 instead of 0x5843 -> E_MAGIC", Packet.hex(badMagic));
        byte[] badLen = Packet.encode(Packet.T_PING, 7, 9, ping);
        Packet.putU16(badLen, 8, 99);
        System.out.printf("  %-74s %s%n", "PAYLEN says 99 but 8 bytes follow -> E_LENGTH", Packet.hex(badLen));
        System.out.println();
        System.out.println("Check any of these with:  java -jar xchg-server.jar --decode \"<hex>\"");
    }

    private static void vec(String label, int type, int session, int seq, byte[] payload) {
        byte[] dgram = Packet.encode(type, session, seq, payload);
        System.out.printf("  %-74s %s%n", label, Packet.hex(dgram));
    }

    /** Decode a hex datagram and explain it, field by field. */
    private static void decode(String hexIn) {
        String clean = hexIn.replaceAll("[^0-9A-Fa-f]", "");
        if (clean.length() % 2 != 0) {
            System.err.println("hex has an odd number of digits");
            System.exit(2);
        }
        byte[] buf = new byte[clean.length() / 2];
        for (int i = 0; i < buf.length; i++)
            buf[i] = (byte) Integer.parseInt(clean.substring(i * 2, i * 2 + 2), 16);

        System.out.println("input  " + Packet.hex(buf) + "   (" + buf.length + " bytes)");
        if (buf.length >= Packet.HEADER_LEN) {
            System.out.printf("  MAGIC   0x%04X%s%n", Packet.getU16(buf, 0),
                    Packet.getU16(buf, 0) == Packet.MAGIC ? "" : "   <-- expected 0x5843");
            System.out.printf("  VER     %d%n", buf[2] & 0xFF);
            System.out.printf("  TYPE    0x%02X  %s%n", buf[3] & 0xFF, Packet.typeName(buf[3] & 0xFF));
            System.out.printf("  SESSION %d%n", Packet.getU16(buf, 4));
            System.out.printf("  SEQ     %d%n", Packet.getU16(buf, 6));
            System.out.printf("  PAYLEN  %d  (so the datagram should be %d bytes; it is %d)%n",
                    Packet.getU16(buf, 8), Packet.OVERHEAD + Packet.getU16(buf, 8), buf.length);
        }
        try {
            Packet p = Packet.decode(buf, buf.length);
            System.out.println("  CRC     ok");
            System.out.println("  PAYLOAD " + (p.payload.length == 0 ? "(empty)" : Packet.hex(p.payload)));
            System.out.println();
            System.out.println("ACCEPTED: " + explain(p));
        } catch (Packet.BadPacket bad) {
            System.out.println();
            System.out.println("REJECTED: " + Packet.errorName(bad.code) + " - " + bad.getMessage());
            if (bad.code == Packet.E_CRC && buf.length >= Packet.OVERHEAD) {
                int paylen = Packet.getU16(buf, 8);
                if (Packet.OVERHEAD + paylen == buf.length) {
                    System.out.printf("          the CRC for these bytes is 0x%04X%n",
                            Crc16.compute(buf, 0, Packet.HEADER_LEN + paylen));
                }
            }
        } catch (Exception e) {
            System.out.println();
            System.out.println("REJECTED: payload too short for its message type");
        }
    }

    private static String explain(Packet p) {
        try {
            switch (p.type) {
                case Packet.T_HELLO: {
                    int n = p.payload.length > 0 ? p.payload[0] & 0xFF : 0;
                    return "HELLO team=\"" + new String(p.payload, 1, n, StandardCharsets.US_ASCII) + "\"";
                }
                case Packet.T_SUBSCRIBE: {
                    int s = Packet.getU16(p.payload, 0);
                    return "SUBSCRIBE " + (s == 0 ? "all symbols" : "symbol " + s);
                }
                case Packet.T_ORDER:
                    return String.format("ORDER clOrdId=%d symbol=%d side=%s qty=%d price=%d",
                            Packet.getU32(p.payload, 0), Packet.getU16(p.payload, 4),
                            (p.payload[6] & 0xFF) == Packet.SIDE_BUY ? "BUY"
                                    : (p.payload[6] & 0xFF) == Packet.SIDE_SELL ? "SELL"
                                    : String.format("invalid 0x%02X", p.payload[6] & 0xFF),
                            Packet.getU16(p.payload, 9), Packet.getU16(p.payload, 7));
                case Packet.T_CANCEL:
                    return String.format("CANCEL clOrdId=%d orderId=%d",
                            Packet.getU32(p.payload, 0), Packet.getU32(p.payload, 4));
                case Packet.T_PING:
                    return "PING echo=" + Packet.hex(p.payload);
                case Packet.T_PONG:
                    return "PONG echo=" + Packet.hex(p.payload);
                case Packet.T_BYE:
                    return "BYE";
                case Packet.T_QUOTE:
                    return String.format("QUOTE symbol=%d bid=%d x%d ask=%d x%d",
                            Packet.getU16(p.payload, 0), Packet.getU16(p.payload, 2),
                            Packet.getU16(p.payload, 4), Packet.getU16(p.payload, 6),
                            Packet.getU16(p.payload, 8));
                case Packet.T_TRADE:
                    return String.format("TRADE symbol=%d price=%d qty=%d aggressor=%s tradeId=%d",
                            Packet.getU16(p.payload, 0), Packet.getU16(p.payload, 2),
                            Packet.getU16(p.payload, 4),
                            (p.payload[6] & 0xFF) == Packet.SIDE_BUY ? "BUY" : "SELL",
                            Packet.getU32(p.payload, 7));
                case Packet.T_ACK:
                    return String.format("ACK clOrdId=%d orderId=%d %s reason=%s filled=%d resting=%d",
                            Packet.getU32(p.payload, 0), Packet.getU32(p.payload, 4),
                            Packet.statusName(p.payload[8] & 0xFF),
                            Packet.reasonName(p.payload[9] & 0xFF),
                            Packet.getU16(p.payload, 10), Packet.getU16(p.payload, 12));
                case Packet.T_WELCOME:
                    return String.format("WELCOME session=%d heartbeat=%dms ttl=%dms symbols=%d",
                            Packet.getU16(p.payload, 0), Packet.getU16(p.payload, 2),
                            Packet.getU16(p.payload, 4), p.payload[6] & 0xFF);
                case Packet.T_ERROR: {
                    int n = p.payload[3] & 0xFF;
                    return "ERROR " + Packet.errorName(p.payload[0] & 0xFF) + " echoSeq="
                            + Packet.getU16(p.payload, 1) + " \""
                            + new String(p.payload, 4, n, StandardCharsets.US_ASCII) + "\"";
                }
                default:
                    return Packet.typeName(p.type) + " payload=" + Packet.hex(p.payload);
            }
        } catch (Exception e) {
            return Packet.typeName(p.type) + " - payload is too short for this type";
        }
    }

    private static void usage() {
        System.out.println(VERSION);
        System.out.println("""

            usage: java -jar xchg-server.jar [options]

            modes
              --selftest            check the CRC against the course vectors, exit
              --vectors             print the XCHG/1 acceptance vectors, exit
              --decode HEX          decode one packet and explain it, exit
              --version, --help

            ports
              --udp-port N          exchange port (default 9001)
              --web-port N          UI port (default 9000)
              --no-web              run without the UI

            link impairment (all off by default)
              --loss P              drop each datagram with probability P, both directions
              --dup P               send each reply twice with probability P
              --delay MS            hold every reply MS before sending
              --seed N              RNG seed, so a run is reproducible (default 2512)

            market
              --no-mm               no built-in market maker (book starts empty)
              --mm-interval MS      re-quote period (default 1000)
              --mm-spread N         market maker spread in cents (default 4)
              --mm-size N           size per level (default 10)

            misc
              --log-size N          packet log depth shown in the UI (default 400)
              --verbose, -v         also print every packet to stdout
            """);
    }
}
