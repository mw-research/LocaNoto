// The chat: send the question to /api/v1/ask?stream=true and show the
// answer while it grows. The growing text is shown as plain text (never
// as HTML); when it is complete, the server renders the message (Markdown
// with HTML switched off, sources, drafts) and that replaces it. The
// button "Search in the web" starts a background search (web_research.py)
// with the text of the question box. A web search the model proposed
// (a draft with data-web-draft) is confirmed here: the answer continues
// the chat with the hits, without a new question.
(function () {
  "use strict";

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  }

  function readFile(file) {
    return new Promise(function (resolve, reject) {
      var r = new FileReader();
      r.onload = function () { resolve(String(r.result).split(",", 2)[1]); };
      r.onerror = reject;
      r.readAsDataURL(file);
    });
  }

  function options(form, box) {
    var body = {
      chat_id: box.getAttribute("data-chat-id") || null,
      rooms: Array.prototype.map.call(form.querySelectorAll("input[name=rooms]:checked"), function (c) { return c.value; }),
      model: form.model ? form.model.value : null,
      preset: form.preset && form.preset.value ? form.preset.value : null,
      web: !!(form.web && form.web.checked),
      sql: !!(form.sql && form.sql.checked),
      images: []
    };
    if (body.sql && form.sql_room) body.sql_room = form.sql_room.value;
    if (!body.rooms.length) body.rooms = null;
    return body;
  }

  async function ask(form, ev) {
    ev.preventDefault();
    var box = document.getElementById("messages");
    var question = form.question.value.trim();
    var files = form.images.files;
    if (!question && !files.length) return;
    var body = options(form, box);
    body.question = question;
    for (var i = 0; i < files.length; i++) {
      body.images.push({ name: files[i].name, data_base64: await readFile(files[i]) });
    }
    var mine = el("article", "msg user");
    mine.appendChild(el("div", "bubble", question));
    box.appendChild(mine);
    form.question.value = "";
    form.images.value = "";
    await stream(form, box, body);
  }

  // A proposed web search, confirmed: same chat, same options, no question.
  async function confirmWeb(form, button) {
    if (form.classList.contains("busy")) return;
    var box = document.getElementById("messages");
    var body = options(form, box);
    body.web_draft = button.getAttribute("data-web-draft");
    button.disabled = true;
    await stream(form, box, body, button.closest("article"));
  }

  // proposing: the answer that holds a confirmed web search draft; it is
  // shown again afterwards, with the draft as done.
  async function stream(form, box, body, proposing) {
    var reply = el("article", "msg assistant pending");
    var status = el("div", "status muted", "…");
    var text = el("div", "answer streaming");
    reply.appendChild(status);
    reply.appendChild(text);
    box.appendChild(reply);
    reply.scrollIntoView({ block: "end" });
    form.classList.add("busy");

    var chatId = body.chat_id;
    try {
      var response = await fetch("/api/v1/ask?stream=true", {
        method: "POST", credentials: "same-origin",
        headers: window.hx.csrfHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify(body)
      });
      if (!response.ok) {
        status.textContent = await window.hx.errorText(response);
        status.className = "status error";
        if (response.status >= 500 && chatId) retryButton(form, box, reply, chatId);
        return;
      }
      var reader = response.body.getReader();
      var decoder = new TextDecoder();
      var buffer = "";
      var done = false;
      while (!done) {
        var chunk = await reader.read();
        if (chunk.done) break;
        buffer += decoder.decode(chunk.value, { stream: true });
        var parts = buffer.split("\n\n");
        buffer = parts.pop();
        for (var p = 0; p < parts.length; p++) {
          var event = "", data = "";
          parts[p].split("\n").forEach(function (line) {
            if (line.indexOf("event: ") === 0) event = line.slice(7);
            else if (line.indexOf("data: ") === 0) data += line.slice(6);
          });
          var d = data ? JSON.parse(data) : {};
          if (event === "chat") {
            chatId = d.chat_id;
            box.setAttribute("data-chat-id", chatId);
            if (d.new) history.replaceState(null, "", "/c/" + chatId);
          } else if (event === "probes") {
            status.textContent = (d.probes || []).join(" · ");
          } else if (event === "search") {
            status.textContent += "  —  " + d.hits + " / " + d.candidates;
          } else if (event === "tool") {
            status.textContent = d.progress;
          } else if (event === "sql") {
            status.textContent = d.query ? "SQL: " + d.query : (d.reason || "");
          } else if (event === "text") {
            text.textContent += d.text;
          } else if (event === "error") {
            status.textContent = d.detail;
            status.className = "status error";
            if (d.chat_id) chatId = d.chat_id;
            if (d.retry && chatId) retryButton(form, box, reply, chatId);
            done = true;
          } else if (event === "done") {
            done = true;
          }
        }
      }
      if (chatId && !status.classList.contains("error")) {
        if (proposing && proposing.id) {
          var again = await fetch("/ui/chats/" + chatId + "/messages/" + proposing.id.slice(1), { credentials: "same-origin" });
          if (again.ok) window.hx.swap(proposing, await again.text(), "outerHTML");
        }
        var rendered = await fetch("/ui/chats/" + chatId + "/messages/-1", { credentials: "same-origin" });
        if (rendered.ok) window.hx.swap(reply, await rendered.text(), "outerHTML");
        var list = await fetch("/ui/chats?current=" + chatId, { credentials: "same-origin" });
        if (list.ok) window.hx.swap(document.getElementById("chatlist"), await list.text(), "innerHTML");
      }
    } catch (e) {
      // the connection broke (a proxy timeout, the server gone)
      status.textContent = String(e);
      status.className = "status error";
      if (chatId) retryButton(form, box, reply, chatId);
    } finally {
      form.classList.remove("busy");
      reply.classList.remove("pending");
    }
  }

  // "Ask again" under a failed answer: the same chat answers its last
  // question again; the failed answer is replaced.
  function retryButton(form, box, reply, chatId) {
    var b = el("button", "primary", form.getAttribute("data-retry") || "Ask again");
    b.type = "button";
    b.addEventListener("click", async function () {
      if (form.classList.contains("busy")) return;
      reply.remove();
      var body = options(form, box);
      body.chat_id = chatId;
      body.retry = true;
      await stream(form, box, body);
    });
    reply.appendChild(b);
  }

  // Start a web search with the text of the question box. The exact text
  // is shown in the chat first and goes out only on a click; then the box
  // is emptied and the chat says the search runs. It runs in the
  // background, the notice comes wherever the user is by then.
  function webSearch(form, button) {
    var query = form.question.value.trim().replace(/\s+/g, " ").slice(0, 200);
    if (query.length < 2) { form.question.focus(); return; }
    var box = document.getElementById("messages");
    var card = el("article", "msg assistant draft webconfirm");
    var p = el("p", "preview", button.getAttribute("data-confirm") + " ");
    p.appendChild(el("code", "", query));
    card.appendChild(p);
    var go = el("button", "primary", button.textContent);
    go.type = "button";
    var cancel = el("button", "", button.getAttribute("data-cancel") || "Cancel");
    cancel.type = "button";
    card.appendChild(go);
    card.appendChild(document.createTextNode(" "));
    card.appendChild(cancel);
    box.appendChild(card);
    card.scrollIntoView({ block: "end" });
    cancel.addEventListener("click", function () { card.remove(); });
    go.addEventListener("click", async function () {
      go.disabled = cancel.disabled = true;
      var response = await fetch("/ui/web/tasks", {
        method: "POST", credentials: "same-origin",
        headers: window.hx.csrfHeaders({ "Content-Type": "application/x-www-form-urlencoded" }),
        body: new URLSearchParams({ query: query })
      });
      if (!response.ok) {
        var bad = el("p", "error", await window.hx.errorText(response));
        card.appendChild(bad);
        go.disabled = cancel.disabled = false;
        return;
      }
      if (form.question.value.trim().replace(/\s+/g, " ").slice(0, 200) === query) form.question.value = "";
      card.textContent = "";
      card.appendChild(el("p", "ok", button.getAttribute("data-started") + " "));
      var link = el("a", "", query);
      link.href = "/web";
      card.firstChild.appendChild(link);
      window.hx.poll();
    });
  }

  // An answer still being written (left and come back, or opened in another
  // tab): show it as it is saved, until it is complete. Nothing is locked --
  // the server answers on without the page.
  function follow(article) {
    var box = document.getElementById("messages");
    var chatId = box && box.getAttribute("data-chat-id");
    var index = article.id ? article.id.slice(1) : "";
    if (!chatId || !index) return;
    setTimeout(async function again() {
      if (!document.body.contains(article)) return;
      try {
        var r = await fetch("/ui/chats/" + chatId + "/messages/" + index, { credentials: "same-origin" });
        if (r.ok) {
          var html = await r.text();
          var tpl = document.createElement("template");
          tpl.innerHTML = html;
          var fresh = tpl.content.firstElementChild;
          window.hx.swap(article, html, "outerHTML");
          if (fresh && fresh.getAttribute("data-running")) {
            follow(document.getElementById(article.id));
          } else {
            var list = await fetch("/ui/chats?current=" + chatId, { credentials: "same-origin" });
            if (list.ok) window.hx.swap(document.getElementById("chatlist"), await list.text(), "innerHTML");
          }
          return;
        }
      } catch (e) { /* offline for a moment */ }
      setTimeout(again, 4000);
    }, 2000);
  }

  document.addEventListener("DOMContentLoaded", function () {
    var form = document.getElementById("ask");
    if (!form) return;
    Array.prototype.forEach.call(document.querySelectorAll("[data-running]"), follow);
    var web = form.querySelector("[data-web-search]");
    if (web) web.addEventListener("click", function () { webSearch(form, web); });
    document.addEventListener("click", function (ev) {
      var b = ev.target.closest && ev.target.closest("[data-web-draft]");
      if (b) { ev.preventDefault(); confirmWeb(form, b); }
      var r = ev.target.closest && ev.target.closest("[data-retry]");
      if (r && !form.classList.contains("busy")) {
        ev.preventDefault();
        var box = document.getElementById("messages");
        var article = r.closest("article");
        var body = options(form, box);
        body.retry = true;
        if (article) article.remove();
        stream(form, box, body);
      }
    });
    form.addEventListener("submit", function (ev) { ask(form, ev); });
    form.question.addEventListener("keydown", function (ev) {
      if (ev.key === "Enter" && !ev.shiftKey) { ev.preventDefault(); form.requestSubmit(); }
    });
    var box = document.getElementById("messages");
    if (box.lastElementChild) box.lastElementChild.scrollIntoView({ block: "end" });
  });
})();
