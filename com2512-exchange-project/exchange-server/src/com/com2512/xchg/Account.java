package com.com2512.xchg;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * One trader's money and stock. Phase 2 onwards.
 *
 * Long only: you cannot sell what you do not hold, and you cannot buy what you
 * cannot pay for. Both checks happen at order ENTRY, not at fill, which means a
 * resting order has to reserve what it would need — otherwise one balance could
 * back an unlimited number of resting orders, and the first few fills would
 * leave the rest unpayable.
 *
 *   cash      = free cash, already net of reservations
 *   reserved  = cash set aside by resting buys
 *   position  = shares held, already net of reservations
 *   onSale    = shares set aside by resting sells
 *
 * Nothing here is persisted. Sessions are the account boundary, so a session
 * that goes away takes its account with it, which is also what makes
 * "settlement only while both sides are online" true: a dead session's resting
 * orders are cancelled, so there is nothing left of it to trade against.
 */
public final class Account {

    public final int session;
    private long cash;                 // cents, free
    private long reserved;             // cents, held by resting buys
    private final long startingCash;
    private final Map<Integer, long[]> stock = new LinkedHashMap<>();  // sym -> {free, onSale}

    /** Realised cash flow and share flow, for the scorecard. */
    public long bought, sold;          // shares
    public long spent, received;       // cents
    public long rejectedFunds, rejectedStock;

    public Account(int session, long startingCash, Map<Integer, Integer> startingStock) {
        this.session = session;
        this.cash = startingCash;
        this.startingCash = startingCash;
        for (Map.Entry<Integer, Integer> e : startingStock.entrySet())
            stock.put(e.getKey(), new long[]{e.getValue(), 0});
    }

    private long[] slot(int sym) {
        return stock.computeIfAbsent(sym, k -> new long[]{0, 0});
    }

    public synchronized long cash() { return cash; }
    public synchronized long reserved() { return reserved; }
    public synchronized long startingCash() { return startingCash; }
    /** Shares held, including any set aside by resting sells. */
    public synchronized long position(int sym) { long[] s = slot(sym); return s[0] + s[1]; }
    public synchronized long free(int sym) { return slot(sym)[0]; }
    public synchronized long onSale(int sym) { return slot(sym)[1]; }
    public synchronized Map<Integer, long[]> stockView() { return new LinkedHashMap<>(stock); }

    /** Cash a buy of qty at price needs. Resting buys reserve at their limit. */
    public static long cost(int price, int qty) { return (long) price * qty; }

    /** Try to reserve cash for a resting or crossing buy. */
    public synchronized boolean reserveCash(int price, int qty) {
        long need = cost(price, qty);
        if (cash < need) { rejectedFunds++; return false; }
        cash -= need;
        reserved += need;
        return true;
    }

    /** Try to set aside shares for a sell. */
    public synchronized boolean reserveStock(int sym, int qty) {
        long[] s = slot(sym);
        if (s[0] < qty) { rejectedStock++; return false; }
        s[0] -= qty;
        s[1] += qty;
        return true;
    }

    /** Give back what an unfilled remainder had reserved (cancel, expiry). */
    public synchronized void releaseCash(int price, int qty) {
        long back = cost(price, qty);
        reserved -= back;
        cash += back;
    }

    public synchronized void releaseStock(int sym, int qty) {
        long[] s = slot(sym);
        s[1] -= qty;
        s[0] += qty;
    }

    /**
     * Settle a buy fill. `limit` is what was reserved per share, `price` what it
     * actually traded at — a buy can only ever improve, and the difference comes
     * back as cash.
     */
    public synchronized void settleBuy(int sym, int limit, int price, int qty) {
        long held = cost(limit, qty);
        long paid = cost(price, qty);
        reserved -= held;
        cash += held - paid;           // price improvement returned
        slot(sym)[0] += qty;
        bought += qty;
        spent += paid;
    }

    /** Settle a sell fill: the reserved shares leave, the cash arrives. */
    public synchronized void settleSell(int sym, int price, int qty) {
        slot(sym)[1] -= qty;
        long got = cost(price, qty);
        cash += got;
        sold += qty;
        received += got;
    }

    /** cash + reserved + every share marked at `mark`. The leaderboard number. */
    public synchronized long markToMarket(Map<Integer, Integer> marks) {
        long v = cash + reserved;
        for (Map.Entry<Integer, long[]> e : stock.entrySet()) {
            Integer px = marks.get(e.getKey());
            if (px == null) continue;
            v += (e.getValue()[0] + e.getValue()[1]) * (long) px;
        }
        return v;
    }

    /** Mark-to-market minus what they started with. Can be negative. */
    public synchronized long pnl(Map<Integer, Integer> marks, long startingValue) {
        return markToMarket(marks) - startingValue;
    }
}
