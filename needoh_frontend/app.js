// NeeDoh Stock Tracker dashboard.
// Fetches the watchlist/sightings/calls, subscribes to the /events SSE stream
// for live updates, and (when permitted) raises desktop notifications and
// registers a service worker for web push.

const $ = (sel) => document.querySelector(sel);

let config = { vapidPublicKey: null, pushEnabled: false };
let settings = { allStores: [], enabledStores: [], callStores: [], storeLabels: {}, socialPlatforms: [] };
let socialAccounts = []; // working copy edited in the UI before save

const PLATFORM_LABELS = { instagram: "Instagram", facebook: "Facebook" };

// ---------- rendering ----------

function fmtPrice(p) {
  return p == null ? "—" : "$" + Number(p).toFixed(2);
}
function fmtTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return isNaN(d) ? iso : d.toLocaleString();
}

function renderProducts(products) {
  const body = $("#products-body");
  if (!products.length) {
    body.innerHTML = '<tr><td colspan="6" class="muted empty">No data yet. Click "Check now".</td></tr>';
    return;
  }
  body.innerHTML = products
    .map((p) => {
      const badge = p.in_stock
        ? '<span class="badge badge--in">In stock</span>'
        : '<span class="badge badge--out">Out</span>';
      const img = p.image ? `<img class="thumb" src="${p.image}" alt="" loading="lazy" />` : "";
      const label = settings.storeLabels[p.store] || p.store;
      return `<tr class="${p.in_stock ? "row--in" : ""}">
        <td>${img}</td>
        <td><a href="${p.url}" target="_blank" rel="noopener">${escapeHtml(p.name)}</a></td>
        <td>${escapeHtml(label)}</td>
        <td>${fmtPrice(p.price)}</td>
        <td>${badge}</td>
        <td class="muted">${fmtTime(p.last_checked)}</td>
      </tr>`;
    })
    .join("");
}

function renderSightings(sightings) {
  const el = $("#sightings");
  if (!sightings.length) {
    el.innerHTML = '<li class="muted empty">No sightings yet.</li>';
    return;
  }
  el.innerHTML = sightings
    .map((s) => {
      const platform = PLATFORM_LABELS[s.platform] || s.platform || "Instagram";
      const storeTag = s.store ? ` → ${escapeHtml(settings.storeLabels[s.store] || s.store)}` : "";
      return `<li>
        <div>${escapeHtml(s.caption || "(no caption)")}</div>
        <div class="feed-meta">${escapeHtml(platform)} · @${escapeHtml(s.account)}${storeTag} ·
          matched "${escapeHtml(s.matched_keyword)}" ·
          <a href="${s.post_url}" target="_blank" rel="noopener">view post</a></div>
      </li>`;
    })
    .join("");
}

function renderCalls(calls) {
  const el = $("#calls");
  if (!calls.length) {
    el.innerHTML = '<li class="muted empty">No calls yet.</li>';
    return;
  }
  el.innerHTML = calls
    .map((c) => {
      const label = settings.storeLabels[c.store] || c.store;
      const result = c.result ? `<div class="feed-meta">${escapeHtml(c.result)}</div>` : "";
      return `<li>
        <div><strong>${escapeHtml(label)}</strong>
          <span class="call-status call-status--${c.status}">${c.status}</span></div>
        <div class="feed-meta">${escapeHtml(c.to_number || "no number")} · ${fmtTime(c.created_at)}</div>
        ${result}
      </li>`;
    })
    .join("");
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
}

// ---------- data loading ----------

async function loadAll() {
  const [prod, sight, calls] = await Promise.all([
    fetch("/api/products").then((r) => r.json()),
    fetch("/api/sightings").then((r) => r.json()),
    fetch("/api/calls").then((r) => r.json()),
  ]);
  renderProducts(prod.products || []);
  renderSightings(sight.sightings || []);
  renderCalls(calls.calls || []);
}

async function loadSettings() {
  settings = await fetch("/api/settings").then((r) => r.json());
  $("#poll-interval").value = settings.pollIntervalS;
  socialAccounts = (settings.socialAccounts || []).map((a) => ({ ...a }));
  renderSocialAccounts();

  const storeToggles = settings.allStores
    .map(
      (s) => `<label><input type="checkbox" name="store" value="${s}"
        ${settings.enabledStores.includes(s) ? "checked" : ""} /> ${escapeHtml(settings.storeLabels[s] || s)}</label>`
    )
    .join("");
  $("#store-toggles").innerHTML = storeToggles;

  const callToggles = settings.allStores
    .map(
      (s) => `<label><input type="checkbox" name="callstore" value="${s}"
        ${settings.callStores.includes(s) ? "checked" : ""} /> ${escapeHtml(settings.storeLabels[s] || s)}</label>`
    )
    .join("");
  $("#call-toggles").innerHTML = callToggles;

  $("#call-buttons").innerHTML = settings.allStores
    .map(
      (s) => `<button class="btn btn--ghost btn--small" data-call="${s}">Call ${escapeHtml(
        settings.storeLabels[s] || s
      )}</button>`
    )
    .join("");

  // Populate the "linked store" dropdown for adding social pages.
  $("#social-store").innerHTML =
    '<option value="">No store link</option>' +
    settings.allStores
      .map((s) => `<option value="${s}">${escapeHtml(settings.storeLabels[s] || s)}</option>`)
      .join("");
}

function renderSocialAccounts() {
  const el = $("#social-list");
  if (!socialAccounts.length) {
    el.innerHTML = '<p class="muted empty">No pages yet — add one below.</p>';
    return;
  }
  el.innerHTML = socialAccounts
    .map((a, i) => {
      const platform = PLATFORM_LABELS[a.platform] || a.platform;
      const storeTag = a.store
        ? ` → ${escapeHtml(settings.storeLabels[a.store] || a.store)}`
        : "";
      return `<div class="social-row">
        <span><strong>${escapeHtml(platform)}</strong> @${escapeHtml(a.account)}${storeTag}</span>
        <button type="button" class="btn btn--ghost btn--small" data-social-remove="${i}">Remove</button>
      </div>`;
    })
    .join("");
}

// ---------- actions ----------

$("#check-btn").addEventListener("click", async () => {
  const btn = $("#check-btn");
  btn.disabled = true;
  btn.textContent = "Checking…";
  try {
    const res = await fetch("/api/check", { method: "POST" }).then((r) => r.json());
    renderProducts(res.products || []);
    const s = res.summary || {};
    $("#cycle-summary").textContent = `checked ${s.checked ?? 0} · restocked ${s.restocked ?? 0} · new IG ${s.new_sightings ?? 0}`;
    await loadAll();
  } finally {
    btn.disabled = false;
    btn.textContent = "Check now";
  }
});

$("#call-buttons").addEventListener("click", async (e) => {
  const btn = e.target.closest("[data-call]");
  if (!btn) return;
  btn.disabled = true;
  await fetch(`/api/calls/${btn.dataset.call}`, { method: "POST" });
  await loadAll();
  btn.disabled = false;
});

$("#social-add-btn").addEventListener("click", () => {
  const platform = $("#social-platform").value;
  const account = $("#social-handle").value.trim().replace(/^@/, "").replace(/\/+$/, "");
  const store = $("#social-store").value || null;
  if (!account) return;
  const exists = socialAccounts.some(
    (a) => a.platform === platform && a.account.toLowerCase() === account.toLowerCase()
  );
  if (!exists) socialAccounts.push({ platform, account, store });
  $("#social-handle").value = "";
  $("#social-store").value = "";
  renderSocialAccounts();
});

$("#social-list").addEventListener("click", (e) => {
  const btn = e.target.closest("[data-social-remove]");
  if (!btn) return;
  socialAccounts.splice(Number(btn.dataset.socialRemove), 1);
  renderSocialAccounts();
});

$("#settings-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const enabledStores = [...document.querySelectorAll('input[name="store"]:checked')].map((i) => i.value);
  const callStores = [...document.querySelectorAll('input[name="callstore"]:checked')].map((i) => i.value);
  await fetch("/api/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      pollIntervalS: Number($("#poll-interval").value),
      enabledStores,
      callStores,
      socialAccounts,
    }),
  });
  await loadSettings();
  $("#settings-saved").textContent = "Saved ✓";
  setTimeout(() => ($("#settings-saved").textContent = ""), 2000);
});

// ---------- notifications + SSE ----------

$("#notify-btn").addEventListener("click", async () => {
  if (!("Notification" in window)) {
    alert("This browser does not support notifications.");
    return;
  }
  const perm = await Notification.requestPermission();
  if (perm === "granted") {
    $("#notify-btn").textContent = "Notifications on";
    await subscribePush();
  }
});

function localNotify(title, body) {
  if ("Notification" in window && Notification.permission === "granted") {
    new Notification(title, { body });
  }
}

function urlBase64ToUint8Array(base64String) {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(base64);
  return Uint8Array.from([...raw].map((c) => c.charCodeAt(0)));
}

async function subscribePush() {
  if (!config.pushEnabled || !config.vapidPublicKey) return;
  if (!("serviceWorker" in navigator) || !("PushManager" in window)) return;
  try {
    const reg = await navigator.serviceWorker.register("/sw.js");
    const sub = await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(config.vapidPublicKey),
    });
    await fetch("/api/push/subscribe", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(sub),
    });
  } catch (err) {
    console.warn("push subscribe failed", err);
  }
}

function connectSSE() {
  const es = new EventSource("/events");
  es.onopen = () => {
    $("#status").classList.replace("status--off", "status--on");
  };
  es.onerror = () => {
    $("#status").classList.replace("status--on", "status--off");
  };
  es.onmessage = (e) => {
    let data;
    try {
      data = JSON.parse(e.data);
    } catch {
      return;
    }
    if (data.type === "restock") {
      const names = (data.products || []).map((p) => p.name).join(", ");
      localNotify("NeeDoh restock!", names);
      loadAll();
    } else if (data.type === "sighting") {
      localNotify("Instagram restock hint", (data.sightings || [])[0]?.caption || "");
      loadAll();
    } else if (data.type === "cycle") {
      $("#cycle-summary").textContent = `checked ${data.checked} · restocked ${data.restocked} · new IG ${data.sightings}`;
      loadAll();
    } else if (data.type === "call" || data.type === "call_result") {
      loadAll();
    }
  };
}

// ---------- init ----------

(async function init() {
  config = await fetch("/api/config").then((r) => r.json());
  if ("Notification" in window && Notification.permission === "granted") {
    $("#notify-btn").textContent = "Notifications on";
    subscribePush();
  }
  await loadSettings();
  await loadAll();
  connectSSE();
})();
