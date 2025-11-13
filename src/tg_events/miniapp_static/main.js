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
  const refreshChannelsBtn = document.getElementById("refreshChannelsBtn");
  const genBtn = document.getElementById("genBtn");
  const genCount = document.getElementById("genCount");
  const genStatus = document.getElementById("genStatus");
  const clearBtn = document.getElementById("clearBtn");
  let lastItems = [];
  let autoTimer = null;

  function sleep(ms) {
    return new Promise((r) => setTimeout(r, ms));
  }

  function buildParams() {
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
    params.set("limit", "500");
    return params;
  }

  function scheduleAutoRefresh() {
    if (autoTimer) {
      clearInterval(autoTimer);
      autoTimer = null;
    }
    autoTimer = setInterval(async () => {
      try {
        const cards = Array.from(document.querySelectorAll(".comment-card"));
        const needIds = [];
        for (const el of cards) {
          const idStr = el.id && el.id.startsWith("comment-") ? el.id.slice("comment-".length) : "";
          const content = el.querySelector(".content");
          if (idStr && content && content.textContent === "Generating…") {
            const idNum = parseInt(idStr, 10);
            if (!Number.isNaN(idNum)) needIds.push(idNum);
          }
        }
        if (!needIds.length) return;
        const r = await fetch(`/miniapp/api/posts?${buildParams().toString()}`);
        const d = await r.json();
        const items = d.items || [];
        const byId = new Map(items.map((x) => [x.id, x]));
        for (const id of needIds) {
          const it = byId.get(id);
          if (it && it.ai_comment) {
            const el = document.getElementById(`comment-${id}`);
            if (el) {
              const t = it.channel_title || it.channel_username || "Channel";
              el.innerHTML = `<div class="title">Comment: ${escapeHtml(t)}</div><div class="content">${escapeHtml(it.ai_comment)}</div>`;
            }
          }
        }
      } catch {}
    }, 2000);
  }

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
    params.set("limit", "500");
    const res = await fetch(`/miniapp/api/posts?${params.toString()}`);
    const data = await res.json();
    const items = data.items || [];
    lastItems = items;
    if (!items.length) {
      listEl.innerHTML = "<p>No posts.</p>";
      return;
    }
    listEl.innerHTML = "";
    for (const it of items) {
      // Row container
      const row = document.createElement("div");
      row.className = "row";
      // Left column: post
      const card = document.createElement("article");
      card.className = "card";
      const title = it.channel_title || it.channel_username || "Channel";
      const link = it.source_url ? `<a href="${it.source_url}" target="_blank">Open</a>` : "";
      const fwdSource = (() => {
        if (!it.forward) return "";
        const u = it.forward.from_username ? `@${it.forward.from_username}` : "";
        const title = it.forward.from_name || it.forward.from_title || "";
        return u || title || (it.forward.from_type || "");
      })();
      const fwdHtml = fwdSource ? 
        `<div class="fwd">Forwarded from ${escapeHtml(fwdSource)}</div>` : "";
      const textHtml = `
        <div class="meta">
          <span class="ch">${title}</span>
          <span class="dt">${new Date(it.date).toLocaleString()}</span>
          ${link}
        </div>
        ${fwdHtml}
        <div class="text">${escapeHtml((it.text || "").slice(0, 800)).replace(/\\n/g, "<br/>")}</div>`;
      card.innerHTML = textHtml;
      if (Array.isArray(it.media) && it.media.length) {
        const gallery = document.createElement("div");
        gallery.className = "gallery";
        for (const m of it.media.slice(0, 4)) {
          if (m.kind === "video") {
            const v = document.createElement("video");
            v.src = m.url;
            v.controls = true;
            v.className = "vd";
            v.preload = "metadata";
            gallery.appendChild(v);
          } else if (m.kind === "gif") {
            const v = document.createElement("video");
            v.src = m.url;
            v.autoplay = true;
            v.loop = true;
            v.muted = true;
            v.playsInline = true;
            v.className = "vd";
            gallery.appendChild(v);
          } else {
            const img = document.createElement("img");
            img.src = m.url;
            img.alt = "photo";
            img.loading = "lazy";
            img.className = "ph";
            gallery.appendChild(img);
          }
        }
        card.appendChild(gallery);
      } else if (Array.isArray(it.media_urls) && it.media_urls.length) {
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
      // Right column: AI comment
      const cc = document.createElement("article");
      cc.className = "comment-card";
      cc.id = `comment-${it.id}`;
      const heading = title ? `Comment: ${escapeHtml(title)}` : "Comment";
      const content = it.ai_comment ? escapeHtml(it.ai_comment) : "Generating…";
      cc.innerHTML = `<div class="title">${heading}</div><div class="content">${content}</div>`;
      row.appendChild(card);
      row.appendChild(cc);
      listEl.appendChild(row);
    }
    scheduleAutoRefresh();
  }

  async function loadChannels() {
    try {
      const prev = channelSelect.value;
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
      // restore previous selection if still available
      if (prev) {
        const found = Array.from(channelSelect.options).some((o) => o.value === prev);
        if (found) channelSelect.value = prev;
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
  window.addEventListener("beforeunload", () => {
    if (autoTimer) {
      clearInterval(autoTimer);
      autoTimer = null;
    }
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
  if (genBtn) {
    genBtn.addEventListener("click", async () => {
      // Generate for ALL visible posts of the current selection (ignore Count)
      const missing = [];
      for (const it of lastItems) {
        if (!it.ai_comment) missing.push(it.id);
      }
      if (!missing.length) return;
      if (genStatus) {
        genStatus.textContent = "Generating… 0/" + missing.length;
        genStatus.className = "status-badge progress";
        genStatus.classList.remove("hidden");
      }
      genBtn.disabled = true;
      const oldLabel = genBtn.textContent;
      genBtn.textContent = `Generating ${missing.length}…`;
      // single request: backend processes sequentially with 1s delay per item
      const selVal = channelSelect.value ? channelSelect.value.trim() : "";
      const u2 = userFilter.value.trim();
      const body = { message_ids: missing };
      if (selVal) {
        if (selVal.startsWith("@")) body.username = selVal.slice(1);
        else body.channel_id = /^\d+$/.test(selVal) ? Number(selVal) : undefined;
      } else if (u2) {
        body.username = u2.startsWith("@") ? u2.slice(1) : u2;
      }
      try {
        await fetch(`/miniapp/api/comments/generate`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
      } catch {}
      // poll updates up to ~10s
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
      params.set("limit", "500");
      let remaining = missing.length;
      // estimate rounds based on ~1s per item; each round = 1.5s
      const maxRounds = Math.min(60, Math.ceil((missing.length * 1.2 + 5) / 1.5));
      for (let round = 0; round < maxRounds; round++) {
        await sleep(1500);
        const r = await fetch(`/miniapp/api/posts?${params.toString()}`);
        const d = await r.json();
        const items2 = d.items || [];
        const byId = new Map(items2.map((x) => [x.id, x]));
        remaining = 0;
        for (const id of missing) {
          const it2 = byId.get(id);
          if (it2 && it2.ai_comment) {
            const el = document.getElementById(`comment-${id}`);
            if (el) {
              const t = it2.channel_title || it2.channel_username || "Channel";
              el.innerHTML = `<div class="title">Comment: ${escapeHtml(t)}</div><div class="content">${escapeHtml(it2.ai_comment)}</div>`;
            }
          } else {
            remaining++;
          }
        }
        if (genStatus) {
          const done = missing.length - remaining;
          genStatus.textContent = `Generating… ${done}/${missing.length}`;
        }
        if (!remaining) break;
      }
      genBtn.disabled = false;
      genBtn.textContent = oldLabel;
      if (genStatus) {
        if (remaining === 0) {
          genStatus.textContent = `✓ Done (${missing.length}/${missing.length})`;
          genStatus.className = "status-badge";
        } else if (remaining < missing.length) {
          const done = missing.length - remaining;
          genStatus.textContent = `Partial: ${done}/${missing.length}`;
          genStatus.className = "status-badge progress";
        } else {
          genStatus.textContent = "No changes";
          genStatus.className = "status-badge error";
        }
      }
    });
  }
  if (clearBtn) {
    clearBtn.addEventListener("click", async () => {
      const selVal = channelSelect.value ? channelSelect.value.trim() : "";
      const u = userFilter.value.trim();
      const scope = {};
      if (selVal) {
        if (selVal.startsWith("@")) scope.username = selVal.slice(1);
        else scope.channel_id = /^\d+$/.test(selVal) ? Number(selVal) : undefined;
      } else if (u) {
        scope.username = u.startsWith("@") ? u.slice(1) : u;
      }
      const confirmText = scope.username || scope.channel_id
        ? "Delete comments only for the selected channel/user?"
        : "Delete ALL generated comments?";
      if (!confirm(confirmText)) return;
      try {
        await fetch(`/miniapp/api/comments`, {
          method: "DELETE",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(scope),
        });
        // after deletion, refresh list
        await load();
        if (genStatus) {
          genStatus.textContent = "✓ Cleared";
          genStatus.className = "status-badge";
          genStatus.classList.remove("hidden");
        }
      } catch (e) {
        if (genStatus) {
          genStatus.textContent = "Error clearing";
          genStatus.className = "status-badge error";
          genStatus.classList.remove("hidden");
        }
        console.error(e);
      }
    });
  }
  ingestBtn.addEventListener("click", async () => {
    const sel = channelSelect.value.trim() || userFilter.value.trim();
    if (!sel) {
      alert("Select a channel or enter @username");
      return;
    }
    const cnt = Math.max(1, Math.min(2000, parseInt(genCount?.value || "50", 10) || 50));
    ingestBtn.disabled = true;
    ingestBtn.textContent = "Ingesting…";
    try {
      const body = { channel: sel, limit: cnt, force_media: true };
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
  if (refreshChannelsBtn) {
    refreshChannelsBtn.addEventListener("click", async () => {
      refreshChannelsBtn.disabled = true;
      const oldText = refreshChannelsBtn.textContent;
      refreshChannelsBtn.textContent = "Refreshing…";
      try {
        await loadChannels();
        await load(); // reload posts for newly selected/available channel
      } catch (e) {
        console.error(e);
      } finally {
        refreshChannelsBtn.disabled = false;
        refreshChannelsBtn.textContent = oldText;
      }
    });
  }
  loadChannels().then(load);
})();


