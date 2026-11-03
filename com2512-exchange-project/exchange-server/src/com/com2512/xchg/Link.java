package com.com2512.xchg;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Random;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;

/**
 * The emulated network link: everything between the UDP socket and the exchange.
 *
 *   DatagramSocket  <->  Link  <->  Server dispatch  <->  Exchange (order book)
 *
 * Every datagram in both directions passes through here, and nothing downstream
 * knows the link is anything other than perfect. That separation is the point:
 * the order book has no idea it is being tested over a bad connection.
 *
 * Two kinds of impairment, deliberately modelled differently:
 *
 *   Per-packet events -- loss, corruption, duplication, reordering. Independent
 *   coin flips, scoped by direction and by message type, so "corrupt the ACKs
 *   only" is expressible.
 *
 *   Congestion -- bandwidth, cross traffic and a finite queue. These are NOT a
 *   probability. Each datagram occupies the link for its serialisation time, a
 *   queue forms behind it, and delay RISES with load until the queue overflows
 *   and packets are tail-dropped. "Slow" and "busy" are the same machinery at
 *   different settings, and congestive loss appears on its own, which is what
 *   makes it worth simulating rather than faking with --loss.
 */
public final class Link {

    public enum Dir {
        IN("in"), OUT("out");
        public final String label;
        Dir(String l) { this.label = l; }
    }

    /** Resolved per-packet settings for one (direction, message type). */
    public static final class Effects {
        public double loss, corrupt, dup, reorder;
        public int latencyMs, jitterMs, corruptBits = 1, reorderMs = 150;

        Effects copy() {
            Effects e = new Effects();
            e.loss = loss; e.corrupt = corrupt; e.dup = dup; e.reorder = reorder;
            e.latencyMs = latencyMs; e.jitterMs = jitterMs;
            e.corruptBits = corruptBits; e.reorderMs = reorderMs;
            return e;
        }
    }

    /** A scoped override: only the fields that were explicitly set apply. */
    public static final class Override {
        public Double loss, corrupt, dup, reorder;
        public Integer latencyMs, jitterMs, corruptBits, reorderMs;

        void applyTo(Effects e) {
            if (loss != null) e.loss = loss;
            if (corrupt != null) e.corrupt = corrupt;
            if (dup != null) e.dup = dup;
            if (reorder != null) e.reorder = reorder;
            if (latencyMs != null) e.latencyMs = latencyMs;
            if (jitterMs != null) e.jitterMs = jitterMs;
            if (corruptBits != null) e.corruptBits = corruptBits;
            if (reorderMs != null) e.reorderMs = reorderMs;
        }

        boolean isEmpty() {
            return loss == null && corrupt == null && dup == null && reorder == null
                && latencyMs == null && jitterMs == null && corruptBits == null
                && reorderMs == null;
        }
    }

    /** Everything the link needs. Built by Main from flags and presets. */
    public static final class Config {
        public String profile = "clean";
        public long seed = 2512;

        /** bits/second, 0 = unlimited. Sets serialisation delay per byte. */
        public long bandwidthBps = 0;
        /** 0..0.95 -- fraction of the link already used by other traffic. */
        public double busyLoad = 0;
        /** datagrams that may be in the link at once, 0 = unbounded. */
        public int queueCapacity = 0;
        /** drop rather than queue a packet that would wait longer than this. */
        public int queueMaxDelayMs = 0;

        public final Map<Dir, Effects> global = new LinkedHashMap<>();
        public final Map<Dir, Map<Integer, Override>> byType = new LinkedHashMap<>();

        public Config() {
            for (Dir d : Dir.values()) {
                global.put(d, new Effects());
                byType.put(d, new LinkedHashMap<>());
            }
        }

        public Override scoped(Dir d, int type) {
            return byType.get(d).computeIfAbsent(type, k -> new Override());
        }

        public boolean isClean() {
            if (bandwidthBps > 0 || busyLoad > 0 || queueCapacity > 0) return false;
            for (Dir d : Dir.values()) {
                Effects e = global.get(d);
                if (e.loss > 0 || e.corrupt > 0 || e.dup > 0 || e.reorder > 0
                        || e.latencyMs > 0 || e.jitterMs > 0) return false;
                for (Override o : byType.get(d).values()) if (!o.isEmpty()) return false;
            }
            return true;
        }

        /** One line for the console banner and the UI. */
        public String describe() {
            if (isClean()) return "clean (no impairment)";
            List<String> parts = new ArrayList<>();
            if (bandwidthBps > 0) parts.add("bandwidth " + humanBps(bandwidthBps));
            if (busyLoad > 0) parts.add(String.format(Locale.ROOT, "cross traffic %.0f%%", busyLoad * 100));
            if (queueCapacity > 0) parts.add("queue " + queueCapacity);
            if (queueMaxDelayMs > 0) parts.add("max wait " + queueMaxDelayMs + "ms");
            for (Dir d : Dir.values()) {
                Effects e = global.get(d);
                List<String> fx = new ArrayList<>();
                if (e.loss > 0) fx.add(String.format(Locale.ROOT, "loss %.0f%%", e.loss * 100));
                if (e.corrupt > 0) fx.add(String.format(Locale.ROOT, "corrupt %.0f%%", e.corrupt * 100));
                if (e.dup > 0) fx.add(String.format(Locale.ROOT, "dup %.0f%%", e.dup * 100));
                if (e.reorder > 0) fx.add(String.format(Locale.ROOT, "reorder %.0f%%", e.reorder * 100));
                if (e.latencyMs > 0) fx.add("latency " + e.latencyMs + "ms");
                if (e.jitterMs > 0) fx.add("jitter " + e.jitterMs + "ms");
                if (!fx.isEmpty()) parts.add(d.label + ": " + String.join(" ", fx));
                for (Map.Entry<Integer, Override> en : byType.get(d).entrySet()) {
                    Override o = en.getValue();
                    if (o.isEmpty()) continue;
                    List<String> sc = new ArrayList<>();
                    if (o.loss != null) sc.add(String.format(Locale.ROOT, "loss %.0f%%", o.loss * 100));
                    if (o.corrupt != null) sc.add(String.format(Locale.ROOT, "corrupt %.0f%%", o.corrupt * 100));
                    if (o.dup != null) sc.add(String.format(Locale.ROOT, "dup %.0f%%", o.dup * 100));
                    if (o.reorder != null) sc.add(String.format(Locale.ROOT, "reorder %.0f%%", o.reorder * 100));
                    if (o.latencyMs != null) sc.add("latency " + o.latencyMs + "ms");
                    if (o.jitterMs != null) sc.add("jitter " + o.jitterMs + "ms");
                    parts.add(d.label + ":" + Packet.typeName(en.getKey()) + ": " + String.join(" ", sc));
                }
            }
            return String.join(", ", parts);
        }
    }

    public static String humanBps(long bps) {
        if (bps >= 1_000_000) return (bps / 1_000_000) + "Mbps";
        if (bps >= 1_000) return (bps / 1_000) + "kbps";
        return bps + "bps";
    }

    // ---- named presets ----------------------------------------------------

    /** The presets --link offers. Add a row here to add a network condition. */
    public static Map<String, String> presetHelp() {
        Map<String, String> m = new LinkedHashMap<>();
        m.put("clean",      "perfect link (default)");
        m.put("slow",       "64kbps, 200ms latency, 40ms jitter -- a bad DSL uplink");
        m.put("busy",       "256kbps with 85% cross traffic and a 24-deep queue: delay");
        m.put("congested",  "128kbps, 95% cross traffic, 16-deep queue, 400ms max wait");
        m.put("lossy",      "20% loss both directions, independent");
        m.put("corrupt",    "15% of datagrams get a bit flipped -- the CRC must catch them");
        m.put("flaky-acks", "ACKs only: 40% lost, 25% corrupted. Orders get through fine");
        m.put("quiet-book", "market data only: QUOTE and TRADE 50% lost. Orders unaffected");
        m.put("satellite",  "600ms latency, 50ms jitter, 2% loss -- a long fat pipe");
        m.put("mobile",     "120ms latency, 150ms jitter, 5% loss, 10% reorder");
        return m;
    }

    public static boolean applyPreset(Config c, String name) {
        Effects in = c.global.get(Dir.IN), out = c.global.get(Dir.OUT);
        switch (name) {
            case "clean":
                return true;
            case "slow":
                c.bandwidthBps = 64_000;
                in.latencyMs = out.latencyMs = 200;
                in.jitterMs = out.jitterMs = 40;
                c.queueCapacity = 64;
                return true;
            case "busy":
                c.bandwidthBps = 256_000;
                c.busyLoad = 0.85;
                c.queueCapacity = 24;
                in.latencyMs = out.latencyMs = 20;
                in.jitterMs = out.jitterMs = 15;
                return true;
            case "congested":
                c.bandwidthBps = 128_000;
                c.busyLoad = 0.95;
                c.queueCapacity = 16;
                c.queueMaxDelayMs = 400;
                in.latencyMs = out.latencyMs = 30;
                return true;
            case "lossy":
                in.loss = out.loss = 0.20;
                return true;
            case "corrupt":
                in.corrupt = out.corrupt = 0.15;
                return true;
            case "flaky-acks": {
                Override o = c.scoped(Dir.OUT, Packet.T_ACK);
                o.loss = 0.40;
                o.corrupt = 0.25;
                return true;
            }
            case "quiet-book": {
                c.scoped(Dir.OUT, Packet.T_QUOTE).loss = 0.50;
                c.scoped(Dir.OUT, Packet.T_TRADE).loss = 0.50;
                return true;
            }
            case "satellite":
                in.latencyMs = out.latencyMs = 600;
                in.jitterMs = out.jitterMs = 50;
                in.loss = out.loss = 0.02;
                return true;
            case "mobile":
                in.latencyMs = out.latencyMs = 120;
                in.jitterMs = out.jitterMs = 150;
                in.loss = out.loss = 0.05;
                in.reorder = out.reorder = 0.10;
                return true;
            default:
                return false;
        }
    }

    // ---- what the link did to one datagram --------------------------------

    public static final class Outcome {
        public final boolean delivered;
        public final String verdict;   // short label for the UI's verdict column
        public final String note;      // human detail, appended to the log line
        public final int delayMs;
        Outcome(boolean delivered, String verdict, String note, int delayMs) {
            this.delivered = delivered; this.verdict = verdict;
            this.note = note; this.delayMs = delayMs;
        }
    }

    /** Called once per datagram the link finishes with, delivered or not. */
    public interface Delivery {
        void accept(byte[] data, int len, Outcome outcome);
    }

    // ---- state ------------------------------------------------------------

    private final Config cfg;
    private final Random rng;
    private final ScheduledExecutorService timers =
            Executors.newScheduledThreadPool(2, r -> {
                Thread t = new Thread(r, "xchg-link");
                t.setDaemon(true);
                return t;
            });

    /** Serialisation timeline per direction: when the link is next free. */
    private final Map<Dir, Long> nextFreeAtMs = new LinkedHashMap<>();
    private final Map<Dir, AtomicInteger> inFlight = new LinkedHashMap<>();

    public final AtomicLong dropped = new AtomicLong();
    public final AtomicLong corrupted = new AtomicLong();
    public final AtomicLong duplicated = new AtomicLong();
    public final AtomicLong reordered = new AtomicLong();
    public final AtomicLong congestionDrops = new AtomicLong();
    public final AtomicLong delayedTotalMs = new AtomicLong();
    public final AtomicLong delayedCount = new AtomicLong();

    public Link(Config cfg) {
        this.cfg = cfg;
        this.rng = new Random(cfg.seed ^ 0x5EEDL);
        for (Dir d : Dir.values()) {
            nextFreeAtMs.put(d, 0L);
            inFlight.put(d, new AtomicInteger());
        }
    }

    public Config config() { return cfg; }
    public int queueDepth(Dir d) { return inFlight.get(d).get(); }
    public long meanDelayMs() {
        long n = delayedCount.get();
        return n == 0 ? 0 : delayedTotalMs.get() / n;
    }

    /** Settings for this direction and message type, scoped overrides applied. */
    public Effects effectsFor(Dir dir, int type) {
        Effects e = cfg.global.get(dir).copy();
        Override o = cfg.byType.get(dir).get(type);
        if (o != null) o.applyTo(e);
        return e;
    }

    /**
     * Hand one datagram to the link. `d` is called exactly once per delivered
     * copy, and once with delivered=false for a datagram the link destroyed.
     * `data` must not be reused by the caller: the link may hold it.
     */
    public void submit(Dir dir, byte[] data, int len, int type, Delivery d) {
        Effects fx = effectsFor(dir, type);

        if (fx.loss > 0 && rng.nextDouble() < fx.loss) {
            dropped.incrementAndGet();
            d.accept(data, len, new Outcome(false, "dropped (loss)",
                    String.format(Locale.ROOT, "link dropped it: %.0f%% loss on %s",
                            fx.loss * 100, dir.label), 0));
            return;
        }

        // Congestion: queue the packet behind whatever is already on the wire.
        int queueMs = 0, serialMs = 0;
        if (cfg.bandwidthBps > 0) {
            synchronized (nextFreeAtMs) {
                long now = System.currentTimeMillis();
                double bits = (len + 28) * 8.0;              // + IP and UDP headers
                double effBps = cfg.bandwidthBps * (1.0 - Math.min(0.95, cfg.busyLoad));
                serialMs = (int) Math.ceil(bits * 1000.0 / Math.max(1.0, effBps));
                long free = Math.max(now, nextFreeAtMs.get(dir));
                queueMs = (int) (free - now);

                boolean full = cfg.queueCapacity > 0
                        && inFlight.get(dir).get() >= cfg.queueCapacity;
                boolean tooLate = cfg.queueMaxDelayMs > 0 && queueMs > cfg.queueMaxDelayMs;
                if (full || tooLate) {
                    dropped.incrementAndGet();
                    congestionDrops.incrementAndGet();
                    String why = full
                            ? "queue full (" + cfg.queueCapacity + " deep)"
                            : "would wait " + queueMs + "ms, over the " + cfg.queueMaxDelayMs + "ms limit";
                    d.accept(data, len, new Outcome(false, "dropped (congestion)",
                            "link is saturated, tail-dropped: " + why, 0));
                    return;
                }
                nextFreeAtMs.put(dir, free + serialMs);
            }
        }

        int jitter = fx.jitterMs > 0 ? rng.nextInt(fx.jitterMs + 1) : 0;
        int delay = fx.latencyMs + jitter + queueMs + serialMs;

        boolean late = fx.reorder > 0 && rng.nextDouble() < fx.reorder;
        if (late) {
            delay += 1 + rng.nextInt(Math.max(1, fx.reorderMs));
            reordered.incrementAndGet();
        }

        byte[] payload = data;
        String corruptNote = null;
        if (fx.corrupt > 0 && rng.nextDouble() < fx.corrupt) {
            payload = data.clone();
            corruptNote = corrupt(payload, len, fx.corruptBits);
            corrupted.incrementAndGet();
        }

        deliver(dir, payload, len, delay, corruptNote, late, queueMs, serialMs, d);

        if (fx.dup > 0 && rng.nextDouble() < fx.dup) {
            duplicated.incrementAndGet();
            int dupDelay = delay + 1 + rng.nextInt(40);
            deliver(dir, payload.clone(), len, dupDelay, corruptNote, late,
                    queueMs, serialMs, (dd, dl, out) -> d.accept(dd, dl,
                            new Outcome(out.delivered, out.verdict,
                                    out.note.isEmpty() ? "duplicate copy"
                                            : out.note + "; duplicate copy", out.delayMs)));
        }
    }

    private void deliver(Dir dir, byte[] data, int len, int delay, String corruptNote,
                         boolean late, int queueMs, int serialMs, Delivery d) {
        List<String> notes = new ArrayList<>();
        if (queueMs > 0) notes.add("queued " + queueMs + "ms");
        if (serialMs > 0) notes.add("serialised " + serialMs + "ms");
        if (late) notes.add("held back to reorder");
        if (corruptNote != null) notes.add(corruptNote);
        String note = String.join(", ", notes);
        String verdict = corruptNote != null ? "corrupted"
                : (delay > 0 ? "delayed " + delay + "ms" : "ok");

        inFlight.get(dir).incrementAndGet();
        if (delay > 0) {
            delayedTotalMs.addAndGet(delay);
            delayedCount.incrementAndGet();
        }
        Runnable job = () -> {
            inFlight.get(dir).decrementAndGet();
            d.accept(data, len, new Outcome(true, verdict, note, delay));
        };
        if (delay > 0) timers.schedule(job, delay, TimeUnit.MILLISECONDS);
        else job.run();
    }

    /**
     * Flip bits somewhere in the datagram and say where, because which region
     * was hit determines which error the receiver reports: the header gives
     * E_MAGIC or E_LENGTH, anything else gives E_CRC.
     */
    private String corrupt(byte[] data, int len, int bits) {
        List<String> where = new ArrayList<>();
        for (int i = 0; i < Math.max(1, bits); i++) {
            int idx = rng.nextInt(len);
            int bit = rng.nextInt(8);
            data[idx] ^= (byte) (1 << bit);
            String region = idx < Packet.HEADER_LEN ? "header"
                    : (idx >= len - Packet.CRC_LEN ? "CRC field" : "payload");
            where.add("byte " + idx + " (" + region + ") bit " + bit);
        }
        return "bit flipped at " + String.join(", ", where);
    }

    public void close() { timers.shutdownNow(); }
}
