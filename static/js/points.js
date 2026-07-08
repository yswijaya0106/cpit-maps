/* RouteGIS — origin/destination/waypoint point handling, markers, manual/CSV input */

function handleMapClick(pt) {
  // If the user focused a specific field (Origin/Destination/a waypoint row)
  // before clicking the map, fill that field — this lets you change an
  // existing point after a route has already been searched. Otherwise fall
  // back to filling whichever point is still empty, then appending waypoints.
  if (state.activeField === "origin") {
    setOrigin(pt);
    state.activeField = null;
    return;
  }
  if (state.activeField === "destination") {
    setDestination(pt);
    state.activeField = null;
    return;
  }
  if (typeof state.activeField === "number") {
    state.waypoints[state.activeField] = pt;
    renderWaypointList();
    updateMarkers();
    state.activeField = null;
    return;
  }

  if (!state.origin) {
    setOrigin(pt);
  } else if (!state.destination) {
    setDestination(pt);
  } else {
    addWaypoint(pt);
  }
}

function setOrigin(pt) {
  if (!pt) return;
  state.origin = pt;
  document.getElementById("inputOrigin").value = pt.label;
  updateMarkers();
}

function setDestination(pt) {
  if (!pt) return;
  state.destination = pt;
  document.getElementById("inputDestination").value = pt.label;
  updateMarkers();
}

function addWaypoint(pt) {
  state.waypoints.push(pt);
  renderWaypointList();
  updateMarkers();
}

function removeWaypoint(idx) {
  state.waypoints.splice(idx, 1);
  renderWaypointList();
  updateMarkers();
}

function moveWaypoint(idx, dir) {
  const j = idx + dir;
  if (j < 0 || j >= state.waypoints.length) return;
  [state.waypoints[idx], state.waypoints[j]] = [state.waypoints[j], state.waypoints[idx]];
  renderWaypointList();
  updateMarkers();
}

function renderWaypointList() {
  const wrap = document.getElementById("waypointList");
  wrap.innerHTML = "";
  document.getElementById("waypointAltHint").hidden = state.waypoints.length === 0;
  state.waypoints.forEach((wp, idx) => {
    const row = document.createElement("div");
    row.className = "waypoint-row";
    row.innerHTML = `
      <span class="point-marker waypoint-marker">${idx + 1}</span>
      <input type="text" value="${escapeHtml(wp.label)}" data-idx="${idx}" placeholder="Cari alamat waypoint" />
      <div class="wp-actions">
        <button data-act="up" title="Naikkan"><i class="bi bi-caret-up-fill"></i></button>
        <button data-act="down" title="Turunkan"><i class="bi bi-caret-down-fill"></i></button>
        <button data-act="del" title="Hapus"><i class="bi bi-x-lg"></i></button>
      </div>`;
    const input = row.querySelector("input");
    attachAutocomplete(input, (place) => {
      const pt = placeToPoint(place);
      if (pt) {
        state.waypoints[idx] = pt;
        updateMarkers();
      }
    });
    input.addEventListener("focus", () => (state.activeField = idx));
    row.querySelector('[data-act="up"]').onclick = () => moveWaypoint(idx, -1);
    row.querySelector('[data-act="down"]').onclick = () => moveWaypoint(idx, 1);
    row.querySelector('[data-act="del"]').onclick = () => removeWaypoint(idx);
    wrap.appendChild(row);
  });
}

/* ---------- Markers ---------- */

function updateMarkers() {
  if (state.markers.origin) state.markers.origin.setMap(null);
  if (state.markers.destination) state.markers.destination.setMap(null);
  state.markers.waypoints.forEach((m) => m.setMap(null));
  state.markers.waypoints = [];

  if (state.origin) {
    state.markers.origin = makeMarker(state.origin, "A", "#22c55e");
  }
  if (state.destination) {
    state.markers.destination = makeMarker(state.destination, "B", "#ef4444");
  }
  state.waypoints.forEach((wp, i) => {
    state.markers.waypoints.push(makeMarker(wp, String(i + 1), "#f59e0b"));
  });
}

function makeMarker(pt, label, color) {
  return new google.maps.Marker({
    position: { lat: pt.lat, lng: pt.lng },
    map: state.map,
    label: { text: label, color: "#fff", fontSize: "11px", fontWeight: "700" },
    icon: {
      path: google.maps.SymbolPath.CIRCLE,
      scale: 13,
      fillColor: color,
      fillOpacity: 1,
      strokeColor: "#0f1420",
      strokeWeight: 2,
    },
  });
}

/* ---------- Manual coordinate / CSV import ---------- */

function bindManualCoord() {
  document.getElementById("btnManualAdd").onclick = () => {
    const lat = parseFloat(document.getElementById("manualLat").value);
    const lng = parseFloat(document.getElementById("manualLng").value);
    const target = document.getElementById("manualTarget").value;
    if (Number.isNaN(lat) || Number.isNaN(lng)) {
      toast("Latitude/Longitude tidak valid", true);
      return;
    }
    const pt = { lat, lng, label: `${lat.toFixed(5)}, ${lng.toFixed(5)}` };
    if (target === "origin") setOrigin(pt);
    else if (target === "destination") setDestination(pt);
    else addWaypoint(pt);
    state.map.panTo(pt);
  };

  document.getElementById("csvImport").addEventListener("change", async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const text = await file.text();
    const rows = text
      .split(/\r?\n/)
      .map((l) => l.trim())
      .filter(Boolean)
      .map((l) => l.split(","))
      .filter((cols) => !Number.isNaN(parseFloat(cols[0])) && !Number.isNaN(parseFloat(cols[1])));

    if (!rows.length) {
      toast("CSV tidak berisi baris koordinat yang valid", true);
      return;
    }
    rows.forEach((cols, idx) => {
      const lat = parseFloat(cols[0]);
      const lng = parseFloat(cols[1]);
      const label = cols[2] ? cols[2].trim() : `${lat.toFixed(5)}, ${lng.toFixed(5)}`;
      const pt = { lat, lng, label };
      if (!state.origin) setOrigin(pt);
      else if (idx === rows.length - 1 && !state.destination) setDestination(pt);
      else if (!state.destination && idx === rows.length - 1) setDestination(pt);
      else addWaypoint(pt);
    });
    toast(`${rows.length} titik diimpor dari CSV`);
    e.target.value = "";
  });
}
