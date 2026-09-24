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

// Warna per kategori "STATUS OPERASI" utk layer "Stasiun Kereta Api" (dari
// scripts/import_kereta_api_kmz_to_postgis.py) -- meniru legenda kategori
// warna ikon Google My Maps sumbernya (dicocokkan lewat styleUrl vs field
// STATUS OPERASI tiap placemark saat impor), bukan warna acak. Dipakai baik
// oleh applyLayerStyle (warna titik di peta) maupun legend (sub-daftar
// kategori di bawah nama layer).
const STASIUN_STATUS_COLORS = {
  "Beroperasi": "#0288D1",
  "Tidak Beroperasi": "#C2185B",
  "Sedang Dibangun": "#673AB7",
  "Beroperasi dan Sedang dikembangkan": "#558B2F",
  "Beroperasi LRT Jabodebek": "#EC407A",
  "Beroperasi MRT": "#212121",
  "Beroperasi LRT Jakarta": "#FF7043",
  "Beroperasi KCJB": "#E53935",
};
const STASIUN_STATUS_DEFAULT_COLOR = "#90a4ae"; // status lain/kosong ("Other / No data")
const STASIUN_STATUS_FIELD = "STATUS OPERASI";
const STASIUN_LAYER_NAME = "Stasiun Kereta Api";

function stasiunStatusColor(status) {
  return STASIUN_STATUS_COLORS[status] || STASIUN_STATUS_DEFAULT_COLOR;
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
      "PELABUHAN PENUMPANG",
      // JALAN DARURAT: bucket nasional flat (scripts/import_jalan_darurat_to_postgis.py),
      // ruas jalan nasional lebar perkerasan >=11m (RNI 2023) yang layak
      // difungsikan sbg landas pacu darurat -- dual-use Jalan<->Udara,
      // sengaja masuk kategori ini (bukan "Jalan") supaya tampil
      // berdampingan dgn BANDARA, lihat docs/kajian_data_baru_11092026.md §1.
      "JALAN DARURAT"].includes(p) },
  // BASARNAS: bucket nasional flat (scripts/import_basarnas_to_postgis.py),
  // layer overlay umum lepas dari IJD/usulan -- lihat
  // docs/kajian_data_baru_docs_new.md §8.
  { id: "sar", label: "Pencarian & Pertolongan (SAR)", icon: "bi-life-preserver",
    match: (p) => p === "BASARNAS" },
  // Jalur Kereta Api: dua bucket nasional flat berbeda sumber --
  // "JALUR KERETA API" dari scripts/import_kereta_api_to_postgis.py (SHP
  // Rel KA_2022 + BTP, lihat docs/kajian_data_baru_docs_new.md §6/§Fase 3)
  // dan "KERETA API" dari scripts/import_kereta_api_kmz_to_postgis.py (KMZ
  // Google My Maps "Peta Jalur Kereta Api" -- tambahan stasiun/jembatan/
  // jalur perkotaan yang tidak ada di sumber SHP). Digabung ke kategori yang
  // sama supaya user tidak perlu tahu ada 2 sumber terpisah.
  { id: "kereta-api", label: "Kereta Api", icon: "bi-train-front",
    // "PERLINTASAN SEBIDANG KA": bucket nasional flat (scripts/import_
    // railway_crossing_tahap_to_postgis.py), 136 titik rencana penanganan
    // JPL bertahap (Tahap I/II/III) -- lihat docs/kajian_data_baru_11092026.md
    // §3, digabung ke kategori Kereta Api yang sama spt "KERETA API" di atas.
    // "TITIK POTONG JALAN-REL KA": bucket nasional flat (scripts/import_
    // titik_potong_jalan_rel.py), titik potong geometris jalan Nasional/
    // Provinsi/Kabupaten-Kota x rel KA (scripts/build_jalan_rel_
    // intersection.py) -- perlintasan sebidang hasil analisis spasial,
    // bukan dari daftar JPL resmi seperti "PERLINTASAN SEBIDANG KA" di atas.
    match: (p) => p === "JALUR KERETA API" || p === "KERETA API" || p === "PERLINTASAN SEBIDANG KA"
      || p === "TITIK POTONG JALAN-REL KA" },
  // Maskapai: bucket nasional flat (scripts/import_maskapai_organisasi_to_postgis.py),
  // sumbernya tabel maskapai_organisasi (hasil scrape_maskapai_organisasi.py +
  // geocode_maskapai_organisasi.py), bukan file .shp -- titik lokasi kantor
  // pusat maskapai dalam negeri/asing yang berhasil digeokode.
  { id: "maskapai", label: "Maskapai", icon: "bi-airplane-engines",
    match: (p) => p === "MASKAPAI" },
  // Bandara Kemenhub: bucket nasional flat (scripts/import_bandara_kemenhub_to_postgis.py),
  // sumbernya tabel bandara_kemenhub (live scrape hubud.kemenhub.go.id, 596
  // bandara) -- TERPISAH dari layer "Bandara" SHP RBI lama (masih di kategori
  // "Simpul Transportasi" di atas, tidak ditimpa). Identify popup-nya
  // menampilkan rute/fasilitas/terdekat/galeri lewat join exact-match
  // "Bandara ID" (attachBandaraKemenhubJoin, static/js/map-tools.js).
  { id: "bandara-kemenhub", label: "Bandara (Live, Kemenhub)", icon: "bi-airplane-fill",
    match: (p) => p === "BANDARA KEMENHUB" },
  // RTRW: bucket per provinsi (scripts/import_rtrw_kalbar_transportasi_to_postgis.py),
  // kabupaten="<nama provinsi RTRW>" (mis. "Kalimantan Barat") -- BUKAN
  // bucket nasional flat spt kategori lain di atas, karena sumbernya baru
  // 1 provinsi (lihat docs/kajian_data_baru_11092026.md §2/§4 -- pilot,
  // bukan cakupan nasional). Simpul+jaringan transportasi dari Rencana
  // Struktur Ruang RTRW (hierarki resmi Bandara/Pelabuhan Pengumpul/
  // Pengumpan, alur pelayaran sungai/danau, dst).
  { id: "rtrw", label: "RTRW (Rencana Tata Ruang)", icon: "bi-map",
    match: (p) => p === "RTRW" },
  // Kapasitas Lintas KA per petak jalan (scripts/import_kaplin_ka.py): bucket
  // flat per pulau (kabupaten = Sumatera/Jawa), garis berwarna menurut utilisasi.
  { id: "kaplin", label: "Kapasitas Lintas KA (KAPLIN)", icon: "bi-train-front",
    match: (p) => p === "KAPASITAS LINTAS KA" },
  // Arus perdagangan domestik antar provinsi (IRIO, scripts/import_arus_irio_provinsi.py):
  // bucket flat nasional, ketebalan garis = rupiah / ton, ada filter di legend.
  { id: "arus-perdagangan", label: "Arus Perdagangan Antar Provinsi", icon: "bi-arrow-left-right",
    match: (p) => p === "ARUS PERDAGANGAN ANTAR PROVINSI" },
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
    // entri "Seluruh ..." (mis. arus perdagangan nasional) selalu paling atas
    .sort((a, b) => (/^Seluruh/.test(b.kabupaten) - /^Seluruh/.test(a.kabupaten))
      || (a.label || a.kabupaten).localeCompare(b.label || b.kabupaten))
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
    if (layer === "KAPLIN STASIUN") bindKaplinLabelZoom();
    if (provinsi === "BATAS KECAMATAN") updateKecamatanLintasan();
    updateMapLegend();
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

/* Filter layer "Arus Perdagangan Antar Provinsi" (kontrolnya di legend,
   map-tools.js renderArusControls): pulau/provinsi dicocokkan ke sisi asal,
   tujuan, atau keduanya menurut `arah`; "antarPulau" menyaring hanya arus
   yang menyeberang pulau (kandidat angkutan laut). */
const ARUS_LAYER_PREFIX = "ARUS PERDAGANGAN";
// Warna garis = satu warna per layer (lihat arusLayerColor); transparansi = kelas nilai 1-5 (20%..100%, skala log rupiah/ton yang
// sama dgn ketebalan); ketebalan tetap menurut nilai. Dipakai juga oleh legenda.
const ARUS_PROVINSI_URUT = [
  "Aceh", "Sumatera Utara", "Sumatera Barat", "Riau", "Jambi", "Sumatera Selatan", "Bengkulu", "Lampung",
  "Kep. Bangka Belitung", "Kep. Riau", "DKI Jakarta", "Jawa Barat", "Jawa Tengah", "DI Yogyakarta",
  "Jawa Timur", "Banten", "Bali", "Nusa Tenggara Barat", "Nusa Tenggara Timur", "Kalimantan Barat",
  "Kalimantan Tengah", "Kalimantan Selatan", "Kalimantan Timur", "Kalimantan Utara", "Sulawesi Utara",
  "Sulawesi Tengah", "Sulawesi Selatan", "Sulawesi Tenggara", "Gorontalo", "Sulawesi Barat", "Maluku",
  "Maluku Utara", "Papua Barat", "Papua",
];
// Warna per LAYER (bukan per garis): satu warna untuk semua garis dalam satu layer.
// "Seluruh Indonesia": Rupiah biru, Ton oranye. Layer per provinsi: warna khas
// provinsi itu (hue sudut emas; Ton = hue komplementer) -- jadi warna baru
// muncul ketika provinsi lain dipilih. Rupiah & Ton selalu beda warna.
function arusLayerColor(key) {
  const meta = state.mapLayers.meta[key] || {};
  const perTon = mapLayerRawName(key).endsWith("TON");
  const idx = ARUS_PROVINSI_URUT.indexOf(meta.kabupaten);
  if (idx < 0) return perTon ? "#d97706" : "#1d4ed8";
  const hue = ((idx * 137.508) + (perTon ? 180 : 0)) % 360;
  return `hsl(${hue.toFixed(0)}, 72%, ${perTon ? 44 : 40}%)`;
}

// kelas 1-5 dari nilai (skala log lo..hi yang dibawa tiap fitur); opacity = 0.2 x kelas
function arusKelas(feature) {
  const v = Number(feature.getProperty("_nilai")), lo = Number(feature.getProperty("_skala_lo")),
    hi = Number(feature.getProperty("_skala_hi"));
  if (!(v > 0) || !(hi > lo)) return 1;
  const t = Math.log(Math.max(v, lo) / lo) / Math.log(hi / lo);
  return Math.min(5, 1 + Math.floor(t * 5));
}
const arusFilter = { pulau: "", provinsi: "", arah: "keduanya", antarPulau: false };

function arusFeatureVisible(f) {
  const pa = f.getProperty("Pulau Asal"), pt = f.getProperty("Pulau Tujuan");
  const va = f.getProperty("Provinsi Asal"), vt = f.getProperty("Provinsi Tujuan");
  if (arusFilter.antarPulau && pa === pt) return false;
  const cocok = (asal, tujuan, nilai) => {
    if (!nilai) return true;
    if (arusFilter.arah === "keluar") return asal === nilai;
    if (arusFilter.arah === "masuk") return tujuan === nilai;
    return asal === nilai || tujuan === nilai;
  };
  return cocok(pa, pt, arusFilter.pulau) && cocok(va, vt, arusFilter.provinsi);
}

function applyArusFilter() {
  Object.keys(state.mapLayers.active).forEach((k) => {
    if (mapLayerRawName(k).startsWith(ARUS_LAYER_PREFIX)) applyLayerStyle(k);
  });
}

function applyLayerStyle(key) {
  const data = state.mapLayers.active[key];
  if (!data) return;
  const color = mapLayerColor(mapLayerRawName(key));
  const opacity = state.mapLayers.opacity[key] ?? 1;
  const isArus = mapLayerRawName(key).startsWith(ARUS_LAYER_PREFIX);
  data.setStyle((feature) => {
    if (isArus && !arusFeatureVisible(feature)) return { visible: false };
    if (feature.getProperty("DILINTASI_RUTE") === "YA") {
      return {
        fillColor: KEC_LINTAS_COLOR, fillOpacity: 0.28 * opacity,
        strokeColor: KEC_LINTAS_COLOR, strokeWeight: 2.6, strokeOpacity: opacity, zIndex: 20,
      };
    }
    const type = feature.getGeometry().getType();
    if ((type === "Point" || type === "MultiPoint") && feature.getProperty("_label")) {
      // titik dgn label (stasiun KAPLIN): nama tampil di atas titik mulai zoom tertentu
      const zoom = state.map ? state.map.getZoom() : 0;
      return {
        icon: {
          path: google.maps.SymbolPath.CIRCLE, scale: 4.5, fillColor: "#ffffff", fillOpacity: opacity,
          strokeColor: "#1f2937", strokeWeight: 1.6, labelOrigin: new google.maps.Point(0, -2.4),
        },
        label: zoom >= KAPLIN_LABEL_MIN_ZOOM
          ? { text: String(feature.getProperty("_label")), fontSize: "11px", fontWeight: "600", color: "#111827" }
          : null,
        zIndex: 50,
      };
    }
    if (type === "Point" || type === "MultiPoint") {
      const pointColor = mapLayerRawName(key) === STASIUN_LAYER_NAME
        ? stasiunStatusColor(feature.getProperty(STASIUN_STATUS_FIELD))
        : color;
      return {
        icon: {
          path: google.maps.SymbolPath.CIRCLE,
          scale: 4,
          fillColor: pointColor,
          fillOpacity: 0.9 * opacity,
          strokeColor: "#0f1420",
          strokeWeight: 1,
        },
      };
    }
    if (type === "Polygon" || type === "MultiPolygon") {
      return { fillColor: color, fillOpacity: 0.18 * opacity, strokeColor: color, strokeWeight: 1.2, strokeOpacity: opacity };
    }
    // Layer "Arus Perdagangan Antar Provinsi" (import_arus_irio_provinsi.py):
    // ketebalan garis sudah dihitung server-side (skala log rupiah/ton) di
    // properti "Ketebalan garis (px)"; garis tipis digambar di atas yang tebal.
    const warnaGaris = feature.getProperty("_warna");
    if (warnaGaris) {
      return { strokeColor: warnaGaris, strokeWeight: Number(feature.getProperty("_lebar")) || 3, strokeOpacity: 0.92 * opacity };
    }
    const lebarGaris = Number(feature.getProperty("Ketebalan garis (px)"));
    if (lebarGaris > 0) {
      return {
        strokeColor: isArus ? arusLayerColor(key) : color,
        strokeWeight: lebarGaris, strokeOpacity: 0.2 * arusKelas(feature) * opacity,
        zIndex: Math.round(100 - lebarGaris * 5),
      };
    }
    return { strokeColor: color, strokeWeight: 1.6, strokeOpacity: 0.9 * opacity };
  });
}

// label stasiun KAPLIN bergantung zoom -> gambar ulang saat zoom berubah
function bindKaplinLabelZoom() {
  if (state._kaplinZoomBound || !state.map) return;
  state._kaplinZoomBound = true;
  state.map.addListener("zoom_changed", () => {
    Object.keys(state.mapLayers.active).forEach((k) => {
      if (mapLayerRawName(k) === "KAPLIN STASIUN") applyLayerStyle(k);
    });
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
