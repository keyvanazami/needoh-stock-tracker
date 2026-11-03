package com.com2512.xchg;

import java.util.ArrayDeque;
import java.util.Deque;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * The Phase 2 reference strategy: fixed-parameter mean reversion.
 *
 * Every student implements exactly this, so nobody is competing on the trading
 * idea and the only thing left to differ is the quality of the system around
 * it. The constants are not tuneable; changing them is out of scope.
 *
 * All arithmetic is integer, and every division floors, so an implementation in
 * any language produces bit-identical decisions. `--algo-vectors` prints a fixed
 * quote sequence and the decisions a correct implementation makes, the same way
 * the CRC check values pin down the framing.
 *
 * This class exists to generate those vectors. The server never trades with it.
 */
public final class Strategy {

    public static final int WINDOW = 20;   // mids in the moving average
    public static final int BAND   = 2;    // cents away from the average before acting
    public static final int SIZE   = 10;   // shares per order

    public enum Action { NONE, BUY, SELL }

    public static final class Decision {
        public final Action action;
        public final int qty, price, mid, sma;
        Decision(Action a, int qty, int price, int mid, int sma) {
            this.action = a; this.qty = qty; this.price = price;
            this.mid = mid; this.sma = sma;
        }
    }

    private final Map<Integer, Deque<Integer>> windows = new LinkedHashMap<>();

    /**
     * Feed one QUOTE, get the decision.
     *
     *   mid = (bid + ask) / 2                      integer division, floors
     *   push mid; keep only the last WINDOW
     *   if fewer than WINDOW samples -> NONE       still warming up
     *   sma = sum(window) / WINDOW                 integer division, floors
     *   mid < sma - BAND  -> BUY  SIZE at ask      it is cheap, lift the offer
     *   mid > sma + BAND  -> SELL SIZE at bid      it is dear, hit the bid
     *   otherwise         -> NONE
     *
     * A one-sided book (bid or ask of 0) is never actionable.
     */
    public Decision onQuote(int symbol, int bid, int ask) {
        if (bid == 0 || ask == 0) return new Decision(Action.NONE, 0, 0, 0, 0);

        int mid = (bid + ask) / 2;
        Deque<Integer> w = windows.computeIfAbsent(symbol, k -> new ArrayDeque<>());
        w.addLast(mid);
        while (w.size() > WINDOW) w.pollFirst();
        if (w.size() < WINDOW) return new Decision(Action.NONE, 0, 0, mid, -1);

        int sum = 0;
        for (int v : w) sum += v;
        int sma = sum / WINDOW;

        if (mid < sma - BAND) return new Decision(Action.BUY, SIZE, ask, mid, sma);
        if (mid > sma + BAND) return new Decision(Action.SELL, SIZE, bid, mid, sma);
        return new Decision(Action.NONE, 0, 0, mid, sma);
    }

    /**
     * The quote sequence the vectors are built from. Deterministic and written
     * out in full, so a student never has to reproduce a random generator —
     * only the decision rule.
     *
     * It holds flat long enough for the window to fill, then walks down through
     * the lower band and back up through the upper one, so both branches and
     * the dead zone are all exercised.
     */
    public static int[][] vectorQuotes() {
        int[] mids = new int[34];
        int i = 0;
        for (; i < 20; i++) mids[i] = 300;                  // warm-up, flat
        int[] tail = {299, 297, 295, 293, 291, 290, 292, 296,
                      300, 304, 308, 310, 309, 305};        // down then up
        for (int t : tail) mids[i++] = t;

        int[][] quotes = new int[mids.length][2];
        for (int k = 0; k < mids.length; k++) {
            quotes[k][0] = mids[k] - 2;                     // bid
            quotes[k][1] = mids[k] + 2;                     // ask
        }
        return quotes;
    }

    /** Print the acceptance vectors for the strategy. */
    public static void printVectors() {
        System.out.println("# Phase 2 strategy acceptance vectors (symbol 1, AAPL)");
        System.out.printf("# WINDOW=%d  BAND=%d  SIZE=%d%n", WINDOW, BAND, SIZE);
        System.out.println("# mid = (bid+ask)/2 and sma = sum/WINDOW, both integer division.");
        System.out.println("# Feed the quotes in order. Your decisions must match this column");
        System.out.println("# for column. '-' in sma means the window is not full yet.");
        System.out.println();
        System.out.printf("  %4s %6s %6s %6s %6s   %s%n", "tick", "bid", "ask", "mid", "sma", "decision");

        Strategy st = new Strategy();
        int[][] quotes = vectorQuotes();
        int buys = 0, sells = 0;
        for (int t = 0; t < quotes.length; t++) {
            int bid = quotes[t][0], ask = quotes[t][1];
            Decision d = st.onQuote(1, bid, ask);
            String what;
            switch (d.action) {
                case BUY:  what = String.format("BUY  %d @ %d", d.qty, d.price); buys++; break;
                case SELL: what = String.format("SELL %d @ %d", d.qty, d.price); sells++; break;
                default:   what = "-";
            }
            System.out.printf("  %4d %6d %6d %6d %6s   %s%n",
                    t, bid, ask, d.mid, d.sma < 0 ? "-" : String.valueOf(d.sma), what);
        }
        System.out.println();
        System.out.printf("  %d BUY and %d SELL decisions over %d quotes.%n",
                buys, sells, quotes.length);
        System.out.println("  Different totals mean your strategy does not match. Check your");
        System.out.println("  integer division before anything else.");
    }
}
