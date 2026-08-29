/*
 * FlyRank capstone — Embeddable Widget renderer bundle.
 * Loaded from any website via a single <script> tag:
 *   <script src="https://<api>/embed/<version>/widget.js?id=<widget_id>" async defer></script>
 *
 * It reads its own URL for (id, api origin), fetches the widget config
 * (cached by the backend), renders the form (or popover launcher), and POSTs
 * submissions back to the public submission endpoint.
 *
 * Served versioned + immutable so it can be cached forever. No build step:
 * this file is the bundle.
 */
(function () {
  "use strict";

  var currentScript = document.currentScript;
  if (!currentScript) return;
  var src = currentScript.src || "";
  var qs = new URLSearchParams(src.split("?")[1] || "");
  var widgetId = qs.get("id");
  if (!widgetId) return;

  var apiBase;
  try { apiBase = new URL(src).origin; } catch (e) { return; }
  if (!apiBase) return;

  var ns = "lcp-" + widgetId;

  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (key) {
        if (key === "style") node.setAttribute("style", attrs.style);
        else if (key.slice(0, 2) === "on") node[key] = attrs[key];
        else if (key === "className") node.className = attrs.className;
        else node.setAttribute(key, attrs[key]);
      });
    }
    (children || []).forEach(function (child) {
      node.appendChild(typeof child === "string" ? document.createTextNode(child) : child);
    });
    return node;
  }

  function escapeHtml(s) {
    var d = document.createElement("div");
    d.textContent = s || "";
    return d.innerHTML;
  }

  function fetchJson(path, opts) {
    opts = opts || {};
    var headers = {};
    headers["Accept"] = "application/json";
    if (opts.headers) for (var k in opts.headers) headers[k] = opts.headers[k];
    return fetch(apiBase + path, opts).then(function (res) {
      return res.text().then(function (text) {
        var body = null;
        try { body = text ? JSON.parse(text) : null; } catch (err) { body = null; }
        return { ok: res.ok, status: res.status, body: body };
      });
    });
  }

  function clientToken() {
    var key = ns + ":token";
    var t = window.sessionStorage.getItem(key);
    if (!t) {
      t = (window.crypto && window.crypto.randomUUID)
        ? window.crypto.randomUUID()
        : (Date.now().toString(36) + "-" + Math.random().toString(36).slice(2));
      window.sessionStorage.setItem(key, t);
    }
    return t;
  }

  function fieldHtml(f) {
    var required = f.required;
    var label = "<label>" + escapeHtml(f.label) + (required ? " <span class=\"lcp-req\">*</span>" : "") + "</label>";
    var wrapper = '<div class="' + ns + '-field">' + label;
    if (f.type === "select") {
      var opts = (f.options || []).map(function (o) {
        return '<option value="' + escapeHtml(o) + '">' + escapeHtml(o) + "</option>";
      }).join("");
      wrapper += '<select name="' + escapeHtml(f.name) + '">' + opts + "</select>";
    } else if (f.type === "textarea") {
      wrapper += '<textarea name="' + escapeHtml(f.name) + '"></textarea>';
    } else {
      var inputType = f.type === "email" ? "email" : (f.type === "phone" ? "tel" : "text");
      wrapper += '<input type="' + inputType + '" name="' + escapeHtml(f.name) + '">';
    }
    return wrapper + "</div>";
  }

  function setStatus(statusEl, message, isError) {
    statusEl.hidden = false;
    statusEl.textContent = message;
    statusEl.style.color = isError ? "#b3261e" : "#1b7f3b";
  }

  function formMarkup(cfg) {
    var honeypot = cfg.honeypot_field
      ? '<div class="lcp-hp" aria-hidden="true"><label>Website</label>' +
        '<input type="text" name="' + escapeHtml(cfg.honeypot_field) + '" tabindex="-1" autocomplete="off"></div>'
      : "";
    var fields = (cfg.fields || []).map(fieldHtml).join("");
    var desc = cfg.description ? '<p class="' + ns + '-desc">' + escapeHtml(cfg.description) + "</p>" : "";
    var btn = cfg.button_text || (cfg.type === "cta" || cfg.type === "popover" ? "Get started" : "Submit");
    return (
      '<div class="' + ns + '-card">' +
        '<h3 class="' + ns + '-title">' + escapeHtml(cfg.title) + "</h3>" +
        desc +
        '<form class="' + ns + '-form" novalidate>' + honeypot + fields +
          '<button class="' + ns + '-btn" style="%BTN_STYLE%">' + escapeHtml(btn) + "</button>" +
        "</form>" +
        '<p class="' + ns + '-status" hidden></p>' +
      "</div>"
    );
  }

  function wireForm(form, cfg, statusEl) {
    form.addEventListener("submit", function (ev) {
      ev.preventDefault();
      var data = {};
      var fields = form.querySelectorAll("input[name], textarea[name], select[name]");
      Array.prototype.forEach.call(fields, function (f) {
        data[f.name] = f.value;
      });

      var ok = true;
      var firstError = "Please review the form.";
      (cfg.fields || []).forEach(function (fc) {
        var val = (data[fc.name] || "").trim();
        if (fc.required && !val) { ok = false; firstError = "Please fill in \u201c" + fc.label + "\u201d."; return; }
        if (fc.type === "email" && val && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(val)) { ok = false; firstError = "Please enter a valid email."; return; }
        if (fc.type === "select" && val && fc.options && fc.options.indexOf(val) === -1) { ok = false; firstError = "Please choose a valid option."; return; }
      });
      if (!ok) { setStatus(statusEl, firstError, true); return; }

      setStatus(statusEl, "Sending\u2026", false);
      fetchJson("/submissions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ widget_id: cfg.id, client_token: clientToken(), data: data })
      }).then(function (res) {
        if (res.status === 429) {
          setStatus(statusEl, (res.body && res.body.detail) ? res.body.detail : "Too many attempts. Please try again later.", true);
          return;
        }
        if (res.ok && res.body && res.body.accepted) {
          setStatus(statusEl, "Thanks! Your submission was received.", false);
          Array.prototype.forEach.call(fields, function (f) { f.value = ""; });
        } else {
          var detail = res.body && res.body.detail;
          setStatus(statusEl, detail ? JSON.stringify(detail) : "Something went wrong. Please try again.", true);
        }
      }).catch(function () {
        setStatus(statusEl, "Network error. Please try again.", true);
      });
    });
  }

  var FLOATING_STYLE =
    "position:fixed;right:24px;bottom:24px;z-index:2147483000;" +
    "background:%ACCENT%;color:#fff;border:0;border-radius:999px;" +
    "padding:14px 22px;font:600 15px/1 system-ui,sans-serif;cursor:pointer;" +
    "box-shadow:0 6px 18px rgba(0,0,0,.25)";
  var MODAL_STYLE =
    "position:fixed;right:24px;bottom:96px;z-index:2147483001;" +
    "width:340px;max-width:calc(100vw - 48px);max-height:70vh;overflow:auto;" +
    "background:#fff;border-radius:14px;box-shadow:0 12px 40px rgba(0,0,0,.28);padding:4px";

  function render(cfg) {
    var accent = (cfg.styles && cfg.styles.accent_color) || "#2563eb";
    /* Only allow clean hex colors in style strings (admin-supplied value). */
    accent = /^#[0-9a-fA-F]{3}$|^#[0-9a-fA-F]{4}$|^#[0-9a-fA-F]{6}$|^#[0-9a-fA-F]{8}$/.test(accent) ? accent : "#2563eb";
    var lang = cfg.locale || "en";
    /* config map drives the render mode; fall back to legacy type-based rules */
    var isPopover = cfg.mode === "popover" || cfg.type === "cta" || cfg.type === "popover";
    var card, form, statusEl;

    if (isPopover) {
      var launcher = el("button", {
        type: "button",
        className: ns + "-launch",
        style: FLOATING_STYLE.replace("%ACCENT%", accent)
      });
      launcher.textContent = cfg.button_text || "Get started";
      var modal = el("div", { className: ns + "-modal", style: MODAL_STYLE, hidden: "" });
      modal.innerHTML = formMarkup(cfg).replace("%BTN_STYLE%", "width:100%;background:" + accent + ";color:#fff;border:0;border-radius:8px;padding:12px;font:600 15px/1 system-ui,sans-serif;cursor:pointer");
      var close = el("button", { type: "button", className: ns + "-close", style: "float:right;border:0;background:none;font-size:20px;cursor:pointer;color:#666", textContent: "\u00d7" });
      modal.insertBefore(close, modal.firstChild);
      close.addEventListener("click", function () { modal.hidden = true; });
      launcher.addEventListener("click", function () { modal.hidden = !modal.hidden; });
      document.body.appendChild(launcher);
      document.body.appendChild(modal);
      card = modal;
      form = modal.querySelector("form");
      statusEl = modal.querySelector("." + ns + "-status");
    } else {
      /* Inline form: render in page flow next to the embed script. Unlike the
         floating launcher it must NOT be position:fixed (that would pin it to a
         viewport corner no matter where the snippet was placed). */
      card = el("div", { className: ns });
      card.style.cssText = "font:400 14px/1.45 system-ui,sans-serif;max-width:420px;";
      card.innerHTML = formMarkup(cfg).replace(
        "%BTN_STYLE%",
        "width:100%;background:" + accent + ";color:#fff;border:0;border-radius:8px;padding:12px;font:600 15px/1 system-ui,sans-serif;cursor:pointer"
      );
      var host = currentScript.parentNode;
      host.insertBefore(card, currentScript.nextSibling);
      form = card.querySelector("form");
      statusEl = card.querySelector("." + ns + "-status");
    }

    var hp = document.head || document.documentElement;
    hp.appendChild(el("style", { type: "text/css" }, [
      "." + ns + "-card{background:#fff;color:#111;border:1px solid #e5e7eb;border-radius:14px;padding:18px;box-shadow:0 8px 28px rgba(0,0,0,.10);min-width:260px}" +
      "." + ns + "-title{margin:0 0 4px;font-size:17px}" +
      "." + ns + "-desc{margin:0 0 12px;color:#555}" +
      "." + ns + "-field{margin:0 0 10px}" +
      "." + ns + "-field label{display:block;font-size:13px;margin:0 0 4px}" +
      "." + ns + "-field input,." + ns + "-field textarea,." + ns + "-field select{width:100%;box-sizing:border-box;padding:9px;border:1px solid #d1d5db;border-radius:8px;font:inherit}" +
      ".lcp-hp{position:absolute;left:-9999px;top:-9999px;opacity:0;height:0;overflow:hidden}" +
      "." + ns + "-status{margin:10px 0 0;font-size:13px;min-height:0}"
    ]));
    if (card && card.setAttribute) card.setAttribute("lang", lang);

    wireForm(form, cfg, statusEl);
  }

  fetchJson("/widgets/" + encodeURIComponent(widgetId) + "/config").then(function (res) {
    if (res.ok && res.body) render(res.body);
  }).catch(function () {
    /* widget config unavailable — fail invisible, never break the host page */
  });
})();