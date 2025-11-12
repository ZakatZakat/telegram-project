(() => {
  const tg = window.Telegram?.WebApp;
  try {
    tg?.expand();
    tg?.ready();
  } catch {}

  const listEl = document.getElementById("list");
  const userFilter = document.getElementById("userFilter");
  const reloadBtn = document.getElementById("reloadBtn");
  const channelSelect = document.getElementById("channelSelect");
  const ingestBtn = document.getElementById("ingestBtn");

  async function load() {
    listEl.innerHTML = "Loading...";
    const params = new URLSearchParams();
    const selected = channelSelect.value ? channelSelect.value.trim() : "";
    const u = userFilter.value.trim();
    if (selected) {
      if (selected.startsWith("@")) {
        params.set("username", selected.slice(1));
      } else {
        params.set("channel_id", selected);
      }
    } else if (u) {
      params.set("username", u.startsWith("@") ? u.slice(1) : u);
    }
    params.set("limit", "100");
    const res = await fetch(`/miniapp/api/posts?${params.toString()}`);
    const data = await res.json();
    const items = data.items || [];
    if (!items.length) {
      listEl.innerHTML = "<p>No posts.</p>";
      return;
    }
    listEl.innerHTML = "";
    for (const it of items) {
      const card = document.createElement("article");
      card.className = "card";
      const title = it.channel_title || it.channel_username || "Channel";
      const link = it.source_url ? `<a href="${it.source_url}" target="_blank">Open</a>` : "";
      const textHtml = `
        <div class="meta">
          <span class="ch">${title}</span>
          <span class="dt">${new Date(it.date).toLocaleString()}</span>
          ${link}
        </div>
        <div class="text">${escapeHtml((it.text || "").slice(0, 800)).replace(/\\n/g, "<br/>")}</div>`;
      card.innerHTML = textHtml;
      if (Array.isArray(it.media_urls) && it.media_urls.length) {
        const gallery = document.createElement("div");
        gallery.className = "gallery";
        for (const url of it.media_urls.slice(0, 4)) {
          const img = document.createElement("img");
          img.src = url;
          img.alt = "photo";
          img.loading = "lazy";
          img.className = "ph";
          gallery.appendChild(img);
        }
        card.appendChild(gallery);
      }
      listEl.appendChild(card);
    }
  }

  async function loadChannels() {
    try {
      const res = await fetch(`/miniapp/api/channels`);
      const data = await res.json();
      const items = data.items || [];
      channelSelect.innerHTML = `<option value="">All channels</option>`;
      for (const ch of items) {
        const label = ch.username ? `@${ch.username}` : ch.name;
        const value = ch.username ? `@${ch.username}` : String(ch.id);
        const opt = document.createElement("option");
        opt.value = value;
        opt.textContent = label;
        channelSelect.appendChild(opt);
      }
    } catch (e) {
      console.error(e);
    }
  }

  channelSelect.addEventListener("change", () => {
    const val = channelSelect.value;
    userFilter.value = val.startsWith("@") ? val : (val ? "" : "");
    load();
  });

  function escapeHtml(s) {
    return s
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  reloadBtn.addEventListener("click", load);
  ingestBtn.addEventListener("click", async () => {
    const sel = channelSelect.value.trim() || userFilter.value.trim();
    if (!sel) {
      alert("Select a channel or enter @username");
      return;
    }
    ingestBtn.disabled = true;
    ingestBtn.textContent = "Ingesting…";
    try {
      const body = { channel: sel, limit: 300, force_media: true };
      const r = await fetch(`/miniapp/api/ingest`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      await r.json().catch(() => ({}));
      await load();
    } catch (e) {
      console.error(e);
    } finally {
      ingestBtn.disabled = false;
      ingestBtn.textContent = "Ingest selected";
    }
  });
  loadChannels().then(load);
})();


