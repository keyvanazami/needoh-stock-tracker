package com.com2512.xchg;

import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.List;
import java.util.Random;
import java.util.TreeMap;

/**
 * A continuous double-auction limit order book with price-time priority.
 *
 * Deliberately small: limit orders only, one tick size, no self-trade
 * prevention, no fees. Phase 1 is about getting bytes on and off the wire, not
 * about market microstructure — but the book is real enough that two students'
 * clients trade against each other, and against the built-in market maker.
 *
 * All public methods are synchronized on this instance: the UDP thread, the
 * market-maker timer and the HTTP handlers all reach in here.
 */
public final class Exchange {

    public static final int MM_SESSION = 0xFFFF;      // the built-in market maker
    public static final int MAX_RESTING_PER_SESSION = 64;

    /** The maker's price cycle. See marketMakerTick for why it is a cycle. */
    public static final int CYCLE_TICKS = 60;      // ticks per full oscillation
    public static final int CYCLE_AMPLITUDE = 9;   // cents either side of anchor

    public static final class Symbol {
        public final int id;
        public final String ticker;
        public int mid;             // market-maker reference price, in cents
        public final int anchor;    // the level the cycle oscillates around
        long tick;                  // ticks elapsed, drives the cycle
        double phase;               // so the four symbols do not move together
        public int last;            // last traded price, 0 if never traded
        public long volume;         // cumulative traded quantity
        Symbol(int id, String ticker, int mid) {
            this.id = id; this.ticker = ticker; this.mid = mid;
            this.anchor = mid; this.last = 0;
        }
    }

    public static final class Order {
        public final long id;
        public final int session;
        public final long clOrdId;
        public final int symbol, side, price;
        public final int qty;
        public int remaining;
        public final long seqNo;     // arrival order, for time priority
        Order(long id, int session, long clOrdId, int symbol, int side, int price,
              int qty, long seqNo) {
            this.id = id; this.session = session; this.clOrdId = clOrdId;
            this.symbol = symbol; this.side = side; this.price = price;
            this.qty = qty; this.remaining = qty; this.seqNo = seqNo;
        }
    }

    public static final class Trade {
        public final long id;
        public final int symbol, price, qty, aggressorSide;
        public final long buyOrderId, sellOrderId;
        public final int buySession, sellSession;
        public final long timeMs;
        Trade(long id, int symbol, int price, int qty, int aggressorSide,
              long buyOrderId, long sellOrderId, int buySession, int sellSession) {
            this.id = id; this.symbol = symbol; this.price = price; this.qty = qty;
            this.aggressorSide = aggressorSide;
            this.buyOrderId = buyOrderId; this.sellOrderId = sellOrderId;
            this.buySession = buySession; this.sellSession = sellSession;
            this.timeMs = System.currentTimeMillis();
        }
    }

    /** What submit() gives back: the ACK fields, plus any trades to broadcast. */
    public static final class Result {
        public long orderId;
        public int status, reason, filledQty, restQty;
        public final List<Trade> trades = new ArrayList<>();
    }

    /** One side of one symbol's book. */
    private static final class Side {
        final TreeMap<Integer, ArrayDeque<Order>> levels;
        Side(boolean descending) {
            this.levels = descending
                    ? new TreeMap<>(Comparator.reverseOrder())
                    : new TreeMap<>();
        }
        void add(Order o) {
            levels.computeIfAbsent(o.price, k -> new ArrayDeque<>()).addLast(o);
        }
        Integer bestPrice() { return levels.isEmpty() ? null : levels.firstKey(); }
        ArrayDeque<Order> bestLevel() { return levels.isEmpty() ? null : levels.firstEntry().getValue(); }
        void pruneEmptyBest() {
            while (!levels.isEmpty() && levels.firstEntry().getValue().isEmpty())
                levels.pollFirstEntry();
        }
        int qtyAt(int price) {
            ArrayDeque<Order> q = levels.get(price);
            if (q == null) return 0;
            int n = 0;
            for (Order o : q) n += o.remaining;
            return n;
        }
    }

    private final TreeMap<Integer, Symbol> symbols = new TreeMap<>();
    private final TreeMap<Integer, Side> bids = new TreeMap<>();
    private final TreeMap<Integer, Side> asks = new TreeMap<>();
    private final TreeMap<Long, Order> byId = new TreeMap<>();
    private final ArrayDeque<Trade> tape = new ArrayDeque<>();
    private final Map<Integer, Account> accounts = new LinkedHashMap<>();
    private final Random rng;
    private long startingCash = 1_000_000L;            // cents
    private int startingShares = 200;

    private long nextOrderId = 1, nextTradeId = 1, arrivalSeq = 1;
    private final int mmSpread, mmSize;
    private final boolean mmEnabled;

    public Exchange(long seed, boolean mmEnabled, int mmSpread, int mmSize) {
        this.rng = new Random(seed);
        this.mmEnabled = mmEnabled;
        this.mmSpread = Math.max(1, mmSpread);
        this.mmSize = Math.max(1, mmSize);
        // Mids in the same range as the hardware acceptance vectors (AAPL = 300).
        addSymbol(1, "AAPL", 300);
        addSymbol(2, "MSFT", 420);
        addSymbol(3, "NVDA", 880);
        addSymbol(4, "TSLA", 250);
        // Spread the symbols around the cycle so they are not one trade.
        int k = 0;
        for (Symbol s : symbols.values()) s.phase = (Math.PI / 2) * (k++);
    }

    public synchronized void setStartingBalances(long cash, int shares) {
        this.startingCash = cash;
        this.startingShares = shares;
    }

    public synchronized long startingCash() { return startingCash; }
    public synchronized int startingShares() { return startingShares; }

    /** Seed a trader on connect. The market maker trades without an account. */
    public synchronized Account openAccount(int session) {
        Map<Integer, Integer> seed = new LinkedHashMap<>();
        for (Symbol s : symbols.values()) seed.put(s.id, startingShares);
        Account a = new Account(session, startingCash, seed);
        accounts.put(session, a);
        return a;
    }

    public synchronized Account account(int session) { return accounts.get(session); }
    public synchronized void closeAccount(int session) { accounts.remove(session); }
    public synchronized Map<Integer, Account> accounts() { return new LinkedHashMap<>(accounts); }

    /** Last trade price per symbol, falling back to the maker's mid. */
    public synchronized Map<Integer, Integer> marks() {
        Map<Integer, Integer> m = new LinkedHashMap<>();
        for (Symbol s : symbols.values()) m.put(s.id, s.last > 0 ? s.last : s.mid);
        return m;
    }

    /** What a fresh account is worth, so P&L starts everyone at zero. */
    public synchronized long startingValue() {
        long v = startingCash;
        for (Symbol s : symbols.values())
            v += (long) startingShares * (s.last > 0 ? s.last : s.mid);
        return v;
    }

    private void addSymbol(int id, String ticker, int mid) {
        symbols.put(id, new Symbol(id, ticker, mid));
        bids.put(id, new Side(true));    // best bid = highest price
        asks.put(id, new Side(false));   // best ask = lowest price
    }

    public synchronized List<Symbol> symbols() { return new ArrayList<>(symbols.values()); }
    public synchronized Symbol symbol(int id) { return symbols.get(id); }
    public synchronized boolean knownSymbol(int id) { return symbols.containsKey(id); }

    public synchronized int bestBid(int sym) {
        Integer p = bids.get(sym).bestPrice(); return p == null ? 0 : p;
    }
    public synchronized int bestAsk(int sym) {
        Integer p = asks.get(sym).bestPrice(); return p == null ? 0 : p;
    }
    public synchronized int bidQty(int sym) {
        Integer p = bids.get(sym).bestPrice(); return p == null ? 0 : bids.get(sym).qtyAt(p);
    }
    public synchronized int askQty(int sym) {
        Integer p = asks.get(sym).bestPrice(); return p == null ? 0 : asks.get(sym).qtyAt(p);
    }

    /** Depth for the UI: up to `levels` price points per side. */
    public synchronized List<int[]> depth(int sym, boolean buySide, int levels) {
        Side s = buySide ? bids.get(sym) : asks.get(sym);
        List<int[]> out = new ArrayList<>();
        for (java.util.Map.Entry<Integer, ArrayDeque<Order>> e : s.levels.entrySet()) {
            int q = 0;
            for (Order o : e.getValue()) q += o.remaining;
            if (q > 0) out.add(new int[]{e.getKey(), q});
            if (out.size() >= levels) break;
        }
        return out;
    }

    public synchronized List<Trade> recentTrades(int max) {
        List<Trade> out = new ArrayList<>(tape);
        java.util.Collections.reverse(out);
        return out.size() > max ? out.subList(0, max) : out;
    }

    public synchronized int restingCount(int session) {
        int n = 0;
        for (Order o : byId.values()) if (o.session == session && o.remaining > 0) n++;
        return n;
    }

    /** Submit a limit order. Validates, matches what it can, rests the remainder. */
    public synchronized Result submit(int session, long clOrdId, int symbol, int side,
                                      int price, int qty) {
        Result r = new Result();
        if (!symbols.containsKey(symbol)) {
            r.status = Packet.ST_REJECTED; r.reason = Packet.R_UNKNOWN_SYMBOL; return r;
        }
        if (side != Packet.SIDE_BUY && side != Packet.SIDE_SELL) {
            r.status = Packet.ST_REJECTED; r.reason = Packet.R_BAD_SIDE; return r;
        }
        if (qty == 0) { r.status = Packet.ST_REJECTED; r.reason = Packet.R_ZERO_QTY; return r; }
        if (price == 0) { r.status = Packet.ST_REJECTED; r.reason = Packet.R_ZERO_PRICE; return r; }
        if (session != MM_SESSION && restingCount(session) >= MAX_RESTING_PER_SESSION) {
            r.status = Packet.ST_REJECTED; r.reason = Packet.R_TOO_MANY; return r;
        }

        // Reserve what the order would need, at ENTRY. A resting order that has
        // not reserved could be unpayable by the time it fills, and one balance
        // would silently back any number of resting orders.
        Account acct = accounts.get(session);
        if (session != MM_SESSION) {
            if (acct == null) {
                r.status = Packet.ST_REJECTED; r.reason = Packet.R_NO_ACCOUNT; return r;
            }
            if (side == Packet.SIDE_BUY && !acct.reserveCash(price, qty)) {
                r.status = Packet.ST_REJECTED; r.reason = Packet.R_NO_FUNDS; return r;
            }
            if (side == Packet.SIDE_SELL && !acct.reserveStock(symbol, qty)) {
                r.status = Packet.ST_REJECTED; r.reason = Packet.R_NO_STOCK; return r;
            }
        }

        Order incoming = new Order(nextOrderId++, session, clOrdId, symbol, side, price,
                                   qty, arrivalSeq++);
        byId.put(incoming.id, incoming);
        r.orderId = incoming.id;

        Side opposite = (side == Packet.SIDE_BUY) ? asks.get(symbol) : bids.get(symbol);
        while (incoming.remaining > 0) {
            opposite.pruneEmptyBest();
            Integer best = opposite.bestPrice();
            if (best == null) break;
            boolean crosses = (side == Packet.SIDE_BUY) ? (best <= price) : (best >= price);
            if (!crosses) break;

            ArrayDeque<Order> level = opposite.bestLevel();
            Order resting = level.peekFirst();
            if (resting == null || resting.remaining == 0) { level.pollFirst(); continue; }

            int fill = Math.min(incoming.remaining, resting.remaining);
            // Trade prints at the RESTING order's price: the passive side set the
            // terms, the aggressor accepted them.
            int tradePx = resting.price;
            incoming.remaining -= fill;
            resting.remaining -= fill;
            if (resting.remaining == 0) level.pollFirst();

            boolean incomingIsBuy = side == Packet.SIDE_BUY;
            Trade t = new Trade(nextTradeId++, symbol, tradePx, fill, side,
                    incomingIsBuy ? incoming.id : resting.id,
                    incomingIsBuy ? resting.id : incoming.id,
                    incomingIsBuy ? incoming.session : resting.session,
                    incomingIsBuy ? resting.session : incoming.session);
            r.trades.add(t);
            tape.addLast(t);
            while (tape.size() > 256) tape.pollFirst();

            // Settlement is immediate and atomic with the print: cash and stock
            // move now, not at some end-of-day. Each side unwinds the reservation
            // it made at entry, so a buy that improves on its limit gets the
            // difference back.
            int buyerLimit = incomingIsBuy ? price : resting.price;
            settle(t.buySession, t.sellSession, symbol, buyerLimit, tradePx, fill);

            Symbol s = symbols.get(symbol);
            s.last = tradePx;
            s.volume += fill;
        }

        r.filledQty = qty - incoming.remaining;
        r.restQty = incoming.remaining;
        if (incoming.remaining == 0) {
            r.status = Packet.ST_FILLED;
            byId.remove(incoming.id);
        } else {
            Side own = (side == Packet.SIDE_BUY) ? bids.get(symbol) : asks.get(symbol);
            own.add(incoming);
            r.status = (r.filledQty > 0) ? Packet.ST_PARTIAL : Packet.ST_RESTING;
        }
        return r;
    }

    private void settle(int buySession, int sellSession, int sym, int buyerLimit,
                        int price, int qty) {
        Account buyer = accounts.get(buySession);
        if (buyer != null) buyer.settleBuy(sym, buyerLimit, price, qty);
        Account seller = accounts.get(sellSession);
        if (seller != null) seller.settleSell(sym, price, qty);
    }

    /** Hand back whatever an order's unfilled remainder still has reserved. */
    private void release(Order o) {
        Account a = accounts.get(o.session);
        if (a == null || o.remaining <= 0) return;
        if (o.side == Packet.SIDE_BUY) a.releaseCash(o.price, o.remaining);
        else a.releaseStock(o.symbol, o.remaining);
    }

    /** Cancel a resting order. Only the session that placed it may cancel it. */
    public synchronized Result cancel(int session, long clOrdId, long orderId) {
        Result r = new Result();
        r.orderId = orderId;
        Order o = byId.get(orderId);
        if (o == null || o.remaining == 0) {
            r.status = Packet.ST_REJECTED; r.reason = Packet.R_UNKNOWN_ORDER; return r;
        }
        if (o.session != session) {
            r.status = Packet.ST_REJECTED; r.reason = Packet.R_NOT_YOUR_ORDER; return r;
        }
        Side s = (o.side == Packet.SIDE_BUY) ? bids.get(o.symbol) : asks.get(o.symbol);
        ArrayDeque<Order> level = s.levels.get(o.price);
        if (level != null) {
            level.remove(o);
            if (level.isEmpty()) s.levels.remove(o.price);
        }
        release(o);
        byId.remove(orderId);
        r.status = Packet.ST_CANCELLED;
        r.restQty = 0;
        r.filledQty = o.qty - o.remaining;
        return r;
    }

    /** Drop every resting order belonging to a session that has gone away. */
    public synchronized void cancelAllFor(int session) {
        List<Long> ids = new ArrayList<>();
        for (Order o : byId.values()) if (o.session == session) ids.add(o.id);
        for (long id : ids) {
            Order o = byId.get(id);
            Side s = (o.side == Packet.SIDE_BUY) ? bids.get(o.symbol) : asks.get(o.symbol);
            ArrayDeque<Order> level = s.levels.get(o.price);
            if (level != null) {
                level.remove(o);
                if (level.isEmpty()) s.levels.remove(o.price);
            }
            release(o);
            byId.remove(id);
        }
    }

    /**
     * One market-maker tick: random-walk each mid, re-quote both sides.
     *
     * Without this the book is empty until two students connect at the same
     * time, and a lone student's first order rests forever with no feedback.
     * Returns the trades its re-quoting caused (it can cross a student order).
     */
    public synchronized List<Trade> marketMakerTick() {
        List<Trade> trades = new ArrayList<>();
        if (!mmEnabled) return trades;
        cancelAllFor(MM_SESSION);
        for (Symbol s : symbols.values()) {
            // A slow cycle plus noise, NOT a random walk.
            //
            // This is a deliberate, and openly synthetic, choice. Against a
            // random walk the reference strategy has no edge: it pays the spread
            // on every round trip and loses steadily, which would mean the
            // highest-scoring client was the one that traded LEAST -- exactly the
            // wrong incentive for an exercise about execution quality. Measured
            // over three seeds, a client that dropped 60% of its market data
            // actually WON two of them, because P&L was pure noise.
            //
            // With a real cycle to capture, the strategy has positive
            // expectancy, the edge is comfortably larger than the spread, and
            // catching more of the signal reliably earns more. Missing quotes
            // now costs money, which is the whole point.
            s.tick++;
            double angle = 2 * Math.PI * s.tick / CYCLE_TICKS + s.phase;
            int target = s.anchor + (int) Math.round(CYCLE_AMPLITUDE * Math.sin(angle));
            s.mid = Math.max(20, Math.min(60000, target + rng.nextInt(3) - 1));
            int half = Math.max(1, mmSpread / 2);
            for (int i = 0; i < 3; i++) {                      // three levels each side
                int bid = s.mid - half - i;
                int ask = s.mid + half + i;
                int size = mmSize * (i + 1);
                if (bid > 0) trades.addAll(submit(MM_SESSION, 0, s.id, Packet.SIDE_BUY, bid, size).trades);
                if (ask < 65535) trades.addAll(submit(MM_SESSION, 0, s.id, Packet.SIDE_SELL, ask, size).trades);
            }
        }
        return trades;
    }
}
