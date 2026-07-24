/* The Next - SiJalan — route result list & per-route analysis panel rendering */

function fastestRouteIndex() {
  if (!state.routes.length) return -1;
  let best = 0;
  state.routes.forEach((r, i) => {
    if (r.duration_min < state.routes[best].duration_min) best = i;
  });
  return best;
}

function shortestRouteIndex() {
  if (!state.routes.length) return -1;
  let best = 0;
  state.routes.forEach((r, i) => {
    if (r.distance_km < state.routes[best].distance_km) best = i;
  });
  return best;
}

function renderRouteList() {
  const wrap = document.getElementById("routeList");
  wrap.innerHTML = "";

  const fastestIdx = fastestRouteIndex();
  const shortestIdx = shortestRouteIndex();
  const fastest = state.routes[fastestIdx];

  // Order like Google Maps: fastest route first, then remaining alternatives.
  const order = state.routes
    .map((_, idx) => idx)
    .sort((a, b) => state.routes[a].duration_min - state.routes[b].duration_min);

  order.forEach((idx) => {
    const route = state.routes[idx];
    const color = ROUTE_COLORS[idx % ROUTE_COLORS.length];
    const isFastest = idx === fastestIdx;
    const isShortest = idx === shortestIdx && !isFastest;

    const deltaMin = formatDelta(route.duration_min - fastest.duration_min, "mnt");
    const deltaKm = formatDelta(route.distance_km - fastest.distance_km, "km");

    const card = document.createElement("div");
    card.className = "route-card" + (idx === state.selectedIndex ? " selected" : "");
    card.innerHTML = `
      <div class="route-card-top">
        <span class="route-color-dot" style="background:${color}"></span>
        <span class="route-card-title">${formatDuration(route.duration_min)}</span>
        ${isFastest ? '<span class="route-card-badge badge-fastest">Tercepat</span>' : ""}
        ${isShortest ? '<span class="route-card-badge badge-shortest">Terpendek</span>' : ""}
        ${route.tollVariant === "no-toll" ? '<span class="route-card-badge badge-no-toll">Tanpa Tol</span>' : ""}
        ${route.tollVariant === "toll" ? '<span class="route-card-badge badge-toll">Dengan Tol</span>' : (route.tollVariant !== "no-toll" && route.is_toll ? '<span class="route-card-badge badge-toll">TOL</span>' : "")}
      </div>
      <div class="route-card-meta">
        <span><i class="bi bi-rulers"></i> ${route.distance_km.toFixed(2)} km${deltaKm ? ` (${deltaKm})` : ""}</span>
        ${deltaMin ? `<span class="route-delta">${deltaMin} dari tercepat</span>` : ""}
      </div>
      ${route.via ? `<div class="route-via">via ${escapeHtml(route.via)}</div>` : ""}
      ${route.tollVariant === "no-toll" && route.is_toll
        ? `<div class="route-via-warning"><i class="bi bi-exclamation-triangle"></i> Google tidak menemukan rute yang sepenuhnya bebas tol — sebagian ruas tol tetap dilalui.</div>`
        : ""}`;
    card.onclick = () => selectRoute(idx);
    wrap.appendChild(card);
  });
}

function renderAnalysis() {
  const route = state.routes[state.selectedIndex];
  const wrap = document.getElementById("analysisContent");
  if (!route) {
    wrap.innerHTML = "";
    return;
  }

  const tollSegments = route.segments.filter((s) => /\btol\b|\btoll\b/i.test(s.road_name));
  const tollPct = route.segments.length ? ((tollSegments.length / route.segments.length) * 100).toFixed(1) : "0.0";

  let html = `
    <div class="stat-grid">
      <div class="stat-box"><div class="val">${route.distance_km.toFixed(2)}</div><div class="lbl">Total Jarak (km)</div></div>
      <div class="stat-box"><div class="val">${formatDuration(route.duration_min)}</div><div class="lbl">Estimasi Waktu</div></div>
      <div class="stat-box"><div class="val">${route.waypoint_count}</div><div class="lbl">Jumlah Waypoint</div></div>
      <div class="stat-box"><div class="val">${route.segment_count}</div><div class="lbl">Jumlah Segmen</div></div>
    </div>
    <div class="stat-grid">
      <div class="stat-box"><div class="val">${tollPct}%</div><div class="lbl">Segmen Jalan Tol</div></div>
      <div class="stat-box"><div class="val">${route.is_toll ? "Ya" : "Tidak"}</div><div class="lbl">Melewati Tol</div></div>
    </div>`;

  if (state.routes.length > 1) {
    const fastestIdx = fastestRouteIndex();
    const fastest = state.routes[fastestIdx];
    const order = state.routes
      .map((_, idx) => idx)
      .sort((a, b) => state.routes[a].duration_min - state.routes[b].duration_min);

    html += `<table class="compare-table"><thead><tr><th>Rute</th><th>Jarak</th><th>Waktu</th><th>Selisih</th><th>Tol</th></tr></thead><tbody>`;
    order.forEach((idx) => {
      const r = state.routes[idx];
      const deltaMin = idx === fastestIdx ? "—" : formatDelta(r.duration_min - fastest.duration_min, "mnt") || "sama";
      const rowClass = idx === state.selectedIndex ? ' class="compare-row-selected"' : "";
      html += `<tr${rowClass}><td>${idx === fastestIdx ? '<i class="bi bi-star-fill" style="color:var(--accent)"></i> ' : ""}${escapeHtml(r.via || r.variant_label)}</td><td>${r.distance_km.toFixed(2)} km</td><td>${formatDuration(r.duration_min)}</td><td>${deltaMin}</td><td>${r.is_toll ? "Ya" : "Tidak"}</td></tr>`;
    });
    html += `</tbody></table>`;
  }

  html += `<div class="segment-scroll">`;
  route.segments.forEach((s) => {
    const isToll = /\btol\b|\btoll\b/i.test(s.road_name);
    html += `<div class="segment-row">
      <span class="seg-name">${isToll ? '<span class="toll-flag">[TOL] </span>' : ""}${escapeHtml(s.road_name || "—")}</span>
      <span class="seg-meta">${s.distance_km.toFixed(2)} km · ${s.bearing.toFixed(0)}°</span>
    </div>`;
  });
  html += `</div>`;

  wrap.innerHTML = html;
}
