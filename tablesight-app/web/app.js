/* TableSight web client. Vanilla JS, no dependencies. All dynamic text goes through textContent (no innerHTML with data). */
(function () {
  "use strict";
  var API = ""; // same origin as the API
  var POLL_MS = 5000, STALE_S = 120, WINDOW_S = 8 * 3600;
  var S = { lang: "en", i18n: null, token: null, locs: [], loc: null, events: null, devAge: null, devKnown: false,
            skew: 0, fetchedAt: 0, netErr: false, acks: {}, wrongOpen: null, mode: "floor", timer: null, lastPointer: 0, dirty: false };
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var main = $("#main");

  // ---------- storage (always guarded) ----------
  function sget(k) { try { return sessionStorage.getItem(k); } catch (e) { return S["_m_" + k] || null; } }
  function sset(k, v) { try { sessionStorage.setItem(k, v); } catch (e) { S["_m_" + k] = v; } }
  function sdel(k) { try { sessionStorage.removeItem(k); } catch (e) { delete S["_m_" + k]; } }
  function lget(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function lset(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* ignore */ } }

  // ---------- i18n ----------
  function t(key, vars) {
    var d = S.i18n || {}, s = (d[S.lang] && d[S.lang][key]) || (d.en && d.en[key]) || key;
    return s.replace(/\{(\w+)\}/g, function (m, k) { return vars && vars[k] != null ? vars[k] : m; });
  }
  function num(n) { try { return new Intl.NumberFormat(S.lang).format(n); } catch (e) { return String(n); } }
  function applyLang(lang) {
    S.lang = lang; lset("ts.lang", lang);
    var rtl = ((S.i18n && S.i18n._rtl) || ["ar"]).indexOf(lang.split("-")[0]) >= 0;
    document.documentElement.lang = lang; document.documentElement.dir = rtl ? "rtl" : "ltr";
    $("#lang").value = lang;
    document.querySelectorAll("[data-i18n]").forEach(function (el) { el.textContent = t(el.getAttribute("data-i18n")); });
    $("#modes").setAttribute("aria-label", t("ui.views"));
    paintTheme();
  }

  // ---------- theme: dark default for in-service ----------
  function theme() { return lget("ts.theme") || "dark"; }
  function paintTheme() {
    var th = theme(); document.documentElement.setAttribute("data-theme", th);
    $("#theme").textContent = th === "dark" ? t("ui.theme.to_light") : t("ui.theme.to_dark");
  }

  // ---------- helpers ----------
  function h(tag, attrs, kids) {
    var e = document.createElement(tag);
    for (var k in (attrs || {})) {
      var v = attrs[k]; if (v == null || v === false) continue;
      if (k === "class") e.className = v; else if (k === "text") e.textContent = v;
      else if (k.slice(0, 2) === "on") e.addEventListener(k.slice(2), v); else e.setAttribute(k, v === true ? "" : v);
    }
    (kids || []).forEach(function (c) { if (c != null) e.appendChild(typeof c === "string" ? document.createTextNode(c) : c); });
    return e;
  }
  var ICONS = {
    attn: '<path d="M12 3 22 20H2z" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linejoin="round"/><path d="M12 9v5M12 16.5v1" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"/>',
    ok: '<circle cx="12" cy="12" r="9" fill="currentColor"/><path d="m8 12.5 3 3 5-6" fill="none" stroke="var(--card)" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/>',
    unk: '<path d="M12 2 22 12 12 22 2 12z" fill="none" stroke="currentColor" stroke-width="2.4" stroke-dasharray="3 2.5" stroke-linejoin="round"/><path d="M9.8 9.5a2.4 2.4 0 1 1 3.4 2.2c-.8.4-1.2.9-1.2 1.8M12 16.5v.5" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/>',
    clean: '<rect x="3.5" y="3.5" width="17" height="17" rx="2" fill="none" stroke="currentColor" stroke-width="2.4"/><path d="M7 17 17 7M7 12l5-5M12 17l5-5" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>',
    idle: '<circle cx="12" cy="12" r="8.5" fill="none" stroke="currentColor" stroke-width="2.4"/>',
    warn: '<path d="M12 3 22 20H2z" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linejoin="round"/><path d="M12 9v5M12 16.5v1" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/>'
  };
  function icon(kind, cls) {
    var s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    s.setAttribute("viewBox", "0 0 24 24"); s.setAttribute("aria-hidden", "true"); s.setAttribute("focusable", "false");
    if (cls) s.setAttribute("class", cls);
    s.innerHTML = ICONS[kind]; // static constants only
    return s;
  }
  function nowS() { return (Date.now() / 1000) + S.skew; }
  function toast(msg, undo) {
    var box = $("#toasts"), el = h("div", { class: "toast" }, [h("span", { text: msg })]);
    var gone = function () { if (el.parentNode) el.parentNode.removeChild(el); };
    if (undo) el.appendChild(h("button", { type: "button", text: t("act.undo"), onclick: function () { undo(); gone(); } }));
    box.appendChild(el); setTimeout(gone, undo ? 4200 : 3500);
  }

  // ---------- API ----------
  function api(path, opts) {
    opts = opts || {};
    var hd = { Accept: "application/json" };
    if (opts.body) hd["Content-Type"] = "application/json";
    if (S.token) hd.Authorization = "Bearer " + S.token;
    return fetch(API + path, { method: opts.method || "GET", headers: hd, body: opts.body ? JSON.stringify(opts.body) : undefined })
      .then(function (r) {
        var d = r.headers.get("Date"); if (d) { var ms = Date.parse(d); if (ms) S.skew = (ms - Date.now()) / 1000; }
        return r.text().then(function (txt) {
          var j = null; try { j = txt ? JSON.parse(txt) : null; } catch (e) { /* non-JSON */ }
          if (!r.ok) { var err = new Error((j && j.detail) || r.statusText); err.status = r.status; throw err; }
          return j;
        });
      });
  }
  function qs(o) { return Object.keys(o).map(function (k) { return encodeURIComponent(k) + "=" + encodeURIComponent(o[k]); }).join("&"); }

  // ---------- routing ----------
  var ROUTES = ["floor", "host", "tv", "settings"];
  function route() {
    var r = (location.hash || "").replace(/^#\/?/, "").split("?")[0];
    if (!S.token) return "login";
    return ROUTES.indexOf(r) >= 0 ? r : "floor";
  }
  function go() {
    clearInterval(S.timer); S.timer = null;
    var r = route(); S.mode = r;
    document.body.className = "m-" + r;
    $("#top").hidden = (r === "login");
    paintNav();
    document.title = "TableSight";
    if (r === "login") return viewLogin();
    if (r === "settings") return viewSettings();
    viewFloor();
  }
  function paintNav() {
    var nav = $("#modes"); nav.textContent = "";
    ROUTES.forEach(function (r) {
      var a = h("a", { href: "#/" + r, text: t("nav." + (r === "tv" ? "tv" : r)) });
      if (r === S.mode) a.setAttribute("aria-current", "page");
      nav.appendChild(a);
    });
  }
  function focusMain() { main.focus({ preventScroll: true }); }

  // ---------- login ----------
  function viewLogin() {
    main.textContent = "";
    var err = h("p", { class: "err", id: "login-err", role: "alert" });
    var email = h("input", { id: "email", type: "email", autocomplete: "username", required: true, "aria-describedby": "login-err" });
    var pw = h("input", { id: "password", type: "password", autocomplete: "current-password", required: true });
    var totp = h("input", { id: "totp", type: "text", inputmode: "numeric", autocomplete: "one-time-code", pattern: "[0-9]*", maxlength: "6", "aria-describedby": "totp-hint" });
    var btn = h("button", { class: "btn", type: "submit", text: t("login.submit") });
    var form = h("form", { class: "login", novalidate: true, "aria-labelledby": "login-h" }, [
      h("h1", { id: "login-h", text: t("login.title") }),
      h("label", { for: "email", text: t("login.email") }), email,
      h("label", { for: "password", text: t("login.password") }), pw,
      h("label", { for: "totp", text: t("login.totp") }), totp,
      h("p", { class: "hint", id: "totp-hint", text: t("login.totp_hint") }),
      err, btn]);
    form.addEventListener("submit", function (ev) {
      ev.preventDefault(); err.textContent = "";
      btn.disabled = true; btn.textContent = t("login.busy");
      var body = { email: email.value.trim(), password: pw.value }; if (totp.value.trim()) body.totp = totp.value.trim();
      api("/login", { method: "POST", body: body }).then(function (r) {
        S.token = r.token; sset("ts.tok", r.token); location.hash = "#/floor"; go();
      }).catch(function (e) {
        var key = "login.err.net", focus = email;
        if (e.status === 401 && /2fa/i.test(e.message)) { key = "login.err.2fa"; focus = totp; }
        else if (e.status === 401) { key = "login.err.invalid"; focus = pw; }
        else if (e.status === 423) key = "login.err.locked";
        else if (e.status === 429) key = "login.err.rate";
        else if (e.status === 403) key = "login.err.unverified";
        err.textContent = ""; err.appendChild(icon("warn", "ico-s")); err.lastChild.setAttribute("width", 20); err.lastChild.setAttribute("height", 20);
        err.appendChild(h("span", { text: t(key) }));
        btn.disabled = false; btn.textContent = t("login.submit"); focus.focus();
      });
    });
    main.appendChild(form); email.focus();
  }
  function logout(silent) {
    var p = S.token ? api("/logout", { method: "POST" }).catch(function () {}) : Promise.resolve();
    S.token = null; sdel("ts.tok"); S.events = null; S.locs = []; S.loc = null;
    p.then(function () { location.hash = "#/login"; go(); if (silent) { $("#login-err").textContent = t("err.session"); } });
  }

  // ---------- data ----------
  function loadLocs() {
    if (S.locs.length) return Promise.resolve();
    return api("/locations").then(function (l) {
      S.locs = l; S.loc = (l.filter(function (x) { return x.id === sget("ts.loc"); })[0] || l[0] || null);
    });
  }
  function demoBanner() {
    var d = $("#demo"), demo = S.loc && /DEMO MODE/i.test(S.loc.name);
    d.hidden = !demo; if (demo) d.textContent = t("demo");
  }
  function refresh() {
    if (!S.loc) return Promise.resolve();
    var ev = api("/events?" + qs({ location_id: S.loc.id, since: Math.floor(nowS() - WINDOW_S) })).then(function (e) {
      S.events = e; S.fetchedAt = Date.now(); S.netErr = false;
    });
    var dv = api("/devices").then(function (d) {
      var mine = d.filter(function (x) { return x.location_id === S.loc.id && x.last_seen; });
      S.devKnown = mine.length > 0;
      S.devAge = S.devKnown ? nowS() - Math.max.apply(null, mine.map(function (x) { return x.last_seen; })) : null;
    }).catch(function (e) { if (e.status === 401) throw e; S.devKnown = false; S.devAge = null; }); // role may not see device health
    return Promise.all([ev, dv]).catch(function (e) {
      if (e.status === 401) { logout(true); return; }
      S.netErr = true;
    });
  }

  // Fold the event stream into one state per table.
  function derive(events) {
    var T = {};
    (events || []).forEach(function (e) {
      var x = T[e.table_id] || (T[e.table_id] = { id: e.table_id, st: "empty", unc: false, party: null, seatedAt: null, lastStaff: null, flagged: false, attnId: null, t: e.t });
      x.t = e.t;
      if (e.kind === "uncertain") { x.unc = true; return; }
      x.unc = false;
      if (e.kind === "seated") { x.st = "seated"; x.seatedAt = e.t; x.party = e.detail && e.detail.party; x.lastStaff = null; x.flagged = false; x.attnId = null; }
      else if (e.kind === "staff_visit") { x.lastStaff = e.t; x.flagged = false; }
      else if (e.kind === "needs_attention") { x.flagged = true; x.attnId = e.event_id; }
      else if (e.kind === "vacated") { x.st = "empty"; x.flagged = false; }
      else if (e.kind === "needs_clean") { x.st = "needs_clean"; }
    });
    var now = nowS();
    return Object.keys(T).map(function (k) {
      var x = T[k];
      x.wait = x.st === "seated" ? Math.max(0, now - (x.lastStaff || x.seatedAt || now)) : 0;
      x.sinceCheck = x.lastStaff != null;
      x.cls = x.st === "empty" ? "idle" : x.st === "needs_clean" ? "clean" : x.unc ? "unk" : x.flagged ? "attn" : "ok";
      x.rank = x.st === "seated" ? 0 : x.st === "needs_clean" ? 1 : 2;
      return x;
    }).sort(function (a, b) { return a.rank - b.rank || b.wait - a.wait || String(a.id).localeCompare(String(b.id), undefined, { numeric: true }); });
  }

  // ---------- floor / host / tv ----------
  var UI = {};
  function viewFloor() {
    main.textContent = "";
    var title = S.mode === "host" ? "host.title" : S.mode === "tv" ? "tv.title" : "floor.title";
    UI = { banners: h("div", { id: "banners" }), summary: h("p", { class: "big", id: "sum" }), fresh: h("span", { class: "tag hint", id: "fresh" }),
           list: h("ul", { class: "floor", "aria-label": t(title) }), body: h("div") };
    var bar = null;
    if (S.mode === "tv") {
      bar = h("div", { class: "tvbar" }, [h("h1", { text: t(title) }), h("span", { class: "hint", text: t("tv.hint") }),
        h("a", { href: "#/floor", text: t("tv.exit") })]);
    } else bar = h("h1", { class: "sr", text: t(title) });
    var sumLive = h("div", { class: "summary" }, [h("div", { role: "status", "aria-live": "polite" }, [UI.summary]), UI.fresh]);
    main.appendChild(bar); main.appendChild(UI.banners); main.appendChild(sumLive);
    if (S.mode !== "tv") main.appendChild(h("p", { class: "coach", text: t("coach.tip") }));
    main.appendChild(UI.body);
    // loading skeleton
    if (S.events == null) { UI.body.appendChild(skeleton()); }
    focusMain();
    loadLocs().then(function () { demoBanner(); return refresh(); }).then(function () { renderFloor(true); })
      .catch(function (e) { if (e.status === 401) logout(true); else { S.netErr = true; renderFloor(true); } });
    S.timer = setInterval(tick, POLL_MS);
  }
  function skeleton() {
    var d = h("div", { role: "status", "aria-busy": "true" }, [h("p", { class: "sr", text: t("loading") })]);
    for (var i = 0; i < 4; i++) d.appendChild(h("div", { class: "skel", "aria-hidden": "true" }));
    return d;
  }
  function interacting() {
    return (UI.list && UI.list.contains(document.activeElement)) || (Date.now() - S.lastPointer < 4000) || S.wrongOpen;
  }
  function tick() {
    if (S.mode === "settings" || S.mode === "login") return;
    refresh().then(function () { if (interacting()) { S.dirty = true; paintBanners(); } else renderFloor(false); });
  }
  document.addEventListener("pointerdown", function () { S.lastPointer = Date.now(); }, true);
  document.addEventListener("focusout", function () { setTimeout(function () { if (S.dirty && !interacting() && UI.list) { S.dirty = false; renderFloor(false); } }, 4100); });

  function mins(sec) { var m = Math.floor(sec / 60); return m < 1 ? t("ui.lt1") : num(m); }
  function isStale() { return S.devKnown && S.devAge > STALE_S; }

  function paintBanners() {
    var b = UI.banners; if (!b) return; b.textContent = "";
    if (S.netErr) {
      b.appendChild(h("div", { class: "banner bad", role: "alert" }, [icon("warn"), h("div", {}, [h("div", { class: "t", text: t("err.title") }), h("div", { text: t("err.body") }),
        h("button", { class: "btn sec", type: "button", text: t("err.retry"), onclick: function () { tick(); } })])]));
    }
    if (isStale()) {
      b.appendChild(h("div", { class: "banner", role: "status", id: "stale-banner" }, [icon("clean"), h("div", {}, [h("div", { class: "t", text: t("state.stale") }),
        h("div", { text: t("stale.body", { m: num(Math.max(1, Math.round(S.devAge / 60))) }) })])]));
    }
    var age = S.fetchedAt ? Math.round((Date.now() - S.fetchedAt) / 1000) : null;
    UI.fresh.textContent = age == null ? "" : t("ui.updated", { s: num(age) });
  }

  function renderFloor() {
    if (!UI.list || !UI.body) return;
    S.dirty = false;
    paintBanners();
    var body = UI.body; body.textContent = "";
    if (S.events == null) { // never loaded
      UI.summary.textContent = "";
      body.appendChild(S.netErr ? stateBox("warn", "err.title", "err.nodata", true) : skeleton());
      return;
    }
    var tables = derive(S.events), stale = isStale();
    var attn = tables.filter(function (x) { return x.cls === "attn" && !ackedFor(x); }).length;
    UI.summary.textContent = tables.length ? (attn ? t("floor.summary_attn", { n: num(attn) }) : t("floor.summary_ok")) : "";
    if (!tables.length) { body.appendChild(stateBox("idle", "empty.title", "empty.body")); return; }
    if (S.mode !== "tv") body.appendChild(h("p", { class: "tag hint", text: t("floor.sorted") }));
    UI.list.textContent = "";
    tables.forEach(function (x) { UI.list.appendChild(rowEl(x, stale)); });
    body.appendChild(UI.list);
    if (!attn) body.appendChild(h("p", { class: "hint", text: t("empty.quiet") }));
  }
  function stateBox(ic, title, text, retry) {
    return h("div", { class: "state", role: "status" }, [icon(ic), h("h2", { text: t(title) }), h("p", { text: t(text) }),
      retry ? h("button", { class: "btn", type: "button", text: t("err.retry"), onclick: tick }) : null]);
  }

  function ackedFor(x) { return x.attnId && S.acks[x.attnId]; }
  function rowEl(x, stale) {
    var cls = "row " + x.cls + (stale ? " stale" : "");
    var stText = x.st === "empty" ? t("state.empty") : x.st === "needs_clean" ? t("state.needs_clean") :
                 x.unc ? t("state.uncertain") : x.cls === "attn" ? t("state.attn") : t("state.ok");
    var li = h("li", { class: cls, "data-table": x.id, "data-status": x.cls });
    li.appendChild(icon(x.cls, "ico"));
    var meta = [];
    if (x.st === "seated" && x.party) meta.push(t("ui.party", { n: num(x.party) }));
    if (x.st === "seated") meta.push(x.sinceCheck ? t("wait.since_check") : t("wait.since_seat"));
    if (x.unc && x.st === "seated") meta.push(t("ui.last_known"));
    if (stale && x.st === "seated" && !x.unc) meta.push(t("ui.last_known"));
    li.appendChild(h("div", {}, [h("div", { class: "name", text: t("ui.table", { table: x.id }) }),
      h("span", { class: "st", text: stText }), meta.length ? h("span", { class: "meta", text: meta.join(" · ") }) : null]));
    if (x.st === "seated") li.appendChild(h("div", { class: "wait" }, [mins(x.wait), h("small", { text: t("ui.min") })]));
    var a = ackedFor(x);
    if (x.cls === "attn" && S.mode !== "tv") {
      if (a) li.appendChild(h("div", { class: "ackd", role: "status", text: (a === "wrong" ? t("act.wrong_sent") : t("act.acked")) }));
      else if (S.wrongOpen === x.attnId) li.appendChild(wrongPanel(x));
      else li.appendChild(h("div", { class: "acts" }, [
        h("button", { class: "btn", type: "button", "aria-label": t("act.ack_aria", { table: x.id }), text: t("act.ack"), onclick: function () { send(x, "ack"); } }),
        h("button", { class: "btn sec", type: "button", "aria-label": t("act.wrong_aria", { table: x.id }), text: t("act.wrong"), onclick: function () { S.wrongOpen = x.attnId; renderFloor(); var f = $('[data-table="' + x.id + '"] .reasons button'); if (f) f.focus(); } })]));
    }
    return li;
  }
  function wrongPanel(x) {
    var reasons = [["visited", "wrong.visited"], ["left", "wrong.left"], ["not_table", "wrong.notable"], ["other", "wrong.other"]];
    var box = h("div", { class: "acts reasons", role: "group", "aria-label": t("wrong.title") }, [h("p", { class: "meta", style: "flex-basis:100%;margin:0", text: t("wrong.title") })]);
    reasons.forEach(function (r) { box.appendChild(h("button", { class: "btn sec", type: "button", text: t(r[1]), onclick: function () { send(x, "wrong_alert", r[0]); } })); });
    box.appendChild(h("button", { class: "btn ghost", type: "button", text: t("wrong.cancel"), onclick: function () { S.wrongOpen = null; renderFloor(); } }));
    box.addEventListener("keydown", function (e) { if (e.key === "Escape") { S.wrongOpen = null; renderFloor(); } });
    return box;
  }
  // Optimistic action with a short undo window; corrections are only sent after it closes.
  function send(x, kind, reason) {
    var id = x.attnId; S.wrongOpen = null; S.acks[id] = kind === "ack" ? "ack" : "wrong";
    var cancelled = false, loc = S.loc.id;
    renderFloor();
    toast(kind === "ack" ? t("act.acked") : t("act.wrong_sent"), function () { cancelled = true; delete S.acks[id]; renderFloor(); });
    setTimeout(function () {
      if (cancelled) return;
      api("/corrections?" + qs({ location_id: loc, kind: kind }), { method: "POST", body: { table: x.id, event_id: id, reason: reason || null } })
        .catch(function (e) { delete S.acks[id]; renderFloor(); toast(e.status === 403 ? t("settings.err.forbidden") : t("act.fail")); });
    }, 4200);
  }

  // ---------- settings (owner) ----------
  function viewSettings() {
    main.textContent = "";
    main.appendChild(h("h1", { text: t("settings.title") }));
    main.appendChild(h("p", { class: "coach", text: t("settings.coach") }));
    var box = h("div", {}); main.appendChild(box); focusMain();
    loadLocs().then(function () {
      demoBanner();
      var l = S.loc; if (!l) return;
      var mode = l.staff_analytics, ret = h("input", { id: "ret", type: "number", min: "1", max: "365", inputmode: "numeric", value: String(l.retention_days), "aria-describedby": "ret-h" });
      var msg = h("p", { role: "status", class: "ok-msg" }), emsg = h("p", { role: "alert", class: "err" });
      var fs = h("fieldset", {}, [h("legend", { text: t("settings.sa.legend") })]);
      ["on", "anonymized", "off"].forEach(function (m) {
        var r = h("input", { type: "radio", name: "sa", value: m, id: "sa-" + m }); if (m === mode) r.checked = true;
        fs.appendChild(h("label", { class: "opt", for: "sa-" + m }, [r, h("div", {}, [h("b", { text: t("settings.sa." + m) }), h("span", { text: t("settings.sa." + m + "_d") })])]));
      });
      var save = h("button", { class: "btn", type: "button", text: t("settings.save"), onclick: function () {
        msg.textContent = ""; emsg.textContent = "";
        var sel = box.querySelector('input[name=sa]:checked');
        save.disabled = true;
        api("/locations/" + encodeURIComponent(l.id) + "/settings?" + qs({ staff_analytics: sel.value, retention_days: ret.value }), { method: "PATCH" })
          .then(function () { l.staff_analytics = sel.value; l.retention_days = parseInt(ret.value, 10); msg.textContent = t("settings.saved"); })
          .catch(function (e) { emsg.textContent = e.status === 403 ? t("settings.err.forbidden") : (e.status === 402 || e.status === 422) ? e.message : t("settings.err.generic"); })
          .then(function () { save.disabled = false; });
      } });
      box.appendChild(h("div", { class: "panel" }, [fs]));
      box.appendChild(h("div", { class: "panel" }, [h("label", { for: "ret", text: t("settings.ret") }), ret, h("p", { class: "hint", id: "ret-h", text: t("settings.ret_hint") })]));
      box.appendChild(save); box.appendChild(msg); box.appendChild(emsg);
    }).catch(function (e) { if (e.status === 401) logout(true); else box.appendChild(stateBox("warn", "err.title", "err.nodata", true)); });
  }

  // ---------- boot ----------
  function boot() {
    fetch("i18n.json").then(function (r) { return r.json(); }).catch(function () { return { en: {} }; }).then(function (d) {
      S.i18n = d;
      var p = new URLSearchParams(location.search), want = p.get("lang") || lget("ts.lang") || "en";
      S.token = sget("ts.tok");
      if (p.get("theme")) lset("ts.theme", p.get("theme"));
      $("#lang").addEventListener("change", function () { applyLang(this.value); go(); });
      $("#theme").addEventListener("click", function () { lset("ts.theme", theme() === "dark" ? "light" : "dark"); paintTheme(); });
      $("#logout").addEventListener("click", function () { logout(false); });
      window.addEventListener("hashchange", go);
      applyLang(d[want] ? want : "en"); go();
    });
  }
  boot();
})();
