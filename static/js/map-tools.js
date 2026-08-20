/* The Next - SiJalan — tool peta gaya ArcGIS: identify, select, ukur jarak/luas, legend layer overlay */

const MEASURE_LINE_COLOR = "#ffb648";

function bindMapToolsToolbar() {
  document.querySelectorAll(".maptool-btn[data-tool]").forEach((btn) => {
    btn.addEventListener("click", () => setMapTool(state.mapTool === btn.dataset.tool ? null : btn.dataset.tool));
  });

  document.getElementById("btnMapLegend").addEventListener("click", () => {
    const panel = document.getElementById("mapLegend");
    panel.hidden = !panel.hidden;
  });
  document.getElementById("mapLegendClose").addEventListener("click", () => {
    document.getElementById("mapLegend").hidden = true;
  });
  document.getElementById("mapLegendClearAll").addEventListener("click", () => {
    clearActiveMapLayers();
  });
  document.getElementById("mapLegendList").addEventListener("click", (e) => {
    const btn = e.target.closest(".map-legend-item-remove");
    if (!btn) return;
    hideMapLayer(btn.dataset.key);
  });

  document.getElementById("btnMeasureFinish").addEventListener("click", finishMeasure);
  document.getElementById("btnMeasureClear").addEventListener("click", clearMeasure);
  document.getElementById("mapSelectionClear").addEventListener("click", clearSelection);

  updateMapLegend();
}

function setMapTool(tool) {
  if (state.mapTool && state.mapTool.startsWith("measure")) clearMeasure();
  if (state.mapTool === "select" && tool !== "select") clearSelection();
  if (state.mapTool === "identify" && tool !== "identify") {
    clearIdentifyHighlight();
    state.identifyInfoWindow?.close();
  }
  state.mapTool = tool;

  document.querySelectorAll(".maptool-btn[data-tool]").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.tool === tool);
  });
  state.map.setOptions({ draggableCursor: tool ? "crosshair" : null });

  document.getElementById("mapMeasureResult").hidden = tool !== "measure-distance" && tool !== "measure-area";
  if (tool !== "measure-distance" && tool !== "measure-area") setMeasureText("");

  const hints = {
    "add-point": "Klik peta (termasuk di atas layer overlay) untuk mengisi Origin/Tujuan/Waypoint",
    identify: "Klik fitur pada layer overlay aktif untuk melihat atributnya",
    select: "Klik fitur untuk memilih, Shift+klik untuk memilih lebih dari satu",
    "measure-distance": "Klik titik-titik di peta untuk mengukur jarak, lalu klik \"Selesai\"",
    "measure-area": "Klik titik-titik di peta untuk mengukur luas area, lalu klik \"Selesai\"",
  };
  setStatus(tool ? hints[tool] : "Peta siap");
}

/* ---------- Identify (klik fitur layer overlay -> tampilkan atribut) ---------- */

function onFeatureClick(layerName, feature, latLng) {
  if (state.mapTool === "identify") {
    showIdentifyInfo(layerName, feature, latLng);
  } else if (state.mapTool === "select") {
    toggleFeatureSelection(layerName, feature);
  }
}

const IDENTIFY_HIGHLIGHT_STYLE = { strokeColor: "#22d3a5", strokeWeight: 4, strokeOpacity: 1, fillOpacity: 0.5, zIndex: 100 };

function showIdentifyInfo(layerName, feature, latLng) {
  clearIdentifyHighlight();
  state.mapLayers.active[layerName]?.overrideStyle(feature, IDENTIFY_HIGHLIGHT_STYLE);
  state.identifyHighlight = { layer: layerName, feature };

  const rows = [];
  feature.forEachProperty((value, key) => {
    if (value === null || value === undefined || value === "") return;
    rows.push(`<tr><th>${escapeHtml(key)}</th><td>${escapeHtml(String(value))}</td></tr>`);
  });
  const body = rows.length
    ? `<table class="identify-table">${rows.join("")}</table>`
    : `<div class="hint">Fitur ini tidak memiliki atribut</div>`;

  // Konten dibangun sebagai DOM node (bukan string) supaya select join tabel
  // di bawah bisa langsung diberi event listener.
  const container = document.createElement("div");
  container.className = "identify-info";
  container.innerHTML = `
    <div class="identify-info-title">${escapeHtml(mapLayerDisplayLabel(layerName))}</div>
    ${body}
  `;
  const kodeKec = feature.getProperty("KODE_KECAMATAN");
  if (kodeKec) attachKecamatanJoin(container, kodeKec);
  // Kantor SAR punya nama_kantor langsung; Pos SAR simpan nama kantor
  // induknya di "Nama Kantor SAR" (lihat scripts/import_basarnas_to_postgis.py)
  // -- keduanya di-join ke tabel referensi BASARNAS yang sama.
  const namaKantorSar = feature.getProperty("nama_kantor") || feature.getProperty("Nama Kantor SAR");
  if (namaKantorSar) attachKantorSarJoin(container, namaKantorSar);

  if (!state.identifyInfoWindow) {
    state.identifyInfoWindow = new google.maps.InfoWindow();
    state.identifyInfoWindow.addListener("closeclick", clearIdentifyHighlight);
  }
  state.identifyInfoWindow.setContent(container);
  state.identifyInfoWindow.setPosition(latLng);
  state.identifyInfoWindow.open(state.map);
}

/* Join atribut poligon kecamatan ke tabel database — pengguna memilih tabel
   yang mau dilihat lewat dropdown di popup identify. */
function attachKecamatanJoin(container, kodeKec) {
  const wrap = document.createElement("div");
  wrap.className = "identify-join";
  wrap.innerHTML = `
    <div class="identify-join-head">
      <i class="bi bi-table"></i> Data database:
      <select class="identify-join-select"></select>
    </div>
    <div class="identify-join-body hint">Memuat...</div>`;
  container.appendChild(wrap);
  const sel = wrap.querySelector("select");
  const bodyEl = wrap.querySelector(".identify-join-body");

  const load = async () => {
    bodyEl.className = "identify-join-body hint";
    bodyEl.textContent = "Memuat...";
    try {
      const tabel = sel.value ? `?tabel=${encodeURIComponent(sel.value)}` : "";
      const res = await fetch(`/api/kecamatan/${kodeKec}/data${tabel}`);
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Gagal memuat");
      if (!sel.options.length) {
        data.tabel_tersedia.forEach((t) => {
          const opt = document.createElement("option");
          opt.value = t.tabel;
          opt.textContent = t.label;
          opt.selected = t.tabel === data.tabel;
          sel.appendChild(opt);
        });
      }
      bodyEl.className = "identify-join-body";
      if (!data.rows.length) {
        bodyEl.innerHTML = `<div class="hint">Tidak ada baris di tabel ini untuk kecamatan tsb.</div>`;
        return;
      }
      const boolCols = data.columns.map(isBoolDbCol);
      const joinCell = (v, j) =>
        boolCols[j] && (v === 0 || v === 1 || v === true || v === false) ? boolCellHtml(v) : escapeHtml(String(v ?? "—"));
      if (data.rows.length === 1) {
        // satu baris -> tampilkan tegak (kolom: nilai) biar muat di popup
        bodyEl.innerHTML = `<table class="identify-table">${data.columns.map((c, i) =>
          `<tr><th>${escapeHtml(c)}</th><td>${joinCell(data.rows[0][i], i)}</td></tr>`
        ).join("")}</table>`;
      } else {
        bodyEl.innerHTML = `<div class="identify-join-scroll"><table class="identify-table identify-join-table">
          <thead><tr>${data.columns.map((c) => `<th>${escapeHtml(c)}</th>`).join("")}</tr></thead>
          <tbody>${data.rows.map((r) =>
            `<tr>${r.map((v, j) => `<td>${joinCell(v, j)}</td>`).join("")}</tr>`
          ).join("")}</tbody></table></div>
          <div class="hint">${data.rows.length} baris</div>`;
      }
    } catch (err) {
      bodyEl.className = "identify-join-body hint";
      bodyEl.textContent = String(err.message || err);
    }
  };
  sel.addEventListener("change", load);
  load();
}

/* Join titik Kantor SAR/Pos SAR (BASARNAS) ke tabel referensi ALUT/Rescuer-
   Potensi/Ops SAR -- pola sama dengan attachKecamatanJoin, tapi kuncinya
   nama kota (best-effort text match, lihat _kantor_sar_kota di app.py),
   bukan kode angka. TIDAK terkait usulan_inpres/IJD. */
function attachKantorSarJoin(container, namaKantor) {
  const wrap = document.createElement("div");
  wrap.className = "identify-join";
  wrap.innerHTML = `
    <div class="identify-join-head">
      <i class="bi bi-table"></i> Data database:
      <select class="identify-join-select"></select>
    </div>
    <div class="identify-join-body hint">Memuat...</div>`;
  container.appendChild(wrap);
  const sel = wrap.querySelector("select");
  const bodyEl = wrap.querySelector(".identify-join-body");

  const load = async () => {
    bodyEl.className = "identify-join-body hint";
    bodyEl.textContent = "Memuat...";
    try {
      const tabel = sel.value ? `&tabel=${encodeURIComponent(sel.value)}` : "";
      const res = await fetch(`/api/kantor-sar/data?nama_kantor=${encodeURIComponent(namaKantor)}${tabel}`);
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Gagal memuat");
      if (!sel.options.length) {
        data.tabel_tersedia.forEach((t) => {
          const opt = document.createElement("option");
          opt.value = t.tabel;
          opt.textContent = t.label;
          opt.selected = t.tabel === data.tabel;
          sel.appendChild(opt);
        });
      }
      bodyEl.className = "identify-join-body";
      if (!data.rows.length) {
        bodyEl.innerHTML = `<div class="hint">Tidak ada baris di tabel ini untuk kantor SAR ini.</div>`;
        return;
      }
      const boolCols = data.columns.map(isBoolDbCol);
      const joinCell = (v, j) =>
        boolCols[j] && (v === 0 || v === 1 || v === true || v === false) ? boolCellHtml(v) : escapeHtml(String(v ?? "—"));
      bodyEl.innerHTML = `<div class="identify-join-scroll"><table class="identify-table identify-join-table">
        <thead><tr>${data.columns.map((c) => `<th>${escapeHtml(c)}</th>`).join("")}</tr></thead>
        <tbody>${data.rows.map((r) =>
          `<tr>${r.map((v, j) => `<td>${joinCell(v, j)}</td>`).join("")}</tr>`
        ).join("")}</tbody></table></div>
        <div class="hint">${data.rows.length} baris</div>`;
    } catch (err) {
      bodyEl.className = "identify-join-body hint";
      bodyEl.textContent = String(err.message || err);
    }
  };
  sel.addEventListener("change", load);
  load();
}

function clearIdentifyHighlight() {
  if (!state.identifyHighlight) return;
  const { layer, feature } = state.identifyHighlight;
  state.mapLayers.active[layer]?.revertStyle(feature);
  state.identifyHighlight = null;
}

/* ---------- Select (klik fitur -> highlight + daftar terpilih) ---------- */

function toggleFeatureSelection(layerName, feature) {
  const data = state.mapLayers.active[layerName];
  if (!data) return;
  const idx = state.selectedFeatures.findIndex((s) => s.layer === layerName && s.feature === feature);
  if (idx >= 0) {
    data.revertStyle(feature);
    state.selectedFeatures.splice(idx, 1);
  } else {
    data.overrideStyle(feature, { strokeColor: "#ffffff", strokeWeight: 3, fillOpacity: 0.55, zIndex: 100 });
    state.selectedFeatures.push({ layer: layerName, feature });
  }
  renderSelectionPanel();
}

function clearSelection() {
  state.selectedFeatures.forEach(({ layer, feature }) => {
    state.mapLayers.active[layer]?.revertStyle(feature);
  });
  state.selectedFeatures = [];
  renderSelectionPanel();
}

function clearSelectionForLayer(layerName) {
  state.selectedFeatures = state.selectedFeatures.filter((s) => s.layer !== layerName);
  renderSelectionPanel();
  if (state.identifyHighlight?.layer === layerName) {
    state.identifyHighlight = null;
    state.identifyInfoWindow?.close();
  }
}

function renderSelectionPanel() {
  const panel = document.getElementById("mapSelectionPanel");
  const listEl = document.getElementById("mapSelectionList");
  const countEl = document.getElementById("mapSelectionCount");

  if (!state.selectedFeatures.length) {
    panel.hidden = true;
    listEl.innerHTML = "";
    return;
  }

  panel.hidden = false;
  countEl.textContent = `${state.selectedFeatures.length} fitur terpilih`;
  listEl.innerHTML = "";
  state.selectedFeatures.forEach(({ layer, feature }, i) => {
    const nameKey = ["nama", "NAMOBJ", "REMARK", "name"].find((k) => feature.getProperty(k));
    const label = nameKey ? feature.getProperty(nameKey) : `Fitur #${i + 1}`;
    const row = document.createElement("div");
    row.className = "map-selection-item";
    row.innerHTML = `
      <span class="maplayer-swatch" style="background:${mapLayerColor(mapLayerRawName(layer))}"></span>
      <span class="map-selection-item-label">${escapeHtml(String(label))}</span>
      <span class="map-selection-item-layer">${escapeHtml(mapLayerDisplayLabel(layer))}</span>
    `;
    listEl.appendChild(row);
  });
}

/* ---------- Measure (ukur jarak/luas langsung di peta, murni client-side) ---------- */

function handleMeasureClick(pt) {
  state.measure.path.push(pt);
  redrawMeasureOverlay();
}

function redrawMeasureOverlay() {
  const path = state.measure.path.map((p) => ({ lat: p.lat, lng: p.lng }));
  if (state.measure.overlay) state.measure.overlay.setMap(null);

  if (state.mapTool === "measure-area") {
    if (path.length < 3) {
      state.measure.overlay = null;
      setMeasureText(path.length ? "Klik minimal 3 titik untuk mengukur luas" : "Klik titik pertama di peta");
      return;
    }
    state.measure.overlay = new google.maps.Polygon({
      paths: path, map: state.map, clickable: false, zIndex: 50,
      strokeColor: MEASURE_LINE_COLOR, strokeWeight: 2, fillColor: MEASURE_LINE_COLOR, fillOpacity: 0.15,
    });
    setMeasureText(`Luas: ${formatMeasureArea(google.maps.geometry.spherical.computeArea(path))}`);
  } else {
    if (path.length < 2) {
      state.measure.overlay = null;
      setMeasureText("Klik titik pertama di peta");
      return;
    }
    state.measure.overlay = new google.maps.Polyline({
      path, map: state.map, clickable: false, zIndex: 50,
      strokeColor: MEASURE_LINE_COLOR, strokeWeight: 3,
    });
    setMeasureText(`Jarak: ${formatMeasureDistance(google.maps.geometry.spherical.computeLength(path))}`);
  }
}

function formatMeasureDistance(meters) {
  return meters >= 1000 ? `${(meters / 1000).toFixed(2)} km` : `${meters.toFixed(0)} m`;
}

function formatMeasureArea(sqMeters) {
  return sqMeters >= 10000 ? `${(sqMeters / 10000).toFixed(2)} ha` : `${sqMeters.toFixed(0)} m²`;
}

function setMeasureText(text) {
  const el = document.getElementById("mapMeasureText");
  if (el) el.textContent = text;
}

function finishMeasure() {
  state.measure.path = [];
  setMeasureText("Klik peta untuk mulai ukuran baru");
}

function clearMeasure() {
  if (state.measure.overlay) state.measure.overlay.setMap(null);
  state.measure = { path: [], overlay: null };
  setMeasureText("");
}

/* ---------- Legend (daftar swatch untuk layer overlay yang aktif) ---------- */

function updateMapLegend() {
  const listEl = document.getElementById("mapLegendList");
  if (!listEl) return;
  const keys = Object.keys(state.mapLayers.active);
  if (!keys.length) {
    listEl.innerHTML = `<div class="maplayer-loading">Belum ada layer overlay aktif</div>`;
    return;
  }
  // Kalau layer bernama sama aktif di >1 kabupaten sekaligus, beri nama
  // kabupatennya juga di legend supaya baris-baris itu bisa dibedakan
  // (dan di-uncheck satu-satu) — bukan cuma "N layer aktif" tanpa rincian
  // sumbernya, gaya panel TOC ArcGIS.
  const rawCounts = {};
  keys.forEach((k) => {
    const raw = mapLayerRawName(k);
    rawCounts[raw] = (rawCounts[raw] || 0) + 1;
  });
  listEl.innerHTML = "";
  keys.forEach((key) => {
    const meta = state.mapLayers.meta[key];
    const raw = mapLayerRawName(key);
    const label = mapLayerDisplayLabel(key)
      + (meta && rawCounts[raw] > 1 ? ` — ${meta.kabupaten || meta.provinsi}` : "");
    const row = document.createElement("div");
    row.className = "map-legend-item";
    row.innerHTML = `
      <span class="maplayer-swatch" style="background:${mapLayerColor(raw)}"></span>
      <span class="map-legend-item-label">${escapeHtml(label)}</span>
      <button type="button" class="map-legend-item-remove" data-key="${escapeHtml(key)}" title="Matikan layer ini"><i class="bi bi-x-lg"></i></button>
    `;
    listEl.appendChild(row);
  });
}
