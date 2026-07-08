/* RouteGIS — overlay peta referensi (layer SHP dari folder Maps/<provinsi>/<kabupaten>/)
   Daftar provinsi/kabupaten/layer dibaca langsung dari isi folder Maps/ setiap
   dropdown dibuka (bukan sekali saat load halaman) — supaya file yang
   ditambah/dipindah di folder tersebut otomatis muncul tanpa reload. */

const MAP_LAYER_PALETTE = ["#4f7cff", "#22d3a5", "#ffb648", "#ff5c7c", "#a78bfa", "#38bdf8", "#f472b6", "#facc15"];

function mapLayerColor(layerName) {
  if (!state.mapLayers.colors[layerName]) {
    const idx = Object.keys(state.mapLayers.colors).length % MAP_LAYER_PALETTE.length;
    state.mapLayers.colors[layerName] = MAP_LAYER_PALETTE[idx];
  }
  return state.mapLayers.colors[layerName];
}

async function initMapLayersControl() {
  const control = document.getElementById("mapLayerControl");
  const hasData = await refreshMapLayerProvinces();
  if (!hasData) return; // folder Maps/ kosong, sembunyikan kontrol

  await refreshMapLayerKabupaten();
  await refreshMapLayerList();

  control.hidden = false;
  bindMapLayerToggle();
  bindMapLayerCombo("mapLayerProvinsiField", "mapLayerProvinsiToggle", "mapLayerProvinsiPanel", async () => {
    await refreshMapLayerProvinces();
  }, async (provinsi) => {
    state.mapLayers.selectedProvinsi = provinsi;
    state.mapLayers.selectedKabupaten = null;
    clearActiveMapLayers();
    await refreshMapLayerKabupaten();
    await refreshMapLayerList();
  });
  bindMapLayerCombo("mapLayerKabupatenField", "mapLayerKabupatenToggle", "mapLayerKabupatenPanel", async () => {
    await refreshMapLayerKabupaten();
  }, async (kabupaten) => {
    state.mapLayers.selectedKabupaten = kabupaten;
    clearActiveMapLayers();
    await refreshMapLayerList();
  });
}

/* ---------- combo dropdown mechanics ---------- */

function bindMapLayerCombo(fieldId, toggleId, panelId, onOpen, onSelect) {
  const field = document.getElementById(fieldId);
  const toggle = document.getElementById(toggleId);
  const panel = document.getElementById(panelId);

  toggle.addEventListener("click", async (e) => {
    e.stopPropagation();
    const willOpen = panel.hidden;
    closeAllMapLayerCombos();
    if (willOpen) {
      await onOpen();
      panel.hidden = false;
      field.classList.add("open");
    }
  });

  panel.addEventListener("click", (e) => {
    const opt = e.target.closest(".maplayer-combo-option");
    if (!opt) return;
    panel.hidden = true;
    field.classList.remove("open");
    onSelect(opt.dataset.value);
  });
}

function closeAllMapLayerCombos() {
  document.querySelectorAll(".maplayer-combo").forEach((field) => {
    field.classList.remove("open");
    field.querySelector(".maplayer-combo-panel").hidden = true;
  });
}

function fillComboPanel(panelId, labelId, rows, valueKey, textFn, selectedValue) {
  const panel = document.getElementById(panelId);
  const label = document.getElementById(labelId);
  panel.innerHTML = "";
  const chosen = rows.find((r) => r[valueKey] === selectedValue) ? selectedValue : rows[0]?.[valueKey];
  rows.forEach((r) => {
    const opt = document.createElement("div");
    opt.className = "maplayer-combo-option" + (r[valueKey] === chosen ? " selected" : "");
    opt.dataset.value = r[valueKey];
    opt.textContent = textFn(r);
    panel.appendChild(opt);
  });
  label.textContent = rows.length ? textFn(rows.find((r) => r[valueKey] === chosen)) : "Tidak ada data";
  return chosen;
}

/* ---------- data loading (re-scans Maps/ folder every call) ---------- */

async function refreshMapLayerProvinces() {
  let provinces = [];
  try {
    const res = await fetch("/api/maps/provinces");
    if (!res.ok) throw new Error(await res.text());
    provinces = await res.json();
  } catch (err) {
    console.error(err);
    return false;
  }
  if (!provinces.length) return false;

  // Kalau belum ada provinsi terpilih, utamakan yang sudah ada data
  // kabupatennya alih-alih provinsi kosong pertama secara alfabet.
  const defaultProvinsi = state.mapLayers.selectedProvinsi
    || provinces.find((p) => p.kabupaten_count > 0)?.provinsi
    || provinces[0].provinsi;

  const chosen = fillComboPanel(
    "mapLayerProvinsiPanel", "mapLayerProvinsiLabel", provinces, "provinsi",
    (p) => `${p.provinsi} (${p.kabupaten_count})`, defaultProvinsi
  );
  state.mapLayers.selectedProvinsi = chosen;
  return true;
}

async function refreshMapLayerKabupaten() {
  const provinsi = state.mapLayers.selectedProvinsi;
  let rows = [];
  try {
    const res = await fetch(`/api/maps/kabupaten?provinsi=${encodeURIComponent(provinsi)}`);
    if (!res.ok) throw new Error(await res.text());
    rows = await res.json();
  } catch (err) {
    console.error(err);
    document.getElementById("mapLayerList").innerHTML = `<div class="maplayer-loading">Gagal memuat daftar kabupaten</div>`;
    return;
  }

  if (!rows.length) {
    document.getElementById("mapLayerKabupatenPanel").innerHTML = "";
    document.getElementById("mapLayerKabupatenLabel").textContent = "Belum ada data";
    document.getElementById("mapLayerList").innerHTML = `<div class="maplayer-loading">Belum ada data kabupaten untuk provinsi ini</div>`;
    state.mapLayers.selectedKabupaten = null;
    return;
  }

  const defaultKabupaten = state.mapLayers.selectedKabupaten
    || rows.find((r) => r.layer_count > 0)?.kabupaten
    || rows[0].kabupaten;

  const chosen = fillComboPanel(
    "mapLayerKabupatenPanel", "mapLayerKabupatenLabel", rows, "kabupaten",
    (r) => `${r.kabupaten} (${r.layer_count} layer)`, defaultKabupaten
  );
  state.mapLayers.selectedKabupaten = chosen;
}

async function refreshMapLayerList() {
  const listEl = document.getElementById("mapLayerList");
  const provinsi = state.mapLayers.selectedProvinsi;
  const kabupaten = state.mapLayers.selectedKabupaten;
  if (!provinsi || !kabupaten) return;

  try {
    const res = await fetch(`/api/maps/layers?provinsi=${encodeURIComponent(provinsi)}&kabupaten=${encodeURIComponent(kabupaten)}`);
    if (!res.ok) throw new Error(await res.text());
    const layers = await res.json();
    if (!layers.length) {
      listEl.innerHTML = `<div class="maplayer-loading">Belum ada layer (.shp) di folder kabupaten ini</div>`;
      return;
    }
    listEl.innerHTML = "";
    layers.forEach((l) => {
      state.mapLayers.labels[l.layer] = l.label;
      const row = document.createElement("label");
      row.className = "maplayer-item";
      const isActive = !!state.mapLayers.active[l.layer];
      const opacity = state.mapLayers.opacity[l.layer] ?? 1;
      row.innerHTML = `
        <input type="checkbox" ${isActive ? "checked" : ""} data-provinsi="${escapeHtml(provinsi)}" data-kabupaten="${escapeHtml(kabupaten)}" data-layer="${escapeHtml(l.layer)}" />
        <span class="maplayer-swatch" style="background:${mapLayerColor(l.layer)}"></span>
        <span class="maplayer-item-label">${escapeHtml(l.label)}</span>
        <span class="maplayer-item-size">${l.size_mb} MB</span>
        <input type="range" class="maplayer-opacity" min="0" max="1" step="0.05" value="${opacity}" data-layer="${escapeHtml(l.layer)}" title="Transparansi layer" ${isActive ? "" : "hidden"} />
      `;
      listEl.appendChild(row);
    });
  } catch (err) {
    console.error(err);
    listEl.innerHTML = `<div class="maplayer-loading">Gagal memuat daftar layer</div>`;
  }
}

/* ---------- top-level toggle + layer show/hide ---------- */

function bindMapLayerToggle() {
  const control = document.getElementById("mapLayerControl");
  const toggle = document.getElementById("mapLayerToggle");
  const panel = document.getElementById("mapLayerPanel");
  const listEl = document.getElementById("mapLayerList");

  const closePanel = () => {
    panel.hidden = true;
    control.classList.remove("open");
    closeAllMapLayerCombos();
  };

  toggle.addEventListener("click", async (e) => {
    e.stopPropagation();
    const willOpen = panel.hidden;
    if (!willOpen) {
      closePanel();
      return;
    }
    await refreshMapLayerProvinces();
    await refreshMapLayerKabupaten();
    await refreshMapLayerList();
    panel.hidden = false;
    control.classList.add("open");
  });

  document.getElementById("mapLayerClose").addEventListener("click", (e) => {
    e.stopPropagation();
    closePanel();
  });

  document.addEventListener("click", (e) => {
    if (!panel.hidden && !control.contains(e.target)) closePanel();
  });

  listEl.addEventListener("change", async (e) => {
    const cb = e.target.closest('input[type="checkbox"]');
    if (!cb) return;
    const { provinsi, kabupaten, layer } = cb.dataset;
    cb.disabled = true;
    if (cb.checked) {
      await showMapLayer(provinsi, kabupaten, layer);
    } else {
      hideMapLayer(layer);
    }
    cb.disabled = false;
    updateMapLayerLabel();
    const range = cb.closest(".maplayer-item").querySelector(".maplayer-opacity");
    if (range) range.hidden = !cb.checked;
  });

  listEl.addEventListener("input", (e) => {
    const range = e.target.closest(".maplayer-opacity");
    if (!range) return;
    setLayerOpacity(range.dataset.layer, parseFloat(range.value));
  });
}

function updateMapLayerLabel() {
  const label = document.getElementById("mapLayerLabel");
  const n = Object.keys(state.mapLayers.active).length;
  label.textContent = n ? `${n} layer aktif` : "Overlay Peta";
}

async function showMapLayer(provinsi, kabupaten, layer) {
  if (state.mapLayers.active[layer]) return;

  try {
    const url = `/api/maps/layer?provinsi=${encodeURIComponent(provinsi)}&kabupaten=${encodeURIComponent(kabupaten)}&layer=${encodeURIComponent(layer)}`;
    const res = await fetch(url);
    if (!res.ok) throw new Error(await res.text());
    const geojson = await res.json();

    if (!geojson.features || !geojson.features.length) {
      // File .shp ada tapi tidak berisi fitur geometri sama sekali — tanpa
      // pesan ini pengguna mengira show/hide layer tidak berfungsi, padahal
      // memang tidak ada yang bisa ditampilkan.
      toast(`Layer "${geojson.label || layer}" tidak memiliki data geometri (file kosong)`, true);
      const cb = listCheckboxFor(layer);
      if (cb) cb.checked = false;
      return;
    }

    const wasEmpty = Object.keys(state.mapLayers.active).length === 0;

    const data = new google.maps.Data({ map: state.map });
    data.addGeoJson(geojson);
    data.addListener("click", (e) => {
      if (state.mapTool === "measure-distance" || state.mapTool === "measure-area") {
        // Data layer feature click konsumsi event sebelum sempat sampai ke
        // listener "click" milik map (map-bootstrap.js) — tanpa ini, klik di
        // atas layer overlay yang aktif tidak menambah titik ukur.
        handleMeasureClick({ lat: e.latLng.lat(), lng: e.latLng.lng() });
        return;
      }
      if (state.mapTool === "add-point") {
        // Sama seperti measure di atas: tanpa ini, klik di atas layer overlay
        // tidak pernah sampai ke handleMapClick (map-bootstrap.js) karena
        // event sudah dikonsumsi oleh fitur Data layer.
        const pt = { lat: e.latLng.lat(), lng: e.latLng.lng(), label: `${e.latLng.lat().toFixed(5)}, ${e.latLng.lng().toFixed(5)}` };
        handleMapClick(pt);
        return;
      }
      if (e.stop) e.stop();
      onFeatureClick(layer, e.feature, e.latLng);
    });

    state.mapLayers.active[layer] = data;
    applyLayerStyle(layer);
    updateMapLegend();

    // Data ini biasanya di luar jendela peta yang sedang tampil (peta default
    // di Jakarta) — arahkan peta ke sana saat layer pertama diaktifkan, agar
    // pengguna langsung melihat hasilnya alih-alih mengira show/hide tidak jalan.
    if (wasEmpty) {
      const bounds = new google.maps.LatLngBounds();
      data.forEach((feature) => feature.getGeometry().forEachLatLng((latLng) => bounds.extend(latLng)));
      fitBoundsCapped(bounds);
    }
  } catch (err) {
    console.error(err);
    toast("Gagal memuat layer peta", true);
    const cb = listCheckboxFor(layer);
    if (cb) cb.checked = false;
  }
}

function applyLayerStyle(layer) {
  const data = state.mapLayers.active[layer];
  if (!data) return;
  const color = mapLayerColor(layer);
  const opacity = state.mapLayers.opacity[layer] ?? 1;
  data.setStyle((feature) => {
    const type = feature.getGeometry().getType();
    if (type === "Point" || type === "MultiPoint") {
      return {
        icon: {
          path: google.maps.SymbolPath.CIRCLE,
          scale: 4,
          fillColor: color,
          fillOpacity: 0.9 * opacity,
          strokeColor: "#0f1420",
          strokeWeight: 1,
        },
      };
    }
    if (type === "Polygon" || type === "MultiPolygon") {
      return { fillColor: color, fillOpacity: 0.18 * opacity, strokeColor: color, strokeWeight: 1.2, strokeOpacity: opacity };
    }
    return { strokeColor: color, strokeWeight: 1.6, strokeOpacity: 0.9 * opacity };
  });
}

function setLayerOpacity(layer, value) {
  state.mapLayers.opacity[layer] = value;
  applyLayerStyle(layer);
}

function hideMapLayer(layer) {
  const data = state.mapLayers.active[layer];
  if (!data) return;
  data.setMap(null);
  delete state.mapLayers.active[layer];
  clearSelectionForLayer(layer);
  updateMapLegend();
}

function clearActiveMapLayers() {
  Object.keys(state.mapLayers.active).forEach((layer) => clearSelectionForLayer(layer));
  Object.values(state.mapLayers.active).forEach((data) => data.setMap(null));
  state.mapLayers.active = {};
  updateMapLegend();
}

function listCheckboxFor(layer) {
  return document.querySelector(`.maplayer-item input[data-layer="${CSS.escape(layer)}"]`);
}
