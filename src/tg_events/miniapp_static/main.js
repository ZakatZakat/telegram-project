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

  function hashToHue(s) {
    let h = 0;
    for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
    return h % 360;
  }

  function styleForUserTag(label) {
    const h = hashToHue(label || "");
    const color = `hsl(${h} 70% 55%)`;
    const border = `hsla(${h}, 70%, 55%, 0.35)`;
    return `color:${color};border-color:${border}`;
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
    for (let i = 0; i < items.length; i++) {
      const it = items[i];
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
      const fwdUsername = it.forward?.from_username ? `@${it.forward.from_username}` : (it.forward?.from_name || "");
      // For header badge show ANY forward source label (channel or user)
      const sourceLabel = fwdUsername || fwdSource || "";
      const userBadge = sourceLabel
        ? `<span class="badge user" style="${styleForUserTag(sourceLabel)}">${escapeHtml(sourceLabel)}</span>`
        : "";
      const fwdHtml = fwdSource ? 
        `<div class="fwd"><span class="fwd-label">Forwarded from ${escapeHtml(fwdSource)}</span></div>` : "";
      const textHtml = `
        <div class="meta">
          <div class="left">
            <span class="num">${String(i + 1)}.</span>
            <span class="ch">${title}</span>
          </div>
          <div class="right">
            <span class="dt">${new Date(it.date).toLocaleString()}</span>
            ${link}
            ${userBadge}
          </div>
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
      const heading = title ? `<span class="num">${String(i + 1)}.</span> Comment: ${escapeHtml(title)}` : `<span class="num">${String(i + 1)}.</span> Comment`;
      const content = it.ai_comment ? escapeHtml(it.ai_comment) : "Generating…";
      cc.innerHTML = `<div class="title">${heading} <button class="action fix-comment" data-id="${it.id}">Fix</button> <button class="action del-comment" data-id="${it.id}">Delete</button></div><div class="content">${content}</div>`;
      // add delete post button into header right
      const right = card.querySelector(".meta .right");
      if (right) {
        const btn = document.createElement("button");
        btn.className = "action danger del";
        btn.dataset.id = String(it.id);
        btn.textContent = "Delete";
        right.appendChild(btn);
      }
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
  // Delegated handlers for delete actions
  listEl.addEventListener("click", async (e) => {
    const t = e.target;
    if (!(t instanceof Element)) return;
    if (t.classList.contains("del")) {
      const id = Number(t.dataset.id || "0");
      if (!id) return;
      try {
        const r = await fetch(`/miniapp/api/posts`, {
          method: "DELETE",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message_ids: [id], delete_media: true }),
        });
        if (!r.ok) {
          console.error("Delete post failed", await r.text());
          return;
        }
        const row = t.closest(".row");
        if (row) row.remove();
        // remove from lastItems and renumber
        lastItems = lastItems.filter((x) => x.id !== id);
        renumberRows();
      } catch (err) {
        console.error(err);
      }
    }
    if (t.classList.contains("del-comment")) {
      const id = Number(t.dataset.id || "0");
      if (!id) return;
      try {
        const r = await fetch(`/miniapp/api/comments`, {
          method: "DELETE",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message_ids: [id] }),
        });
        if (!r.ok) {
          console.error("Delete comment failed", await r.text());
          return;
        }
        const el = document.getElementById(`comment-${id}`);
        if (el) {
          const titleEl = el.querySelector(".title");
          const contentEl = el.querySelector(".content");
          if (contentEl) contentEl.textContent = "Generating…";
          // also reset in lastItems
          for (const it of lastItems) {
            if (it.id === id) {
              it.ai_comment = null;
              break;
            }
          }
        }
      } catch (err) {
        console.error(err);
      }
    }
    if (t.classList.contains("fix-comment")) {
      const id = Number(t.dataset.id || "0");
      if (!id) return;
      const el = document.getElementById(`comment-${id}`);
      if (!el) return;
      const contentEl = el.querySelector(".content");
      if (!contentEl) return;
      // if already editing, ignore
      if (el.querySelector("textarea.edit")) return;
      const orig = contentEl.textContent || "";
      const ta = document.createElement("textarea");
      ta.className = "edit";
      ta.style.width = "100%";
      ta.style.minHeight = "80px";
      ta.value = orig;
      const save = document.createElement("button");
      save.className = "action";
      save.textContent = "Save";
      const cancel = document.createElement("button");
      cancel.className = "action";
      cancel.textContent = "Cancel";
      const actions = document.createElement("div");
      actions.style.marginTop = "6px";
      actions.appendChild(save);
      actions.appendChild(cancel);
      contentEl.replaceWith(ta);
      el.appendChild(actions);
      cancel.addEventListener("click", () => {
        ta.replaceWith(contentEl);
        actions.remove();
      });
      save.addEventListener("click", async () => {
        const text = ta.value.trim();
        try {
          await fetch(`/miniapp/api/comments`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ message_id: id, text }),
          });
          // update UI
          const newDiv = document.createElement("div");
          newDiv.className = "content";
          newDiv.textContent = text || " ";
          ta.replaceWith(newDiv);
          actions.remove();
          for (const it of lastItems) {
            if (it.id === id) {
              it.ai_comment = text;
              break;
            }
          }
        } catch (err) {
          console.error(err);
        }
      });
    }
  });

  function renumberRows() {
    const rows = Array.from(document.querySelectorAll(".row"));
    rows.forEach((row, idx) => {
      const n = String(idx + 1) + ".";
      const leftNum = row.querySelector(".meta .left .num");
      if (leftNum) leftNum.textContent = n;
      const rightNum = row.querySelector(".comment-card .title .num");
      if (rightNum) rightNum.textContent = n;
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


