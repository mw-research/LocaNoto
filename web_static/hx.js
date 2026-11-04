// A small subset of htmx (https://htmx.org), same attribute names, so the
// official file can replace this one without changing a page:
//
//   hx-get / hx-post      request on submit (forms) or click (others)
//   hx-trigger            another event, e.g. "input delay:300ms" (waits until
//                         typing pauses)
//   hx-target             CSS selector of the element to fill ("this" = self)
//   hx-swap               innerHTML (default) | outerHTML | beforeend | afterbegin
//   hx-confirm            ask before sending
//   HX-Redirect header    the response sends the browser elsewhere
//
// Every request carries the CSRF header the server expects with the
// session cookie. Errors show as a short message, never as page content.
// Plus helpers for this app: sign-in, sign-out, upload forms,
// data-userpick -- a text field that suggests user names while typing
// (comma separated lists too) -- and notices: every signed-in page asks
// /ui/notifications every few seconds (often while a web search runs,
// rarely otherwise), shows each finished task once with a link to it and
// a count on the "Web sources" tab, and refreshes the task list there.
(function () {
  "use strict";

  function cookie(name) {
    var m = document.cookie.match("(?:^|; )" + name + "=([^;]*)");
    return m ? decodeURIComponent(m[1]) : "";
  }

  function csrfHeaders(extra) {
    var h = { "X-LocaNoto-CSRF": cookie("locanoto_csrf"), "HX-Request": "true" };
    for (var k in extra || {}) h[k] = extra[k];
    return h;
  }

  function toast(text, bad) {
    var t = document.getElementById("toast");
    if (!t) return;
    t.textContent = text;
    t.className = "show" + (bad ? " bad" : "");
    clearTimeout(t._timer);
    t._timer = setTimeout(function () { t.className = ""; }, 6000);
  }

  async function errorText(response) {
    try {
      var body = await response.json();
      return body.detail ? String(typeof body.detail === "string" ? body.detail
        : JSON.stringify(body.detail)) : response.statusText;
    } catch (e) {
      return response.status + " " + response.statusText;
    }
  }

  function targetOf(el) {
    var sel = el.getAttribute("hx-target");
    if (!sel || sel === "this") return el;
    if (sel.indexOf("closest ") === 0) return el.closest(sel.slice(8));
    return document.querySelector(sel);
  }

  function swap(target, html, how) {
    if (!target) return;
    if (how === "outerHTML") {
      var tpl = document.createElement("template");
      tpl.innerHTML = html;
      var nodes = Array.prototype.slice.call(tpl.content.childNodes);
      target.replaceWith.apply(target, nodes);
      nodes.forEach(function (n) { if (n.nodeType === 1) process(n); });
      return;
    }
    if (how === "beforeend") target.insertAdjacentHTML("beforeend", html);
    else if (how === "afterbegin") target.insertAdjacentHTML("afterbegin", html);
    else target.innerHTML = html;
    process(target);
  }

  async function send(el, event) {
    var confirmText = el.getAttribute("hx-confirm");
    if (confirmText && !window.confirm(confirmText)) return;
    var method = el.hasAttribute("hx-post") ? "POST" : "GET";
    var url = el.getAttribute(method === "POST" ? "hx-post" : "hx-get");
    var init = { method: method, headers: csrfHeaders(), credentials: "same-origin" };
    if (el.tagName === "FORM") {
      var data = new FormData(el);
      var submitter = event && event.submitter;
      if (submitter && submitter.name) data.append(submitter.name, submitter.value);
      if (method === "POST") init.body = new URLSearchParams(data);
      else url += (url.indexOf("?") < 0 ? "?" : "&") + new URLSearchParams(data);
    }
    el.classList.add("busy");
    try {
      var response = await fetch(url, init);
      if (response.status === 401) { location.href = "/login?next=" + encodeURIComponent(location.pathname); return; }
      var redirect = response.headers.get("HX-Redirect");
      if (redirect) { location.href = redirect; return; }
      if (!response.ok) { toast(await errorText(response), true); return; }
      swap(targetOf(el), await response.text(), el.getAttribute("hx-swap") || "innerHTML");
    } catch (e) {
      toast(String(e), true);
    } finally {
      el.classList.remove("busy");
    }
  }

  function process(root) {
    var els = root.querySelectorAll ? root.querySelectorAll("[hx-get],[hx-post]") : [];
    if (root.matches && root.matches("[hx-get],[hx-post]")) els = [root].concat(Array.prototype.slice.call(els));
    Array.prototype.forEach.call(els, function (el) {
      if (el._hx) return;
      el._hx = true;
      var spec = (el.getAttribute("hx-trigger") || (el.tagName === "FORM" ? "submit" : "click")).split(/\s+/);
      var trigger = spec[0];
      var delay = 0;
      spec.forEach(function (part) {
        var m = part.match(/^delay:(\d+)ms$/);
        if (m) delay = parseInt(m[1], 10);
      });
      if (trigger === "load") { send(el); return; }
      var timer = null;
      el.addEventListener(trigger, function (ev) {
        if (trigger === "submit" || trigger === "click") ev.preventDefault();
        if (!delay) { send(el, ev); return; }
        clearTimeout(timer);
        timer = setTimeout(function () { send(el, ev); }, delay);
      });
    });
  }

  // --- app helpers ---

  async function login(form, ev) {
    ev.preventDefault();
    var err = form.querySelector("[data-error]");
    var response = await fetch("/api/v1/auth/login", {
      method: "POST", headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify({ username: form.username.value, password: form.password.value })
    });
    if (response.ok) { location.href = form.getAttribute("data-next") || "/"; return; }
    err.textContent = await errorText(response);
    err.hidden = false;
  }

  async function upload(form, ev) {
    ev.preventDefault();
    var progress = form.querySelector("[data-progress]");
    progress.hidden = false;
    progress.textContent = "…";
    form.classList.add("busy");
    try {
      var response = await fetch("/api/v1/documents", {
        method: "POST", headers: csrfHeaders(), credentials: "same-origin",
        body: new FormData(form)
      });
      if (!response.ok) { toast(await errorText(response), true); progress.hidden = true; return; }
      var r = await response.json();
      progress.textContent = r.file + ": " + r.passages + (r.note ? " – " + r.note : "");
      var list = await fetch("/ui/documents", { credentials: "same-origin" });
      if (list.ok) swap(document.getElementById("doclist"), await list.text(), "innerHTML");
      form.reset();
    } finally {
      form.classList.remove("busy");
    }
  }

  // Suggest user names for a text field; the last comma separated part is
  // the one being typed.
  function userpick(input) {
    var box = document.createElement("div");
    box.className = "userpick";
    box.hidden = true;
    input.insertAdjacentElement("afterend", box);
    var timer = null;
    input.setAttribute("autocomplete", "off");
    input.addEventListener("input", function () {
      clearTimeout(timer);
      timer = setTimeout(async function () {
        var parts = input.value.split(",");
        var q = parts[parts.length - 1].trim();
        if (q.length < 1) { box.hidden = true; return; }
        var r = await fetch("/ui/users/suggest?q=" + encodeURIComponent(q), { credentials: "same-origin" });
        if (!r.ok) { box.hidden = true; return; }
        var names = await r.json();
        box.innerHTML = "";
        names.forEach(function (n) {
          var b = document.createElement("button");
          b.type = "button";
          b.textContent = n;
          b.addEventListener("click", function () {
            parts[parts.length - 1] = (parts.length > 1 ? " " : "") + n;
            input.value = parts.join(",") + (input.hasAttribute("data-multiple") ? ", " : "");
            box.hidden = true;
            input.focus();
          });
          box.appendChild(b);
        });
        box.hidden = !names.length;
      }, 200);
    });
    input.addEventListener("blur", function () { setTimeout(function () { box.hidden = true; }, 200); });
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("input[data-userpick]").forEach(userpick);
    var accent = document.documentElement.getAttribute("data-accent");
    if (accent) document.documentElement.style.setProperty("--accent", accent);
    process(document.body);
    document.querySelectorAll("form[data-login]").forEach(function (f) {
      f.addEventListener("submit", function (ev) { login(f, ev); });
    });
    document.querySelectorAll("form[data-upload]").forEach(function (f) {
      f.addEventListener("submit", function (ev) { upload(f, ev); });
    });
    if (document.querySelector("header.top")) pollTimer = setTimeout(poll, 1500);
    document.addEventListener("click", function (ev) {
      var b = ev.target.closest && ev.target.closest("[data-select-all]");
      if (!b) return;
      var form = b.closest("section").querySelector("form[id^=takeover-]");
      if (form) document.querySelectorAll('input[name=pick][form="' + form.id + '"]').forEach(function (c) { c.checked = true; });
    });
    document.querySelectorAll("[data-logout]").forEach(function (b) {
      b.addEventListener("click", async function () {
        await fetch("/api/v1/auth/logout", { method: "POST", headers: csrfHeaders(), credentials: "same-origin" });
        location.href = "/login";
      });
    });
  });

  // --- notices for background tasks (web_research.py) ---

  function shownIds() {
    try { return JSON.parse(sessionStorage.getItem("locanoto_shown") || "[]"); } catch (e) { return []; }
  }

  function remember(ids) {
    try { sessionStorage.setItem("locanoto_shown", JSON.stringify(ids.slice(-100))); } catch (e) { /* private window */ }
  }

  function notice(item, view) {
    var t = document.getElementById("toast");
    if (!t) return;
    t.textContent = item.text + " ";
    var a = document.createElement("a");
    a.href = "/web?task=" + encodeURIComponent(item.id);
    a.textContent = view + " →";
    t.appendChild(a);
    t.className = "show notice" + (item.bad ? " bad" : "");
    clearTimeout(t._timer);
    t._timer = setTimeout(function () { t.className = ""; }, 15000);
  }

  function badge(count) {
    var link = document.querySelector('nav.tabs a[href="/web"]');
    if (!link) return;
    var b = link.querySelector(".badge");
    if (!count) { if (b) b.remove(); return; }
    if (!b) { b = document.createElement("span"); b.className = "badge"; link.appendChild(b); }
    b.textContent = String(count);
  }

  var lastState = "";
  var pollTimer = null;
  var polling = false;
  var pollAgain = false;

  async function poll() {
    if (polling) { pollAgain = true; return; }
    polling = true;
    clearTimeout(pollTimer);
    var wait = 20000;
    try {
      var r = await fetch("/ui/notifications", { credentials: "same-origin" });
      if (r.ok) {
        var n = await r.json();
        var shown = shownIds();
        n.finished.forEach(function (item) {
          if (shown.indexOf(item.id) < 0) { notice(item, n.view); shown.push(item.id); }
        });
        remember(shown);
        badge(n.finished.length);
        var state = n.running + ":" + n.finished.map(function (i) { return i.id; }).join(",");
        var list = document.getElementById("webtasks");
        if (list && lastState && state !== lastState) {
          var page = await fetch("/ui/web/tasks", { credentials: "same-origin" });
          if (page.ok) swap(list, await page.text(), "innerHTML");
        }
        lastState = state;
        if (n.running) wait = 4000;
      }
    } catch (e) { /* offline for a moment: try again later */ }
    polling = false;
    if (pollAgain) { pollAgain = false; wait = 0; }
    pollTimer = setTimeout(poll, document.hidden ? Math.max(wait, 30000) : wait);
  }

  window.hx = { process: process, swap: swap, toast: toast, csrfHeaders: csrfHeaders, errorText: errorText, poll: poll };
})();
