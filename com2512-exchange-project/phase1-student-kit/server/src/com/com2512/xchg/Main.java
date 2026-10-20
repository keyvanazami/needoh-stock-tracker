package com.com2512.xchg;

import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

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
        boolean mm = true, verbose = false, noWeb = false;

        // Everything between the socket and the order book lives in Link.
        Link.Config link = new Link.Config();
        List<String> impairArgs = new ArrayList<>();

        final int[] iv = new int[1];
        for (int i = 0; i < args.length; i++) {
            String a = args[i];
            iv[0] = i + 1;          // index of this flag's value, for the lambdas
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
                    case "--link": {
                        String name = args[++i];
                        if ("list".equals(name)) { linkList(); return; }
                        if (!Link.applyPreset(link, name)) {
                            System.err.println("unknown link profile: " + name);
                            linkList();
                            System.exit(2);
                        }
                        link.profile = name;
                        break;
                    }
                    // Global per-packet effects, both directions, every type.
                    case "--loss": both(link).forEach(e -> e.loss = pd(args[iv[0]])); i++; break;
                    case "--dup": both(link).forEach(e -> e.dup = pd(args[iv[0]])); i++; break;
                    case "--corrupt": both(link).forEach(e -> e.corrupt = pd(args[iv[0]])); i++; break;
                    case "--reorder": both(link).forEach(e -> e.reorder = pd(args[iv[0]])); i++; break;
                    case "--delay": case "--latency":
                        both(link).forEach(e -> e.latencyMs = pi(args[iv[0]])); i++; break;
                    case "--jitter": both(link).forEach(e -> e.jitterMs = pi(args[iv[0]])); i++; break;
                    case "--corrupt-bits":
                        both(link).forEach(e -> e.corruptBits = pi(args[iv[0]])); i++; break;
                    // Congestion.
                    case "--bandwidth": link.bandwidthBps = parseBps(args[++i]); break;
                    case "--busy": link.busyLoad = Double.parseDouble(args[++i]); break;
                    case "--queue": link.queueCapacity = Integer.parseInt(args[++i]); break;
                    case "--max-wait": link.queueMaxDelayMs = Integer.parseInt(args[++i]); break;
                    // Scoped rules, e.g. --impair out:ACK:corrupt=0.5
                    case "--impair": impairArgs.add(args[++i]); break;
                    case "--seed": link.seed = Long.parseLong(args[++i]); break;
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

        for (String rule : impairArgs) {
            String err = applyImpairRule(link, rule);
            if (err != null) {
                System.err.println("--impair " + rule + ": " + err);
                System.err.println("  form: [in|out][:TYPE]:effect=value"
                        + "   e.g. out:ACK:corrupt=0.5   in:loss=0.2");
                System.exit(2);
            }
        }
        // Bare flags without --link still make the link dirty; do not call it "clean".
        if (link.profile.equals("clean") && !link.isClean()) link.profile = "custom";

        if (link.busyLoad < 0 || link.busyLoad >= 1) {
            System.err.println("--busy must be between 0 and 0.95");
            System.exit(2);
        }

        StringBuilder crc = new StringBuilder();
        if (!Crc16.selfTest(crc)) {
            System.err.println("CRC self-test FAILED - refusing to start:");
            System.err.print(crc);
            System.exit(1);
        }

        Exchange exchange = new Exchange(link.seed, mm, mmSpread, mmSize);
        Server server = new Server(udpPort, exchange, new Link(link), logCap, verbose);

        System.out.println(VERSION);
        System.out.println("  exchange   UDP  0.0.0.0:" + udpPort);
        if (!noWeb) {
            WebUi web = new WebUi(webPort, server);
            web.start();
            System.out.println("  UI         http://localhost:" + webPort + "/");
        }
        System.out.printf("  symbols    %s%n", tickerList(exchange));
        System.out.printf("  link       %s%n", link.profile);
        System.out.printf("             %s  (seed %d)%n", link.describe(), link.seed);
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


    // ---- link flag helpers -------------------------------------------------

    /** The two global Effects, so a plain flag hits both directions. */
    private static List<Link.Effects> both(Link.Config c) {
        return List.of(c.global.get(Link.Dir.IN), c.global.get(Link.Dir.OUT));
    }

    private static double pd(String v) {
        double d = Double.parseDouble(v);
        if (d < 0 || d > 1) throw new NumberFormatException("expected a probability 0..1, got " + v);
        return d;
    }

    private static int pi(String v) { return Integer.parseInt(v); }

    /** Accepts 64000, 64k, 1M, 256kbps. */
    static long parseBps(String v) {
        String t = v.trim().toLowerCase(java.util.Locale.ROOT).replace("bps", "").replace("b", "");
        long mult = 1;
        if (t.endsWith("k")) { mult = 1_000; t = t.substring(0, t.length() - 1); }
        else if (t.endsWith("m")) { mult = 1_000_000; t = t.substring(0, t.length() - 1); }
        return (long) (Double.parseDouble(t) * mult);
    }

    /**
     * Parse one scoped rule: [in|out][:TYPE]:effect=value
     *
     *   out:ACK:corrupt=0.5     corrupt half the ACKs leaving the server
     *   in:loss=0.2             drop a fifth of what arrives
     *   out:QUOTE:drop=1.0      cut market data off entirely
     *   ORDER:latency=500       both directions, ORDER only
     *
     * Returns null on success, or a message describing what was wrong.
     */
    static String applyImpairRule(Link.Config c, String rule) {
        int eq = rule.lastIndexOf('=');
        if (eq < 0) return "no '=' in the rule";
        String lhs = rule.substring(0, eq);
        String value = rule.substring(eq + 1).trim();

        String[] parts = lhs.split(":");
        if (parts.length == 0) return "nothing before the '='";
        String effect = parts[parts.length - 1].trim().toLowerCase(java.util.Locale.ROOT);

        List<Link.Dir> dirs = List.of(Link.Dir.IN, Link.Dir.OUT);
        Integer type = null;
        for (int i = 0; i < parts.length - 1; i++) {
            String tok = parts[i].trim();
            if (tok.isEmpty()) continue;
            if (tok.equalsIgnoreCase("in")) dirs = List.of(Link.Dir.IN);
            else if (tok.equalsIgnoreCase("out")) dirs = List.of(Link.Dir.OUT);
            else {
                type = typeByName(tok);
                if (type == null) return "unknown message type '" + tok + "'";
            }
        }

        for (Link.Dir d : dirs) {
            if (type == null) {
                Link.Effects e = c.global.get(d);
                String err = setEffect(e, effect, value);
                if (err != null) return err;
            } else {
                Link.Override o = c.scoped(d, type);
                String err = setOverride(o, effect, value);
                if (err != null) return err;
            }
        }
        if (c.profile.equals("clean")) c.profile = "custom";
        return null;
    }

    private static Integer typeByName(String name) {
        for (int t = 0; t <= 0xFF; t++) {
            String n = Packet.typeName(t);
            if (n.equalsIgnoreCase(name)) return t;
        }
        try {
            String h = name.toLowerCase(java.util.Locale.ROOT);
            return Integer.parseInt(h.startsWith("0x") ? h.substring(2) : h, 16);
        } catch (NumberFormatException e) {
            return null;
        }
    }

    private static String setEffect(Link.Effects e, String effect, String v) {
        try {
            switch (effect) {
                case "loss": case "drop": e.loss = pd(v); return null;
                case "corrupt": e.corrupt = pd(v); return null;
                case "dup": case "duplicate": e.dup = pd(v); return null;
                case "reorder": e.reorder = pd(v); return null;
                case "latency": case "delay": e.latencyMs = pi(v); return null;
                case "jitter": e.jitterMs = pi(v); return null;
                case "bits": case "corrupt-bits": e.corruptBits = pi(v); return null;
                case "reorder-ms": e.reorderMs = pi(v); return null;
                default: return "unknown effect '" + effect + "'";
            }
        } catch (NumberFormatException ex) {
            return "bad value '" + v + "': " + ex.getMessage();
        }
    }

    private static String setOverride(Link.Override o, String effect, String v) {
        try {
            switch (effect) {
                case "loss": case "drop": o.loss = pd(v); return null;
                case "corrupt": o.corrupt = pd(v); return null;
                case "dup": case "duplicate": o.dup = pd(v); return null;
                case "reorder": o.reorder = pd(v); return null;
                case "latency": case "delay": o.latencyMs = pi(v); return null;
                case "jitter": o.jitterMs = pi(v); return null;
                case "bits": case "corrupt-bits": o.corruptBits = pi(v); return null;
                case "reorder-ms": o.reorderMs = pi(v); return null;
                default: return "unknown effect '" + effect + "'";
            }
        } catch (NumberFormatException ex) {
            return "bad value '" + v + "': " + ex.getMessage();
        }
    }

    private static void linkList() {
        System.out.println("link profiles (--link NAME):");
        for (Map.Entry<String, String> e : Link.presetHelp().entrySet())
            System.out.printf("  %-11s %s%n", e.getKey(), e.getValue());
        System.out.println();
        System.out.println("Any profile can be adjusted with the flags below it, and with");
        System.out.println("scoped rules:  --impair [in|out][:TYPE]:effect=value");
        System.out.println("  --impair out:ACK:corrupt=0.5     corrupt half the ACKs");
        System.out.println("  --impair in:loss=0.2             drop a fifth of what arrives");
        System.out.println("  --impair out:QUOTE:drop=1.0      cut market data off entirely");
        System.out.println("effects: loss drop corrupt dup reorder latency jitter bits reorder-ms");
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

            network conditions (clean by default) -- see Link.java
              --link NAME           a named profile; --link list prints them all
              --impair RULE         scoped rule, repeatable:
                                    [in|out][:TYPE]:effect=value
                                    e.g. out:ACK:corrupt=0.5, in:loss=0.2

              per-packet effects (both directions, every message type)
              --loss P              drop a datagram with probability P
              --corrupt P           flip a bit in it with probability P
              --dup P               deliver it twice with probability P
              --reorder P           hold it back so later packets overtake it
              --latency MS          fixed one-way delay (--delay is an alias)
              --jitter MS           random extra delay, 0..MS
              --corrupt-bits N      bits to flip when corrupting (default 1)

              congestion (a queue, not a probability: delay rises with load)
              --bandwidth BPS       link rate, e.g. 64k, 256kbps, 1M
              --busy F              fraction of the link used by other traffic, 0..0.95
              --queue N             datagrams in flight before tail-dropping
              --max-wait MS         drop rather than queue longer than this

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
