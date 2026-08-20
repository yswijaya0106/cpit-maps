/* The Next - SiJalan — overlay peta referensi (layer SHP dari folder Maps/<provinsi>/<kabupaten>/,
   sekarang disajikan lewat PostGIS map_layers/map_layer_meta, lihat app.py).
   Panel-nya pohon ArcGIS-style: kategori (Jalan/Batas Administrasi/Simpul
   Transportasi) -> provinsi -> kabupaten/kota -> layer (checkbox), tiap
   tingkat di-expand LAZY (fetch baru saat node dibuka, bukan sekaligus di
   awal) — supaya layer yang ditambah/diimpor ulang otomatis muncul tanpa
   reload halaman, panel cuma perlu dibuka ulang. */

const MAP_LAYER_PALETTE = [
  "#4f7cff", "#22d3a5", "#ffb648", "#ff5c7c", "#a78bfa", "#38bdf8", "#f472b6", "#facc15",
  "#34d399", "#fb923c", "#818cf8", "#2dd4bf", "#e879f9", "#a3e635", "#f87171", "#60a5fa",
];

// Warna dari palet HANYA dipesan buat layer yang benar-benar diaktifkan (dipanggil
// dari applyLayerStyle/legend/seleksi) -- kalau dipesan juga tiap kali daftar
// checkbox di-render (termasuk yang belum dicentang), slot 8-16 warnanya cepat
// habis begitu user browsing puluhan tipe layer RBI lintas kabupaten, dan layer
// aktif yang index-nya bentrok modulo panjang palet jadi keliatan sama warnanya
// walau beda layer (bug yang dilaporkan user). Preview swatch di daftar pilihan
// (belum aktif) pakai mapLayerPreviewColor di bawah, TIDAK memesan slot palet.
function mapLayerColor(layerName) {
  if (!state.mapLayers.colors[layerName]) {
    const idx = Object.keys(state.mapLayers.colors).length % MAP_LAYER_PALETTE.length;
    state.mapLayers.colors[layerName] = MAP_LAYER_PALETTE[idx];
  }
  return state.mapLayers.colors[layerName];
}

// Warna preview murni dari hash nama layer -- stabil per nama, tapi TIDAK
// menyentuh state.mapLayers.colors (jadi tidak mengurangi slot palet buat
// layer yang benar-benar aktif). Dipakai di daftar checkbox pilihan layer.
function mapLayerPreviewColor(layerName) {
  let hash = 0;
  for (let i = 0; i < layerName.length; i++) hash = (hash * 31 + layerName.charCodeAt(i)) >>> 0;
  return MAP_LAYER_PALETTE[hash % MAP_LAYER_PALETTE.length];
}

/* Kunci komposit provinsi+kabupaten+layer -- lihat catatan di state.js.
   Fungsi kecil di bawah dipakai di sini dan map-tools.js (legend/seleksi/
   identify) untuk menerjemahkan layerKey balik ke nama layer mentah
   (dipakai buat warna/label yang memang mau konsisten lintas kabupaten). */
function mapLayerKey(provinsi, kabupaten, layer) {
  return `${provinsi}::${kabupaten}::${layer}`;
}
function mapLayerRawName(layerKey) {
  return state.mapLayers.meta[layerKey]?.layer || layerKey;
}
function mapLayerDisplayLabel(layerKey) {
  const raw = mapLayerRawName(layerKey);
  return state.mapLayers.labels[raw] || raw;
}

async function initMapLayersControl() {
  const control = document.getElementById("mapLayerControl");
  const hasData = await loadMapLayerTree();
  if (!hasData) return; // folder Maps/ kosong, sembunyikan kontrol
  control.hidden = false;
  bindMapLayerToggle();
}

/* ---------- kategori & tree (ArcGIS-style: kategori -> provinsi -> [kabupaten
   ->] layer, expand lazy per tingkat) ----------

   "provinsi" dari /api/maps/provinces sebenarnya campuran: 34 provinsi RBI asli
   (isinya semata layer jalan kabupaten/kota) + beberapa bucket nasional
   khusus (JALAN NASIONAL/PROVINSI/TOL, BATAS KECAMATAN/KABUPATEN/PROVINSI,
   BANDARA, PELABUHAN*, KONEKTIVITAS SIMPUL TRANSPORTASI). Aturan kategori di
   bawah cuma perlu mendaftar bucket KHUSUS itu -- 34 provinsi RBI otomatis
   jatuh ke kategori catch-all terakhir ("Jalan") karena memang isinya cuma
   itu, tanpa perlu hardcode nama 34 provinsi di sini. SETIAP bucket batas
   administrasi baru (lihat scripts/import_batas_administrasi_*.py) WAJIB
   didaftarkan di sini juga -- backend tidak tahu apa-apa soal kategori tree
   ini, jadi bucket yang lupa didaftarkan diam-diam jatuh ke "Jalan" (bug
   yang terjadi persis di BATAS KABUPATEN/PROVINSI, ditemukan 27 Jul 2026). */
const MAP_LAYER_CATEGORIES = [
  { id: "batas-admin", label: "Batas Administrasi", icon: "bi-bounding-box",
    match: (p) => ["BATAS KECAMATAN", "BATAS KABUPATEN", "BATAS PROVINSI"].includes(p) },
  { id: "simpul", label: "Simpul Transportasi", icon: "bi-airplane",
    match: (p) => ["BANDARA", "PELABUHAN", "PELABUHAN LAUT", "PELABUHAN PENYEBRANGAN",
      "KONEKTIVITAS SIMPUL TRANSPORTASI",
      // Ditambahkan Fase 4 (scripts/import_pelabuhan_tersus_tuks_to_postgis.py,
      // import_pelabuhan_penyeberangan_operasi_to_postgis.py,
      // import_terminal_tipe_a_to_postgis.py) -- lihat
      // docs/kajian_data_baru_docs_new.md §Fase 4.
      "PELABUHAN TERSUS/TUKS", "PELABUHAN PENYEBERANGAN OPERASI", "TERMINAL TIPE A",
      "PELABUHAN PENUMPANG"].includes(p) },
  // BASARNAS: bucket nasional flat (scripts/import_basarnas_to_postgis.py),
  // layer overlay umum lepas dari IJD/usulan -- lihat
  // docs/kajian_data_baru_docs_new.md §8.
  { id: "sar", label: "Pencarian & Pertolongan (SAR)", icon: "bi-life-preserver",
    match: (p) => p === "BASARNAS" },
  // Jalur Kereta Api: bucket nasional flat (scripts/import_kereta_api_to_postgis.py)
  // -- lihat docs/kajian_data_baru_docs_new.md §6/§Fase 3.
  { id: "kereta-api", label: "Kereta Api", icon: "bi-train-front",
    match: (p) => p === "JALUR KERETA API" },
  { id: "jalan", label: "Jalan", icon: "bi-signpost-2", match: () => true }, // catch-all, HARUS terakhir
];

function categoryForProvinsi(provinsi) {
  return MAP_LAYER_CATEGORIES.find((c) => c.match(provinsi));
}

function titleCaseWilayah(s) {
  return String(s).toLowerCase().replace(/(^|\s)\S/g, (c) => c.toUpperCase());
}

async function loadMapLayerTree() {
  const tree = document.getElementById("mapLayerTree");
  let provinces = [];
  try {
    const res = await fetch("/api/maps/provinces");
    if (!res.ok) throw new Error(await res.text());
    provinces = await res.json();
  } catch (err) {
    console.error(err);
    tree.innerHTML = `<div class="maplayer-loading">Gagal memuat daftar layer</div>`;
    return false;
  }
  if (!provinces.length) return false;

  const grouped = new Map(); // cat.id -> { cat, rows: [] }
  provinces.forEach((p) => {
    const cat = categoryForProvinsi(p.provinsi);
    if (!grouped.has(cat.id)) grouped.set(cat.id, { cat, rows: [] });
    grouped.get(cat.id).rows.push(p);
  });

  tree.innerHTML = "";
  MAP_LAYER_CATEGORIES.forEach((cat) => {
    const group = grouped.get(cat.id);
    if (!group || !group.rows.length) return;
    tree.appendChild(renderTreeNode({
      icon: cat.icon,
      label: cat.label,
      count: group.rows.length,
      countSuffix: "provinsi",
      loadChildren: () => renderProvinsiChildren(group.rows),
    }));
  });

  // "PETA KORIDOR" BUKAN bucket provinsi terpisah (beda dari BATAS
  // KECAMATAN/BANDARA dst.) -- baris DB-nya pakai provinsi ASLI (ACEH, BALI,
  // ...), sama seperti layer jalan RBI biasa, jadi tidak bisa dibedakan lewat
  // categoryForProvinsi(). Dipromosikan jadi kategori top-level sendiri di
  // sini secara manual, reuse daftar provinsi RBI yang sama dgn kategori
  // "Jalan" (grup catch-all "jalan"), tapi drill-downnya di-filter cuma ke
  // layer "PETA KORIDOR" (lihat opts.onlyLayer di loadLayerChildren) --
  // supaya tidak nyempil tercampur dgn layer jalan lain 3 tingkat dalam
  // kategori "Jalan" (temuan user 28 Jul 2026).
  const jalanGroup = grouped.get("jalan");
  if (jalanGroup && jalanGroup.rows.length) {
    tree.appendChild(renderTreeNode({
      icon: "bi-signpost-split",
      label: "Peta Koridor",
      count: jalanGroup.rows.length,
      countSuffix: "provinsi",
      loadChildren: () => renderProvinsiChildren(jalanGroup.rows, { onlyLayer: "PETA KORIDOR" }),
    }));
  }
  return true;
}

function renderProvinsiChildren(rows, opts = {}) {
  const frag = document.createDocumentFragment();
  rows
    .slice()
    .sort((a, b) => a.provinsi.localeCompare(b.provinsi))
    .forEach((p) => {
      frag.appendChild(renderTreeNode({
        label: titleCaseWilayah(p.provinsi),
        count: p.kabupaten_count,
        countSuffix: "kab/kota",
        loadChildren: () => loadKabupatenChildren(p.provinsi, opts),
      }));
    });
  return frag;
}

async function loadKabupatenChildren(provinsi, opts = {}) {
  let rows = [];
  try {
    const qs = new URLSearchParams({ provinsi });
    // Mode normal (kategori Batas Administrasi/Simpul Transportasi/Jalan):
    // singkirkan kabupaten yang cuma py layer PETA KORIDOR (lihat
    // exclude_layer di app.py) supaya tidak ada entri kosong. Mode
    // onlyLayer="PETA KORIDOR" (kategori Peta Koridor sendiri) tidak perlu
    // exclude apapun -- justru itu yang mau ditampilkan.
    if (opts.onlyLayer) qs.set("only_layer", opts.onlyLayer);
    else qs.set("exclude_layer", "PETA KORIDOR");
    const res = await fetch(`/api/maps/kabupaten?${qs}`);
    if (!res.ok) throw new Error(await res.text());
    rows = await res.json();
  } catch (err) {
    console.error(err);
    return mapLayerTreeError("Gagal memuat daftar kabupaten/kota");
  }
  if (!rows.length) return mapLayerTreeError("Belum ada data");

  // Bucket nasional flat (mis. JALAN NASIONAL/JALAN TOL): satu baris dengan
  // kabupaten="" berarti tidak ada level kabupaten sama sekali -- lompat
  // langsung ke daftar layer, sama spt fallback maps_kabupaten() di app.py.
  if (rows.length === 1 && rows[0].kabupaten === "") {
    return loadLayerChildren(provinsi, "", opts);
  }

  const frag = document.createDocumentFragment();
  rows
    .slice()
    .sort((a, b) => (a.label || a.kabupaten).localeCompare(b.label || b.kabupaten))
    .forEach((r) => {
      frag.appendChild(renderTreeNode({
        label: r.label || r.kabupaten,
        count: r.layer_count,
        countSuffix: "layer",
        loadChildren: () => loadLayerChildren(provinsi, r.kabupaten, opts),
      }));
    });
  return frag;
}

async function loadLayerChildren(provinsi, kabupaten, opts = {}) {
  let layers = [];
  try {
    const res = await fetch(`/api/maps/layers?provinsi=${encodeURIComponent(provinsi)}&kabupaten=${encodeURIComponent(kabupaten)}`);
    if (!res.ok) throw new Error(await res.text());
    layers = await res.json();
  } catch (err) {
    console.error(err);
    return mapLayerTreeError("Gagal memuat daftar layer");
  }
  // "PETA KORIDOR" sengaja disembunyikan dari daftar layer generik (kategori
  // "Jalan" dkk.) -- dia punya kategori top-level sendiri (lihat
  // loadMapLayerTree), jadi di sini cuma dimunculkan kalau memang sedang
  // di-drill lewat kategori itu (opts.onlyLayer === "PETA KORIDOR").
  layers = opts.onlyLayer
    ? layers.filter((l) => l.layer === opts.onlyLayer)
    : layers.filter((l) => l.layer !== "PETA KORIDOR");
  if (!layers.length) return mapLayerTreeError("Belum ada layer (.shp) untuk kabupaten ini");

  const frag = document.createDocumentFragment();
  layers.forEach((l) => {
    state.mapLayers.labels[l.layer] = l.label;
    const key = mapLayerKey(provinsi, kabupaten, l.layer);
    const isActive = !!state.mapLayers.active[key];
    const opacity = state.mapLayers.opacity[key] ?? 1;
    const row = document.createElement("label");
    row.className = "maplayer-item";
    row.innerHTML = `
      <input type="checkbox" ${isActive ? "checked" : ""} data-provinsi="${escapeHtml(provinsi)}" data-kabupaten="${escapeHtml(kabupaten)}" data-layer="${escapeHtml(l.layer)}" />
      <span class="maplayer-swatch" style="background:${isActive ? mapLayerColor(l.layer) : mapLayerPreviewColor(l.layer)}"></span>
      <span class="maplayer-item-label">${escapeHtml(l.label)}</span>
      <span class="maplayer-item-size">${l.size_mb != null ? `${l.size_mb} MB` : ""}</span>
      <input type="range" class="maplayer-opacity" min="0" max="1" step="0.05" value="${opacity}" data-provinsi="${escapeHtml(provinsi)}" data-kabupaten="${escapeHtml(kabupaten)}" data-layer="${escapeHtml(l.layer)}" title="Transparansi layer" ${isActive ? "" : "hidden"} />
    `;
    frag.appendChild(row);
  });
  return frag;
}

function mapLayerTreeError(msg) {
  const div = document.createElement("div");
  div.className = "maplayer-loading";
  div.textContent = msg;
  return div;
}

/* Node tree generik dgn expand/collapse lazy: loadChildren() cuma dipanggil
   sekali (saat pertama dibuka), hasilnya menempel di DOM jadi buka/tutup
   berikutnya tinggal toggle hidden -- sama dgn semangat combo lama (data
   di-fetch saat dropdown dibuka, bukan semua sekaligus di awal). */
function renderTreeNode({ icon, label, count, countSuffix, loadChildren }) {
  const node = document.createElement("div");
  node.className = "maplayer-tree-node";

  const row = document.createElement("div");
  row.className = "maplayer-tree-row";
  row.innerHTML = `
    <i class="bi bi-chevron-right maplayer-tree-caret"></i>
    ${icon ? `<i class="bi ${icon} maplayer-tree-icon"></i>` : ""}
    <span class="maplayer-tree-label">${escapeHtml(label)}</span>
    ${count != null ? `<span class="maplayer-tree-count">${count}${countSuffix ? " " + countSuffix : ""}</span>` : ""}
  `;

  const children = document.createElement("div");
  children.className = "maplayer-tree-children";
  children.hidden = true;

  let loaded = false;
  row.addEventListener("click", async () => {
    const willOpen = children.hidden;
    if (willOpen && !loaded) {
      children.hidden = false;
      node.classList.add("open");
      children.innerHTML = `<div class="maplayer-loading">Memuat...</div>`;
      const result = await loadChildren();
      children.innerHTML = "";
      children.appendChild(result);
      loaded = true;
      return;
    }
    children.hidden = !willOpen;
    node.classList.toggle("open", willOpen);
  });

  node.appendChild(row);
  node.appendChild(children);
  return node;
}

/* ---------- combo dropdown mechanics ---------- */

function bindMapLayerCombo(fieldId, toggleId, panelId, labelId, onOpen, onSelect) {
  const field = document.getElementById(fieldId);
  const toggle = document.getElementById(toggleId);
  const panel = document.getElementById(panelId);
  const label = document.getElementById(labelId);

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
    // Update label & selected state langsung, jangan tunggu panel dibuka lagi
    // (fillComboPanel baru jalan saat onOpen berikutnya).
    panel.querySelectorAll(".maplayer-combo-option.selected").forEach((o) => o.classList.remove("selected"));
    opt.classList.add("selected");
    label.textContent = opt.textContent;
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

/* ---------- top-level toggle + layer show/hide ---------- */

function bindMapLayerToggle() {
  const control = document.getElementById("mapLayerControl");
  const toggle = document.getElementById("mapLayerToggle");
  const panel = document.getElementById("mapLayerPanel");
  const treeEl = document.getElementById("mapLayerTree");

  const closePanel = () => {
    panel.hidden = true;
    control.classList.remove("open");
  };

  toggle.addEventListener("click", async (e) => {
    e.stopPropagation();
    const willOpen = panel.hidden;
    if (!willOpen) {
      closePanel();
      return;
    }
    // Rescan Maps/ tiap dibuka (sama spt combo lama) -- pohon dibangun ulang
    // dari kosong, jadi expand/collapse sebelumnya tidak dipertahankan.
    await loadMapLayerTree();
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

  treeEl.addEventListener("change", async (e) => {
    const cb = e.target.closest('input[type="checkbox"]');
    if (!cb) return;
    const { provinsi, kabupaten, layer } = cb.dataset;
    cb.disabled = true;
    if (cb.checked) {
      await showMapLayer(provinsi, kabupaten, layer);
    } else {
      hideMapLayer(mapLayerKey(provinsi, kabupaten, layer));
    }
    cb.disabled = false;
    updateMapLayerLabel();
    const range = cb.closest(".maplayer-item").querySelector(".maplayer-opacity");
    if (range) range.hidden = !cb.checked;
  });

  treeEl.addEventListener("input", (e) => {
    const range = e.target.closest(".maplayer-opacity");
    if (!range) return;
    const { provinsi, kabupaten, layer } = range.dataset;
    setLayerOpacity(mapLayerKey(provinsi, kabupaten, layer), parseFloat(range.value));
  });
}

function updateMapLayerLabel() {
  const label = document.getElementById("mapLayerLabel");
  const n = Object.keys(state.mapLayers.active).length;
  label.textContent = n ? `${n} layer aktif` : "Overlay Peta";
}

async function showMapLayer(provinsi, kabupaten, layer) {
  const key = mapLayerKey(provinsi, kabupaten, layer);
  if (state.mapLayers.active[key]) return;
  // Diisi di awal (bukan cuma saat sukses) supaya listCheckboxFor bisa
  // menemukan checkbox-nya lagi kalau load gagal/kosong di bawah.
  state.mapLayers.meta[key] = { provinsi, kabupaten, layer };

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
      const cb = listCheckboxFor(key);
      if (cb) cb.checked = false;
      delete state.mapLayers.meta[key];
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
      onFeatureClick(key, e.feature, e.latLng);
    });

    state.mapLayers.active[key] = data;
    state.mapLayers.meta[key] = { provinsi, kabupaten, layer };
    applyLayerStyle(key);
    if (provinsi === "BATAS KECAMATAN") updateKecamatanLintasan();
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
    const cb = listCheckboxFor(key);
    if (cb) cb.checked = false;
    delete state.mapLayers.meta[key];
  }
}

/* ---------- kecamatan yang dilintasi rute KML usulan diberi warna beda ---------- */

// Kontras dengan polyline rute usulan (oranye #f59e0b) dan warna-warna palet
// layer — jangan samakan, supaya poligon terlintas tidak menyatu dengan rute.
const KEC_LINTAS_COLOR = "#e11d74";

function _routeSamplePoints(maxPts = 80) {
  const pts = [];
  (state.browseUsulanPolylines || []).forEach((pl) => {
    const path = pl.getPath();
    for (let i = 0; i < path.getLength(); i++) pts.push(path.getAt(i));
  });
  if (pts.length <= maxPts) return pts;
  const step = pts.length / maxPts;
  return Array.from({ length: maxPts }, (_, i) => pts[Math.floor(i * step)]);
}

function _pointInRing(lat, lng, ring) {
  // ray casting sederhana; ring = array LatLng cincin luar poligon
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const yi = ring[i].lat(), xi = ring[i].lng();
    const yj = ring[j].lat(), xj = ring[j].lng();
    if ((yi > lat) !== (yj > lat) && lng < ((xj - xi) * (lat - yi)) / (yj - yi) + xi) {
      inside = !inside;
    }
  }
  return inside;
}

function _featureOuterRings(feature) {
  const rings = [];
  const walk = (g) => {
    const t = g.getType();
    if (t === "Polygon") rings.push(g.getAt(0).getArray());
    else if (t === "MultiPolygon" || t === "GeometryCollection") g.getArray().forEach(walk);
  };
  walk(feature.getGeometry());
  return rings;
}

/* Tandai fitur layer BATAS KECAMATAN yang dilintasi rute usulan yang sedang
   tampil (properti DILINTASI_RUTE, dibaca applyLayerStyle & popup identify).
   Dipanggil setiap rute usulan digambar/dihapus dan setiap layer di bawah
   provinsi bucket "BATAS KECAMATAN" diaktifkan (key = "BATAS KECAMATAN::<provinsi
   asli>::<kabupaten/kota asli>", lihat mapLayerKey). */
function updateKecamatanLintasan() {
  const pts = _routeSamplePoints();
  Object.entries(state.mapLayers.active).forEach(([key, data]) => {
    if (!key.startsWith("BATAS KECAMATAN::")) return;
    data.forEach((feature) => {
      let kena = false;
      if (pts.length) {
        for (const ring of _featureOuterRings(feature)) {
          // pra-saring bbox supaya ray casting tidak jalan untuk poligon jauh
          let minLat = 90, maxLat = -90, minLng = 180, maxLng = -180;
          ring.forEach((p) => {
            const la = p.lat(), ln = p.lng();
            if (la < minLat) minLat = la; if (la > maxLat) maxLat = la;
            if (ln < minLng) minLng = ln; if (ln > maxLng) maxLng = ln;
          });
          kena = pts.some((p) => {
            const la = p.lat(), ln = p.lng();
            return la >= minLat && la <= maxLat && ln >= minLng && ln <= maxLng
              && _pointInRing(la, ln, ring);
          });
          if (kena) break;
        }
      }
      feature.setProperty("DILINTASI_RUTE", kena ? "YA" : null);
    });
    applyLayerStyle(key);
  });
}

function applyLayerStyle(key) {
  const data = state.mapLayers.active[key];
  if (!data) return;
  const color = mapLayerColor(mapLayerRawName(key));
  const opacity = state.mapLayers.opacity[key] ?? 1;
  data.setStyle((feature) => {
    if (feature.getProperty("DILINTASI_RUTE") === "YA") {
      return {
        fillColor: KEC_LINTAS_COLOR, fillOpacity: 0.28 * opacity,
        strokeColor: KEC_LINTAS_COLOR, strokeWeight: 2.6, strokeOpacity: opacity, zIndex: 20,
      };
    }
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

function setLayerOpacity(key, value) {
  state.mapLayers.opacity[key] = value;
  applyLayerStyle(key);
}

function hideMapLayer(key) {
  const data = state.mapLayers.active[key];
  if (!data) return;
  data.setMap(null);
  delete state.mapLayers.active[key];
  delete state.mapLayers.opacity[key];
  delete state.mapLayers.meta[key];
  clearSelectionForLayer(key);
  updateMapLayerLabel();
  updateMapLegend();
  // Kalau checkbox layer ini sedang tampil (konteks provinsi/kabupaten yang
  // sama sedang di-browse), sinkronkan tampilannya juga.
  const cb = listCheckboxFor(key);
  if (cb) {
    cb.checked = false;
    const range = cb.closest(".maplayer-item")?.querySelector(".maplayer-opacity");
    if (range) range.hidden = true;
  }
}

// Matikan SEMUA layer overlay aktif sekaligus (dipakai tombol "Hapus semua"
// di panel legend, bukan lagi dipanggil otomatis saat ganti provinsi/
// kabupaten yang di-browse — itu sekarang cuma ganti daftar pilihan, bukan
// mematikan layer yang sudah aktif).
function clearActiveMapLayers() {
  Object.keys(state.mapLayers.active).forEach((key) => clearSelectionForLayer(key));
  Object.values(state.mapLayers.active).forEach((data) => data.setMap(null));
  state.mapLayers.active = {};
  state.mapLayers.opacity = {};
  state.mapLayers.meta = {};
  updateMapLayerLabel();
  updateMapLegend();
}

function listCheckboxFor(key) {
  const meta = state.mapLayers.meta[key];
  if (!meta) return null;
  return document.querySelector(
    `.maplayer-item input[data-provinsi="${CSS.escape(meta.provinsi)}"]`
    + `[data-kabupaten="${CSS.escape(meta.kabupaten)}"][data-layer="${CSS.escape(meta.layer)}"]`
  );
}
