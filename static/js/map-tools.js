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
    hideIdentifyPanel();
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
    select: "Klik fitur untuk memilih, Shift+klik untuk memilih lebih dari satu",
    "measure-distance": "Klik titik-titik di peta untuk mengukur jarak, lalu klik \"Selesai\"",
    "measure-area": "Klik titik-titik di peta untuk mengukur luas area, lalu klik \"Selesai\"",
  };
  setStatus(tool ? (hints[tool] || "") : "Peta siap");
}

/* ---------- Identify (klik fitur layer overlay -> tampilkan atribut) ---------- */

function onFeatureClick(layerName, feature, latLng) {
  if (state.mapTool === "identify") {
    if (state.identifyHighlight?.layer === layerName && state.identifyHighlight?.feature === feature) {
      clearIdentifyHighlight();
      hideIdentifyPanel();
      return;
    }
    showIdentifyInfo(layerName, feature, latLng);
  } else if (state.mapTool === "select") {
    toggleFeatureSelection(layerName, feature);
  }
}

const IDENTIFY_HIGHLIGHT_STYLE = { strokeColor: "#22d3a5", strokeWeight: 4, strokeOpacity: 1, fillOpacity: 0.5, zIndex: 100 };

// Ikon pin (bentuk "location_on" Material) untuk fitur TITIK yang sedang dipilih:
// lingkaran kecil bawaan layer (scale 4) nyaris tidak terbedakan dari titik
// lain, sedangkan strokeColor/strokeWeight di atas tidak berpengaruh pada
// titik. Dibangun lewat fungsi (bukan konstanta) karena google.maps.Point baru
// ada setelah Maps SDK termuat. Poligon/garis mengabaikan properti `icon`.
const PIN_PATH = "M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7zm0 9.5c-1.38 0-2.5-1.12-2.5-2.5s1.12-2.5 2.5-2.5 2.5 1.12 2.5 2.5-1.12 2.5-2.5 2.5z";

function identifyHighlightStyle(color = "#ef1c1c") {
  return {
    ...IDENTIFY_HIGHLIGHT_STYLE,
    zIndex: 1000,
    icon: {
      path: PIN_PATH, fillColor: color, fillOpacity: 1,
      strokeColor: "#ffffff", strokeWeight: 1.5,
      scale: 1.9, anchor: new google.maps.Point(12, 22),
    },
  };
}

// Beberapa sumber (mis. KML KAI) menyimpan deskripsi sebagai satu string
// dengan literal "<br>" sebagai pemisah baris -- escape dulu isinya lalu
// ganti pemisah itu jadi <br> sungguhan, supaya tidak tampil sebagai teks
// mentah "&lt;br&gt;" di popup identify.
function formatIdentifyValue(raw) {
  return raw
    .split(/<br\s*\/?>/i)
    .map((part) => escapeHtml(part.trim()))
    .filter((part) => part !== "")
    .join("<br>");
}

function showIdentifyInfo(layerName, feature, latLng) {
  clearIdentifyHighlight();
  state.mapLayers.active[layerName]?.overrideStyle(feature, identifyHighlightStyle());
  state.identifyHighlight = { layer: layerName, feature };

  const rows = [];
  feature.forEachProperty((value, key) => {
    if (value === null || value === undefined || value === "") return;
    if (String(key).startsWith("_")) return; // atribut teknis (legenda/filter), bukan utk ditampilkan
    rows.push(`<tr><th>${escapeHtml(key)}</th><td>${formatIdentifyValue(String(value))}</td></tr>`);
  });
  const body = rows.length
    ? `<table class="identify-table">${rows.join("")}</table>`
    : `<div class="hint">Fitur ini tidak memiliki atribut</div>`;

  // Konten dibangun sebagai DOM node (bukan string) supaya select join tabel
  // di bawah bisa langsung diberi event listener.
  const container = document.createElement("div");
  container.className = "identify-info";
  container.innerHTML = body;
  const kodeKec = feature.getProperty("KODE_KECAMATAN");
  if (kodeKec) attachKecamatanJoin(container, kodeKec);
  // Kantor SAR punya nama_kantor langsung; Pos SAR simpan nama kantor
  // induknya di "Nama Kantor SAR" (lihat scripts/import_basarnas_to_postgis.py)
  // -- keduanya di-join ke tabel referensi BASARNAS yang sama.
  const namaKantorSar = feature.getProperty("nama_kantor") || feature.getProperty("Nama Kantor SAR");
  if (namaKantorSar) {
    attachKantorSarWilayah(container, namaKantorSar, !feature.getProperty("nama_kantor"));
    attachKantorSarJoin(container, namaKantorSar);
  }
  if (layerName.startsWith("BATAS PROVINSI::")) {
    const namaProvinsi = feature.getProperty("PROVINSI");
    if (namaProvinsi) attachLakaLantasJoin(container, namaProvinsi);
  }
  // Layer "Bandara Kemenhub" (native, titik = baris bandara_kemenhub
  // sendiri) punya "Bandara ID" persis -- exact match, GET
  // /api/bandara-kemenhub/{id}. Layer "Bandara"/"Bandara(1)" (SHP RBI lama,
  // titik terpisah tanpa ID ini) fallback ke padanan nama best-effort,
  // GET /api/maps/bandara-kemenhub-by-nama.
  if (mapLayerRawName(layerName).startsWith("Bandara")) {
    const bandaraId = feature.getProperty("Bandara ID");
    const namaBandara = feature.getProperty("Name");
    if (bandaraId != null) {
      attachBandaraKemenhubJoin(container, `/api/bandara-kemenhub/${encodeURIComponent(bandaraId)}`);
    } else if (namaBandara) {
      attachBandaraKemenhubJoin(container, `/api/maps/bandara-kemenhub-by-nama?nama=${encodeURIComponent(namaBandara)}`);
    }
  }

  openIdentifyPanel(mapLayerDisplayLabel(layerName), container);
}

/* Panel identify mengambang (pengganti google.maps.InfoWindow, 24 Sep 2026):
   InfoWindow menempel di titik klik dan tidak bisa digeser, jadi menutupi
   fitur/poligon yang sedang diidentifikasi (mis. wilayah tanggung jawab SAR).
   Panel ini digeser lewat headernya, bisa diciutkan, dan posisinya diingat
   selama halaman terbuka. Isi (`container`) & gayanya sama seperti popup lama. */
function getIdentifyPanel() {
  let panel = document.getElementById("identifyPanel");
  if (panel) return panel;
  panel = document.createElement("div");
  panel.id = "identifyPanel";
  panel.className = "identify-panel";
  panel.hidden = true;
  panel.innerHTML = `
    <div class="identify-panel-head" title="Geser untuk memindahkan panel">
      <i class="bi bi-grip-vertical"></i>
      <span class="identify-panel-title"></span>
      <button type="button" class="identify-panel-btn" data-act="collapse" title="Ciutkan / bentangkan"><i class="bi bi-dash-lg"></i></button>
      <button type="button" class="identify-panel-btn" data-act="close" title="Tutup"><i class="bi bi-x-lg"></i></button>
    </div>
    <div class="identify-panel-body"></div>`;
  const area = document.querySelector(".map-area");
  area.appendChild(panel);

  const head = panel.querySelector(".identify-panel-head");
  let drag = null;
  head.addEventListener("pointerdown", (e) => {
    if (e.target.closest("button")) return;
    const r = panel.getBoundingClientRect();
    drag = { dx: e.clientX - r.left, dy: e.clientY - r.top };
    head.setPointerCapture(e.pointerId);
    head.classList.add("dragging");
  });
  head.addEventListener("pointermove", (e) => {
    if (!drag) return;
    const a = area.getBoundingClientRect();
    const w = panel.offsetWidth;
    // header harus tetap terjangkau: sisakan minimal 80px di dalam area peta
    const left = Math.min(Math.max(e.clientX - drag.dx - a.left, 80 - w), a.width - 80);
    const top = Math.min(Math.max(e.clientY - drag.dy - a.top, 0), a.height - 40);
    panel.style.left = `${left}px`;
    panel.style.top = `${top}px`;
  });
  const endDrag = () => { drag = null; head.classList.remove("dragging"); };
  head.addEventListener("pointerup", endDrag);
  head.addEventListener("pointercancel", endDrag);

  panel.querySelector('[data-act="collapse"]').addEventListener("click", () => {
    panel.classList.toggle("collapsed");
  });
  panel.querySelector('[data-act="close"]').addEventListener("click", () => {
    hideIdentifyPanel();
    clearIdentifyHighlight();
  });
  return panel;
}

function openIdentifyPanel(title, contentEl) {
  const panel = getIdentifyPanel();
  panel.querySelector(".identify-panel-title").textContent = title;
  const body = panel.querySelector(".identify-panel-body");
  body.replaceChildren(contentEl);
  panel.classList.remove("collapsed");
  panel.hidden = false;
}

function hideIdentifyPanel() {
  const panel = document.getElementById("identifyPanel");
  if (panel) panel.hidden = true;
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

/* Wilayah tanggung jawab SAR: klik titik Kantor SAR/Pos SAR (mode Identify)
   -> poligon wilayah kerja kantornya digambar di layer Data khusus, terpisah
   dari overlay "Wilayah Tanggung Jawab SAR" di panel layer (yang memuat 43
   poligon sekaligus, ~22 MB). Dibersihkan lewat clearIdentifyHighlight.
   Kantor Pos SAR memakai wilayah kantor induknya. */
let kantorSarWilayahData = null;
let kantorSarWilayahToken = 0;

function clearKantorSarWilayah() {
  kantorSarWilayahToken++; // batalkan fetch yang masih jalan
  if (kantorSarWilayahData) {
    kantorSarWilayahData.forEach((f) => kantorSarWilayahData.remove(f));
  }
}

function zoomKantorSarWilayah() {
  if (!kantorSarWilayahData) return;
  const bounds = new google.maps.LatLngBounds();
  kantorSarWilayahData.forEach((f) => f.getGeometry().forEachLatLng((ll) => bounds.extend(ll)));
  if (!bounds.isEmpty()) state.map.fitBounds(bounds);
}

function attachKantorSarWilayah(container, namaKantor, isPos = false) {
  const wrap = document.createElement("div");
  wrap.className = "identify-join";
  wrap.innerHTML = `
    <div class="identify-join-head"><i class="bi bi-bounding-box-circles"></i> ${isPos ? "Wilayah Kantor SAR induk" : "Wilayah tanggung jawab"}</div>
    <div class="identify-join-body hint">Memuat...</div>`;
  container.appendChild(wrap);
  const bodyEl = wrap.querySelector(".identify-join-body");
  const token = ++kantorSarWilayahToken;

  (async () => {
    try {
      const res = await fetch(`/api/kantor-sar/wilayah?nama_kantor=${encodeURIComponent(namaKantor)}`);
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Gagal memuat");
      if (token !== kantorSarWilayahToken) return; // popup sudah ditutup/pindah ke fitur lain
      if (!data.tersedia) {
        bodyEl.textContent = isPos
          ? `Pos SAR tidak memiliki poligon sendiri, dan poligon Kantor SAR induknya (${data.kantor}) juga tidak ada di data sumber.`
          : data.catatan;
        return;
      }
      if (!kantorSarWilayahData) kantorSarWilayahData = new google.maps.Data({ map: state.map });
      kantorSarWilayahData.forEach((f) => kantorSarWilayahData.remove(f));
      kantorSarWilayahData.addGeoJson(data.geojson);
      // Pos SAR: data sumber BASARNAS TIDAK punya poligon per Pos SAR (hanya 43
      // poligon milik Kantor SAR), jadi yang digambar adalah wilayah kantor
      // induknya -- warna oranye + catatan eksplisit agar tidak dikira wilayah Pos itu sendiri.
      const warna = isPos ? "#f59e0b" : "#3b82f6";
      kantorSarWilayahData.setStyle({
        fillColor: warna, fillOpacity: 0.12, strokeColor: warna, strokeWeight: 2,
        clickable: false, zIndex: 1,
      });
      bodyEl.className = "identify-join-body";
      const catatanPos = isPos
        ? `<div class="hint">Pos SAR tidak memiliki poligon wilayah sendiri di data sumber. Yang ditampilkan adalah wilayah tanggung jawab <b>Kantor SAR ${escapeHtml(data.kantor)}</b> (induknya), bukan wilayah kerja Pos ini.</div>`
        : "";
      bodyEl.innerHTML = `${catatanPos}Ditampilkan di peta (${data.call_sign ? escapeHtml(data.call_sign) + " · " : ""}Kelas ${escapeHtml(data.tipe_kelas || "-")} ·
        ${data.luas_km2.toLocaleString("id-ID")} km²)
        <button type="button" class="btn btn-ghost btn-sm identify-wilayah-zoom"><i class="bi bi-zoom-in"></i> Zoom ke wilayah</button>`;
      bodyEl.querySelector(".identify-wilayah-zoom").addEventListener("click", zoomKantorSarWilayah);
    } catch (err) {
      bodyEl.textContent = String(err.message || err);
    }
  })();
}

/* Join layer "BATAS PROVINSI" ke anev_laka_lantas_polda (statistik
   kecelakaan lalu lintas Korlantas POLRI per POLDA, 2020-2025) -- beda dari
   attachKecamatanJoin/attachKantorSarJoin di atas krn cuma 1 sumber (tidak
   perlu dropdown pilih tabel); padanan provinsi->polda-nya sendiri sudah
   diselesaikan di backend (PROVINSI_POLDA_MAP, app.py) krn nama POLDA tidak
   selalu sama dengan nama provinsinya (mis. DKI Jakarta -> "METRO JAYA"). */
function attachLakaLantasJoin(container, namaProvinsi) {
  const wrap = document.createElement("div");
  wrap.className = "identify-join";
  wrap.innerHTML = `
    <div class="identify-join-head"><i class="bi bi-exclamation-triangle"></i> Kecelakaan Lalu Lintas (Korlantas POLRI)</div>
    <div class="identify-join-body hint">Memuat...</div>`;
  container.appendChild(wrap);
  const bodyEl = wrap.querySelector(".identify-join-body");

  (async () => {
    try {
      const res = await fetch(`/api/provinsi/${encodeURIComponent(namaProvinsi)}/laka-lantas`);
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Gagal memuat");
      if (!data.tersedia || !data.rows.length) {
        bodyEl.innerHTML = `<div class="hint">Data POLDA belum tersedia untuk provinsi ini.</div>`;
        return;
      }
      bodyEl.className = "identify-join-body";
      bodyEl.innerHTML = `<div class="identify-join-scroll"><table class="identify-table identify-join-table">
        <thead><tr><th>Tahun</th><th>Kejadian</th><th>Korban MD</th><th>Korban LB</th><th>Korban LR</th><th>Kerugian (Rp)</th></tr></thead>
        <tbody>${data.rows.map((r) => `<tr>
          <td>${escapeHtml(String(r.tahun ?? "—"))}</td>
          <td>${r.kejadian ?? "—"}</td>
          <td>${r.korban_md ?? "—"}</td>
          <td>${r.korban_lb ?? "—"}</td>
          <td>${r.korban_lr ?? "—"}</td>
          <td>${r.kerugian_materi != null ? formatRupiah(r.kerugian_materi) : "—"}</td>
        </tr>`).join("")}</tbody></table></div>
        <div class="hint">POLDA ${escapeHtml(data.polda)} · ${data.rows.length} tahun</div>`;
    } catch (err) {
      bodyEl.className = "identify-join-body hint";
      bodyEl.textContent = String(err.message || err);
    }
  })();
}

/* Join layer overlay "Bandara"/"Bandara(1)" (SHP RBI, map_layers) ke
   bandara_kemenhub (596 bandara, live scrape hubud.kemenhub.go.id, lihat
   scripts/scrape_bandara_kemenhub.py) -- name-match best-effort via
   GET /api/maps/bandara-kemenhub-by-nama, pola sama dgn
   attachLakaLantasJoin (1 sumber, tanpa dropdown pilih tabel). Isi lebih
   kaya dari sekadar tabel kolom=nilai (rute/fasilitas/terdekat/galeri),
   jadi dirender custom, bukan reuse identify-table generik. */
function attachBandaraKemenhubJoin(container, fetchUrl) {
  const wrap = document.createElement("div");
  wrap.className = "identify-join";
  wrap.innerHTML = `
    <div class="identify-join-head"><i class="bi bi-airplane"></i> Data Bandara (hubud.kemenhub.go.id)</div>
    <div class="identify-join-body hint">Memuat...</div>`;
  container.appendChild(wrap);
  const bodyEl = wrap.querySelector(".identify-join-body");

  (async () => {
    try {
      const res = await fetch(fetchUrl);
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Gagal memuat");
      bodyEl.className = "identify-join-body";
      // Reuse renderer yang sama dgn panel "Jelajahi Usulan Inpres" (moda
      // Udara, static/js/usulan-inpres.js) -- semua tab (rute/terdekat/
      // fasilitas/galeri) sekaligus, bukan versi ringkas terpisah.
      renderBandaraKemenhubEnrichment(bodyEl, data);
    } catch (err) {
      bodyEl.className = "identify-join-body hint";
      bodyEl.textContent = String(err.message || err);
    }
  })();
}

function clearIdentifyHighlight() {
  clearKantorSarWilayah();
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
    data.overrideStyle(feature, {
      ...identifyHighlightStyle("#ffb648"), strokeColor: "#ffffff", strokeWeight: 3, fillOpacity: 0.55,
    });
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
    hideIdentifyPanel();
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
    // Layer "Stasiun Kereta Api" punya banyak warna sekaligus (per STATUS
    // OPERASI, lihat STASIUN_STATUS_COLORS di maps-overlay.js) -- satu swatch
    // polos di atas tidak cukup mewakilinya, jadi tambahkan sub-daftar
    // kategori di bawahnya, meniru legenda sumber Google My Maps-nya.
    const kaplinLegend = raw === "KAPLIN PETAK JALAN" ? KAPLIN_UTILISASI_LEGEND
      : raw === "KAPLIN KORIDOR UTAMA" ? KAPLIN_KORIDOR_LEGEND : null;
    if (kaplinLegend) {
      const sub = document.createElement("div");
      sub.className = "map-legend-subitems";
      sub.innerHTML = kaplinLegend.map(([c, t]) => `
        <div class="map-legend-subitem">
          <span style="display:inline-block;width:28px;height:4px;background:${c};border-radius:2px"></span>
          <span class="map-legend-subitem-label">${escapeHtml(t)}</span>
        </div>`).join("");
      listEl.appendChild(sub);
    }
    if (raw.startsWith(ARUS_LAYER_PREFIX)) {
      listEl.appendChild(renderArusLegend(key, raw));
      if (key === keys.find((k) => mapLayerRawName(k).startsWith(ARUS_LAYER_PREFIX))) {
        listEl.appendChild(renderArusControls(key));
      }
    }
    if (raw === STASIUN_LAYER_NAME) {
      const sub = document.createElement("div");
      sub.className = "map-legend-subitems";
      sub.innerHTML = Object.entries(STASIUN_STATUS_COLORS).map(([status, c]) => `
        <div class="map-legend-subitem">
          <span class="maplayer-swatch" style="background:${c}"></span>
          <span class="map-legend-subitem-label">${escapeHtml(status)}</span>
        </div>
      `).join("");
      listEl.appendChild(sub);
    }
  });
}


/* ---------- Legend & filter layer Arus Perdagangan Antar Provinsi ---------- */

// Skala ketebalan: 5 contoh garis dari nilai terkecil (di atas batas bawah
// skala) sampai terbesar, dengan interpolasi log seperti di
// scripts/import_arus_irio_provinsi.py (0.8-12 px).
function renderArusLegend(key, raw) {
  const data = state.mapLayers.active[key];
  const perTon = raw.endsWith("TON");
  // skala global (sama utk "Seluruh Indonesia" dan tiap provinsi) dibawa di tiap fitur
  let lo = 0, hi = 0;
  data.forEach((f) => {
    if (hi) return;
    lo = Number(f.getProperty("_skala_lo")) || 0;
    hi = Number(f.getProperty("_skala_hi")) || 0;
  });
  if (!lo) lo = hi;
  const fmtNilai = (v) => {
    if (perTon) return `${Math.round(v).toLocaleString("id-ID")} ton`;
    return v >= 1e6 ? `Rp ${(v / 1e6).toLocaleString("id-ID", { maximumFractionDigits: 1 })} triliun`
      : `Rp ${Math.round(v).toLocaleString("id-ID")} juta`;
  };
  const wrap = document.createElement("div");
  wrap.className = "map-legend-subitems";
  const color = "#7a8599"; // abu netral: contoh ketebalan saja, warna = pulau asal (di bawah)
  wrap.innerHTML = `<div class="map-legend-subitem-label" style="font-weight:600;margin:2px 0">Ketebalan garis</div>` + [0, 0.25, 0.5, 0.75, 1].map((t) => {
    const w = 0.8 + (12 - 0.8) * t;
    const v = hi > lo ? lo * Math.pow(hi / lo, t) : hi;
    return `<div class="map-legend-subitem">
      <span style="display:inline-block;width:34px;height:${Math.max(1, w)}px;background:${color};opacity:.7;border-radius:2px"></span>
      <span class="map-legend-subitem-label">${t === 0 ? "≤ " : ""}${escapeHtml(fmtNilai(v))}</span>
    </div>`;
  }).join("") + `<div class="map-legend-subitem-label" style="font-weight:600;margin:6px 0 2px">Warna garis = pulau asal</div>`
    + Object.entries(ARUS_PULAU_COLORS).map(([nama, c]) => `<div class="map-legend-subitem">
      <span class="maplayer-swatch" style="background:${c}"></span>
      <span class="map-legend-subitem-label">${escapeHtml(nama)}</span>
    </div>`).join("");
  return wrap;
}

function renderArusControls(key) {
  const data = state.mapLayers.active[key];
  const pulau = new Set(), prov = new Set();
  data.forEach((f) => {
    [f.getProperty("Pulau Asal"), f.getProperty("Pulau Tujuan")].forEach((p) => p && pulau.add(p));
    [f.getProperty("Provinsi Asal"), f.getProperty("Provinsi Tujuan")].forEach((p) => p && prov.add(p));
  });
  const opts = (set, semua, sel) => `<option value="">${semua}</option>`
    + [...set].sort((a, b) => a.localeCompare(b, "id"))
      .map((v) => `<option value="${escapeHtml(v)}"${v === sel ? " selected" : ""}>${escapeHtml(v)}</option>`).join("");
  const wrap = document.createElement("div");
  wrap.className = "map-legend-subitems arus-filter";
  wrap.innerHTML = `
    <div class="map-legend-subitem-label" style="font-weight:600;margin:6px 0 2px">Filter arus</div>
    <select class="laporan-moda-select" data-f="pulau" title="Filter gugus pulau">${opts(pulau, "Nasional (semua pulau)", arusFilter.pulau)}</select>
    <select class="laporan-moda-select" data-f="provinsi" title="Filter provinsi">${opts(prov, "Semua provinsi", arusFilter.provinsi)}</select>
    <select class="laporan-moda-select" data-f="arah" title="Pulau/provinsi sebagai...">
      <option value="keduanya">Asal atau tujuan</option>
      <option value="keluar">Asal saja (keluar)</option>
      <option value="masuk">Tujuan saja (masuk)</option>
    </select>
    <label class="map-legend-subitem-label" style="display:block;margin-top:4px">
      <input type="checkbox" data-f="antarPulau" ${arusFilter.antarPulau ? "checked" : ""}/> Hanya antar pulau
    </label>`;
  wrap.querySelector('[data-f="arah"]').value = arusFilter.arah;
  wrap.addEventListener("change", (e) => {
    const f = e.target.dataset.f;
    if (!f) return;
    arusFilter[f] = e.target.type === "checkbox" ? e.target.checked : e.target.value;
    applyArusFilter();
  });
  return wrap;
}
