(() => {
  const tg = window.Telegram?.WebApp;
  try {
    tg?.expand();
    tg?.ready();
  } catch {}

  const listEl = document.getElementById("list");
  const userFilter = document.getElementById("userFilter");
  const reloadBtn = document.getElementById("reloadBtn");

  async function load() {
    listEl.innerHTML = "Loading...";
    const params = new URLSearchParams();
    const u = userFilter.value.trim();
    if (u) params.set("username", u.startsWith("@") ? u.slice(1) : u);
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
      card.innerHTML = `
        <div class="meta">
          <span class="ch">${title}</span>
          <span class="dt">${new Date(it.date).toLocaleString()}</span>
          ${link}
        </div>
        <div class="text">${escapeHtml((it.text || "").slice(0, 800)).replace(/\\n/g, "<br/>")}</div>
      `;
      listEl.appendChild(card);
    }
  }

  function escapeHtml(s) {
    return s
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  reloadBtn.addEventListener("click", load);
  load();
})();


