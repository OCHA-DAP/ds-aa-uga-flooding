/* Line charts for the season monitoring page. Generic: every title, value and label comes from
 * the page that calls MonCharts.draw(days, specs); nothing here is specific to a trigger.
 * spec = { id, title, unit: "pct"|"mm"|"m", series: [{ name, values, color, note? }],
 *          lines: [{ y, label }], met: [index...], metValues: [value...], yMin, yMax, ticks,
 *          height, extra: [{ label, values, unit }] } */
(function () {
  "use strict";
  const NS = "http://www.w3.org/2000/svg";
  const FMT = {
    pct: (v) => Math.round(v * 100) + " %",
    mm: (v) => Math.round(v) + " mm",
    m: (v) => (v > 0 ? "+" : "") + v.toFixed(2) + " m",
    raw: (v) => String(v),
  };
  const AXIS = { pct: (v) => Math.round(v * 100) + " %", mm: (v) => String(Math.round(v)), m: (v) => v.toFixed(1), raw: String };
  const dayLabel = (s) => {
    const d = new Date(s + "T00:00:00Z");
    return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });
  };
  function el(tag, attrs, parent) {
    const e = document.createElementNS(NS, tag);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    parent.appendChild(e);
    return e;
  }
  function niceTicks(lo, hi, k) {
    const span = hi - lo, raw = span / k, mag = Math.pow(10, Math.floor(Math.log10(raw)));
    const step = [1, 2, 2.5, 5, 10].map((f) => f * mag).find((s) => span / s <= k) || raw;
    const out = [];
    for (let t = Math.ceil(lo / step) * step; t <= hi + 1e-9; t += step) out.push(+t.toFixed(6));
    return out;
  }
  function draw(days, spec) {
    const host = document.getElementById(spec.id);
    if (!host) return;
    const W = 860, H = spec.height || 250, m = { l: 48, r: 14, t: 10, b: 26 };
    const n = days.length, iw = W - m.l - m.r, ih = H - m.t - m.b;
    const fmt = FMT[spec.unit] || FMT.raw, axis = AXIS[spec.unit] || AXIS.raw;
    const vals = spec.series.flatMap((s) => s.values.filter((v) => v !== null));
    const lines = (spec.lines || []).map((l) => l.y);
    const lo = spec.yMin ?? Math.min(0, ...vals, ...lines);
    const hi = spec.yMax ?? Math.max(...vals, ...lines) * 1.08;
    const x = (i) => m.l + (n === 1 ? iw / 2 : (i / (n - 1)) * iw);
    const y = (v) => m.t + ih - ((Math.max(lo, Math.min(hi, v)) - lo) / (hi - lo)) * ih;

    host.innerHTML = "";
    const title = document.createElement("div");
    title.className = "chart-title";
    title.textContent = spec.title;
    host.appendChild(title);
    const lg = document.createElement("div");
    lg.className = "legend";
    if (spec.series.length > 1 || lines.length || (spec.met || []).length) {
      for (const s of spec.series) lg.insertAdjacentHTML("beforeend", `<span><i style="border-color:var(${s.color})"></i></span>`), lg.lastChild.append(s.name);
      for (const l of spec.lines || []) lg.insertAdjacentHTML("beforeend", `<span><i class="dash" style="border-color:var(--n8)"></i></span>`), lg.lastChild.append(l.label);
      if ((spec.met || []).length) lg.insertAdjacentHTML("beforeend", `<span><i class="dot"></i></span>`), lg.lastChild.append(spec.metLabel || "trigger met");
      host.appendChild(lg);
    }
    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, class: "plot", role: "img", "aria-label": spec.title }, host);
    for (const t of spec.ticks || niceTicks(lo, hi, 5)) {
      if (t < lo - 1e-9 || t > hi + 1e-9) continue;
      el("line", { x1: m.l, x2: W - m.r, y1: y(t), y2: y(t), stroke: "var(--grid)", "stroke-width": 1 }, svg);
      el("text", { x: m.l - 6, y: y(t) + 4, "text-anchor": "end" }, svg).textContent = axis(t);
    }
    days.forEach((d, i) => {
      if (i === 0 || d.endsWith("-01")) {
        el("line", { x1: x(i), x2: x(i), y1: m.t + ih, y2: m.t + ih + 4, stroke: "var(--n7)" }, svg);
        el("text", { x: x(i), y: H - 8, "text-anchor": i === 0 ? "start" : "middle" }, svg).textContent = dayLabel(d);
      }
    });
    el("line", { x1: m.l, x2: W - m.r, y1: m.t + ih, y2: m.t + ih, stroke: "var(--n7)", "stroke-width": 1 }, svg);
    for (const l of spec.lines || [])
      el("line", { x1: m.l, x2: W - m.r, y1: y(l.y), y2: y(l.y), stroke: "var(--n8)", "stroke-width": 1.5, "stroke-dasharray": "5 4" }, svg);
    for (const s of spec.series) {
      let d = "", pen = false;
      s.values.forEach((v, i) => {
        if (v === null) { pen = false; return; }
        d += (pen ? "L" : "M") + x(i).toFixed(1) + " " + y(v).toFixed(1);
        pen = true;
      });
      el("path", { d, fill: "none", stroke: `var(${s.color})`, "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }, svg);
      s.values.forEach((v, i) => {  // a value with no neighbour draws no line: a dot instead
        if (v !== null && (s.values[i - 1] ?? null) === null && (s.values[i + 1] ?? null) === null)
          el("circle", { cx: x(i), cy: y(v), r: 3, fill: `var(${s.color})` }, svg);
      });
    }
    (spec.met || []).forEach((i, k) =>
      el("circle", { cx: x(i), cy: y(spec.metValues[k]), r: 5, fill: "var(--met)", stroke: "#fff", "stroke-width": 2 }, svg));

    const cross = el("line", { y1: m.t, y2: m.t + ih, stroke: "var(--n7)", "stroke-width": 1, visibility: "hidden" }, svg);
    const tip = document.createElement("div");
    tip.className = "tip";
    tip.hidden = true;
    host.appendChild(tip);
    const hit = el("rect", { x: m.l, y: m.t, width: iw, height: ih, fill: "transparent" }, svg);
    const line = (label, v, f) => `<div>${label}: <b>${v === null || v === undefined ? "no data" : f(v)}</b></div>`;
    hit.addEventListener("pointermove", (ev) => {
      const r = svg.getBoundingClientRect(), px = ((ev.clientX - r.left) / r.width) * W;
      const i = Math.max(0, Math.min(n - 1, Math.round(((px - m.l) / iw) * (n - 1))));
      cross.setAttribute("x1", x(i));
      cross.setAttribute("x2", x(i));
      cross.setAttribute("visibility", "visible");
      tip.innerHTML = `<div>${dayLabel(days[i])} issue</div>`
        + spec.series.map((s) => line(s.name, s.values[i], fmt) + (s.note && s.note[i] ? `<div>${s.note[i]}</div>` : "")).join("")
        + (spec.extra || []).map((e) => line(e.label, e.values[i], FMT[e.unit] || FMT.raw)).join("");
      tip.hidden = false;
      const hr = host.getBoundingClientRect();
      tip.style.left = Math.max(4, Math.min(ev.clientX - hr.left + 12, hr.width - tip.offsetWidth - 6)) + "px";
      tip.style.top = Math.max(4, ev.clientY - hr.top - tip.offsetHeight - 10) + "px";
    });
    hit.addEventListener("pointerleave", () => { tip.hidden = true; cross.setAttribute("visibility", "hidden"); });

    const det = document.createElement("details");
    const head = spec.series.map((s) => `<th class="n"></th>`).join("");
    det.innerHTML = `<summary>Table</summary><div class="tw"><table><thead><tr><th>Issue</th>${head}</tr></thead><tbody></tbody></table></div>`;
    det.querySelectorAll("th.n").forEach((th, k) => (th.textContent = spec.series[k].name));
    const tb = det.querySelector("tbody");
    days.forEach((d, i) => {
      const tr = document.createElement("tr");
      tr.insertAdjacentHTML("beforeend", `<td>${d}</td>`);
      for (const s of spec.series) {
        const td = document.createElement("td");
        td.className = "n";
        td.textContent = s.values[i] === null ? "" : fmt(s.values[i]);
        tr.appendChild(td);
      }
      tb.appendChild(tr);
    });
    host.appendChild(det);
  }
  window.MonCharts = { draw: (days, specs) => specs.forEach((s) => draw(days, s)) };
})();
