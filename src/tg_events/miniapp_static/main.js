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
  const deletePostsBtn = document.getElementById("deletePostsBtn");
  const pickerEl = document.getElementById("picker");
  const backBtn = document.getElementById("backBtn");
  const topicsEl = document.getElementById("topics");
  const boardEl = document.getElementById("board");
  let lastItems = [];
  let autoTimer = null;
  let channelsCache = [];
  let topicsBoardListenerAttached = false;
  // topic name -> id index from server
  const topicIndex = new Map();
  const topicMembership = new Map();

  function rebuildTopicMembershipIndex(source) {
    topicMembership.clear();
    if (source && typeof source === "object") {
      for (const [name, payload] of Object.entries(source)) {
        // merge ids from resolved message_ids and from snapshots carrying legacy message_id
        const mergedIds = [];
        if (Array.isArray(payload?.ids)) mergedIds.push(...payload.ids);
        if (Array.isArray(payload?.snapshots)) {
          for (const snap of payload.snapshots) {
            if (snap && typeof snap === "object" && snap.message_id != null) {
              mergedIds.push(snap.message_id);
            }
          }
        }
        for (const rawId of mergedIds) {
          const id = Number(rawId);
          if (!Number.isFinite(id)) continue;
          const bucket = topicMembership.get(id) || [];
          if (!bucket.includes(name)) {
            bucket.push(name);
          }
          topicMembership.set(id, bucket);
        }
      }
    }
    refreshAllVisibleTopicBadges();
  }

  function addTopicMembershipEntry(messageId, topicName) {
    const id = Number(messageId);
    if (!Number.isFinite(id) || !topicName) return;
    const list = topicMembership.get(id) || [];
    if (!list.includes(topicName)) {
      list.push(topicName);
      topicMembership.set(id, list);
    }
    refreshTopicBadgesForMessage(id);
  }

  function removeTopicMembershipEntry(messageId, topicName) {
    const id = Number(messageId);
    if (!Number.isFinite(id) || !topicName) return;
    const list = topicMembership.get(id);
    if (!list) return;
    const next = list.filter((name) => name !== topicName);
    if (next.length) {
      topicMembership.set(id, next);
    } else {
      topicMembership.delete(id);
    }
    refreshTopicBadgesForMessage(id);
  }

  function removeTopicFromAllTopics(topicName) {
    if (!topicName) return;
    const affected = [];
    topicMembership.forEach((names, id) => {
      const idx = names.indexOf(topicName);
      if (idx >= 0) {
        names.splice(idx, 1);
        if (!names.length) {
          topicMembership.delete(id);
        }
        affected.push(id);
      }
    });
    affected.forEach((id) => refreshTopicBadgesForMessage(id));
  }

  function hydrateTopicBadgeElement(el, messageId) {
    const names = topicMembership.get(Number(messageId)) || [];
    if (!names.length) {
      el.innerHTML = "";
      el.classList.add("hidden");
      return;
    }
    el.innerHTML = names.map((name) => `<span class="badge topic">${escapeHtml(name)}</span>`).join("");
    el.classList.remove("hidden");
  }

  function refreshTopicBadgesForMessage(messageId) {
    const row = document.querySelector(`.row[data-id="${messageId}"]`);
    if (!row) return;
    const box = row.querySelector(".topic-tags");
    if (box) hydrateTopicBadgeElement(box, messageId);
  }

  function refreshAllVisibleTopicBadges() {
    const rows = document.querySelectorAll(".row[data-id]");
    rows.forEach((row) => {
      const id = Number(row.dataset.id);
      if (!Number.isFinite(id)) return;
      const box = row.querySelector(".topic-tags");
      if (box) hydrateTopicBadgeElement(box, id);
    });
  }

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
    const fwdEl = document.getElementById("fwdSelect") || document.getElementById("fwdFilter");
    const fwd = fwdEl && "value" in fwdEl ? (fwdEl.value || "") : "";
    if (fwd) params.set("fwd_username", fwd.startsWith("@") ? fwd.slice(1) : fwd);
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
          if (idStr && content && content.textContent === "Комментарий отсутствует") {
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

  async function fetchTopicsFromServer() {
    try {
      const r = await fetch(`/miniapp/api/topics`);
      const d = await r.json();
      const out = {};
      topicIndex.clear();
      const items = Array.isArray(d.items) ? d.items : [];
      for (const t of items) {
        const name = t.name || "";
        const id = t.id;
        if (name && id) topicIndex.set(name, id);
        out[name] = {
          ids: Array.isArray(t.message_ids) ? t.message_ids : [],
          snapshots: Array.isArray(t.items) ? t.items : [],
        };
      }
      rebuildTopicMembershipIndex(out);
      return out;
    } catch {
      topicIndex.clear();
      topicMembership.clear();
      refreshAllVisibleTopicBadges();
      return {};
    }
  }
  async function apiCreateTopic(name) {
    const r = await fetch(`/miniapp/api/topics`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
    const d = await r.json().catch(() => ({}));
    if (d && d.id) topicIndex.set(name, d.id);
  }
  async function apiDeleteTopic(name) {
    const id = topicIndex.get(name);
    if (!id) return;
    await fetch(`/miniapp/api/topics/${id}`, { method: "DELETE" });
    topicIndex.delete(name);
  }
  async function apiAddToTopic(name, messageId) {
    const id = topicIndex.get(name);
    if (!id) return false;
    const resp = await fetch(`/miniapp/api/topics/add`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ topic_id: id, message_id: messageId }),
    });
    return resp.ok;
  }

  async function renderTopicsSidebar(preloadedData) {
    if (!topicsEl) return;
    topicsEl.classList.remove("hidden");
    const data = preloadedData || (await fetchTopicsFromServer());
    topicsEl.innerHTML = `
      <h3>Topics</h3>
      <div style="display:flex; gap:6px; margin-bottom:8px">
        <input id="newTopic" placeholder="Add topic" style="flex:1; padding:6px 8px; border:1px solid var(--border); border-radius:8px; background:var(--card); color:var(--fg)"/>
        <button id="addTopicBtn" class="action">Add</button>
      </div>
      <div id="topicsList"></div>
    `;
    const list = topicsEl.querySelector("#topicsList");
    const keys = Object.keys(data);
    if (keys.length === 0) list.innerHTML = `<div class="subtitle">Drag posts here</div>`;
    keys.forEach((name) => {
      const t = document.createElement("div");
      t.className = "topic";
      t.innerHTML = `<header><span>${escapeHtml(name)}</span><button class="action" data-rm="${escapeHtml(name)}">Remove</button></header><div class="bucket" data-topic="${escapeHtml(name)}"></div>`;
      list.appendChild(t);
      const bucket = t.querySelector(".bucket");
      // cache numeric topic id on bucket to avoid map misses
      const tid = topicIndex.get(name);
      if (tid) bucket.dataset.topicId = String(tid);
      const topicEntry = data[name] || { ids: [], snapshots: [] };
      const ids = Array.isArray(topicEntry.ids) ? topicEntry.ids : [];
      const snapshots = Array.isArray(topicEntry.snapshots) ? topicEntry.snapshots : [];
      const snapByMessageId = new Map();
      snapshots.forEach((snap) => {
        if (snap && typeof snap === "object" && snap.message_id != null) {
          snapByMessageId.set(snap.message_id, snap);
        }
      });
      for (const id of ids) {
        const snap = snapByMessageId.get(id);
        const mini = buildMiniCard(id) || buildMiniPlaceholder(id);
        if (mini) {
          const wrap = createTopicMiniWrap(mini, {
            messageId: id,
            msgId: snap?.msg_id ?? null,
            channelTgId: snap?.channel_tg_id ?? null,
            topicItemId: snap?.id ?? null,
            topicName: name,
          });
          bucket.appendChild(wrap);
        }
      }
      // dnd events
      bucket.addEventListener("dragover", (e) => { e.preventDefault(); bucket.classList.add("drop-hover"); });
      bucket.addEventListener("dragleave", () => bucket.classList.remove("drop-hover"));
      bucket.addEventListener("drop", async (e) => {
        e.preventDefault(); bucket.classList.remove("drop-hover");
        const idStr = e.dataTransfer.getData("text/plain");
        const id = Number(idStr || "0"); if (!id) return;
        const c = document.getElementById(`comment-${id}`);
        const contentText = (c && c.querySelector(".content")) ? (c.querySelector(".content").textContent || "") : "";
        // also look at model state (DOM may be out-of-sync)
        const item = lastItems.find((x) => x.id === id);
        const hasCommentModel = !!(item && item.ai_comment && String(item.ai_comment).trim().length > 0);
        // snapshot: combine main + preceding 👆 text and include comment
        let postText = "";
        let stableChannel = null;
        let stableMsg = null;
        const idx = lastItems.findIndex((x) => x.id === id);
        let addOk = false;
        if (idx >= 0) {
          const it = lastItems[idx];
          let extra = "";
          if (idx - 1 >= 0) {
            const prev = lastItems[idx - 1];
            const prevIsUp = typeof prev.text === "string" && prev.text.trim().startsWith("👆");
            if (prevIsUp) extra = prev.text || "";
          }
          postText = extra ? `${it.text || ""}\\n\\n${extra}` : (it.text || "");
          stableChannel = it.channel_tg_id || null;
          stableMsg = it.msg_id || null;
          const cmText = hasCommentModel ? String(item.ai_comment) : contentText;
          const commentText = cmText === "Комментарий отсутствует" ? null : cmText;
          const sourceUrl = it.source_url || null;
          const channelUsername = it.channel_username || null;
          try {
            const resp = await fetch(`/miniapp/api/topics/add`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                topic_id: Number(bucket.dataset.topicId || topicIndex.get(name) || 0),
                message_id: id,
                channel_tg_id: stableChannel,
                msg_id: stableMsg,
                post_text: postText,
                comment_text: commentText,
                channel_username: channelUsername,
                source_url: sourceUrl,
              }),
            });
            addOk = resp.ok;
          } catch {
            addOk = false;
          }
        } else {
          addOk = await apiAddToTopic(name, id);
        }
        if (!addOk) return;
        addTopicMembershipEntry(id, name);
        const mini = buildMiniCard(id) || buildMiniPlaceholder(id);
        if (mini) {
          const wrap = createTopicMiniWrap(mini, {
            messageId: id,
            msgId: stableMsg,
            channelTgId: stableChannel,
            topicItemId: null,
            topicName: name,
          });
          bucket.appendChild(wrap);
        }
      });
      // click handlers inside bucket (remove post from topic)
      bucket.addEventListener("click", async (e) => {
        const target = e.target;
        if (!(target instanceof Element)) return;
        if (target.classList.contains("mini-rm")) {
          const id = Number(target.dataset.id || "0");
          const topicId = Number(bucket.dataset.topicId || "0");
          if (!id || !topicId) return;
          const topicItemId = target.dataset.topicItemId ? Number(target.dataset.topicItemId) : null;
          let channelTgId = target.dataset.channelTgId ? Number(target.dataset.channelTgId) : null;
          let msgId = target.dataset.msgId ? Number(target.dataset.msgId) : null;
          try {
            const resp = await fetch(`/miniapp/api/topics/remove`, {
              method: "DELETE",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                topic_id: topicId,
                message_id: id,
                channel_tg_id: channelTgId,
                msg_id: msgId,
                topic_item_id: topicItemId,
              }),
            });
            if (!resp.ok) return;
            const wrap = target.closest(".mini-wrap");
            if (wrap) wrap.remove();
            removeTopicMembershipEntry(id, name);
            // notify other parts (e.g., Topics board) to refresh
            window.dispatchEvent(new CustomEvent("topics:changed"));
          } catch {}
        }
      });
      // remove topic
      t.querySelector("button[data-rm]").addEventListener("click", async () => {
        await apiDeleteTopic(name);
        removeTopicFromAllTopics(name);
        await renderTopicsSidebar();
      });
    });
    const addBtn = topicsEl.querySelector("#addTopicBtn");
    const inp = topicsEl.querySelector("#newTopic");
    if (addBtn && inp) {
      const add = async () => {
        const name = (inp.value || "").trim(); if (!name) return;
        await apiCreateTopic(name);
        inp.value = "";
        await renderTopicsSidebar();
      };
      addBtn.addEventListener("click", add);
      inp.addEventListener("keydown", (e) => { if (e.key === "Enter") add(); });
    }
    return data;
  }
  function buildMiniCard(id) {
    // find in lastItems
    const it = lastItems.find((x) => x.id === id);
    const c = document.getElementById(`comment-${id}`);
    const cm = c && c.querySelector(".content") ? c.querySelector(".content").textContent || "" : "";
    if (!it) return null;
    const el = document.createElement("div");
    el.className = "mini";
    const title = it.channel_title || it.channel_username || "Channel";
    const text = (it.text || "").split("\n")[0].slice(0, 140);
    el.innerHTML = `<div class="tx"><strong>${escapeHtml(title)}</strong>: ${escapeHtml(text)}</div>${cm ? `<div class="cm">${escapeHtml(cm.slice(0, 160))}</div>` : ""}`;
    return el;
  }
  function buildMiniPlaceholder(id) {
    const el = document.createElement("div");
    el.className = "mini";
    el.innerHTML = `<div class="tx"><strong>Post</strong> #${id}</div>`;
    return el;
  }
  function createTopicMiniWrap(miniEl, options) {
    const wrap = document.createElement("div");
    wrap.className = "mini-wrap";
    wrap.dataset.id = String(options.messageId);
    if (options.msgId != null) wrap.dataset.msgId = String(options.msgId);
    if (options.channelTgId != null) wrap.dataset.channelTgId = String(options.channelTgId);
    if (options.topicItemId != null) wrap.dataset.topicItemId = String(options.topicItemId);
    wrap.appendChild(miniEl);
    const btn = document.createElement("button");
    btn.className = "mini-rm";
    btn.textContent = "×";
    btn.title = "Remove from topic";
    btn.dataset.id = String(options.messageId);
    if (options.msgId != null) btn.dataset.msgId = String(options.msgId);
    if (options.channelTgId != null) btn.dataset.channelTgId = String(options.channelTgId);
    if (options.topicItemId != null) btn.dataset.topicItemId = String(options.topicItemId);
    if (options.topicName) btn.dataset.topicName = options.topicName;
    wrap.appendChild(btn);
    return wrap;
  }

  async function load() {
    if (pickerEl) pickerEl.classList.add("hidden");
    listEl.classList.remove("hidden");
    if (boardEl) { boardEl.classList.add("hidden"); boardEl.style.display = "none"; }
    listEl.innerHTML = "Loading...";
    const res = await fetch(`/miniapp/api/posts?${buildParams().toString()}`);
    const data = await res.json();
    const items = data.items || [];
    lastItems = items;
    const topicsData = await fetchTopicsFromServer();
    if (!items.length) {
      listEl.innerHTML = "<p>No posts.</p>";
      await renderTopicsSidebar(topicsData);
      return;
    }
    listEl.innerHTML = "";
    const rendered = new Set();
    for (let i = 0; i < items.length; i++) {
      if (rendered.has(i)) continue;
      const curr = items[i];
      const isUp = typeof curr.text === "string" && curr.text.trim().startsWith("👆");
      // Make draggable
      // Do not allow dragging child rows themselves; drag the main card only
      const dragAllowed = !isUp;
      // If current is an 'up' comment and the next item exists and is NOT an 'up' comment,
      // skip now; it will be rendered as a child of the next main post.
      if (isUp && i + 1 < items.length) {
        const nextIsUp = typeof items[i + 1].text === "string" && items[i + 1].text.trim().startsWith("👆");
        if (!nextIsUp) continue;
      }
      // Determine main item index to render now
      let mainIdx = i;
      let childIdx = -1;
      if (!isUp) {
        if (i - 1 >= 0) {
          const prev = items[i - 1];
          const prevIsUp = typeof prev.text === "string" && prev.text.trim().startsWith("👆");
          if (prevIsUp && !rendered.has(i - 1)) childIdx = i - 1;
        }
      } else {
        childIdx = i;
        mainIdx = i;
      }
      function buildRow(it, displayIndex, asChild) {
        const row = document.createElement("div");
        row.className = asChild ? "row child" : "row";
        if (!asChild) {
          row.setAttribute("draggable", "true");
          row.dataset.id = String(it.id);
          row.addEventListener("dragstart", (e) => {
            e.dataTransfer.setData("text/plain", String(it.id));
          });
        }
        const card = document.createElement("article");
        card.className = "card";
        if (!asChild) {
          card.setAttribute("draggable", "true");
          card.addEventListener("dragstart", (e) => {
            e.dataTransfer.setData("text/plain", String(it.id));
          });
        }
        const title = it.channel_title || it.channel_username || "Channel";
        const link = it.source_url ? `<a href="${it.source_url}" target="_blank">Open</a>` : "";
        const fwdSource = (() => {
          if (!it.forward) return "";
          const u = it.forward.from_username ? `@${it.forward.from_username}` : "";
          const title = it.forward.from_name || it.forward.from_title || "";
          return u || title || (it.forward.from_type || "");
        })();
        const fwdUsername = it.forward?.from_username ? `@${it.forward.from_username}` : (it.forward?.from_name || "");
        const sourceLabel = fwdUsername || fwdSource || "";
        const userBadge = sourceLabel ? `<span class="badge user" style="${styleForUserTag(sourceLabel)}">${escapeHtml(sourceLabel)}</span>` : "";
        const fwdHtml = fwdSource ? `<div class="fwd"><span class="fwd-label">Forwarded from ${escapeHtml(fwdSource)}</span></div>` : "";
        const textHtml = `
          <div class="meta">
            <div class="left">
              <span class="num">${String(displayIndex + 1)}.</span>
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
        if (!asChild) {
          const topicBadgeBox = document.createElement("div");
          topicBadgeBox.className = "topic-tags hidden";
          topicBadgeBox.dataset.messageId = String(it.id);
          hydrateTopicBadgeElement(topicBadgeBox, it.id);
          // place badges inline in meta, right after number and channel name
          const leftMeta = card.querySelector(".meta .left");
          if (leftMeta) {
            leftMeta.appendChild(topicBadgeBox);
          } else {
            // fallback (should not happen)
            card.appendChild(topicBadgeBox);
          }
        }
        // media
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
        row.appendChild(card);
        if (!asChild) {
          const cc = document.createElement("article");
          cc.className = "comment-card";
          cc.id = `comment-${it.id}`;
          const heading = title ? `<span class="num">${String(displayIndex + 1)}.</span> Comment: ${escapeHtml(title)}` : `<span class="num">${String(displayIndex + 1)}.</span> Comment`;
          const content = it.ai_comment ? escapeHtml(it.ai_comment) : "Комментарий отсутствует";
          cc.innerHTML = `<div class="title">${heading} <button class="action fix-comment" data-id="${it.id}">Fix</button> <button class="action del-comment" data-id="${it.id}">Delete</button></div><div class="content">${content}</div>`;
          row.appendChild(cc);
        }
        return row;
      }
      // Render main row
      const mainRow = buildRow(items[mainIdx], mainIdx, false);
      listEl.appendChild(mainRow);
      rendered.add(mainIdx);
      if (childIdx >= 0 && childIdx !== mainIdx) {
        const childRow = buildRow(items[childIdx], childIdx, true);
        mainRow.insertAdjacentElement("afterend", childRow);
        rendered.add(childIdx);
      }
    }
    scheduleAutoRefresh();
    await renderTopicsSidebar(topicsData);
  }

  function renderPicker(items) {
    channelsCache = items || [];
    if (!pickerEl) return;
    pickerEl.innerHTML = `
      <div class="tile picker-card">
        <div class="title"><span>Select a channel or user</span></div>
        <div class="subtitle" style="margin:6px 0 10px">Choose a dialog to view posts</div>
        <div id="pickerControls"></div>
      </div>
      <div class="tile tool-card">
        <div class="title"><span>Tools</span></div>
        <div class="toolbar">
          <select id="fwdSelect" style="flex:1; min-width:240px; padding:8px 10px; border:1px solid var(--border); border-radius:8px; background:var(--card); color: var(--fg);">
            <option value="">All forwards</option>
          </select>
          <button id="clearFwdFilter" class="action">Clear</button>
          <button id="editPromptBtn" class="action">Edit prompt</button>
        </div>
      </div>`;
    // render board (topics only) below picker into dedicated section
    if (boardEl) {
      boardEl.innerHTML = `
      <div class="tile compact" id="topicsBoard">
        <div class="title"><span>Topics board</span></div>
        <div id="topicsBoardInner" style="display:grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap:10px;"></div>
      </div>`;
      boardEl.classList.remove("hidden");
      boardEl.style.display = "";
    }
    pickerEl.insertAdjacentHTML("beforeend", `
      <div id="promptModal" class="modal">
        <div class="panel">
          <h3>Edit comment prompt</h3>
          <div class="subtitle" style="margin-bottom:6px">Шаблон поддерживает плейсхолдер {post}</div>
          <textarea id="promptText"></textarea>
          <div class="actions">
            <button id="promptCancel" class="action">Cancel</button>
            <button id="promptSave" class="action">Save</button>
          </div>
        </div>
      </div>`);
    pickerEl.classList.remove("hidden");
    listEl.classList.add("hidden");
    if (boardEl) { boardEl.classList.remove("hidden"); boardEl.style.display = ""; }
    const holder = document.getElementById("pickerControls");
    const bar = document.getElementById("controlsBar");
    if (holder && bar) holder.appendChild(bar);
    // ensure Stop button exists in controls bar (next to Generate)
    if (bar && !document.getElementById("stopGenBtn")) {
      const btn = document.createElement("button");
      btn.id = "stopGenBtn";
      btn.className = "action hidden";
      btn.textContent = "Stop";
      bar.appendChild(btn);
    }
    const clearBtnF = document.getElementById("clearFwdFilter");
    const fwdSel = document.getElementById("fwdSelect");
    const stopBtn = document.getElementById("stopGenBtn");
    const editPromptBtn = document.getElementById("editPromptBtn");
    const modal = document.getElementById("promptModal");
    const promptText = document.getElementById("promptText");
    const promptCancel = document.getElementById("promptCancel");
    const promptSave = document.getElementById("promptSave");

    async function loadForwardSenders() {
      const params = new URLSearchParams();
      const selected = channelSelect.value ? channelSelect.value.trim() : "";
      if (selected) {
        if (selected.startsWith("@")) {
          params.set("username", selected.slice(1));
        } else if (/^\d+$/.test(selected)) {
          params.set("channel_id", selected);
        }
      }
      try {
        const r = await fetch(`/miniapp/api/forwards?${params.toString()}`);
        const d = await r.json();
        const items = Array.isArray(d.items) ? d.items : [];
        if (fwdSel) {
          fwdSel.innerHTML =
            `<option value="">All forwards</option>` +
            items
              .map((it) => {
                const v = it.username ? `@${it.username}` : "";
                return v ? `<option value="${v}">${v}</option>` : "";
              })
              .join("");
        }
      } catch (err) {
        console.error("loadForwardSenders failed", err);
        if (fwdSel) {
          fwdSel.innerHTML = `<option value="">All forwards</option>`;
        }
      }
    }

    async function loadTopicsBoard() {
      const r = await fetch(`/miniapp/api/topics`);
      const d = await r.json();
      const inner = document.getElementById("topicsBoardInner");
      inner.innerHTML = "";
      const items = Array.isArray(d.items) ? d.items : [];
      for (const t of items) {
        const col = document.createElement("div");
        col.className = "card topic-card";
        const head = document.createElement("div");
        head.className = "topic-title";
        head.textContent = t.name;
        col.appendChild(head);
        const bucket = document.createElement("div");
        bucket.className = "mini-grid";
        for (const it of (t.items || [])) {
          const mini = document.createElement("div");
          mini.className = "mini";
          const postFull = (it.post_text || "");
          const shortText = postFull.length > 220 ? (postFull.slice(0, 220) + "…") : postFull;
          const shortHtml = escapeHtml(shortText).replace(/\n/g, "<br/>");
          const cmHtml = (it.comment_text && String(it.comment_text).trim().length > 0) ? escapeHtml(it.comment_text).replace(/\n/g, "<br/>") : "Комментарий отсутствует";
          mini.innerHTML = `<div class=\"tx\" style=\"font-size:12px\">${shortHtml}</div><div class=\"cm\" style=\"font-size:11px;color:var(--muted)\">${cmHtml}</div>`;
          // store snapshot
          mini.dataset.snapshot = JSON.stringify({
            channel_tg_id: it.channel_tg_id || null,
            msg_id: it.msg_id || null,
            post_text: it.post_text || "",
            comment_text: it.comment_text || null,
            channel_username: it.channel_username || null,
            source_url: it.source_url || null,
          });
          if (postFull.length > 220) {
            mini.dataset.fullPost = postFull;
            mini.dataset.shortPost = shortText;
            const actions = document.createElement("div");
            actions.className = "mini-actions";
            const btn = document.createElement("button");
            btn.className = "action sm toggle";
            btn.textContent = "Expand";
            btn.addEventListener("click", (e) => {
              e.stopPropagation();
              const tx = mini.querySelector(".tx");
              const expanded = mini.classList.toggle("expanded");
              if (tx) {
                if (expanded) {
                  tx.innerHTML = escapeHtml(mini.dataset.fullPost || "").replace(/\n/g, "<br/>");
                  btn.textContent = "Collapse";
                } else {
                  tx.innerHTML = escapeHtml(mini.dataset.shortPost || "").replace(/\n/g, "<br/>");
                  btn.textContent = "Expand";
                }
              }
            });
            actions.appendChild(btn);
            mini.appendChild(actions);
          }
          bucket.appendChild(mini);
        }
        col.appendChild(bucket);
        inner.appendChild(col);
      }
      // no actions in board for now
    }

    loadForwardSenders().catch(()=>{});
    loadTopicsBoard().catch(()=>{});
    if (!topicsBoardListenerAttached) {
      window.addEventListener("topics:changed", () => {
        loadTopicsBoard().catch(()=>{});
      });
      topicsBoardListenerAttached = true;
    }

    clearBtnF && clearBtnF.addEventListener("click", () => { if (fwdSel && "value" in fwdSel) fwdSel.value = ""; pickerEl.classList.add("hidden"); listEl.classList.remove("hidden"); if (boardEl) { boardEl.classList.add("hidden"); boardEl.style.display = "none"; } load(); });
    if (fwdSel) fwdSel.addEventListener("change", () => { pickerEl.classList.add("hidden"); listEl.classList.remove("hidden"); if (boardEl) { boardEl.classList.add("hidden"); boardEl.style.display = "none"; } load(); });

    if (editPromptBtn && modal && promptText && promptCancel && promptSave) {
      editPromptBtn.addEventListener("click", async () => {
        try { const r = await fetch(`/miniapp/api/prompt`); const d = await r.json(); promptText.value = d.template || ""; } catch {}
        modal.style.display = "flex";
      });
      promptCancel.addEventListener("click", () => { modal.style.display = "none"; });
      promptSave.addEventListener("click", async () => {
        try { const tmpl = promptText.value || ""; await fetch(`/miniapp/api/prompt`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ template: tmpl }) }); } catch {}
        modal.style.display = "none";
      });
      modal.addEventListener("click", (e) => { if (e.target === modal) modal.style.display = "none"; });
      document.addEventListener("keydown", (e) => { if (e.key === "Escape") modal.style.display = "none"; });
    }

    // Projects block removed for now

    channelSelect.addEventListener("change", () => loadForwardSenders().catch(() => {}));
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
      renderPicker(items);
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
    // switch to posts view immediately
    const pickerEl = document.getElementById("picker");
    if (pickerEl) pickerEl.classList.add("hidden");
    listEl.classList.remove("hidden");
    if (boardEl) { boardEl.classList.add("hidden"); boardEl.style.display = "none"; }
    load();
  });
  window.addEventListener("beforeunload", () => {
    if (autoTimer) {
      clearInterval(autoTimer);
      autoTimer = null;
    }
  });
  if (backBtn) {
    backBtn.addEventListener("click", () => {
      if (pickerEl) pickerEl.classList.remove("hidden");
      listEl.classList.add("hidden");
      if (boardEl) boardEl.classList.remove("hidden");
      if (!channelsCache.length) loadChannels();
    });
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
  if (genBtn) {
    genBtn.addEventListener("click", async () => {
      // Build list of main items and overrides (prepend child text if exists)
      const overrides = [];
      for (let i = 0; i < lastItems.length; i++) {
        const it = lastItems[i];
        const isUp = typeof it.text === "string" && it.text.trim().startsWith("👆");
        if (!isUp) {
          // check child at i-1
          let extra = "";
          if (i - 1 >= 0) {
            const prev = lastItems[i - 1];
            const prevIsUp = typeof prev.text === "string" && prev.text.trim().startsWith("👆");
            if (prevIsUp) extra = prev.text || "";
          }
          // always generate for main posts (even if ai_comment exists), skipping only 👆 items
          const combined = extra ? `${it.text || ""}\n\n${extra}` : (it.text || "");
          overrides.push({ message_id: it.id, text: combined });
        }
      }
      if (!overrides.length) return;
      if (genStatus) {
        genStatus.textContent = `Generating… 0/${overrides.length}`;
        genStatus.className = "status-badge progress";
        genStatus.classList.remove("hidden");
      }
      genBtn.disabled = true;
      const oldLabel = genBtn.textContent;
      genBtn.textContent = `Generating ${overrides.length}…`;
      const stopBtn = document.getElementById("stopGenBtn");
      if (stopBtn) { stopBtn.disabled = false; stopBtn.classList.remove("hidden"); }
      try {
        await fetch(`/miniapp/api/comments/generate_override`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ items: overrides }),
        });
      } catch {}
      // Polling same as before
      const params = buildParams();
      let remaining = overrides.length;
      const maxRounds = Math.min(60, Math.ceil((overrides.length * 1.2 + 5) / 1.5));
      for (let round = 0; round < maxRounds; round++) {
        await sleep(1500);
        const r = await fetch(`/miniapp/api/posts?${params.toString()}`);
        const d = await r.json();
        const items2 = d.items || [];
        const byId = new Map(items2.map((x) => [x.id, x]));
        remaining = 0;
        for (const it of overrides) {
          const it2 = byId.get(it.message_id);
          if (it2 && it2.ai_comment) {
            const el = document.getElementById(`comment-${it.message_id}`);
            if (el) {
              const t = it2.channel_title || it2.channel_username || "Channel";
              el.innerHTML = `<div class="title"><span class="num"></span> Comment: ${escapeHtml(t)} <button class="action fix-comment" data-id="${it2.id}">Fix</button> <button class="action del-comment" data-id="${it2.id}">Delete</button></div><div class="content">${escapeHtml(it2.ai_comment)}</div>`;
            }
          } else {
            remaining++;
          }
        }
        if (genStatus) {
          const done = overrides.length - remaining;
          genStatus.textContent = `Generating… ${done}/${overrides.length}`;
        }
        if (!remaining) break;
      }
      genBtn.disabled = false;
      genBtn.textContent = oldLabel;
      if (genStatus) {
        if (remaining === 0) {
          genStatus.textContent = `✓ Done (${overrides.length}/${overrides.length})`;
          genStatus.className = "status-badge";
        } else {
          const done = overrides.length - remaining;
          genStatus.textContent = `Partial: ${done}/${overrides.length}`;
          genStatus.className = "status-badge progress";
        }
      }
      if (stopBtn) { stopBtn.disabled = true; }
    });
  }
  // Stop generation button in controls bar
  const stopGenBtn = document.getElementById("stopGenBtn");
  if (stopGenBtn) {
    stopGenBtn.addEventListener("click", async () => {
      stopGenBtn.disabled = true;
      try {
        await fetch(`/miniapp/api/comments/stop`, { method: "POST" });
        if (genStatus) {
          genStatus.textContent = "Stopping…";
          genStatus.className = "status-badge progress";
          genStatus.classList.remove("hidden");
        }
      } catch {}
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
          if (contentEl) contentEl.textContent = "Комментарий отсутствует";
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
  if (deletePostsBtn) {
    deletePostsBtn.addEventListener("click", async () => {
      try {
        const ids = Array.isArray(lastItems) ? lastItems.map((x) => x.id) : [];
        if (!ids.length) return;
        deletePostsBtn.disabled = true;
        deletePostsBtn.textContent = "Deleting…";
        await fetch(`/miniapp/api/posts`, {
          method: "DELETE",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message_ids: ids, delete_media: true }),
        });
        await load();
        if (genStatus) {
          genStatus.textContent = "✓ Posts deleted";
          genStatus.className = "status-badge";
          genStatus.classList.remove("hidden");
        }
      } catch (e) {
        console.error(e);
        if (genStatus) {
          genStatus.textContent = "Error deleting posts";
          genStatus.className = "status-badge error";
          genStatus.classList.remove("hidden");
        }
      } finally {
        deletePostsBtn.disabled = false;
        deletePostsBtn.textContent = "Delete posts";
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
        // if list is visible, reload posts; otherwise stay on picker
        if (!pickerEl || pickerEl.classList.contains("hidden")) {
          await load();
        }
      } catch (e) {
        console.error(e);
      } finally {
        refreshChannelsBtn.disabled = false;
        refreshChannelsBtn.textContent = oldText;
      }
    });
  }
  // initial: show picker only
  loadChannels();
})();


