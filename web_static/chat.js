// The chat: send the question to /api/v1/ask?stream=true and show the
// answer while it grows. The growing text is shown as plain text (never
// as HTML); when it is complete, the server renders the message (Markdown
// with HTML switched off, sources, drafts) and that replaces it.
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

  async function ask(form, ev) {
    ev.preventDefault();
    var box = document.getElementById("messages");
    var question = form.question.value.trim();
    var files = form.images.files;
    if (!question && !files.length) return;
    var body = {
      question: question,
      chat_id: box.getAttribute("data-chat-id") || null,
      rooms: Array.prototype.map.call(form.querySelectorAll("input[name=rooms]:checked"), function (c) { return c.value; }),
      model: form.model ? form.model.value : null,
      preset: form.preset && form.preset.value ? form.preset.value : null,
      web: !!(form.web && form.web.checked),
      images: []
    };
    if (!body.rooms.length) body.rooms = null;
    for (var i = 0; i < files.length; i++) {
      body.images.push({ name: files[i].name, data_base64: await readFile(files[i]) });
    }

    var mine = el("article", "msg user");
    mine.appendChild(el("div", "bubble", question));
    box.appendChild(mine);
    var reply = el("article", "msg assistant pending");
    var status = el("div", "status muted", "…");
    var text = el("div", "answer streaming");
    reply.appendChild(status);
    reply.appendChild(text);
    box.appendChild(reply);
    reply.scrollIntoView({ block: "end" });
    form.question.value = "";
    form.images.value = "";
    form.classList.add("busy");

    var chatId = body.chat_id;
    try {
      var response = await fetch("/api/v1/ask?stream=true", {
        method: "POST", credentials: "same-origin",
        headers: window.hx.csrfHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify(body)
      });
      if (!response.ok) { status.textContent = await window.hx.errorText(response); status.className = "status error"; return; }
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
          } else if (event === "text") {
            text.textContent += d.text;
          } else if (event === "error") {
            status.textContent = d.detail;
            status.className = "status error";
            done = true;
          } else if (event === "done") {
            done = true;
          }
        }
      }
      if (chatId && !status.classList.contains("error")) {
        var rendered = await fetch("/ui/chats/" + chatId + "/messages/-1", { credentials: "same-origin" });
        if (rendered.ok) window.hx.swap(reply, await rendered.text(), "outerHTML");
        var list = await fetch("/ui/chats?current=" + chatId, { credentials: "same-origin" });
        if (list.ok) window.hx.swap(document.getElementById("chatlist"), await list.text(), "innerHTML");
      }
    } catch (e) {
      status.textContent = String(e);
      status.className = "status error";
    } finally {
      form.classList.remove("busy");
      reply.classList.remove("pending");
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    var form = document.getElementById("ask");
    if (!form) return;
    form.addEventListener("submit", function (ev) { ask(form, ev); });
    form.question.addEventListener("keydown", function (ev) {
      if (ev.key === "Enter" && !ev.shiftKey) { ev.preventDefault(); form.requestSubmit(); }
    });
    var box = document.getElementById("messages");
    if (box.lastElementChild) box.lastElementChild.scrollIntoView({ block: "end" });
  });
})();
