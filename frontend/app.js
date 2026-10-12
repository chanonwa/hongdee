/* HongDee — single page management console.
   No build step, no framework: fetch + template strings + event delegation. */

(() => {
  "use strict";

  // ----------------------------------------------------------------- state --
  const S = {
    token: localStorage.getItem("hongdee_token") || null,
    user: null,
    route: "dashboard",
    currency: "GBP",
    renderId: 0,
    cache: {},
  };

  const app = () => document.getElementById("app");
  const tip = () => document.getElementById("chart-tip");

  // ------------------------------------------------------------------- api --
  async function api(path, { method = "GET", body, form } = {}) {
    const headers = {};
    if (S.token) headers.Authorization = `Bearer ${S.token}`;
    let payload;
    if (form) {
      headers["Content-Type"] = "application/x-www-form-urlencoded";
      payload = new URLSearchParams(form).toString();
    } else if (body !== undefined) {
      headers["Content-Type"] = "application/json";
      payload = JSON.stringify(body);
    }
    const res = await fetch(path, { method, headers, body: payload });
    if (res.status === 401) {
      logout();
      throw new Error("Session expired — please sign in again.");
    }
    if (res.status === 204) return null;
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const d = data.detail;
      throw new Error(
        typeof d === "string" ? d : Array.isArray(d) ? d.map((e) => e.msg).join("; ") : "Request failed"
      );
    }
    return data;
  }

  // --------------------------------------------------------------- helpers --
  const esc = (v) =>
    String(v ?? "").replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
    );

  const SYM = { GBP: "£", USD: "$", EUR: "€", THB: "฿" };
  const cur = (n, dp = 0) =>
    (SYM[S.currency] || "") +
    Number(n || 0).toLocaleString(undefined, { minimumFractionDigits: dp, maximumFractionDigits: dp });
  const pct = (n) => `${Number(n || 0).toFixed(1)}%`;
  const num = (n) => Number(n || 0).toLocaleString();
  const title = (s) => String(s || "").replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  // Calendar dates in the browser's timezone. toISOString() is UTC, which put "today" a day out
  // around midnight anywhere off UTC, and made addDays() fall a day short east of UTC (UK summer time included).
  const isoDate = (t) =>
    `${t.getFullYear()}-${String(t.getMonth() + 1).padStart(2, "0")}-${String(t.getDate()).padStart(2, "0")}`;
  const today = () => isoDate(new Date());
  const addDays = (iso, d) => {
    const t = new Date(iso + "T00:00:00");
    t.setDate(t.getDate() + d);
    return isoDate(t);
  };
  const fmtDate = (iso) =>
    iso ? new Date(iso + "T00:00:00").toLocaleDateString(undefined, { day: "2-digit", month: "short", year: "2-digit" }) : "—";

  function toast(msg, isErr = false) {
    document.querySelectorAll(".toast").forEach((t) => t.remove());
    const d = document.createElement("div");
    d.className = "toast" + (isErr ? " err" : "");
    d.textContent = msg;
    document.body.appendChild(d);
    setTimeout(() => d.remove(), 3600);
  }

  const STATUS_TONE = {
    paid: "good", active: "good", confirmed: "good", checked_in: "good", resolved: "good",
    closed: "good", available: "good", clean: "good", good: "good",
    open: "neutral", draft: "neutral", pending: "neutral", occupied: "neutral",
    checked_out: "neutral", reserved: "neutral", ended: "neutral", inspected: "neutral", info: "neutral",
    partial: "warning", in_progress: "warning", notice_given: "warning", dirty: "warning",
    maintenance: "warning", on_hold: "warning", medium: "warning", warning: "warning",
    high: "serious", serious: "serious", no_show: "serious",
    overdue: "critical", terminated: "critical", cancelled: "critical", urgent: "critical",
    critical: "critical", out_of_service: "critical",
  };
  const badge = (v) =>
    `<span class="badge ${STATUS_TONE[v] || "neutral"}"><span class="dot"></span>${esc(title(v))}</span>`;

  // ---------------------------------------------------------------- charts --
  function chartColors() {
    const cs = getComputedStyle(document.documentElement);
    return {
      s1: cs.getPropertyValue("--series-1").trim(),
      s2: cs.getPropertyValue("--series-2").trim(),
      s3: cs.getPropertyValue("--series-3").trim(),
      grid: cs.getPropertyValue("--grid").trim(),
      axis: cs.getPropertyValue("--axis").trim(),
      muted: cs.getPropertyValue("--text-muted").trim(),
      surface: cs.getPropertyValue("--surface-1").trim(),
    };
  }

  function niceTicks(max, count = 4) {
    if (max <= 0) return [0, 1];
    const raw = max / count;
    const mag = Math.pow(10, Math.floor(Math.log10(raw)));
    const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) || 10 * mag;
    const out = [];
    for (let v = 0; v <= max + step * 0.001; v += step) out.push(v);
    return out;
  }

  /* Multi-series line chart with a crosshair tooltip.
     One y-axis only — measures of different units get their own chart. */
  function lineChart(node, { labels, series, fmt = num, height = 210 }) {
    const c = chartColors();
    const W = node.clientWidth || 640;
    const padL = 52, padR = 14, padT = 10, padB = 26;
    const iw = Math.max(W - padL - padR, 40), ih = height - padT - padB;
    const maxV = Math.max(1, ...series.flatMap((s) => s.values));
    const ticks = niceTicks(maxV);
    const top = ticks[ticks.length - 1];
    const x = (i) => padL + (labels.length === 1 ? iw / 2 : (i * iw) / (labels.length - 1));
    const y = (v) => padT + ih - (v / top) * ih;

    const gridLines = ticks
      .map((t) => `<line x1="${padL}" x2="${padL + iw}" y1="${y(t)}" y2="${y(t)}" stroke="${c.grid}" stroke-width="1"/>
        <text x="${padL - 8}" y="${y(t) + 4}" text-anchor="end" font-size="10" fill="${c.muted}">${fmt(t)}</text>`)
      .join("");

    const step = Math.ceil(labels.length / 7);
    const xLabels = labels
      .map((l, i) => (i % step === 0 || i === labels.length - 1
        ? `<text x="${x(i)}" y="${height - 6}" text-anchor="middle" font-size="10" fill="${c.muted}">${esc(l)}</text>` : ""))
      .join("");

    const paths = series
      .map((s) => {
        const d = s.values.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
        return `<path d="${d}" fill="none" stroke="${s.color}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>`;
      })
      .join("");

    const dots = series
      .map((s) => s.values.map((v, i) =>
        `<circle cx="${x(i)}" cy="${y(v)}" r="4" fill="${s.color}" stroke="${c.surface}" stroke-width="2" opacity="0" data-dot="${i}"/>`).join(""))
      .join("");

    node.innerHTML =
      (series.length > 1
        ? `<div class="chart-legend">${series
            .map((s) => `<span class="key"><span class="swatch" style="background:${s.color}"></span>${esc(s.name)}</span>`)
            .join("")}</div>`
        : "") +
      `<svg class="chart" viewBox="0 0 ${W} ${height}" role="img" aria-label="line chart">
         ${gridLines}${xLabels}
         <line class="cross" x1="0" x2="0" y1="${padT}" y2="${padT + ih}" stroke="${c.axis}" stroke-width="1" opacity="0"/>
         ${paths}${dots}
         <rect x="${padL}" y="${padT}" width="${iw}" height="${ih}" fill="transparent" class="hit"/>
       </svg>`;

    const svg = node.querySelector("svg");
    const cross = svg.querySelector(".cross");
    const allDots = [...svg.querySelectorAll("[data-dot]")];
    svg.querySelector(".hit").addEventListener("mousemove", (ev) => {
      const r = svg.getBoundingClientRect();
      const px = ((ev.clientX - r.left) / r.width) * W;
      let i = Math.round(((px - padL) / iw) * (labels.length - 1));
      i = Math.max(0, Math.min(labels.length - 1, i));
      cross.setAttribute("x1", x(i));
      cross.setAttribute("x2", x(i));
      cross.setAttribute("opacity", "1");
      allDots.forEach((d) => d.setAttribute("opacity", d.dataset.dot == i ? "1" : "0"));
      showTip(ev, `<div class="t-head">${esc(labels[i])}</div>` +
        series.map((s) => `<div class="t-row"><span>${esc(s.name)}</span><span>${fmt(s.values[i])}</span></div>`).join(""));
    });
    svg.addEventListener("mouseleave", () => {
      cross.setAttribute("opacity", "0");
      allDots.forEach((d) => d.setAttribute("opacity", "0"));
      hideTip();
    });
  }

  /* Horizontal bar chart — magnitude by identity. 4px rounded data-end. */
  function barChart(node, { rows, color, fmt = num, sub }) {
    const c = chartColors();
    const W = node.clientWidth || 480;
    const rowH = 30, labelW = Math.min(150, Math.max(90, W * 0.3));
    const height = Math.max(rows.length * rowH + 8, 40);
    const maxV = Math.max(1, ...rows.map((r) => r.value));
    const barW = Math.max(W - labelW - 78, 40);
    const col = color || chartColors().s1;

    const bars = rows
      .map((r, i) => {
        const w = Math.max((r.value / maxV) * barW, 2);
        const yy = i * rowH + 6;
        return `<text x="0" y="${yy + 13}" font-size="12" fill="${c.muted}">${esc(r.label)}</text>
          <rect x="${labelW}" y="${yy + 3}" width="${w}" height="14" rx="4" fill="${col}" data-bar="${i}"/>
          <text x="${labelW + w + 8}" y="${yy + 14}" font-size="11.5" fill="${c.muted}">${fmt(r.value)}</text>`;
      })
      .join("");

    node.innerHTML = `<svg class="chart" viewBox="0 0 ${W} ${height}" role="img" aria-label="bar chart">${bars}</svg>`;
    node.querySelectorAll("[data-bar]").forEach((b) => {
      b.addEventListener("mousemove", (ev) => {
        const r = rows[+b.dataset.bar];
        showTip(ev, `<div class="t-head">${esc(r.label)}</div>
          <div class="t-row"><span>${esc(sub?.primary || "Value")}</span><span>${fmt(r.value)}</span></div>` +
          (sub && r.secondary !== undefined
            ? `<div class="t-row"><span>${esc(sub.secondary)}</span><span>${fmt(r.secondary)}</span></div>` : ""));
      });
      b.addEventListener("mouseleave", hideTip);
    });
  }

  function showTip(ev, html) {
    const t = tip();
    t.innerHTML = html;
    t.style.opacity = "1";
    const pad = 14;
    let left = ev.clientX + pad, topY = ev.clientY + pad;
    const r = t.getBoundingClientRect();
    if (left + r.width > window.innerWidth - 8) left = ev.clientX - r.width - pad;
    if (topY + r.height > window.innerHeight - 8) topY = ev.clientY - r.height - pad;
    t.style.left = left + "px";
    t.style.top = topY + "px";
  }
  const hideTip = () => (tip().style.opacity = "0");

  // ----------------------------------------------------------------- modal --
  function modal(heading, fieldsHtml, onSubmit) {
    const back = document.createElement("div");
    back.className = "modal-backdrop";
    back.innerHTML = `<div class="modal"><h2>${esc(heading)}</h2>
      <form id="modal-form">${fieldsHtml}
        <div class="modal-actions">
          <button type="button" class="btn" data-close>Cancel</button>
          <button type="submit" class="btn primary">Save</button>
        </div>
      </form></div>`;
    document.body.appendChild(back);
    const close = () => back.remove();
    back.querySelector("[data-close]").onclick = close;
    back.onclick = (e) => { if (e.target === back) close(); };
    back.querySelector("#modal-form").onsubmit = async (e) => {
      e.preventDefault();
      const fd = Object.fromEntries(new FormData(e.target).entries());
      try {
        await onSubmit(fd);
        close();
      } catch (err) {
        toast(err.message, true);
      }
    };
    return close;
  }

  const F = {
    text: (n, l, v = "", req = true, type = "text") =>
      `<div class="field"><label>${esc(l)}</label><input name="${n}" type="${type}" value="${esc(v)}" ${req ? "required" : ""}></div>`,
    number: (n, l, v = "", step = "0.01") =>
      `<div class="field"><label>${esc(l)}</label><input name="${n}" type="number" step="${step}" value="${esc(v)}" required></div>`,
    date: (n, l, v = "") => F.text(n, l, v, true, "date"),
    area: (n, l, v = "") =>
      `<div class="field"><label>${esc(l)}</label><textarea name="${n}" rows="2">${esc(v)}</textarea></div>`,
    select: (n, l, opts, v = "") =>
      `<div class="field"><label>${esc(l)}</label><select name="${n}">${opts
        .map((o) => {
          const [val, lab] = Array.isArray(o) ? o : [o, title(o)];
          return `<option value="${esc(val)}" ${String(val) === String(v) ? "selected" : ""}>${esc(lab)}</option>`;
        })
        .join("")}</select></div>`,
    row: (a, b) => `<div class="field-row">${a}${b}</div>`,
  };

  // ------------------------------------------------------------------ auth --
  function logout() {
    S.token = null;
    S.user = null;
    localStorage.removeItem("hongdee_token");
    renderLogin();
  }

  function renderLogin(msg) {
    app().innerHTML = `<div class="login-wrap"><div class="login-card">
      <h1>Hong<span style="color:var(--series-1)">Dee</span></h1>
      <p class="sub">Apartment &amp; hostel management console</p>
      <form id="login-form">
        ${F.text("username", "Email", "admin@hongdee.co.uk", true, "email")}
        ${F.text("password", "Password", "admin1234", true, "password")}
        <button class="btn primary" style="width:100%;margin-top:6px" type="submit">Sign in</button>
      </form>
      ${msg ? `<p style="color:var(--critical);font-size:12.5px;margin-top:12px">${esc(msg)}</p>` : ""}
      <div class="demo-accounts"><strong>Demo accounts</strong>
        <button data-acct="admin@hongdee.co.uk|admin1234">Admin — full access</button>
        <button data-acct="manager@hongdee.co.uk|manager1234">Manager — no user admin</button>
        <button data-acct="frontdesk@hongdee.co.uk|frontdesk1234">Front desk — operations only</button>
        <button data-acct="owner@hongdee.co.uk|viewer1234">Owner — read only</button>
      </div>
    </div></div>`;

    app().querySelectorAll("[data-acct]").forEach((b) => {
      b.onclick = () => {
        const [u, p] = b.dataset.acct.split("|");
        app().querySelector('[name="username"]').value = u;
        app().querySelector('[name="password"]').value = p;
      };
    });
    app().querySelector("#login-form").onsubmit = async (e) => {
      e.preventDefault();
      const fd = Object.fromEntries(new FormData(e.target).entries());
      try {
        const r = await api("/api/auth/login", { method: "POST", form: fd });
        S.token = r.access_token;
        S.user = r.user;
        localStorage.setItem("hongdee_token", r.access_token);
        renderShell();
      } catch (err) {
        renderLogin(err.message);
      }
    };
  }

  // ----------------------------------------------------------------- shell --
  const NAV = [
    ["dashboard", "Dashboard", "◲"],
    ["frontdesk", "Front desk", "◷"],
    ["portfolio", "Properties & units", "▤"],
    ["people", "Tenants & guests", "☺"],
    ["leases", "Leases", "✎"],
    ["bookings", "Bookings", "▦"],
    ["billing", "Billing & arrears", "£"],
    ["maintenance", "Maintenance", "⚙"],
    ["analytics", "Analytics", "◪"],
  ];

  function renderShell() {
    app().innerHTML = `<div class="shell">
      <nav class="sidebar">
        <div class="brand">Hong<span>Dee</span></div>
        ${NAV.map(([k, l, i]) => `<button class="nav-item" data-route="${k}"><span class="ic">${i}</span>${l}</button>`).join("")}
        <div class="nav-spacer"></div>
        <button class="nav-item" id="theme-toggle"><span class="ic">◐</span>Theme</button>
        <button class="nav-item" id="logout"><span class="ic">⏻</span>Sign out</button>
        <div style="padding:10px;font-size:11.5px;color:var(--text-muted)">
          ${esc(S.user?.full_name || "")}<br>${esc(title(S.user?.role || ""))}
        </div>
      </nav>
      <main class="main" id="view"><div class="spinner">Loading…</div></main>
    </div>`;

    app().querySelectorAll("[data-route]").forEach((b) => (b.onclick = () => go(b.dataset.route)));
    app().querySelector("#logout").onclick = logout;
    app().querySelector("#theme-toggle").onclick = () => {
      const cur = document.documentElement.getAttribute("data-theme");
      const next = cur === "dark" ? "light" : "dark";
      document.documentElement.setAttribute("data-theme", next);
      localStorage.setItem("hongdee_theme", next);
      go(S.route);
    };
    go(S.route);
  }

  /* Views are async. If the user navigates again mid-load, the older render
     must not paint over the newer one — so writes go through a guard that
     drops anything from a superseded render. */
  function go(route) {
    S.route = route;
    const id = ++S.renderId;
    document.querySelectorAll(".nav-item[data-route]").forEach((b) =>
      b.classList.toggle("active", b.dataset.route === route)
    );
    const host = document.getElementById("view");
    host.innerHTML = `<div class="spinner">Loading…</div>`;

    const view = {
      get stale() { return id !== S.renderId; },
      set innerHTML(html) { if (!this.stale) host.innerHTML = html; },
      get innerHTML() { return host.innerHTML; },
      querySelector: (s) => host.querySelector(s),
      querySelectorAll: (s) => host.querySelectorAll(s),
    };

    (VIEWS[route] || VIEWS.dashboard)(view).catch((e) => {
      view.innerHTML = `<div class="card"><h2>Something went wrong</h2><p class="muted">${esc(e.message)}</p></div>`;
    });
  }

  const head = (h1, sub, actions = "") =>
    `<div class="page-head"><div><h1>${esc(h1)}</h1><div class="sub">${esc(sub)}</div></div>
     <div class="head-actions">${actions}</div></div>`;

  const table = (cols, rows) =>
    `<div class="table-wrap"><table><thead><tr>${cols
      .map((c) => `<th class="${c.num ? "num" : ""}">${esc(c.label)}</th>`)
      .join("")}</tr></thead><tbody>${
      rows.length
        ? rows.join("")
        : `<tr><td colspan="${cols.length}"><div class="empty">Nothing here yet.</div></td></tr>`
    }</tbody></table></div>`;

  // ------------------------------------------------------------------ views --
  const VIEWS = {};

  VIEWS.dashboard = async (view) => {
    const [k, trend, recs, perf, mix] = await Promise.all([
      api("/api/analytics/summary"),
      api("/api/analytics/trend?months=12"),
      api("/api/analytics/recommendations"),
      api("/api/analytics/property-performance"),
      api("/api/analytics/channel-mix"),
    ]);
    S.currency = k.currency;

    const kpi = (label, value, note, tone = "") =>
      `<div class="kpi"><div class="label">${esc(label)}</div><div class="value">${value}</div>
       <div class="note ${tone}">${note}</div></div>`;

    view.innerHTML =
      head("Dashboard", `Portfolio position as at ${fmtDate(k.as_of)}`,
        `<button class="btn" id="rent-run">Run monthly rent billing</button>`) +
      `<div class="kpi-grid">
        ${kpi("Occupancy", pct(k.occupancy_rate), `long stay ${pct(k.long_stay_occupancy)} · short stay ${pct(k.short_stay_occupancy)}`)}
        ${kpi("Monthly recurring rent", cur(k.monthly_recurring_revenue), `${k.active_leases} active tenancies`)}
        ${kpi("Collected this month", cur(k.collected_this_month), `${pct(k.collection_rate)} of ${cur(k.billed_this_month)} billed`,
          k.collection_rate >= 90 ? "good" : k.collection_rate < 70 ? "bad" : "")}
        ${kpi("Outstanding", cur(k.outstanding_balance), `${k.overdue_invoices} invoice(s) overdue`, k.overdue_invoices ? "bad" : "good")}
        ${kpi("ADR / RevPAR", `${cur(k.adr)} / ${cur(k.revpar)}`, "trailing 30 nights, short stay")}
        ${kpi("Net operating income", cur(k.net_operating_income), `after ${cur(k.expenses_this_month)} of costs this month`)}
        ${kpi("Today", `${k.arrivals_today} in · ${k.departures_today} out`, "arrivals and departures")}
        ${kpi("Maintenance", num(k.open_tickets), `${k.urgent_tickets} urgent`, k.urgent_tickets ? "bad" : "")}
      </div>

      <div class="grid-3">
        <div style="display:grid;gap:14px">
          <div class="card">
            <h2>Billed vs collected</h2>
            <div class="card-sub">Last 12 months, all revenue streams</div>
            <div id="ch-money"></div>
          </div>
          <div class="card">
            <h2>Occupancy</h2>
            <div class="card-sub">Point-in-time, whole portfolio</div>
            <div id="ch-occ"></div>
          </div>
          <div class="card">
            <h2>Short-stay revenue by channel</h2>
            <div class="card-sub">Last 6 months — hover for commission paid</div>
            <div id="ch-mix"></div>
          </div>
        </div>
        <div class="card">
          <h2>Where the money is leaking</h2>
          <div class="card-sub">Generated from live portfolio data</div>
          <div id="recs"></div>
        </div>
      </div>

      <div class="card" style="margin-top:14px">
        <h2>Property performance</h2>
        <div class="card-sub">Year to date</div>
        ${table(
          [{ label: "Property" }, { label: "Type" }, { label: "Units", num: 1 }, { label: "Occupancy", num: 1 },
           { label: "Billed", num: 1 }, { label: "Collected", num: 1 }, { label: "Costs", num: 1 },
           { label: "NOI", num: 1 }, { label: "Arrears", num: 1 }],
          perf.map((p) => `<tr>
            <td><strong>${esc(p.property_name)}</strong></td>
            <td>${badge(p.type)}</td>
            <td class="num">${p.units}</td>
            <td class="num">${pct(p.occupancy_rate)}</td>
            <td class="num">${cur(p.revenue_ytd)}</td>
            <td class="num">${cur(p.collected_ytd)}</td>
            <td class="num">${cur(p.expenses_ytd)}</td>
            <td class="num" style="color:${p.noi_ytd >= 0 ? "var(--good-ink)" : "var(--critical)"}">${cur(p.noi_ytd)}</td>
            <td class="num">${cur(p.arrears)}</td></tr>`)
        )}
      </div>`;

    const c = chartColors();
    lineChart(document.getElementById("ch-money"), {
      labels: trend.map((t) => t.period.slice(2)),
      series: [
        { name: "Billed", color: c.s1, values: trend.map((t) => t.revenue) },
        { name: "Collected", color: c.s2, values: trend.map((t) => t.collected) },
        { name: "Operating costs", color: c.s3, values: trend.map((t) => t.expenses) },
      ],
      fmt: (v) => cur(v),
    });
    lineChart(document.getElementById("ch-occ"), {
      labels: trend.map((t) => t.period.slice(2)),
      series: [{ name: "Occupancy", color: c.s1, values: trend.map((t) => t.occupancy) }],
      fmt: (v) => `${Math.round(v)}%`,
      height: 190,
    });
    barChart(document.getElementById("ch-mix"), {
      rows: mix.map((m) => ({ label: title(m.label), value: m.value, secondary: m.secondary })),
      fmt: (v) => cur(v),
      sub: { primary: "Revenue", secondary: "Commission" },
    });

    const ICON = { critical: "⛔", warning: "⚠️", info: "ℹ️" };
    document.getElementById("recs").innerHTML =
      recs.length
        ? recs.map((r) => `<div class="rec">
            <div class="icon">${ICON[r.severity]}</div>
            <div class="body">
              <div class="title">${esc(r.title)} ${badge(r.severity)}</div>
              <div class="detail">${esc(r.detail)}</div>
              ${r.impact_estimate ? `<div class="impact">Estimated value at stake: ${cur(r.impact_estimate)}</div>` : ""}
            </div></div>`).join("")
        : `<div class="empty">No issues detected. Nice.</div>`;

    document.getElementById("rent-run").onclick = () => {
      const now = new Date();
      modal(
        "Run monthly rent billing",
        F.row(F.number("year", "Year", now.getFullYear(), "1"), F.number("month", "Month", now.getMonth() + 1, "1")) +
          `<p class="muted" style="font-size:12.5px">Raises one rent invoice per active tenancy. Safe to run twice — existing invoices are skipped.</p>`,
        async (fd) => {
          const r = await api("/api/billing/rent-run", {
            method: "POST",
            body: { year: +fd.year, month: +fd.month },
          });
          toast(`${r.created} invoice(s) raised worth ${cur(r.total_billed)} · ${r.skipped} already existed`);
          go("dashboard");
        }
      );
    };
  };

  // ---------------------------------------------------------------- frontdesk
  VIEWS.frontdesk = async (view) => {
    const board = await api("/api/bookings/today");
    // The action column only offers the step the booking is actually ready for.
    const actionFor = (b, phase) => {
      if (phase === "in") return b.status === "checked_in" ? null : "in";
      if (phase === "out") return b.status === "checked_in" ? "out" : "in";
      return null;
    };
    const row = (b, action) => `<tr>
      <td><strong>${esc(b.guest_name)}</strong><div class="muted" style="font-size:12px">${esc(b.reference)}</div></td>
      <td>${esc(b.property_name)} · ${esc(b.unit_name)}${b.bed_label ? ` · ${esc(b.bed_label)}` : ""}</td>
      <td class="nowrap">${fmtDate(b.check_in)} → ${fmtDate(b.check_out)}</td>
      <td class="num">${b.nights}</td>
      <td class="num" style="${b.balance > 0 ? "color:var(--critical)" : ""}">${cur(b.balance, 2)}</td>
      <td>${badge(b.status)}</td>
      <td>${action
        ? `<button class="btn sm" data-act="${action}" data-id="${b.id}">${action === "in" ? "Check in" : "Check out"}</button>`
        : `<span class="muted" style="font-size:12px">—</span>`}</td>
    </tr>`;
    const cols = [{ label: "Guest" }, { label: "Room" }, { label: "Stay" }, { label: "Nights", num: 1 },
                  { label: "Balance", num: 1 }, { label: "Status" }, { label: "" }];

    view.innerHTML =
      head("Front desk", `Arrivals, departures and in-house guests for ${fmtDate(board.date)}`) +
      `<div class="card"><h2>Arriving today (${board.arrivals.length})</h2>
        <div class="card-sub">Take payment on arrival where a balance is showing</div>
        ${table(cols, board.arrivals.map((b) => row(b, actionFor(b, "in"))))}</div>
       <div class="card" style="margin-top:14px"><h2>Departing today (${board.departures.length})</h2>
        <div class="card-sub">Checking out flags the room for housekeeping</div>
        ${table(cols, board.departures.map((b) => row(b, actionFor(b, "out"))))}</div>
       <div class="card" style="margin-top:14px"><h2>In house (${board.in_house.length})</h2>
        <div class="card-sub">Currently staying — check out from here too if a guest leaves early</div>
        ${table(cols, board.in_house.map((b) => row(b, "out")))}</div>`;

    view.querySelectorAll("[data-act]").forEach((b) => {
      b.onclick = async () => {
        try {
          await api(`/api/bookings/${b.dataset.id}/check-${b.dataset.act === "in" ? "in" : "out"}`, { method: "POST" });
          toast(b.dataset.act === "in" ? "Checked in" : "Checked out");
          go("frontdesk");
        } catch (e) {
          toast(e.message, true);
        }
      };
    });
  };

  // ---------------------------------------------------------------- portfolio
  VIEWS.portfolio = async (view) => {
    const [props, units] = await Promise.all([api("/api/properties"), api("/api/units")]);
    S.cache.props = props;
    S.cache.units = units;

    view.innerHTML =
      head("Properties & units", `${props.length} properties · ${units.length} lettable spaces`,
        `<button class="btn" id="add-prop">New property</button><button class="btn primary" id="add-unit">New unit</button>`) +
      `<div class="card"><h2>Properties</h2><div class="card-sub">Buildings in the portfolio</div>
        ${table(
          [{ label: "Name" }, { label: "Code" }, { label: "Type" }, { label: "City" }, { label: "Units", num: 1 }, { label: "Notes" }],
          props.map((p) => `<tr><td><strong>${esc(p.name)}</strong></td><td class="mono">${esc(p.code)}</td>
            <td>${badge(p.type)}</td><td>${esc(p.city || "—")}</td><td class="num">${p.unit_count}</td>
            <td class="muted">${esc((p.notes || "").slice(0, 70))}</td></tr>`)
        )}</div>

      <div class="card" style="margin-top:14px"><h2>Units</h2>
        <div class="card-sub">Apartments are let on leases; dorms and private rooms sell nightly</div>
        <div class="filters">
          <select id="f-prop"><option value="">All properties</option>${props.map((p) => `<option value="${p.id}">${esc(p.name)}</option>`).join("")}</select>
          <select id="f-type"><option value="">All types</option>${["apartment", "studio", "private_room", "dorm"].map((t) => `<option value="${t}">${title(t)}</option>`).join("")}</select>
          <select id="f-status"><option value="">Any status</option>${["available", "occupied", "reserved", "maintenance", "offline"].map((t) => `<option value="${t}">${title(t)}</option>`).join("")}</select>
        </div>
        <div id="unit-table"></div></div>`;

    const draw = () => {
      const fp = view.querySelector("#f-prop").value;
      const ft = view.querySelector("#f-type").value;
      const fs = view.querySelector("#f-status").value;
      const rows = units.filter((u) =>
        (!fp || String(u.property_id) === fp) && (!ft || u.type === ft) && (!fs || u.status === fs));
      view.querySelector("#unit-table").innerHTML = table(
        [{ label: "Property" }, { label: "Unit" }, { label: "Type" }, { label: "Beds", num: 1 },
         { label: "Capacity", num: 1 }, { label: "Market rent /mo", num: 1 }, { label: "Nightly", num: 1 },
         { label: "Status" }, { label: "Housekeeping" }],
        rows.map((u) => `<tr>
          <td>${esc(u.property_name)}</td>
          <td><strong>${esc(u.name)}</strong></td>
          <td>${badge(u.type)}</td>
          <td class="num">${u.beds.length || "—"}</td>
          <td class="num">${u.capacity}</td>
          <td class="num">${u.market_rent ? cur(u.market_rent) : "—"}</td>
          <td class="num">${u.nightly_rate ? cur(u.nightly_rate) : "—"}</td>
          <td>${badge(u.status)}</td>
          <td>${badge(u.housekeeping)}</td></tr>`)
      );
    };
    ["#f-prop", "#f-type", "#f-status"].forEach((s) => (view.querySelector(s).onchange = draw));
    draw();

    view.querySelector("#add-prop").onclick = () =>
      modal("New property",
        F.text("name", "Name") + F.row(F.text("code", "Short code"), F.select("type", "Type", ["apartment", "hostel", "mixed"])) +
        F.text("address_line1", "Address", "", false) + F.row(F.text("city", "City", "", false), F.text("postcode", "Postcode", "", false)) +
        F.text("country", "Country", "United Kingdom", false),
        async (fd) => { await api("/api/properties", { method: "POST", body: fd }); toast("Property created"); go("portfolio"); });

    view.querySelector("#add-unit").onclick = () =>
      modal("New unit",
        F.select("property_id", "Property", props.map((p) => [p.id, p.name])) +
        F.row(F.text("name", "Unit name / number"), F.select("type", "Type", ["apartment", "studio", "private_room", "dorm"])) +
        F.row(F.number("bedrooms", "Bedrooms", 1, "1"), F.number("capacity", "Capacity", 2, "1")) +
        F.row(F.number("market_rent", "Market rent /month", 0), F.number("nightly_rate", "Nightly rate", 0)) +
        F.number("bed_count", "Beds to create (dorms)", 0, "1"),
        async (fd) => {
          await api("/api/units", { method: "POST", body: {
            property_id: +fd.property_id, name: fd.name, type: fd.type,
            bedrooms: +fd.bedrooms, capacity: +fd.capacity,
            market_rent: +fd.market_rent || null, nightly_rate: +fd.nightly_rate || null,
            bed_count: +fd.bed_count } });
          toast("Unit created"); go("portfolio");
        });
  };

  // ------------------------------------------------------------------- people
  VIEWS.people = async (view) => {
    const load = async (q = "", type = "") =>
      api(`/api/people?limit=300${type ? `&type=${type}` : ""}${q ? `&q=${encodeURIComponent(q)}` : ""}`);
    const people = await load();

    view.innerHTML =
      head("Tenants & guests", "One contact record shared by long stays and short stays",
        `<button class="btn primary" id="add">New contact</button>`) +
      `<div class="card">
        <div class="filters">
          <input id="q" placeholder="Search name, email or phone" style="min-width:240px">
          <select id="type"><option value="">Everyone</option><option value="tenant">Tenants</option>
            <option value="guest">Guests</option><option value="prospect">Prospects</option></select>
        </div><div id="tbl"></div></div>`;

    const draw = (rows) => {
      view.querySelector("#tbl").innerHTML = table(
        [{ label: "Name" }, { label: "Type" }, { label: "Email" }, { label: "Phone" },
         { label: "Nationality" }, { label: "Screening" }, { label: "Balance", num: 1 }],
        rows.map((p) => `<tr>
          <td><strong>${esc(p.full_name)}</strong></td>
          <td>${badge(p.type)}</td>
          <td class="muted">${esc(p.email || "—")}</td>
          <td class="muted">${esc(p.phone || "—")}</td>
          <td>${esc(p.nationality || "—")}</td>
          <td>${p.screening_status ? badge(p.screening_status === "passed" ? "good" : "warning") : "—"}</td>
          <td class="num" style="${p.balance > 0 ? "color:var(--critical)" : ""}">${cur(p.balance, 2)}</td></tr>`)
      );
    };
    draw(people);

    let t;
    const refresh = async () => {
      const rows = await load(view.querySelector("#q").value, view.querySelector("#type").value);
      draw(rows);
    };
    view.querySelector("#q").oninput = () => { clearTimeout(t); t = setTimeout(refresh, 250); };
    view.querySelector("#type").onchange = refresh;

    view.querySelector("#add").onclick = () =>
      modal("New contact",
        F.text("full_name", "Full name") +
        F.row(F.select("type", "Type", ["tenant", "guest", "prospect"]), F.text("nationality", "Nationality", "", false)) +
        F.row(F.text("email", "Email", "", false, "email"), F.text("phone", "Phone", "", false)) +
        F.text("id_document", "ID / passport number", "", false),
        async (fd) => {
          Object.keys(fd).forEach((k) => { if (fd[k] === "") delete fd[k]; });
          await api("/api/people", { method: "POST", body: fd }); toast("Contact created"); go("people");
        });
  };

  // ------------------------------------------------------------------- leases
  VIEWS.leases = async (view) => {
    const [leases, units, people] = await Promise.all([
      api("/api/leases"), api("/api/units?type=apartment"), api("/api/people?type=tenant&limit=300"),
    ]);
    const studios = await api("/api/units?type=studio");
    const lettable = [...units, ...studios];

    view.innerHTML =
      head("Leases", `${leases.filter((l) => l.status === "active").length} active tenancies`,
        `<button class="btn primary" id="add">New lease</button>`) +
      `<div class="card">
        <div class="filters"><select id="st"><option value="">All statuses</option>
          ${["active", "notice_given", "ended", "terminated", "draft"].map((s) => `<option value="${s}">${title(s)}</option>`).join("")}
        </select></div><div id="tbl"></div></div>`;

    const draw = () => {
      const st = view.querySelector("#st").value;
      const rows = leases.filter((l) => !st || l.status === st);
      view.querySelector("#tbl").innerHTML = table(
        [{ label: "Tenant" }, { label: "Unit" }, { label: "Term" }, { label: "Rent /mo", num: 1 },
         { label: "Bill day", num: 1 }, { label: "Deposit", num: 1 }, { label: "Balance", num: 1 }, { label: "Status" }],
        rows.map((l) => `<tr>
          <td><strong>${esc(l.tenant_name)}</strong></td>
          <td>${esc(l.property_name)} · ${esc(l.unit_name)}</td>
          <td class="nowrap">${fmtDate(l.start_date)} → ${l.end_date ? fmtDate(l.end_date) : "open"}</td>
          <td class="num">${cur(l.rent_amount)}</td>
          <td class="num">${l.billing_day}</td>
          <td class="num">${cur(l.deposit_amount)}</td>
          <td class="num" style="${l.balance > 0 ? "color:var(--critical)" : ""}">${cur(l.balance, 2)}</td>
          <td>${badge(l.status)}</td></tr>`)
      );
    };
    view.querySelector("#st").onchange = draw;
    draw();

    view.querySelector("#add").onclick = () =>
      modal("New lease",
        F.select("unit_id", "Unit", lettable.map((u) => [u.id, `${u.property_name} · ${u.name}`])) +
        F.select("person_id", "Tenant", people.map((p) => [p.id, p.full_name])) +
        F.row(F.date("start_date", "Start", today()), F.date("end_date", "End", addDays(today(), 365))) +
        F.row(F.number("rent_amount", "Rent per month"), F.number("billing_day", "Billing day (1-28)", 1, "1")) +
        F.number("deposit_amount", "Deposit", 0),
        async (fd) => {
          await api("/api/leases", { method: "POST", body: {
            unit_id: +fd.unit_id, person_id: +fd.person_id, start_date: fd.start_date,
            end_date: fd.end_date || null, rent_amount: +fd.rent_amount,
            billing_day: +fd.billing_day, deposit_amount: +fd.deposit_amount } });
          toast("Lease created"); go("leases");
        });
  };

  // ----------------------------------------------------------------- bookings
  VIEWS.bookings = async (view) => {
    const from = addDays(today(), -14);
    const [bookings, guests] = await Promise.all([
      api(`/api/bookings?date_from=${from}&limit=400`), api("/api/people?type=guest&limit=300"),
    ]);

    view.innerHTML =
      head("Bookings", "Short-stay reservations across dorms and private rooms",
        `<button class="btn" id="check-avail">Check availability</button><button class="btn primary" id="add">New booking</button>`) +
      `<div class="card">
        <div class="filters"><select id="st"><option value="">All statuses</option>
          ${["pending", "confirmed", "checked_in", "checked_out", "cancelled", "no_show"].map((s) => `<option value="${s}">${title(s)}</option>`).join("")}
        </select><span class="muted" style="font-size:12.5px">Stays from ${fmtDate(from)} onward</span>
        <span class="muted" id="count" style="font-size:12.5px"></span></div>
        <div id="tbl"></div></div>`;

    const draw = () => {
      const st = view.querySelector("#st").value;
      const all = bookings.filter((b) => !st || b.status === st);
      const LIMIT = 60;
      const rows = all.slice(0, LIMIT);
      view.querySelector("#count").textContent =
        all.length > LIMIT ? `· showing ${LIMIT} of ${all.length}` : `· ${all.length} booking(s)`;
      view.querySelector("#tbl").innerHTML = table(
        [{ label: "Ref" }, { label: "Guest" }, { label: "Room" }, { label: "Stay" }, { label: "Nights", num: 1 },
         { label: "Rate", num: 1 }, { label: "Total", num: 1 }, { label: "Channel" }, { label: "Balance", num: 1 }, { label: "Status" }],
        rows.map((b) => `<tr>
          <td class="mono">${esc(b.reference)}</td>
          <td><strong>${esc(b.guest_name)}</strong></td>
          <td>${esc(b.unit_name)}${b.bed_label ? ` · ${esc(b.bed_label)}` : ""}</td>
          <td class="nowrap">${fmtDate(b.check_in)} → ${fmtDate(b.check_out)}</td>
          <td class="num">${b.nights}</td>
          <td class="num">${cur(b.nightly_rate, 2)}</td>
          <td class="num">${cur(b.total_amount, 2)}</td>
          <td>${esc(title(b.channel))}${b.commission_rate ? `<span class="muted"> ${Math.round(b.commission_rate * 100)}%</span>` : ""}</td>
          <td class="num" style="${b.balance > 0 ? "color:var(--critical)" : ""}">${cur(b.balance, 2)}</td>
          <td>${badge(b.status)}</td></tr>`)
      );
    };
    view.querySelector("#st").onchange = draw;
    draw();

    const availabilityFields = (ci, co) =>
      F.row(F.date("check_in", "Check in", ci), F.date("check_out", "Check out", co));

    view.querySelector("#check-avail").onclick = () =>
      modal("Check availability", availabilityFields(today(), addDays(today(), 2)), async (fd) => {
        const rows = await api(`/api/bookings/availability?check_in=${fd.check_in}&check_out=${fd.check_out}`);
        modal(`Available ${fmtDate(fd.check_in)} → ${fmtDate(fd.check_out)}`,
          `<div class="table-wrap"><table><thead><tr><th>Property</th><th>Unit</th><th>Type</th><th class="num">Free beds</th><th class="num">Rate</th></tr></thead>
           <tbody>${rows.map((r) => `<tr><td>${esc(r.property_name)}</td><td>${esc(r.unit_name)}</td><td>${badge(r.type)}</td>
             <td class="num">${r.free_beds.length || (r.whole_unit_available ? "whole unit" : 0)}</td>
             <td class="num">${r.nightly_rate ? cur(r.nightly_rate) : "—"}</td></tr>`).join("") ||
             `<tr><td colspan="5"><div class="empty">Fully booked.</div></td></tr>`}</tbody></table></div>`,
          async () => {});
      });

    view.querySelector("#add").onclick = async () => {
      const avail = await api(`/api/bookings/availability?check_in=${today()}&check_out=${addDays(today(), 2)}`);
      const opts = [];
      avail.forEach((u) => {
        if (u.free_beds.length) u.free_beds.forEach((b) => opts.push([`${u.unit_id}:${b.id}`, `${u.property_name} · ${u.unit_name} · ${b.label}`]));
        else opts.push([`${u.unit_id}:`, `${u.property_name} · ${u.unit_name} (whole room)`]);
      });
      modal("New booking",
        F.select("slot", "Room / bed (available tonight)", opts) +
        F.select("person_id", "Guest", guests.map((p) => [p.id, p.full_name])) +
        availabilityFields(today(), addDays(today(), 2)) +
        F.row(F.number("nightly_rate", "Nightly rate", 25), F.select("channel", "Channel",
          ["direct", "website", "walk_in", "booking_com", "hostelworld", "airbnb", "agent"])) +
        `<p class="muted" style="font-size:12.5px">An accommodation invoice is raised automatically.</p>`,
        async (fd) => {
          const [unitId, bedId] = fd.slot.split(":");
          await api("/api/bookings", { method: "POST", body: {
            unit_id: +unitId, bed_id: bedId ? +bedId : null, person_id: +fd.person_id,
            check_in: fd.check_in, check_out: fd.check_out, nightly_rate: +fd.nightly_rate,
            channel: fd.channel, commission_rate: ["booking_com", "hostelworld", "airbnb"].includes(fd.channel) ? 0.15 : 0 } });
          toast("Booking confirmed"); go("bookings");
        });
    };
  };

  // ------------------------------------------------------------------ billing
  VIEWS.billing = async (view) => {
    const [invoices, arrears] = await Promise.all([
      api("/api/billing/invoices?limit=300"), api("/api/billing/arrears"),
    ]);
    const totals = arrears.reduce((a, r) => ({
      current: a.current + r.current, d1_30: a.d1_30 + r.d1_30, d31_60: a.d31_60 + r.d31_60,
      d61_90: a.d61_90 + r.d61_90, d90_plus: a.d90_plus + r.d90_plus, total: a.total + r.total,
    }), { current: 0, d1_30: 0, d31_60: 0, d61_90: 0, d90_plus: 0, total: 0 });

    view.innerHTML =
      head("Billing & arrears", "One ledger for rent and accommodation revenue",
        `<button class="btn" id="sync">Refresh statuses</button><button class="btn primary" id="add">Raise invoice</button>`) +
      `<div class="kpi-grid">
        <div class="kpi"><div class="label">Not yet due</div><div class="value">${cur(totals.current)}</div></div>
        <div class="kpi"><div class="label">1–30 days late</div><div class="value">${cur(totals.d1_30)}</div></div>
        <div class="kpi"><div class="label">31–60 days</div><div class="value">${cur(totals.d31_60)}</div></div>
        <div class="kpi"><div class="label">61–90 days</div><div class="value">${cur(totals.d61_90)}</div></div>
        <div class="kpi"><div class="label">90+ days</div><div class="value" style="color:var(--critical)">${cur(totals.d90_plus)}</div></div>
      </div>

      <div class="card"><h2>Aged debt</h2><div class="card-sub">Chase oldest first — worst ${Math.min(arrears.length, 25)} shown</div>
      ${table(
        [{ label: "Debtor" }, { label: "Contact" }, { label: "Not due", num: 1 }, { label: "1–30", num: 1 },
         { label: "31–60", num: 1 }, { label: "61–90", num: 1 }, { label: "90+", num: 1 }, { label: "Total", num: 1 }],
        arrears.slice(0, 25).map((r) => `<tr>
          <td><strong>${esc(r.person_name)}</strong></td>
          <td class="muted">${esc(r.email || r.phone || "—")}</td>
          <td class="num">${cur(r.current)}</td><td class="num">${cur(r.d1_30)}</td>
          <td class="num">${cur(r.d31_60)}</td><td class="num">${cur(r.d61_90)}</td>
          <td class="num" style="${r.d90_plus > 0 ? "color:var(--critical)" : ""}">${cur(r.d90_plus)}</td>
          <td class="num"><strong>${cur(r.total)}</strong></td></tr>`)
      )}</div>

      <div class="card" style="margin-top:14px"><h2>Invoices</h2>
        <div class="filters"><select id="st"><option value="">All statuses</option>
          ${["open", "partial", "paid", "overdue", "void"].map((s) => `<option value="${s}">${title(s)}</option>`).join("")}
        </select><label style="font-size:12.5px;color:var(--text-secondary)"><input type="checkbox" id="unpaid"> Unpaid only</label>
        <span class="muted" id="count" style="font-size:12.5px"></span></div>
        <div id="tbl"></div></div>`;

    const draw = () => {
      const st = view.querySelector("#st").value;
      const unpaidOnly = view.querySelector("#unpaid").checked;
      const rows = invoices.filter((i) => (!st || i.status === st) && (!unpaidOnly || i.balance > 0.005));
      const LIMIT = 50;
      view.querySelector("#count").textContent =
        rows.length > LIMIT ? `Showing ${LIMIT} of ${rows.length} matching invoices` : `${rows.length} invoice(s)`;
      view.querySelector("#tbl").innerHTML = table(
        [{ label: "Number" }, { label: "Debtor" }, { label: "For" }, { label: "Issued" }, { label: "Due" },
         { label: "Total", num: 1 }, { label: "Paid", num: 1 }, { label: "Balance", num: 1 }, { label: "Status" }, { label: "" }],
        rows.slice(0, LIMIT).map((i) => `<tr>
          <td class="mono">${esc(i.number)}</td>
          <td>${esc(i.person_name)}</td>
          <td class="muted">${esc((i.description || title(i.charge_type)).slice(0, 44))}</td>
          <td class="nowrap">${fmtDate(i.issue_date)}</td>
          <td class="nowrap">${fmtDate(i.due_date)}</td>
          <td class="num">${cur(i.total, 2)}</td>
          <td class="num">${cur(i.paid, 2)}</td>
          <td class="num" style="${i.balance > 0 ? "color:var(--critical)" : ""}">${cur(i.balance, 2)}</td>
          <td>${badge(i.status)}</td>
          <td>${i.balance > 0.005 && i.status !== "void"
            ? `<button class="btn sm" data-pay="${i.id}" data-bal="${i.balance}">Record payment</button>` : ""}</td></tr>`)
      );
      view.querySelectorAll("[data-pay]").forEach((b) => {
        b.onclick = () =>
          modal("Record payment",
            F.number("amount", "Amount", b.dataset.bal) + F.date("paid_on", "Received on", today()) +
            F.select("method", "Method", ["bank_transfer", "card", "cash", "online", "standing_order"]) +
            F.text("reference", "Reference", "", false),
            async (fd) => {
              await api("/api/billing/payments", { method: "POST", body: {
                invoice_id: +b.dataset.pay, amount: +fd.amount, paid_on: fd.paid_on,
                method: fd.method, reference: fd.reference || null } });
              toast("Payment recorded"); go("billing");
            });
      });
    };
    view.querySelector("#st").onchange = draw;
    view.querySelector("#unpaid").onchange = draw;
    draw();

    view.querySelector("#sync").onclick = async () => {
      const r = await api("/api/billing/sync-statuses", { method: "POST" });
      toast(`${r.updated} invoice status(es) updated`); go("billing");
    };

    view.querySelector("#add").onclick = async () => {
      const people = await api("/api/people?limit=300");
      modal("Raise invoice",
        F.select("person_id", "Debtor", people.map((p) => [p.id, p.full_name])) +
        F.select("charge_type", "Charge type", ["rent", "accommodation", "deposit", "utilities", "late_fee", "cleaning", "extras", "other"]) +
        F.text("description", "Description", "", false) +
        F.row(F.date("issue_date", "Issue date", today()), F.date("due_date", "Due date", addDays(today(), 14))) +
        F.number("amount", "Amount"),
        async (fd) => {
          await api("/api/billing/invoices", { method: "POST", body: {
            person_id: +fd.person_id, charge_type: fd.charge_type, description: fd.description || null,
            issue_date: fd.issue_date, due_date: fd.due_date, amount: +fd.amount } });
          toast("Invoice raised"); go("billing");
        });
    };
  };

  // -------------------------------------------------------------- maintenance
  VIEWS.maintenance = async (view) => {
    const [tickets, props, units] = await Promise.all([
      api("/api/maintenance"), api("/api/properties"), api("/api/units"),
    ]);

    view.innerHTML =
      head("Maintenance", `${tickets.filter((t) => ["open", "in_progress", "on_hold"].includes(t.status)).length} tickets open`,
        `<button class="btn primary" id="add">Log a job</button>`) +
      `<div class="card">
        <div class="filters">
          <select id="st"><option value="">All statuses</option>
            ${["open", "in_progress", "on_hold", "resolved", "closed"].map((s) => `<option value="${s}">${title(s)}</option>`).join("")}</select>
          <select id="pr"><option value="">Any priority</option>
            ${["urgent", "high", "medium", "low"].map((s) => `<option value="${s}">${title(s)}</option>`).join("")}</select>
        </div><div id="tbl"></div></div>`;

    const draw = () => {
      const st = view.querySelector("#st").value, pr = view.querySelector("#pr").value;
      const rows = tickets.filter((t) => (!st || t.status === st) && (!pr || t.priority === pr));
      view.querySelector("#tbl").innerHTML = table(
        [{ label: "Job" }, { label: "Location" }, { label: "Category" }, { label: "Priority" },
         { label: "Assigned" }, { label: "Reported" }, { label: "Days open", num: 1 },
         { label: "Cost", num: 1 }, { label: "Status" }, { label: "" }],
        rows.map((t) => `<tr>
          <td><strong>${esc(t.title)}</strong></td>
          <td>${esc(t.property_name)}${t.unit_name ? ` · ${esc(t.unit_name)}` : ""}</td>
          <td class="muted">${esc(t.category || "—")}</td>
          <td>${badge(t.priority)}</td>
          <td class="muted">${esc(t.assignee || "—")}</td>
          <td class="nowrap">${fmtDate(t.reported_at)}</td>
          <td class="num" style="${t.days_open > 14 && !t.resolved_at ? "color:var(--critical)" : ""}">${t.days_open}</td>
          <td class="num">${cur(t.cost, 2)}</td>
          <td>${badge(t.status)}</td>
          <td>${["resolved", "closed"].includes(t.status) ? "" : `<button class="btn sm" data-done="${t.id}">Resolve</button>`}</td></tr>`)
      );
      view.querySelectorAll("[data-done]").forEach((b) => {
        b.onclick = async () => {
          await api(`/api/maintenance/${b.dataset.done}`, { method: "PATCH", body: { status: "resolved", resolved_at: today() } });
          toast("Ticket resolved"); go("maintenance");
        };
      });
    };
    view.querySelector("#st").onchange = draw;
    view.querySelector("#pr").onchange = draw;
    draw();

    view.querySelector("#add").onclick = () =>
      modal("Log a maintenance job",
        F.text("title", "What's wrong?") +
        F.row(F.select("property_id", "Property", props.map((p) => [p.id, p.name])),
              F.select("priority", "Priority", ["low", "medium", "high", "urgent"], "medium")) +
        F.select("unit_id", "Unit", [["", "— none —"], ...units.map((u) => [u.id, `${u.property_name} · ${u.name}`])]) +
        F.row(F.text("category", "Category", "", false), F.text("assignee", "Assign to", "", false)) +
        F.area("description", "Details"),
        async (fd) => {
          await api("/api/maintenance", { method: "POST", body: {
            property_id: +fd.property_id, unit_id: fd.unit_id ? +fd.unit_id : null,
            title: fd.title, description: fd.description || null, category: fd.category || null,
            priority: fd.priority, assignee: fd.assignee || null, reported_at: today() } });
          toast("Job logged"); go("maintenance");
        });
  };

  // ---------------------------------------------------------------- analytics
  VIEWS.analytics = async (view) => {
    const months = S.cache.anMonths || 12;
    const [trend, mix, yield_, k] = await Promise.all([
      api(`/api/analytics/trend?months=${months}`), api(`/api/analytics/channel-mix?months=${months}`),
      api("/api/analytics/unit-yield?limit=12"), api("/api/analytics/summary"),
    ]);
    S.currency = k.currency;

    view.innerHTML =
      head("Analytics", "Revenue, occupancy and yield — the levers that move sales and rent",
        `<span class="muted" style="font-size:12.5px">Range</span>
         <select id="range">${[6, 12, 18, 24].map((m) => `<option value="${m}" ${m === months ? "selected" : ""}>${m} months</option>`).join("")}</select>`) +
      `<div class="grid-2">
        <div class="card"><h2>Revenue vs cost</h2><div class="card-sub">Billed against operating costs</div><div id="a1"></div></div>
        <div class="card"><h2>Occupancy</h2><div class="card-sub">Point-in-time each month end</div><div id="a2"></div></div>
      </div>
      <div class="grid-2" style="margin-top:14px">
        <div class="card"><h2>Revenue by channel</h2><div class="card-sub">Hover a bar for commission paid</div><div id="a3"></div></div>
        <div class="card"><h2>Top earning units</h2><div class="card-sub">Trailing 12 months of billed revenue</div><div id="a4"></div></div>
      </div>
      <div class="card" style="margin-top:14px"><h2>Monthly detail</h2>
        <div class="card-sub">Table view of the charts above</div>
        ${table(
          [{ label: "Month" }, { label: "Billed", num: 1 }, { label: "Collected", num: 1 },
           { label: "Costs", num: 1 }, { label: "Net", num: 1 }, { label: "Occupancy", num: 1 }],
          [...trend].reverse().map((t) => `<tr><td class="mono">${esc(t.period)}</td>
            <td class="num">${cur(t.revenue)}</td><td class="num">${cur(t.collected)}</td>
            <td class="num">${cur(t.expenses)}</td>
            <td class="num" style="color:${t.collected - t.expenses >= 0 ? "var(--good-ink)" : "var(--critical)"}">${cur(t.collected - t.expenses)}</td>
            <td class="num">${pct(t.occupancy)}</td></tr>`)
        )}</div>`;

    const c = chartColors();
    lineChart(document.getElementById("a1"), {
      labels: trend.map((t) => t.period.slice(2)),
      series: [
        { name: "Billed", color: c.s1, values: trend.map((t) => t.revenue) },
        { name: "Operating costs", color: c.s2, values: trend.map((t) => t.expenses) },
      ],
      fmt: (v) => cur(v),
    });
    lineChart(document.getElementById("a2"), {
      labels: trend.map((t) => t.period.slice(2)),
      series: [{ name: "Occupancy", color: c.s1, values: trend.map((t) => t.occupancy) }],
      fmt: (v) => `${Math.round(v)}%`,
    });
    barChart(document.getElementById("a3"), {
      rows: mix.map((m) => ({ label: title(m.label), value: m.value, secondary: m.secondary })),
      fmt: (v) => cur(v), sub: { primary: "Revenue", secondary: "Commission" },
    });
    barChart(document.getElementById("a4"), {
      rows: yield_.map((u) => ({ label: u.label.split(" · ").pop(), value: u.value })),
      color: c.s3, fmt: (v) => cur(v), sub: { primary: "Revenue" },
    });

    view.querySelector("#range").onchange = (e) => {
      S.cache.anMonths = +e.target.value;
      go("analytics");
    };
  };

  // ------------------------------------------------------------------ boot ---
  const savedTheme = localStorage.getItem("hongdee_theme");
  if (savedTheme) document.documentElement.setAttribute("data-theme", savedTheme);

  // Charts are sized in absolute units, so only a real width change needs a redraw.
  let lastWidth = window.innerWidth;
  window.addEventListener("resize", () => {
    clearTimeout(window.__rz);
    window.__rz = setTimeout(() => {
      if (!S.user || Math.abs(window.innerWidth - lastWidth) < 40) return;
      lastWidth = window.innerWidth;
      go(S.route);
    }, 300);
  });

  (async () => {
    if (!S.token) return renderLogin();
    try {
      S.user = await api("/api/auth/me");
      renderShell();
    } catch {
      renderLogin();
    }
  })();
})();
