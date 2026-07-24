/* The Next - SiJalan — polyline drawing, hover info, route selection */

function clearPolylines() {
  state.polylines.forEach((pl) => pl.setMap(null));
  state.polylines = [];
}

function clearUsulanPolylines() {
  state.usulanPolylines.forEach((pl) => pl.setMap(null));
  state.usulanPolylines = [];
  state.usulanBounds = null;
}

function drawPolylines() {
  clearPolylines();
  state.routes.forEach((route, idx) => {
    const color = ROUTE_COLORS[idx % ROUTE_COLORS.length];
    const path = route.coordinates.map(([lat, lng]) => ({ lat, lng }));
    const pl = new google.maps.Polyline({
      path,
      strokeColor: color,
      strokeOpacity: idx === state.selectedIndex ? 0.95 : 0.45,
      strokeWeight: idx === state.selectedIndex ? 6 : 4,
      map: state.map,
      zIndex: idx === state.selectedIndex ? 10 : 1,
    });
    pl.addListener("click", () => selectRoute(idx));
    pl.addListener("mousemove", (e) => showSegmentHover(route, e.latLng));
    pl.addListener("mouseout", () => state.hoverInfoWindow.close());
    state.polylines.push(pl);
  });

  const bounds = new google.maps.LatLngBounds();
  state.routes.forEach((r) => r.coordinates.forEach(([lat, lng]) => bounds.extend({ lat, lng })));
  if (!bounds.isEmpty()) state.map.fitBounds(bounds, 60);
}

function showSegmentHover(route, latLng) {
  if (!route.segments || !route.segments.length) return;

  let nearest = null;
  let nearestDist = Infinity;
  route.segments.forEach((s) => {
    const mid = {
      lat: (s.start_lat + s.end_lat) / 2,
      lng: (s.start_lng + s.end_lng) / 2,
    };
    const d = google.maps.geometry.spherical.computeDistanceBetween(latLng, mid);
    if (d < nearestDist) {
      nearestDist = d;
      nearest = s;
    }
  });
  if (!nearest) return;

  const isToll = /\btol\b|\btoll\b/i.test(nearest.road_name);
  const html = `
    <div class="hover-info">
      <div class="hover-info-title">${escapeHtml(nearest.road_name || "Tanpa nama")}${isToll ? ' <span class="toll-flag">[TOL]</span>' : ""}</div>
      <div class="hover-info-row"><i class="bi bi-rulers"></i> ${nearest.distance_km.toFixed(2)} km &nbsp; <i class="bi bi-stopwatch"></i> ${(nearest.duration_min * 60).toFixed(0)} dtk</div>
      <div class="hover-info-row"><i class="bi bi-compass"></i> ${bearingToCompass(nearest.bearing)} (${nearest.bearing.toFixed(0)}°)</div>
      <div class="hover-info-row">Segmen #${nearest.segment_id + 1} — ${route.route_name}</div>
    </div>`;

  state.hoverInfoWindow.setContent(html);
  state.hoverInfoWindow.setPosition(latLng);
  if (!state.hoverInfoWindow.getMap()) state.hoverInfoWindow.open(state.map);
}

function selectRoute(idx) {
  state.selectedIndex = idx;
  drawPolylines();
  renderRouteList();
  renderAnalysis();
  clearAdvancedResults();
}

function clearAdvancedResults() {
  document.getElementById("adminRegionsContent").innerHTML = "";
  document.getElementById("roadClassContent").innerHTML = "";
  document.getElementById("usulanInpresContent").innerHTML = "";
  state.lastAdminRegions = null;
  state.lastRoadClass = null;
  state.lastUsulanNearby = null;
}

const USULAN_MAX_ZOOM = 14; // batasi seberapa dekat auto zoom ke ruas pendek, biar konteks sekitarnya tetap kelihatan

function fitBoundsCapped(bounds, padding = 80, maxZoom = USULAN_MAX_ZOOM) {
  if (bounds.isEmpty()) return;
  state.map.fitBounds(bounds, padding);
  google.maps.event.addListenerOnce(state.map, "bounds_changed", () => {
    if (state.map.getZoom() > maxZoom) state.map.setZoom(maxZoom);
  });
}
