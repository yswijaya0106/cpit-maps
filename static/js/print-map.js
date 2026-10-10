/* The Next - SiJalan — cetak peta (PDF/DOCX) dengan label & tabel atribut.

   Mengumpulkan semua yang sedang tergambar DI DALAM tampilan peta saat ini --
   layer overlay aktif (google.maps.Data, gaya diambil dari fungsi setStyle
   yang sama dgn di layar, jadi warna per kategori/_warna ikut), polyline
   usulan Inpres, rute, dan marker titik rute -- lalu mengirimnya ke
   POST /api/peta/cetak. Render basemap, label, legenda, tata letak halaman
   dan tabel atribut dikerjakan server (map_print.py). */

// Kandidat kolom nama utk label default (dicocokkan tanpa beda huruf besar/kecil).
const PRINT_LABEL_CANDIDATES = [
  "_label", "NAMOBJ", "NAMA_RUAS", "NAMA RUAS", "NAMRJL", "NAMA_JALAN", "NAMA JALAN", "NAMA", "NAME",
  "WADMKC", "WADMKK", "WADMPR", "KECAMATAN", "NO_KORIDOR", "REMARK",
];
const PRINT_MAX_FEATURES_PER_LAYER = 20000;

// Pilihan per layer di dialog (dikunci layerKey), bertahan selama sesi.
const printLayerPrefs = {};

function bindPrintMap() {
  const btn = document.getElementById("btnPrintMap");
  if (!btn) return;
  btn.addEventListener("click", openPrintMapDialog);
  document.getElementById("printMapClose").addEventListener("click", closePrintMapDialog);
  document.getElementById("printMapCancel").addEventListener("click", closePrintMapDialog);
  document.getElementById("printMapOverlay").addEventListener("click", (e) => {
    if (e.target.id === "printMapOverlay") closePrintMapDialog();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    if (document.getElementById("printPreviewOverlay")) closePrintPreview();
    else if (!document.getElementById("printMapOverlay").hidden) closePrintMapDialog();
  });
  document.getElementById("printMapPreview").addEventListener("click", previewPrintMap);
  document.getElementById("printMapForm").addEventListener("submit", (e) => {
    e.preventDefault();
    submitPrintMap(buildPrintPayload());
  });
}

function closePrintMapDialog() {
  document.getElementById("printMapOverlay").hidden = true;
}

/* ---------- pengumpulan fitur ---------- */

// google.maps.Data.Geometry -> GeoJSON geometry, SINKRON. Jangan pakai
// feature.toGeoJson(cb): callback-nya dipanggil asinkron di Maps JS versi
// sekarang, jadi hasilnya masih kosong saat dibaca -> semua fitur terbuang.
function printLL(ll) {
  return [Math.round(ll.lng() * 1e6) / 1e6, Math.round(ll.lat() * 1e6) / 1e6];
}

function printRing(ring) {
  const c = ring.getArray().map(printLL);
  if (c.length && (c[0][0] !== c[c.length - 1][0] || c[0][1] !== c[c.length - 1][1])) c.push(c[0]);
  return c;
}

function printGeomToGeoJson(g) {
  const type = g.getType();
  switch (type) {
    case "Point": return { type, coordinates: printLL(g.get()) };
    case "MultiPoint": return { type, coordinates: g.getArray().map(printLL) };
    case "LineString": return { type, coordinates: g.getArray().map(printLL) };
    case "LinearRing": return { type: "LineString", coordinates: printRing(g) };
    case "MultiLineString": return { type, coordinates: g.getArray().map((ls) => ls.getArray().map(printLL)) };
    case "Polygon": return { type, coordinates: g.getArray().map(printRing) };
    case "MultiPolygon": return { type, coordinates: g.getArray().map((p) => p.getArray().map(printRing)) };
    case "GeometryCollection": return { type, geometries: g.getArray().map(printGeomToGeoJson) };
    default: return null;
  }
}

function printFeatureProps(f) {
  const props = {};
  f.forEachProperty((v, k) => { props[k] = v; });
  return props;
}

function printGeomBounds(geom) {
  const b = new google.maps.LatLngBounds();
  geom.forEachLatLng((ll) => b.extend(ll));
  return b;
}

function printGeomJenis(type) {
  if (type === "Point" || type === "MultiPoint") return "titik";
  if (type === "LineString" || type === "MultiLineString" || type === "LinearRing") return "garis";
  return "poligon";
}

function printGuessLabelField(fields) {
  const lower = new Map(fields.map((f) => [f.toLowerCase(), f]));
  for (const c of PRINT_LABEL_CANDIDATES) {
    if (lower.has(c.toLowerCase())) return lower.get(c.toLowerCase());
  }
  return fields.find((f) => /nama|name/i.test(f)) || fields.find((f) => !f.startsWith("_")) || "";
}

function printLabelText(props, field) {
  if (!field) return "";
  const v = props[field];
  if (v === null || v === undefined) return "";
  return String(v).trim();
}

// Sub-legenda: meniru updateMapLegend() (map-tools.js) supaya legenda cetak
// sama dgn legenda di layar.
function printLegendSubitems(key, raw, meta, jenis) {
  let items = null;
  if (raw === "KAPLIN PETAK JALAN") items = KAPLIN_UTILISASI_LEGEND;
  else if (raw === "KAPLIN KORIDOR UTAMA") items = KAPLIN_KORIDOR_LEGEND;
  else if (meta && meta.provinsi === KLASTER_BUCKET) items = KLASTER_LEGEND;
  else if (raw === PERLINTASAN_BTP_LAYER) return PERLINTASAN_BTP_LEGEND.map(([warna, teks]) => ({ warna, teks, jenis: "titik" }));
  else if (typeof RTRW_PAPSEL_LEGEND !== "undefined" && RTRW_PAPSEL_LEGEND[raw]) items = RTRW_PAPSEL_LEGEND[raw];
  else if (LEGENDA_PER_LAYER[raw]) items = LEGENDA_PER_LAYER[raw];
  if (items) return items.map(([warna, teks]) => ({ warna, teks, jenis }));
  if (raw === TOL_RENCANA_LAYER) return TOL_STATUS_LEGEND.map(([warna, teks]) => ({ warna, teks, jenis: "garis" }));
  const kelasJalan = jalanKelasDiLayer(key);
  if (kelasJalan.length) return kelasJalan.map((k) => ({ warna: JALAN_KELAS[k].warna, teks: JALAN_KELAS[k].teks, jenis: "garis" }));
  if (raw === "PETA KORIDOR") return [{ warna: KORIDOR_GAYA.warna, teks: KORIDOR_GAYA.teks, jenis: "garis" }];
  if (raw === AWP1_LAYER) return [{ warna: AWP1_WARNA, teks: "Koridor AWP-1 (skor CER, eksperimental)", jenis: "garis" }];
  if (raw === STASIUN_LAYER_NAME) {
    return Object.entries(STASIUN_STATUS_COLORS).map(([teks, warna]) => ({ warna, teks, jenis: "titik" }))
      .concat([{ warna: STASIUN_STATUS_DEFAULT_COLOR, teks: "Lainnya / tanpa data", jenis: "titik" }]);
  }
  return [];
}

function printStyleFromGoogle(st, jenis, fallbackColor) {
  st = st || {};
  if (jenis === "titik") {
    const icon = st.icon && typeof st.icon === "object" ? st.icon : {};
    const gaya = { point_color: icon.fillColor || fallbackColor, point_radius: icon.scale || 4 };
    // Ikon gambar (pesawat bandara, jangkar, ...): URL-nya dirasterisasi jadi
    // PNG oleh printSiapkanIkon() sebelum dikirim, supaya hasil cetak memakai
    // ikon yang sama dgn di layar, bukan lingkaran (deck 20261007 slide 3).
    const url = typeof st.icon === "string" ? st.icon : icon.url;
    if (typeof url === "string" && url.startsWith("data:image/")) {
      gaya.point_icon_url = url;
      gaya.point_size = icon.scaledSize?.width || 24;
    }
    return gaya;
  }
  return {
    fill: jenis === "poligon" ? (st.fillColor || fallbackColor) : null,
    fill_opacity: jenis === "poligon" ? (st.fillOpacity ?? 0.3) : 0,
    stroke: st.strokeColor || fallbackColor,
    stroke_width: st.strokeWeight ?? 1.5,
    stroke_opacity: st.strokeOpacity ?? 1,
  };
}

// Satu layer overlay -> {key, nama, sumber, warna, jenis, fields, legend, feats:[{gj, style}]}
function printCollectOverlay(key, view, dupRaw) {
  const data = state.mapLayers.active[key];
  const meta = state.mapLayers.meta[key] || {};
  const raw = mapLayerRawName(key);
  const color = mapLayerColor(raw);
  const styleFn = data.getStyle();
  const feats = [];
  const fields = new Set();
  const jenisCount = { titik: 0, garis: 0, poligon: 0 };
  let dilewati = 0;
  data.forEach((f) => {
    const g = f.getGeometry();
    if (!g) return;
    const st = typeof styleFn === "function" ? styleFn(f) : styleFn;
    if (st && st.visible === false) return;
    if (!view.intersects(printGeomBounds(g))) return;
    if (feats.length >= PRINT_MAX_FEATURES_PER_LAYER) { dilewati++; return; }
    const geometry = printGeomToGeoJson(g);
    if (!geometry) return;
    const gj = { geometry, properties: printFeatureProps(f) };
    const jenis = printGeomJenis(g.getType());
    jenisCount[jenis]++;
    Object.keys(gj.properties || {}).forEach((k) => fields.add(k));
    feats.push({ gj, style: printStyleFromGoogle(st, jenis, color) });
  });
  const jenis = Object.entries(jenisCount).sort((a, b) => b[1] - a[1])[0][0];
  const kelasJalan = jalanKelasDiLayer(key);
  return {
    key,
    nama: mapLayerDisplayLabel(key) + (dupRaw[raw] > 1 ? ` — ${meta.kabupaten || meta.provinsi}` : ""),
    sumber: [meta.provinsi, meta.kabupaten].filter(Boolean).join(" / "),
    warna: kelasJalan.length === 1 ? JALAN_KELAS[kelasJalan[0]].warna
      : kelasJalan.length > 1 ? JALAN_KELAS.kabkota.warna
      : raw === "PETA KORIDOR" ? KORIDOR_GAYA.warna : raw === AWP1_LAYER ? AWP1_WARNA : color,
    jenis,
    fields: [...fields],
    legend: printLegendSubitems(key, raw, meta, jenis),
    feats,
    dilewati,
  };
}

function printPolylinePath(pl) {
  return pl.getPath().getArray().map((ll) => [ll.lng(), ll.lat()]);
}

// Polyline usulan Inpres yang tergambar (panel detail & Jelajahi) -> 1 layer,
// digabung per ID usulan (1 usulan bisa beberapa LineString).
function printCollectUsulan(view) {
  const byId = new Map();
  [...(state.usulanPolylines || []), ...(state.browseUsulanPolylines || []), ...usulanMultiPolylines()].forEach((pl) => {
    if (!pl.getMap()) return;
    const path = printPolylinePath(pl);
    if (path.length < 2) return;
    const b = new google.maps.LatLngBounds();
    path.forEach(([lng, lat]) => b.extend({ lat, lng }));
    if (!view.intersects(b)) return;
    const info = pl.get("printInfo") || { id: `garis-${byId.size + 1}`, label: "Usulan", properties: {} };
    const ent = byId.get(info.id) || {
      info, paths: [],
      style: { stroke: pl.get("strokeColor") || "#f59e0b", stroke_width: pl.get("strokeWeight") || 5, stroke_opacity: pl.get("strokeOpacity") ?? 0.95 },
    };
    ent.paths.push(path);
    byId.set(info.id, ent);
  });
  if (!byId.size) return null;
  const feats = [...byId.values()].map((e) => ({
    gj: {
      geometry: e.paths.length === 1 ? { type: "LineString", coordinates: e.paths[0] } : { type: "MultiLineString", coordinates: e.paths },
      properties: { _label: e.info.label, ...e.info.properties },
    },
    style: e.style,
  }));
  return {
    key: "__usulan__", nama: "Usulan Inpres (ruas ditampilkan)", sumber: "SITIA — geometri KML usulan",
    warna: feats[0].style.stroke, jenis: "garis", fields: ["_label", ...Object.keys(feats[0].gj.properties).filter((k) => k !== "_label")],
    legend: [], feats, dilewati: 0,
  };
}

function printCollectRoutes(view) {
  if (!state.routes.length || !state.polylines.length || !state.polylines[0].getMap()) return null;
  const feats = [];
  state.routes.forEach((r, idx) => {
    const coords = r.coordinates.map(([lat, lng]) => [lng, lat]);
    const b = new google.maps.LatLngBounds();
    r.coordinates.forEach(([lat, lng]) => b.extend({ lat, lng }));
    if (!view.intersects(b)) return;
    const selected = idx === state.selectedIndex;
    feats.push({
      gj: {
        geometry: { type: "LineString", coordinates: coords },
        properties: {
          _label: r.route_name || `Rute ${idx + 1}`,
          "Nama Rute": r.route_name || `Rute ${idx + 1}`,
          "Terpilih": selected ? "Ya" : "Tidak",
          "Jarak (km)": Number((r.distance_km || 0).toFixed(2)),
          "Durasi (menit)": Math.round(r.duration_min || 0),
          "Moda": r.transport_mode || "",
        },
      },
      style: { stroke: ROUTE_COLORS[idx % ROUTE_COLORS.length], stroke_width: selected ? 6 : 4, stroke_opacity: selected ? 0.95 : 0.5 },
    });
  });
  if (!feats.length) return null;
  return {
    key: "__rute__", nama: "Rute", sumber: "Google Directions", warna: ROUTE_COLORS[0], jenis: "garis",
    fields: ["_label", "Nama Rute", "Terpilih", "Jarak (km)", "Durasi (menit)", "Moda"], legend: [], feats, dilewati: 0,
  };
}

function printCollectMarkers(view) {
  const pts = [];
  const add = (p, kode, peran, warna) => {
    if (!p || typeof p.lat !== "number" || !view.contains({ lat: p.lat, lng: p.lng })) return;
    pts.push({
      gj: {
        geometry: { type: "Point", coordinates: [p.lng, p.lat] },
        properties: { _label: `${kode} · ${p.label || ""}`.replace(/ · $/, ""), "Kode": kode, "Peran": peran, "Lokasi": p.label || "", "Lintang": Number(p.lat.toFixed(6)), "Bujur": Number(p.lng.toFixed(6)) },
      },
      style: { point_color: warna, point_radius: 7 },
    });
  };
  add(state.origin, "A", "Asal", "#22c55e");
  (state.waypoints || []).forEach((wp, i) => add(wp, String(i + 1), "Waypoint", "#f59e0b"));
  add(state.destination, "B", "Tujuan", "#ef4444");
  if (!pts.length) return null;
  return {
    key: "__titik__", nama: "Titik Rute", sumber: "", warna: "#22c55e", jenis: "titik",
    fields: ["_label", "Kode", "Peran", "Lokasi", "Lintang", "Bujur"],
    legend: [{ warna: "#22c55e", teks: "Asal", jenis: "titik" }, { warna: "#f59e0b", teks: "Waypoint", jenis: "titik" }, { warna: "#ef4444", teks: "Tujuan", jenis: "titik" }],
    feats: pts, dilewati: 0,
  };
}

// Layer hasil Asisten AI yang sedang tampil (chat.js tampilkan_di_peta) -> 1 layer cetak per dataset,
// gaya per fitur diambil dari setStyle-nya sendiri (warna kategori ikut).
function printCollectChat(view) {
  if (typeof chatLayerTampil !== "function") return [];
  return chatLayerTampil().map(([id, l]) => {
    const styleFn = l.data.getStyle();
    const feats = [];
    const fields = new Set();
    let dilewati = 0;
    l.data.forEach((f) => {
      const g = f.getGeometry();
      if (!g || !view.intersects(printGeomBounds(g))) return;
      if (feats.length >= PRINT_MAX_FEATURES_PER_LAYER) { dilewati++; return; }
      const geometry = printGeomToGeoJson(g);
      if (!geometry) return;
      const properties = printFeatureProps(f);
      if (l.kolomLabel && properties[l.kolomLabel] != null) properties._label = String(properties[l.kolomLabel]);
      Object.keys(properties).forEach((k) => fields.add(k));
      const st = typeof styleFn === "function" ? styleFn(f) : styleFn;
      feats.push({ gj: { geometry, properties }, style: printStyleFromGoogle(st, printGeomJenis(g.getType()), l.warna) });
    });
    const kat = Object.entries(l.warnaKat || {});
    return {
      key: `chat:${id}`, nama: l.judul, sumber: "Hasil analisis Asisten AI", warna: kat.length === 1 ? kat[0][1] : l.warna,
      jenis: l.jenis, fields: [...fields],
      legend: kat.length > 1 ? kat.map(([teks, warna]) => ({ warna, teks, jenis: l.jenis })) : [],
      feats, dilewati,
    };
  }).filter((x) => x.feats.length);
}

function printCollectAll() {
  const view = state.map.getBounds();
  const keys = Object.keys(state.mapLayers.active);
  const dupRaw = {};
  keys.forEach((k) => { const r = mapLayerRawName(k); dupRaw[r] = (dupRaw[r] || 0) + 1; });
  const layers = keys.map((k) => printCollectOverlay(k, view, dupRaw)).concat(printCollectChat(view));
  [printCollectUsulan(view), printCollectRoutes(view), printCollectMarkers(view)].forEach((l) => l && layers.push(l));
  return layers;
}

/* ---------- dialog ---------- */

function printDefaultTitle(layers) {
  const usulan = layers.find((l) => l.key === "__usulan__");
  if (usulan && usulan.feats.length === 1) return `Peta Lokasi ${usulan.feats[0].gj.properties._label}`;
  const nama = layers.filter((l) => l.feats.length && !l.key.startsWith("__")).map((l) => l.nama);
  if (nama.length) return `Peta ${nama.slice(0, 2).join(" & ")}${nama.length > 2 ? " dkk." : ""}`;
  return "Peta Lokasi";
}

function printDefaultBasemap() {
  if (state.mapProvider === "osm") return "osm";
  const t = state.map.getMapTypeId();
  return t === "satellite" || t === "hybrid" ? "satelit" : "osm";
}

let printCollected = [];

function openPrintMapDialog() {
  if (!state.map || !state.map.getBounds()) {
    toast("Peta belum siap", true);
    return;
  }
  printCollected = printCollectAll();
  const judul = document.getElementById("printJudul");
  if (!judul.dataset.edited) judul.value = printDefaultTitle(printCollected);
  judul.oninput = () => { judul.dataset.edited = "1"; };
  document.getElementById("printBasemap").value = printDefaultBasemap();
  renderPrintLayerList();
  document.getElementById("printStatus").textContent = "Geser/zoom peta dulu untuk mengatur area cetak.";
  document.getElementById("printMapOverlay").hidden = false;
}

function renderPrintLayerList() {
  const list = document.getElementById("printLayerList");
  const total = printCollected.reduce((n, l) => n + l.feats.length, 0);
  document.getElementById("printLayerMeta").textContent =
    `(${printCollected.length} layer, ${total.toLocaleString("id-ID")} fitur dalam tampilan)`;
  if (!printCollected.length) {
    list.innerHTML = `<div class="print-empty">Belum ada layer overlay, usulan, atau rute di peta — hasil cetak hanya berisi basemap.</div>`;
    return;
  }
  list.innerHTML = "";
  printCollected.forEach((l) => {
    const pref = printLayerPrefs[l.key] || {};
    const fields = l.fields.filter((f) => f === "_label" || !f.startsWith("_"));
    const labelField = pref.labelField !== undefined && (pref.labelField === "" || fields.includes(pref.labelField))
      ? pref.labelField
      // label yg sedang ditampilkan di peta (menu klik kanan, layer-label.js) jadi bawaan cetak
      : (state.mapLayers.labelCfg?.[l.key]?.aktif && fields.includes(state.mapLayers.labelCfg[l.key].field)
        ? state.mapLayers.labelCfg[l.key].field : printGuessLabelField(fields));
    const row = document.createElement("div");
    row.className = "print-layer-row" + (l.feats.length ? "" : " is-empty");
    row.dataset.key = l.key;
    row.innerHTML = `
      <label class="print-layer-include">
        <input type="checkbox" class="print-inc" ${pref.include === false || !l.feats.length ? "" : "checked"} ${l.feats.length ? "" : "disabled"} />
        <span class="maplayer-swatch" style="background:${escapeHtml(l.warna)}"></span>
        <span class="print-layer-name" title="${escapeHtml(l.sumber)}">${escapeHtml(l.nama)}</span>
      </label>
      <span class="print-layer-count">${l.feats.length.toLocaleString("id-ID")} fitur${l.dilewati ? ` (+${l.dilewati} dilewati)` : ""}</span>
      <select class="print-label-field" title="Kolom atribut untuk label">
        <option value="">— tanpa label —</option>
        ${fields.map((f) => `<option value="${escapeHtml(f)}" ${f === labelField ? "selected" : ""}>${f === "_label" ? "(label bawaan)" : escapeHtml(f)}</option>`).join("")}
      </select>
      <label class="print-layer-table" title="Sertakan layer ini di tabel atribut lampiran">
        <input type="checkbox" class="print-tbl" ${pref.tabel === false ? "" : "checked"} /> Tabel
      </label>`;
    const save = () => {
      printLayerPrefs[l.key] = {
        include: row.querySelector(".print-inc").checked,
        labelField: row.querySelector(".print-label-field").value,
        tabel: row.querySelector(".print-tbl").checked,
      };
    };
    row.querySelectorAll("input,select").forEach((el) => el.addEventListener("change", save));
    list.appendChild(row);
  });
}

function buildPrintPayload() {
  const layers = [];
  document.querySelectorAll("#printLayerList .print-layer-row").forEach((row) => {
    const l = printCollected.find((x) => x.key === row.dataset.key);
    if (!l || !row.querySelector(".print-inc").checked || !l.feats.length) return;
    const labelField = row.querySelector(".print-label-field").value;
    layers.push({
      nama: l.nama,
      sumber: l.sumber,
      warna: l.warna,
      jenis: l.jenis,
      label_field: labelField && labelField !== "_label" ? labelField : null,
      tabel: row.querySelector(".print-tbl").checked,
      legend: l.legend,
      features: l.feats.map(({ gj, style }) => ({
        geometry: gj.geometry,
        properties: gj.properties || {},
        style,
        label: printLabelText(gj.properties || {}, labelField),
      })),
    });
  });
  const b = state.map.getBounds();
  const ne = b.getNorthEast();
  const sw = b.getSouthWest();
  return {
    format: document.querySelector('input[name="printFormat"]:checked').value,
    judul: document.getElementById("printJudul").value.trim() || "Peta",
    subjudul: document.getElementById("printSubjudul").value.trim(),
    catatan: document.getElementById("printCatatan").value.trim(),
    kertas: document.getElementById("printKertas").value,
    orientasi: document.getElementById("printOrientasi").value,
    basemap: document.getElementById("printBasemap").value,
    label_mode: document.getElementById("printLabelMode").value,
    ukuran_label: document.getElementById("printUkuranLabel").value,
    sertakan_tabel: document.getElementById("printTabel").checked,
    grid: document.getElementById("printGrid").checked,
    maks_baris: Number(document.getElementById("printMaksBaris").value) || 300,
    bounds: { west: sw.lng(), south: sw.lat(), east: ne.lng(), north: ne.lat() },
    layers,
  };
}

// Pratinjau terakhir (selalu PDF): dipakai ulang oleh "Cetak"/"Unduh" kalau
// format PDF & pengaturan/fitur tidak berubah, supaya tidak render dua kali.
let printPreviewCache = null; // {key, blob, filename, url}

function printPayloadKey(payload) {
  return JSON.stringify({ ...payload, format: "pdf" });
}

// URL ikon (SVG data URL) -> PNG data URL lewat canvas. Server tidak bisa
// merender SVG (Pillow), jadi rasterisasi dilakukan browser. Hasil di-cache.
const _printIkonPngCache = {};
function printIkonKePng(url, sisi = 96) {
  if (!_printIkonPngCache[url]) {
    _printIkonPngCache[url] = new Promise((resolve) => {
      const img = new Image();
      img.onload = () => {
        const w = img.naturalWidth || sisi, h = img.naturalHeight || sisi;
        const skala = sisi / Math.max(w, h);
        const cv = document.createElement("canvas");
        cv.width = Math.max(1, Math.round(w * skala));
        cv.height = Math.max(1, Math.round(h * skala));
        cv.getContext("2d").drawImage(img, 0, 0, cv.width, cv.height);
        try { resolve(cv.toDataURL("image/png")); } catch (_) { resolve(null); }
      };
      img.onerror = () => resolve(null);
      img.src = url;
    });
  }
  return _printIkonPngCache[url];
}

// Ganti point_icon_url di setiap fitur dgn kunci ke payload.ikon (satu PNG per
// ikon unik), lalu isi ikon layer (legenda tunggal) & ikon sub-legenda titik
// (dicocokkan lewat warna). Ikon yg gagal dirasterisasi -> tetap lingkaran.
async function printSiapkanIkon(payload) {
  const kunciUrl = new Map();
  payload.layers.forEach((l) => l.features.forEach((f) => {
    const u = f.style && f.style.point_icon_url;
    if (u && !kunciUrl.has(u)) kunciUrl.set(u, `i${kunciUrl.size}`);
  }));
  const ikon = {};
  const png = await Promise.all([...kunciUrl.keys()].map((u) => printIkonKePng(u)));
  [...kunciUrl.entries()].forEach(([, k], i) => { if (png[i]) ikon[k] = png[i]; });
  const layers = payload.layers.map((l) => {
    const hitung = {};
    const perWarna = {};
    const features = l.features.map((f) => {
      const { point_icon_url: u, ...style } = f.style || {};
      const k = u && ikon[kunciUrl.get(u)] ? kunciUrl.get(u) : null;
      if (k) {
        style.point_icon = k;
        hitung[k] = (hitung[k] || 0) + 1;
        if (style.point_color && !perWarna[style.point_color]) perWarna[style.point_color] = k;
      } else {
        delete style.point_size;
      }
      return { ...f, style };
    });
    const dominan = Object.entries(hitung).sort((a, b) => b[1] - a[1])[0];
    const legend = (l.legend || []).map((x) => (x.jenis === "titik" && perWarna[x.warna] ? { ...x, ikon: perWarna[x.warna] } : x));
    return { ...l, features, legend, ikon: l.jenis === "titik" && dominan ? dominan[0] : null };
  });
  return { ...payload, layers, ikon };
}

async function requestPrintFile(payload) {
  const res = await fetch("/api/peta/cetak", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(await printSiapkanIkon(payload)),
  });
  if (!res.ok) {
    let msg = await res.text();
    try { msg = JSON.parse(msg).detail || msg; } catch (_) { /* teks biasa */ }
    throw new Error(msg);
  }
  const blob = await res.blob();
  const match = (res.headers.get("Content-Disposition") || "").match(/filename="?([^";]+)"?/);
  return { blob, filename: match ? match[1] : `peta.${payload.format}` };
}

function setPrintBusy(busy, text) {
  ["printMapSubmit", "printMapPreview"].forEach((id) => { document.getElementById(id).disabled = busy; });
  if (text) document.getElementById("printStatus").textContent = text;
}

function printBusyText(payload, aksi) {
  const n = payload.layers.reduce((acc, l) => acc + l.features.length, 0);
  return `${aksi} — memuat basemap & menggambar ${n.toLocaleString("id-ID")} fitur...`;
}

async function submitPrintMap(payload = buildPrintPayload()) {
  const fmt = payload.format.toUpperCase();
  setPrintBusy(true, printBusyText(payload, `Membuat ${fmt}`));
  setStatus(`Mencetak peta (${fmt})...`);
  try {
    let file;
    if (payload.format === "pdf" && printPreviewCache && printPreviewCache.key === printPayloadKey(payload)) {
      file = printPreviewCache;
    } else {
      file = await requestPrintFile(payload);
    }
    downloadBlob(file.blob, file.filename);
    toast(`Peta tersimpan: ${file.filename}`);
    setStatus("");
    closePrintPreview();
    closePrintMapDialog();
  } catch (err) {
    console.error(err);
    document.getElementById("printStatus").textContent = `Gagal: ${String(err.message || err).slice(0, 200)}`;
    toast("Gagal mencetak peta", true);
    setStatus("Gagal mencetak peta");
  } finally {
    setPrintBusy(false);
  }
}

async function previewPrintMap() {
  const payload = buildPrintPayload();
  const key = printPayloadKey(payload);
  if (!printPreviewCache || printPreviewCache.key !== key) {
    setPrintBusy(true, printBusyText(payload, "Membuat pratinjau"));
    setStatus("Membuat pratinjau peta...");
    try {
      const file = await requestPrintFile({ ...payload, format: "pdf" });
      if (printPreviewCache) URL.revokeObjectURL(printPreviewCache.url);
      printPreviewCache = { key, ...file, url: URL.createObjectURL(file.blob) };
      setStatus("");
    } catch (err) {
      console.error(err);
      document.getElementById("printStatus").textContent = `Gagal pratinjau: ${String(err.message || err).slice(0, 200)}`;
      toast("Gagal membuat pratinjau", true);
      setStatus("Gagal membuat pratinjau");
      return;
    } finally {
      setPrintBusy(false);
    }
  }
  document.getElementById("printStatus").textContent = "Pratinjau siap.";
  openPrintPreview(payload);
}

// Overlay pratinjau di atas dialog cetak (dialog tetap terbuka di belakang,
// jadi "Ubah pengaturan" cukup menutup overlay ini).
function openPrintPreview(payload) {
  closePrintPreview();
  const fmt = payload.format.toUpperCase();
  const overlay = document.createElement("div");
  overlay.className = "pdf-modal-overlay print-preview-overlay";
  overlay.id = "printPreviewOverlay";
  overlay.innerHTML = `
    <div class="pdf-modal print-preview-modal">
      <div class="pdf-modal-header">
        <span><i class="bi bi-eye"></i> Pratinjau — ${escapeHtml(payload.judul)}</span>
        <div class="print-preview-actions">
          <button type="button" class="btn btn-ghost btn-sm" data-act="back"><i class="bi bi-sliders"></i> Ubah pengaturan</button>
          <button type="button" class="btn btn-primary btn-sm" data-act="download"><i class="bi bi-download"></i> Unduh ${fmt}</button>
        </div>
      </div>
      ${payload.format === "docx" ? `<div class="print-preview-note"><i class="bi bi-info-circle"></i>
        Pratinjau ditampilkan sebagai PDF. Isi DOCX sama (peta, label, legenda, info, tabel atribut);
        hanya penempatan panel legenda di halaman Word yang sedikit berbeda.</div>` : ""}
      <div class="pdf-modal-body"><iframe src="${printPreviewCache.url}#view=FitH" title="Pratinjau cetak peta"></iframe></div>
    </div>`;
  overlay.addEventListener("click", (e) => { if (e.target === overlay) closePrintPreview(); });
  overlay.querySelector('[data-act="back"]').addEventListener("click", closePrintPreview);
  const btnUnduh = overlay.querySelector('[data-act="download"]');
  btnUnduh.addEventListener("click", () => {
    btnUnduh.disabled = true;
    submitPrintMap(payload).finally(() => { btnUnduh.disabled = false; });
  });
  document.body.appendChild(overlay);
}

function closePrintPreview() {
  const el = document.getElementById("printPreviewOverlay");
  if (el) el.remove();
}

bindPrintMap();
