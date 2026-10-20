package com.com2512.xchg;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.concurrent.Executors;

/**
 * The exchange UI: a static page plus a JSON state endpoint, served by the JDK's
 * built-in HTTP server so the kit stays a single dependency-free jar.
 *
 *   GET /             the dashboard (resources/ui/index.html, embedded in the jar)
 *   GET /api/state    whole-world snapshot, polled by the page
 */
public final class WebUi {

    private final HttpServer http;
    private final Server server;
    private final byte[] page;

    public WebUi(int port, Server server) throws IOException {
        this.server = server;
        this.http = HttpServer.create(new InetSocketAddress(port), 0);
        this.page = loadPage();
        http.createContext("/", this::serveRoot);
        http.createContext("/api/state", this::serveState);
        http.setExecutor(Executors.newFixedThreadPool(4));
    }

    public void start() { http.start(); }
    public void stop() { http.stop(0); }

    private byte[] loadPage() throws IOException {
        try (InputStream in = WebUi.class.getResourceAsStream("/ui/index.html")) {
            if (in == null)
                return "<h1>ui/index.html missing from the jar</h1>".getBytes(StandardCharsets.UTF_8);
            return in.readAllBytes();
        }
    }

    private void serveRoot(HttpExchange ex) throws IOException {
        if (!"/".equals(ex.getRequestURI().getPath())) {
            ex.sendResponseHeaders(404, -1);
            ex.close();
            return;
        }
        ex.getResponseHeaders().add("Content-Type", "text/html; charset=utf-8");
        ex.sendResponseHeaders(200, page.length);
        try (OutputStream out = ex.getResponseBody()) { out.write(page); }
    }

    private void serveState(HttpExchange ex) throws IOException {
        byte[] body = snapshot().getBytes(StandardCharsets.UTF_8);
        ex.getResponseHeaders().add("Content-Type", "application/json");
        ex.getResponseHeaders().add("Cache-Control", "no-store");
        ex.sendResponseHeaders(200, body.length);
        try (OutputStream out = ex.getResponseBody()) { out.write(body); }
    }

    // ---- JSON (hand-rolled: no dependencies, and the shapes are tiny) -----

    private static String esc(String s) {
        if (s == null) return "";
        StringBuilder sb = new StringBuilder(s.length() + 8);
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            switch (c) {
                case '"': sb.append("\\\""); break;
                case '\\': sb.append("\\\\"); break;
                case '\n': sb.append("\\n"); break;
                case '\r': sb.append("\\r"); break;
                case '\t': sb.append("\\t"); break;
                default:
                    if (c < 0x20) sb.append(String.format("\\u%04x", (int) c));
                    else sb.append(c);
            }
        }
        return sb.toString();
    }

    private String snapshot() {
        Exchange ex = server.exchange;
        StringBuilder b = new StringBuilder(16384);
        long now = System.currentTimeMillis();

        b.append("{\"server\":{")
         .append("\"udpPort\":").append(server.udpPort)
         .append(",\"uptimeMs\":").append(now - server.startedMs)
         .append(",\"heartbeatMs\":").append(Server.HEARTBEAT_MS)
         .append(",\"ttlMs\":").append(Server.SESSION_TTL_MS)
         .append("},\"totals\":{")
         .append("\"rx\":").append(server.totalRx.get())
         .append(",\"tx\":").append(server.totalTx.get())
         .append(",\"bad\":").append(server.totalBad.get())
         .append(",\"dropped\":").append(server.totalDropped.get())
         .append("},\"symbols\":[");

        boolean first = true;
        for (Exchange.Symbol sy : ex.symbols()) {
            if (!first) b.append(',');
            first = false;
            b.append("{\"id\":").append(sy.id)
             .append(",\"ticker\":\"").append(esc(sy.ticker)).append('"')
             .append(",\"last\":").append(sy.last)
             .append(",\"volume\":").append(sy.volume)
             .append(",\"bid\":").append(ex.bestBid(sy.id))
             .append(",\"bidQty\":").append(ex.bidQty(sy.id))
             .append(",\"ask\":").append(ex.bestAsk(sy.id))
             .append(",\"askQty\":").append(ex.askQty(sy.id))
             .append(",\"bids\":").append(levels(ex.depth(sy.id, true, 4)))
             .append(",\"asks\":").append(levels(ex.depth(sy.id, false, 4)))
             .append('}');
        }

        b.append("],\"sessions\":[");
        first = true;
        for (Server.Session s : server.sessionList()) {
            if (!first) b.append(',');
            first = false;
            String subs = s.subscriptions.contains(0) ? "all" : s.subscriptions.toString();
            b.append("{\"id\":").append(s.id)
             .append(",\"team\":\"").append(esc(s.team)).append('"')
             .append(",\"peer\":\"").append(esc(s.key())).append('"')
             .append(",\"rx\":").append(s.rx.get())
             .append(",\"tx\":").append(s.tx.get())
             .append(",\"gaps\":").append(s.gaps.get())
             .append(",\"dups\":").append(s.dups.get())
             .append(",\"ooo\":").append(s.outOfOrder.get())
             .append(",\"orders\":").append(s.orders.get())
             .append(",\"fills\":").append(s.fills.get())
             .append(",\"rejected\":").append(s.rejected.get())
             .append(",\"resting\":").append(ex.restingCount(s.id))
             .append(",\"highestSeq\":").append(s.highestSeq)
             .append(",\"idleMs\":").append(now - s.lastSeenMs)
             .append(",\"ageMs\":").append(now - s.firstSeenMs)
             .append(",\"subs\":\"").append(esc(subs)).append('"')
             .append('}');
        }

        b.append("],\"trades\":[");
        first = true;
        for (Exchange.Trade t : ex.recentTrades(40)) {
            if (!first) b.append(',');
            first = false;
            Exchange.Symbol sy = ex.symbol(t.symbol);
            b.append("{\"id\":").append(t.id)
             .append(",\"sym\":\"").append(sy == null ? "?" : esc(sy.ticker)).append('"')
             .append(",\"px\":").append(t.price)
             .append(",\"qty\":").append(t.qty)
             .append(",\"aggr\":\"").append(t.aggressorSide == Packet.SIDE_BUY ? "BUY" : "SELL").append('"')
             .append(",\"buySession\":").append(t.buySession)
             .append(",\"sellSession\":").append(t.sellSession)
             .append(",\"agoMs\":").append(now - t.timeMs)
             .append('}');
        }

        b.append("],\"log\":[");
        first = true;
        for (Server.LogEntry e : server.recentLog(300)) {
            if (!first) b.append(',');
            first = false;
            b.append("{\"agoMs\":").append(now - e.timeMs)
             .append(",\"in\":").append(e.inbound)
             .append(",\"peer\":\"").append(esc(e.peer)).append('"')
             .append(",\"type\":\"").append(esc(e.type)).append('"')
             .append(",\"session\":").append(e.session)
             .append(",\"seq\":").append(e.seq)
             .append(",\"bytes\":").append(e.bytes)
             .append(",\"verdict\":\"").append(esc(e.verdict)).append('"')
             .append(",\"detail\":\"").append(esc(e.detail)).append('"')
             .append(",\"hex\":\"").append(esc(e.hex)).append('"')
             .append('}');
        }
        b.append("]}");
        return b.toString();
    }

    private static String levels(List<int[]> ls) {
        StringBuilder b = new StringBuilder("[");
        for (int i = 0; i < ls.size(); i++) {
            if (i > 0) b.append(',');
            b.append('[').append(ls.get(i)[0]).append(',').append(ls.get(i)[1]).append(']');
        }
        return b.append(']').toString();
    }
}
