package com.com2512.xchg;

import java.net.DatagramPacket;
import java.net.DatagramSocket;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Random;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;

/**
 * The XCHG/1 UDP endpoint: one socket, one receive loop, soft session state.
 *
 * Because UDP has no connections, "who is this" is answered by the source
 * address plus the SESSION field, and liveness is the server's own invention —
 * a session the server has not heard from within its TTL is reaped and its
 * resting orders cancelled. Students see that happen in the UI.
 */
public final class Server {

    public static final int HEARTBEAT_MS = 5000;
    public static final int SESSION_TTL_MS = 15000;
    public static final int RATE_LIMIT_PER_SEC = 200;

    public static final class Session {
        public final int id;
        public volatile String team;
        public final InetAddress addr;
        public final int port;
        public volatile long firstSeenMs = System.currentTimeMillis();
        public volatile long lastSeenMs = System.currentTimeMillis();
        public final AtomicLong rx = new AtomicLong();
        public final AtomicLong tx = new AtomicLong();
        public final AtomicLong rejected = new AtomicLong();
        public final AtomicLong orders = new AtomicLong();
        public final AtomicLong fills = new AtomicLong();
        /** Client seq accounting — how the server sees the student's stream. */
        public volatile int highestSeq = 0;
        public final AtomicLong gaps = new AtomicLong();
        public final AtomicLong dups = new AtomicLong();
        public final AtomicLong outOfOrder = new AtomicLong();
        final Set<Integer> seenSeq = java.util.Collections.synchronizedSet(new HashSet<>());
        /** Server's own outbound seq, so the student can detect loss inbound. */
        final AtomicInteger txSeq = new AtomicInteger(0);
        public final Set<Integer> subscriptions = java.util.Collections.synchronizedSet(new HashSet<>());
        volatile long rateWindowStart = System.currentTimeMillis();
        final AtomicInteger rateCount = new AtomicInteger();

        Session(int id, String team, InetAddress addr, int port) {
            this.id = id; this.team = team; this.addr = addr; this.port = port;
        }
        public String key() { return addr.getHostAddress() + ":" + port; }
        public boolean subscribedTo(int sym) {
            return subscriptions.contains(0) || subscriptions.contains(sym);
        }
    }

    /** One line in the UI's packet log. This is the main debugging aid. */
    public static final class LogEntry {
        public final long timeMs = System.currentTimeMillis();
        public final boolean inbound;
        public final String peer;
        public final String type;
        public final int session, seq, bytes;
        public final String verdict;   // "ok" or why it was rejected
        public final String detail;    // decoded fields, human readable
        public final String hex;
        LogEntry(boolean inbound, String peer, String type, int session, int seq,
                 int bytes, String verdict, String detail, String hex) {
            this.inbound = inbound; this.peer = peer; this.type = type;
            this.session = session; this.seq = seq; this.bytes = bytes;
            this.verdict = verdict; this.detail = detail; this.hex = hex;
        }
    }

    public final Exchange exchange;
    public final Map<String, Session> sessions = new ConcurrentHashMap<>();
    private final ArrayDeque<LogEntry> log = new ArrayDeque<>();
    private final int logCap;

    private final DatagramSocket socket;
    private final AtomicInteger nextSession = new AtomicInteger(1);
    private final Random rng;
    private final double lossProb, dupProb;
    private final int delayMs;
    private final boolean verbose;
    private final ScheduledExecutorService timers = Executors.newScheduledThreadPool(2);

    public final AtomicLong totalRx = new AtomicLong();
    public final AtomicLong totalTx = new AtomicLong();
    public final AtomicLong totalBad = new AtomicLong();
    public final AtomicLong totalDropped = new AtomicLong();
    public final long startedMs = System.currentTimeMillis();
    public final int udpPort;

    public Server(int udpPort, Exchange exchange, long seed, double lossProb,
                  double dupProb, int delayMs, int logCap, boolean verbose) throws Exception {
        this.udpPort = udpPort;
        this.exchange = exchange;
        this.rng = new Random(seed ^ 0x5EEDL);
        this.lossProb = lossProb;
        this.dupProb = dupProb;
        this.delayMs = delayMs;
        this.logCap = logCap;
        this.verbose = verbose;
        this.socket = new DatagramSocket(udpPort);
    }

    public void start(int mmIntervalMs) {
        timers.scheduleAtFixedRate(this::mmTick, mmIntervalMs, mmIntervalMs, TimeUnit.MILLISECONDS);
        timers.scheduleAtFixedRate(this::reapSessions, 2000, 2000, TimeUnit.MILLISECONDS);
        Thread t = new Thread(this::receiveLoop, "xchg-udp");
        t.setDaemon(false);
        t.start();
    }

    // ---- receive loop -----------------------------------------------------

    private void receiveLoop() {
        byte[] buf = new byte[65535];
        while (!socket.isClosed()) {
            DatagramPacket dg = new DatagramPacket(buf, buf.length);
            try {
                socket.receive(dg);
            } catch (Exception e) {
                if (!socket.isClosed()) System.err.println("receive failed: " + e);
                continue;
            }
            totalRx.incrementAndGet();
            String peer = dg.getAddress().getHostAddress() + ":" + dg.getPort();
            int len = dg.getLength();
            String hex = Packet.hex(dg.getData(), dg.getOffset(), Math.min(len, 48));

            // Inbound impairment: pretend the datagram never arrived.
            if (lossProb > 0 && rng.nextDouble() < lossProb) {
                totalDropped.incrementAndGet();
                addLog(new LogEntry(true, peer, "?", 0, 0, len, "dropped (--loss)",
                        "the server discarded this datagram before parsing it", hex));
                continue;
            }

            try {
                Packet p = Packet.decode(dg.getData(), len);
                handle(p, dg.getAddress(), dg.getPort(), peer, len, hex);
            } catch (Packet.BadPacket bad) {
                totalBad.incrementAndGet();
                addLog(new LogEntry(true, peer, "?", 0, 0, len,
                        Packet.errorName(bad.code), bad.getMessage(), hex));
                // Reply anyway, best effort: we cannot trust the session or seq
                // in a packet that did not decode, so both go out as 0.
                send(dg.getAddress(), dg.getPort(), null, Packet.T_ERROR,
                        Packet.errorPayload(bad.code, 0, bad.getMessage()));
            } catch (Exception e) {
                totalBad.incrementAndGet();
                addLog(new LogEntry(true, peer, "?", 0, 0, len, "E_PAYLOAD",
                        "payload shorter than its message type requires", hex));
                send(dg.getAddress(), dg.getPort(), null, Packet.T_ERROR,
                        Packet.errorPayload(Packet.E_PAYLOAD, 0,
                                "payload too short for message type"));
            }
        }
    }

    private void handle(Packet p, InetAddress addr, int port, String peer, int len, String hex)
            throws Exception {
        String key = addr.getHostAddress() + ":" + port;

        if (p.type == Packet.T_HELLO) {
            String team = "anon";
            if (p.payload.length >= 1) {
                int n = p.payload[0] & 0xFF;
                if (n > 0 && 1 + n <= p.payload.length)
                    team = new String(p.payload, 1, n, StandardCharsets.US_ASCII);
            }
            team = team.replaceAll("[^\\x20-\\x7E]", "").trim();
            if (team.isEmpty()) team = "anon";
            if (team.length() > 24) team = team.substring(0, 24);

            Session s = sessions.get(key);
            if (s == null) {
                s = new Session(nextSession.getAndIncrement() & 0xFFFE, team, addr, port);
                if (s.id == 0 || s.id == Exchange.MM_SESSION)
                    s = new Session(nextSession.getAndIncrement() & 0xFFFE, team, addr, port);
                sessions.put(key, s);
            } else {
                s.team = team;              // re-HELLO keeps the session id
            }
            s.lastSeenMs = System.currentTimeMillis();
            s.rx.incrementAndGet();
            s.subscriptions.add(0);         // subscribe to everything by default
            noteSeq(s, p.seq);
            addLog(new LogEntry(true, peer, "HELLO", p.session, p.seq, len, "ok",
                    "team=\"" + team + "\" -> session " + s.id, hex));
            sendWelcome(s);
            publishQuote(s, 0);
            return;
        }

        Session s = sessions.get(key);
        if (s == null) {
            addLog(new LogEntry(true, peer, Packet.typeName(p.type), p.session, p.seq, len,
                    "E_NOHELLO", "no session for " + key + "; send HELLO first", hex));
            send(addr, port, null, Packet.T_ERROR,
                    Packet.errorPayload(Packet.E_NOHELLO, p.seq, "send HELLO first"));
            return;
        }
        if (p.session != s.id) {
            s.rejected.incrementAndGet();
            addLog(new LogEntry(true, peer, Packet.typeName(p.type), p.session, p.seq, len,
                    "E_SESSION", "SESSION " + p.session + " but this address holds session " + s.id, hex));
            send(addr, port, s, Packet.T_ERROR, Packet.errorPayload(Packet.E_SESSION, p.seq,
                    "wrong session, yours is " + s.id));
            return;
        }

        long now = System.currentTimeMillis();
        if (now - s.rateWindowStart >= 1000) { s.rateWindowStart = now; s.rateCount.set(0); }
        if (s.rateCount.incrementAndGet() > RATE_LIMIT_PER_SEC) {
            s.rejected.incrementAndGet();
            addLog(new LogEntry(true, peer, Packet.typeName(p.type), p.session, p.seq, len,
                    "E_RATE", "over " + RATE_LIMIT_PER_SEC + " packets/sec", hex));
            send(addr, port, s, Packet.T_ERROR, Packet.errorPayload(Packet.E_RATE, p.seq,
                    "rate limit " + RATE_LIMIT_PER_SEC + "/s"));
            return;
        }

        s.lastSeenMs = now;
        s.rx.incrementAndGet();
        noteSeq(s, p.seq);

        switch (p.type) {
            case Packet.T_ORDER:    onOrder(s, p, peer, len, hex); break;
            case Packet.T_CANCEL:   onCancel(s, p, peer, len, hex); break;
            case Packet.T_SUBSCRIBE: onSubscribe(s, p, peer, len, hex); break;
            case Packet.T_PING:     onPing(s, p, peer, len, hex); break;
            case Packet.T_BYE:
                addLog(new LogEntry(true, peer, "BYE", p.session, p.seq, len, "ok",
                        "session " + s.id + " closed, resting orders cancelled", hex));
                exchange.cancelAllFor(s.id);
                sessions.remove(s.key());
                break;
            default:
                s.rejected.incrementAndGet();
                addLog(new LogEntry(true, peer, Packet.typeName(p.type), p.session, p.seq, len,
                        "E_TYPE", "server does not accept this type from a client", hex));
                send(s, Packet.T_ERROR, Packet.errorPayload(Packet.E_TYPE, p.seq,
                        "unexpected type " + Packet.typeName(p.type)));
        }
    }

    /** Track gaps, duplicates and reordering in the client's seq stream. */
    private void noteSeq(Session s, int seq) {
        if (!s.seenSeq.add(seq)) { s.dups.incrementAndGet(); return; }
        if (s.seenSeq.size() > 4096) s.seenSeq.clear();
        if (seq > s.highestSeq + 1 && s.highestSeq != 0)
            s.gaps.addAndGet(seq - s.highestSeq - 1);
        if (seq < s.highestSeq) s.outOfOrder.incrementAndGet();
        if (seq > s.highestSeq) s.highestSeq = seq;
    }

    // ---- message handlers -------------------------------------------------

    private void onOrder(Session s, Packet p, String peer, int len, String hex) {
        if (p.payload.length != 11) {
            s.rejected.incrementAndGet();
            addLog(new LogEntry(true, peer, "ORDER", p.session, p.seq, len, "E_PAYLOAD",
                    "ORDER payload is " + p.payload.length + " bytes, spec says 11", hex));
            send(s, Packet.T_ERROR, Packet.errorPayload(Packet.E_PAYLOAD, p.seq,
                    "ORDER payload must be 11 bytes, got " + p.payload.length));
            return;
        }
        long clOrdId = Packet.getU32(p.payload, 0);
        int sym = Packet.getU16(p.payload, 4);
        int side = p.payload[6] & 0xFF;
        int price = Packet.getU16(p.payload, 7);
        int qty = Packet.getU16(p.payload, 9);

        Exchange.Result r = exchange.submit(s.id, clOrdId, sym, side, price, qty);
        s.orders.incrementAndGet();
        if (r.status == Packet.ST_REJECTED) s.rejected.incrementAndGet();
        s.fills.addAndGet(r.filledQty);

        Exchange.Symbol sy = exchange.symbol(sym);
        String detail = String.format("clOrdId=%d %s %s %d @ %d -> %s%s filled=%d resting=%d",
                clOrdId, sy == null ? ("sym" + sym) : sy.ticker,
                side == Packet.SIDE_BUY ? "BUY" : side == Packet.SIDE_SELL ? "SELL" : "side?" + side,
                qty, price, Packet.statusName(r.status),
                r.status == Packet.ST_REJECTED ? " (" + Packet.reasonName(r.reason) + ")" : "",
                r.filledQty, r.restQty);
        addLog(new LogEntry(true, peer, "ORDER", p.session, p.seq, len, "ok", detail, hex));

        send(s, Packet.T_ACK, Packet.ackPayload(clOrdId, r.orderId, r.status, r.reason,
                r.filledQty, r.restQty));
        fanOutTrades(r.trades);
        if (!r.trades.isEmpty() || r.restQty > 0) publishQuoteAll(sym);
    }

    private void onCancel(Session s, Packet p, String peer, int len, String hex) {
        if (p.payload.length != 8) {
            s.rejected.incrementAndGet();
            addLog(new LogEntry(true, peer, "CANCEL", p.session, p.seq, len, "E_PAYLOAD",
                    "CANCEL payload is " + p.payload.length + " bytes, spec says 8", hex));
            send(s, Packet.T_ERROR, Packet.errorPayload(Packet.E_PAYLOAD, p.seq,
                    "CANCEL payload must be 8 bytes, got " + p.payload.length));
            return;
        }
        long clOrdId = Packet.getU32(p.payload, 0);
        long orderId = Packet.getU32(p.payload, 4);
        Exchange.Result r = exchange.cancel(s.id, clOrdId, orderId);
        if (r.status == Packet.ST_REJECTED) s.rejected.incrementAndGet();
        addLog(new LogEntry(true, peer, "CANCEL", p.session, p.seq, len, "ok",
                String.format("orderId=%d -> %s%s", orderId, Packet.statusName(r.status),
                        r.status == Packet.ST_REJECTED ? " (" + Packet.reasonName(r.reason) + ")" : ""),
                hex));
        send(s, Packet.T_ACK, Packet.ackPayload(clOrdId, orderId, r.status, r.reason,
                r.filledQty, r.restQty));
        for (Exchange.Symbol sy : exchange.symbols()) publishQuoteAll(sy.id);
    }

    private void onSubscribe(Session s, Packet p, String peer, int len, String hex) {
        if (p.payload.length != 2) {
            s.rejected.incrementAndGet();
            addLog(new LogEntry(true, peer, "SUBSCRIBE", p.session, p.seq, len, "E_PAYLOAD",
                    "SUBSCRIBE payload is " + p.payload.length + " bytes, spec says 2", hex));
            send(s, Packet.T_ERROR, Packet.errorPayload(Packet.E_PAYLOAD, p.seq,
                    "SUBSCRIBE payload must be 2 bytes, got " + p.payload.length));
            return;
        }
        int sym = Packet.getU16(p.payload, 0);
        if (sym != 0 && !exchange.knownSymbol(sym)) {
            addLog(new LogEntry(true, peer, "SUBSCRIBE", p.session, p.seq, len, "E_PAYLOAD",
                    "unknown symbol id " + sym, hex));
            send(s, Packet.T_ERROR, Packet.errorPayload(Packet.E_PAYLOAD, p.seq,
                    "unknown symbol " + sym));
            return;
        }
        if (sym == 0) { s.subscriptions.clear(); s.subscriptions.add(0); }
        else { s.subscriptions.remove(0); s.subscriptions.add(sym); }
        addLog(new LogEntry(true, peer, "SUBSCRIBE", p.session, p.seq, len, "ok",
                sym == 0 ? "all symbols" : ("symbol " + sym), hex));
        publishQuote(s, sym);
    }

    private void onPing(Session s, Packet p, String peer, int len, String hex) {
        if (p.payload.length != 8) {
            s.rejected.incrementAndGet();
            addLog(new LogEntry(true, peer, "PING", p.session, p.seq, len, "E_PAYLOAD",
                    "PING payload is " + p.payload.length + " bytes, spec says 8", hex));
            send(s, Packet.T_ERROR, Packet.errorPayload(Packet.E_PAYLOAD, p.seq,
                    "PING payload must be 8 bytes, got " + p.payload.length));
            return;
        }
        addLog(new LogEntry(true, peer, "PING", p.session, p.seq, len, "ok",
                "echo=" + Packet.hex(p.payload), hex));
        send(s, Packet.T_PONG, p.payload.clone());
    }

    // ---- outbound ---------------------------------------------------------

    private void sendWelcome(Session s) {
        List<Exchange.Symbol> syms = exchange.symbols();
        byte[] pay = new byte[7 + syms.size() * 6];
        Packet.putU16(pay, 0, s.id);
        Packet.putU16(pay, 2, HEARTBEAT_MS);
        Packet.putU16(pay, 4, SESSION_TTL_MS);
        pay[6] = (byte) syms.size();
        int off = 7;
        for (Exchange.Symbol sy : syms) {
            Packet.putU16(pay, off, sy.id);
            byte[] t = String.format("%-4s", sy.ticker).getBytes(StandardCharsets.US_ASCII);
            System.arraycopy(t, 0, pay, off + 2, 4);
            off += 6;
        }
        send(s, Packet.T_WELCOME, pay);
    }

    private void publishQuote(Session s, int sym) {
        for (Exchange.Symbol sy : exchange.symbols()) {
            if (sym != 0 && sy.id != sym) continue;
            if (!s.subscribedTo(sy.id)) continue;
            send(s, Packet.T_QUOTE, Packet.quotePayload(sy.id,
                    exchange.bestBid(sy.id), exchange.bidQty(sy.id),
                    exchange.bestAsk(sy.id), exchange.askQty(sy.id)));
        }
    }

    private void publishQuoteAll(int sym) {
        byte[] pay = Packet.quotePayload(sym, exchange.bestBid(sym), exchange.bidQty(sym),
                exchange.bestAsk(sym), exchange.askQty(sym));
        for (Session s : sessions.values())
            if (s.subscribedTo(sym)) send(s, Packet.T_QUOTE, pay);
    }

    private void fanOutTrades(List<Exchange.Trade> trades) {
        for (Exchange.Trade t : trades) {
            byte[] pay = Packet.tradePayload(t.symbol, t.price, t.qty, t.aggressorSide, t.id);
            for (Session s : sessions.values())
                if (s.subscribedTo(t.symbol)) send(s, Packet.T_TRADE, pay);
        }
    }

    private void send(Session s, int type, byte[] payload) {
        send(s.addr, s.port, s, type, payload);
    }

    /** Encode, apply outbound impairment, transmit. `s` may be null (pre-session). */
    private void send(InetAddress addr, int port, Session s, int type, byte[] payload) {
        int seq = (s == null) ? 0 : s.txSeq.incrementAndGet() & 0xFFFF;
        int sess = (s == null) ? 0 : s.id;
        byte[] dgram = Packet.encode(type, sess, seq, payload);
        String peer = addr.getHostAddress() + ":" + port;
        String detail = describeOutbound(type, payload);

        if (lossProb > 0 && rng.nextDouble() < lossProb) {
            totalDropped.incrementAndGet();
            addLog(new LogEntry(false, peer, Packet.typeName(type), sess, seq, dgram.length,
                    "dropped (--loss)", detail + " [never left the server]",
                    Packet.hex(dgram, 0, Math.min(dgram.length, 48))));
            return;
        }
        transmit(addr, port, dgram, s, type, sess, seq, detail, peer);
        if (dupProb > 0 && rng.nextDouble() < dupProb) {
            transmit(addr, port, dgram, s, type, sess, seq, detail + " [duplicate]", peer);
        }
    }

    private void transmit(InetAddress addr, int port, byte[] dgram, Session s, int type,
                          int sess, int seq, String detail, String peer) {
        // An outbound ERROR transmitted successfully is still a rejection: log it
        // under the error's own name so the UI does not mark it green "ok" and
        // the inbound/outbound pair reads as one event.
        final String verdict = (type == Packet.T_ERROR && dgram.length > Packet.HEADER_LEN)
                ? Packet.errorName(dgram[Packet.HEADER_LEN] & 0xFF) : "ok";
        Runnable job = () -> {
            try {
                socket.send(new DatagramPacket(dgram, dgram.length, addr, port));
                totalTx.incrementAndGet();
                if (s != null) s.tx.incrementAndGet();
                addLog(new LogEntry(false, peer, Packet.typeName(type), sess, seq, dgram.length,
                        verdict, detail, Packet.hex(dgram, 0, Math.min(dgram.length, 48))));
            } catch (Exception e) {
                addLog(new LogEntry(false, peer, Packet.typeName(type), sess, seq, dgram.length,
                        "send failed", String.valueOf(e), ""));
            }
        };
        if (delayMs > 0) timers.schedule(job, delayMs, TimeUnit.MILLISECONDS);
        else job.run();
    }

    private String describeOutbound(int type, byte[] p) {
        try {
            switch (type) {
                case Packet.T_QUOTE: {
                    Exchange.Symbol sy = exchange.symbol(Packet.getU16(p, 0));
                    return String.format("%s bid %d x%d / ask %d x%d",
                            sy == null ? "?" : sy.ticker, Packet.getU16(p, 2),
                            Packet.getU16(p, 4), Packet.getU16(p, 6), Packet.getU16(p, 8));
                }
                case Packet.T_TRADE: {
                    Exchange.Symbol sy = exchange.symbol(Packet.getU16(p, 0));
                    return String.format("%s %d @ %d aggressor=%s tradeId=%d",
                            sy == null ? "?" : sy.ticker, Packet.getU16(p, 4),
                            Packet.getU16(p, 2), (p[6] & 0xFF) == Packet.SIDE_BUY ? "BUY" : "SELL",
                            Packet.getU32(p, 7));
                }
                case Packet.T_ACK:
                    return String.format("clOrdId=%d orderId=%d %s%s filled=%d resting=%d",
                            Packet.getU32(p, 0), Packet.getU32(p, 4),
                            Packet.statusName(p[8] & 0xFF),
                            (p[8] & 0xFF) == Packet.ST_REJECTED
                                    ? " (" + Packet.reasonName(p[9] & 0xFF) + ")" : "",
                            Packet.getU16(p, 10), Packet.getU16(p, 12));
                case Packet.T_WELCOME:
                    return String.format("session=%d heartbeat=%dms ttl=%dms symbols=%d",
                            Packet.getU16(p, 0), Packet.getU16(p, 2), Packet.getU16(p, 4),
                            p[6] & 0xFF);
                case Packet.T_ERROR: {
                    int n = p[3] & 0xFF;
                    return Packet.errorName(p[0] & 0xFF) + ": "
                            + new String(p, 4, Math.min(n, p.length - 4), StandardCharsets.US_ASCII);
                }
                case Packet.T_PONG:
                    return "echo=" + Packet.hex(p);
                default:
                    return Packet.hex(p);
            }
        } catch (Exception e) {
            return Packet.hex(p);
        }
    }

    // ---- timers -----------------------------------------------------------

    private void mmTick() {
        try {
            List<Exchange.Trade> trades = exchange.marketMakerTick();
            fanOutTrades(trades);
            for (Exchange.Symbol sy : exchange.symbols()) publishQuoteAll(sy.id);
        } catch (Exception e) {
            System.err.println("market maker tick failed: " + e);
        }
    }

    private void reapSessions() {
        long now = System.currentTimeMillis();
        for (Session s : new ArrayList<>(sessions.values())) {
            if (now - s.lastSeenMs > SESSION_TTL_MS) {
                exchange.cancelAllFor(s.id);
                sessions.remove(s.key());
                addLog(new LogEntry(false, s.key(), "-", s.id, 0, 0, "session expired",
                        "silent for more than " + SESSION_TTL_MS
                        + "ms; resting orders cancelled. Send PING to keep a session alive.", ""));
                if (verbose) System.out.println("session " + s.id + " (" + s.team + ") expired");
            }
        }
    }

    // ---- log --------------------------------------------------------------

    private void addLog(LogEntry e) {
        synchronized (log) {
            log.addLast(e);
            while (log.size() > logCap) log.pollFirst();
        }
        if (verbose) {
            System.out.printf("%s %-5s %-9s sess=%-5d seq=%-5d %3dB  %-16s %s%n",
                    e.inbound ? "<<" : ">>", e.inbound ? "in" : "out", e.type,
                    e.session, e.seq, e.bytes, e.verdict, e.detail);
        }
    }

    public List<LogEntry> recentLog(int max) {
        synchronized (log) {
            List<LogEntry> out = new ArrayList<>(log);
            java.util.Collections.reverse(out);
            return out.size() > max ? new ArrayList<>(out.subList(0, max)) : out;
        }
    }

    public List<Session> sessionList() {
        List<Session> out = new ArrayList<>(sessions.values());
        out.sort((a, b) -> Integer.compare(a.id, b.id));
        return out;
    }

    public void close() {
        timers.shutdownNow();
        socket.close();
    }
}
