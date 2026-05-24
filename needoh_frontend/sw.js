// Service worker for web-push notifications. Shows a notification even when
// the dashboard tab is closed. Payload is the JSON sent by notifier._push.

self.addEventListener("push", (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch {
    data = { title: "NeeDoh Tracker", body: event.data ? event.data.text() : "" };
  }
  const title = data.title || "NeeDoh Tracker";
  const options = {
    body: data.body || "",
    data: { url: data.url || "/" },
    icon: "/icon.png",
    badge: "/icon.png",
  };
  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || "/";
  event.waitUntil(
    clients.matchAll({ type: "window", includeUncontrolled: true }).then((wins) => {
      for (const win of wins) {
        if (win.url === url && "focus" in win) return win.focus();
      }
      if (clients.openWindow) return clients.openWindow(url);
    })
  );
});
