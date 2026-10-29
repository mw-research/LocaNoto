// A small subset of htmx (https://htmx.org), same attribute names, so the
// official file can replace this one without changing a page:
//
//   hx-get / hx-post      request on submit (forms) or click (others)
//   hx-target             CSS selector of the element to fill ("this" = self)
//   hx-swap               innerHTML (default) | outerHTML | beforeend | afterbegin
//   hx-confirm            ask before sending
//   HX-Redirect header    the response sends the browser elsewhere
//
// Every request carries the CSRF header the server expects with the
// session cookie. Errors show as a short message, never as page content.
// Plus three helpers for this app: sign-in, sign-out and upload forms.
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
      var trigger = el.getAttribute("hx-trigger") || (el.tagName === "FORM" ? "submit" : "click");
      if (trigger === "load") { send(el); return; }
      el.addEventListener(trigger, function (ev) { ev.preventDefault(); send(el, ev); });
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

  document.addEventListener("DOMContentLoaded", function () {
    var accent = document.documentElement.getAttribute("data-accent");
    if (accent) document.documentElement.style.setProperty("--accent", accent);
    process(document.body);
    document.querySelectorAll("form[data-login]").forEach(function (f) {
      f.addEventListener("submit", function (ev) { login(f, ev); });
    });
    document.querySelectorAll("form[data-upload]").forEach(function (f) {
      f.addEventListener("submit", function (ev) { upload(f, ev); });
    });
    document.querySelectorAll("[data-logout]").forEach(function (b) {
      b.addEventListener("click", async function () {
        await fetch("/api/v1/auth/logout", { method: "POST", headers: csrfHeaders(), credentials: "same-origin" });
        location.href = "/login";
      });
    });
  });

  window.hx = { process: process, swap: swap, toast: toast, csrfHeaders: csrfHeaders, errorText: errorText };
})();
