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
// Warna tetap utk layer kawasan tematik Bappenas (bukan palet bergilir), supaya
// arti warnanya konsisten di peta, legenda, dan cetak.
const KAWASAN_TEMATIK_WARNA = {
  "Kawasan Perkebunan": "#2e7d32",
  "Kawasan Kelautan & Perikanan": "#0277bd",
  "Kawasan Transmigrasi": "#ef6c00",
  "Kawasan Industri Prioritas": "#6a1b9a",
  "Lokus PKPN 3T": "#c62828",
};

function mapLayerColor(layerName) {
  if (KAWASAN_TEMATIK_WARNA[layerName]) return KAWASAN_TEMATIK_WARNA[layerName];
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
  if (KAWASAN_TEMATIK_WARNA[layerName]) return KAWASAN_TEMATIK_WARNA[layerName];
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
  // Klaster/Subklaster pangan-perkebunan-peternakan Merauke (scripts/import_subklaster_to_postgis.py):
  // bucket flat, poligon diwarnai per klaster (properti _warna), legenda KLASTER_LEGEND.
  { id: "klaster", label: "Klaster & Subklaster (Merauke)", icon: "bi-grid-3x3-gap",
    match: (p) => p === "KLASTER SUBKLASTER" },
  // UPT pendidikan/pelatihan BPSDM Perhubungan (scripts/import_bpsdm_perhubungan.py):
  // bucket flat, satu layer per matra + kantor pusat/PPSDM; popup join ke tabel bpsdm_*.
  { id: "bpsdm", label: "Pendidikan SDM Perhubungan (BPSDMP)", icon: "bi-mortarboard",
    match: (p) => p === "BPSDM PERHUBUNGAN" },
  // Keselamatan: bucket nasional flat, sementara berisi layer "PSC 119" (titik
  // Public Safety Center, scripts/import_psc119_lokasi_to_postgis.py). Blackspot &
  // LRK tetap di bucket JALAN NASIONAL (sudah lebih dulu ada di sana).
  { id: "keselamatan", label: "Keselamatan & Layanan Darurat", icon: "bi-heart-pulse",
    match: (p) => p === "KESELAMATAN" },
  // Kawasan tematik Bappenas (tabel kawasan_tematik, aslinya tanpa geometri) yang
  // dipetakan ke poligon kecamatan/kab-kota oleh scripts/build_kawasan_tematik_layer.py.
  // Warna tetap per kategori: KAWASAN_TEMATIK_WARNA di bawah.
  // KORIDOR AWP-1: ruas PETA KORIDOR + skor CER (scripts/import_cer_awp1.py), model eksperimental.
  { id: "koridor-awp1", label: "Koridor AWP-1 (CER, eksperimental)", icon: "bi-bezier2",
    match: (p) => p === "KORIDOR AWP-1" },
  { id: "kawasan-bappenas", label: "Kawasan Tematik (Bappenas)", icon: "bi-pin-map",
    match: (p) => p === "KAWASAN TEMATIK BAPPENAS" },
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
    if (!group) return;
    // Mode normal men-exclude PETA KORIDOR (lihat loadKabupatenChildren) --
    // provinsi yang isinya cuma PETA KORIDOR (mis. DI Yogyakarta, provinsi
    // pemekaran Papua) disembunyikan di sini supaya tidak jadi node kosong.
    const rows = group.rows
      .filter((p) => (p.kabupaten_count_tanpa_koridor ?? p.kabupaten_count) > 0)
      .map((p) => ({ ...p, kabupaten_count: p.kabupaten_count_tanpa_koridor ?? p.kabupaten_count }));
    if (!rows.length) return;
    tree.appendChild(renderTreeNode({
      icon: cat.icon,
      label: cat.label,
      count: rows.length,
      countSuffix: "provinsi",
      loadChildren: () => renderProvinsiChildren(rows),
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
    // Bucket nasional flat (JALAN NASIONAL, PELABUHAN, ...) dipecah jadi entri
    // "Seluruh Indonesia" + satu entri per provinsi (kabupaten virtual = nama
    // provinsi, lihat _map_layer_pecahan_provinsi di app.py).
    qs.set("per_provinsi", "1");
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
      <span class="maplayer-item-label" title="${escapeHtml(l.label)}">${escapeHtml(l.label)}</span>
      <span class="maplayer-item-size">${l.size_mb != null ? `${l.size_mb} MB` : ""}</span>
      <button type="button" class="maplayer-download" data-provinsi="${escapeHtml(provinsi)}" data-kabupaten="${escapeHtml(kabupaten)}" data-layer="${escapeHtml(l.layer)}"
        title="Unduh SHP + data atribut layer ini"><i class="bi bi-download"></i></button>
      <input type="range" class="maplayer-opacity" min="0" max="1" step="0.05" value="${opacity}" data-provinsi="${escapeHtml(provinsi)}" data-kabupaten="${escapeHtml(kabupaten)}" data-layer="${escapeHtml(l.layer)}" title="Transparansi layer" ${isActive ? "" : "hidden"} />
    `;
    // Baris ini adalah <label> yg membungkus checkbox -- browser meneruskan klik APAPUN di
    // dalamnya (termasuk tombol unduh) ke checkbox itu (perilaku native <label>) SELAMA
    // event belum di-preventDefault() pada titik event mencapai <label>. Listener yg
    // di-delegasikan ke leluhur label (mis. treeEl) baru jalan SETELAH label memproses
    // default action-nya sendiri -- sudah terlambat. Makanya listener tombol unduh dipasang
    // di sini, langsung ke tombolnya (anak label), bukan lewat delegasi treeEl.click di bawah.
    row.querySelector(".maplayer-download").addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      const qs = new URLSearchParams({ provinsi, kabupaten: kabupaten || "", layer: l.layer });
      const a = document.createElement("a");
      a.href = `/api/maps/layer/export/shp?${qs}`;
      a.rel = "noopener";
      document.body.appendChild(a);
      a.click();
      a.remove();
    });
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
    const geojson = await fetchMapLayerGeojson(provinsi, kabupaten, layer, mapLayerLodForZoom());

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
    state.mapLayers.lod[key] = { lod: geojson.lod ?? 2, tersedia: !!geojson.lod_tersedia };
    bindMapLayerLodRefresh();
    applyLayerStyle(key);
    if (layer === "KAPLIN STASIUN") bindKaplinLabelZoom();
    if (provinsi === "BATAS KECAMATAN") updateKecamatanLintasan();
    updateMapLegend();
    panToLayerIfOffscreen(data);
  } catch (err) {
    console.error(err);
    toast("Gagal memuat layer peta", true);
    const cb = listCheckboxFor(key);
    if (cb) cb.checked = false;
    delete state.mapLayers.meta[key];
  }
}

async function fetchMapLayerGeojson(provinsi, kabupaten, layer, lod) {
  const qs = new URLSearchParams({ provinsi, kabupaten, layer, lod });
  const res = await fetch(`/api/maps/layer?${qs}`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

/* ---------- level of detail geometri menurut zoom ----------
   Layer garis/poligon berat (server menandai lod_tersedia) dimuat dlm 3 tingkat
   detail: 0 = zoom <=6, 1 = zoom 7-9, 2 = detail (lihat _MAP_LAYER_LOD_TOLERANSI
   di app.py). Saat zoom berhenti di tingkat lain, fitur layer ditukar dgn versi
   yang sesuai -- di zoom jauh browser tidak lagi menggambar ribuan vertex yang
   toh lebih rapat dari satu piksel (penyebab utama peta patah-patah saat pan).
   Layer yang sedang di-identify/dipilih tidak ditukar dulu (referensi fiturnya
   akan hilang); ditukar pada zoom berikutnya setelah dilepas. */
function mapLayerLodForZoom() {
  const z = state.map ? state.map.getZoom() : 5;
  return z <= 6 ? 0 : z <= 9 ? 1 : 2;
}

function bindMapLayerLodRefresh() {
  if (state._mapLayerLodBound || !state.map) return;
  state._mapLayerLodBound = true;
  state.map.addListener("idle", refreshMapLayerLod);
}

function mapLayerSedangDipakai(key) {
  return state.identifyHighlight?.layer === key || state.selectedFeatures.some((s) => s.layer === key);
}

function refreshMapLayerLod() {
  const target = mapLayerLodForZoom();
  Object.entries(state.mapLayers.lod).forEach(([key, info]) => {
    if (!info.tersedia || info.memuat || info.lod === target) return;
    if (!state.mapLayers.active[key] || mapLayerSedangDipakai(key)) return;
    swapMapLayerLod(key, target);
  });
}

async function swapMapLayerLod(key, lod) {
  const info = state.mapLayers.lod[key];
  const { provinsi, kabupaten, layer } = state.mapLayers.meta[key] || {};
  info.memuat = true;
  let tertukar = false;
  try {
    const geojson = await fetchMapLayerGeojson(provinsi, kabupaten, layer, lod);
    const data = state.mapLayers.active[key];
    // layer bisa saja dimatikan / user mulai identify selama unduhan berjalan
    if (!data || state.mapLayers.lod[key] !== info || mapLayerSedangDipakai(key)) return;
    data.forEach((f) => data.remove(f));
    data.addGeoJson(geojson);
    info.lod = geojson.lod ?? lod;
    tertukar = true;
    if (provinsi === "BATAS KECAMATAN") updateKecamatanLintasan();
  } catch (err) {
    console.error(err); // tetap pakai geometri yang sudah tampil
  } finally {
    info.memuat = false;
  }
  // zoom bisa sudah berubah lagi selama unduhan
  if (tertukar && info.lod !== mapLayerLodForZoom()) refreshMapLayerLod();
}

// Saat layer dibuka: geser peta ke tengah layer TANPA mengubah zoom -- hanya
// bila tak satu pun bagian layer terlihat di viewport sekarang (layer nasional
// tidak menarik peta menjauh dari wilayah yang sedang dilihat user).
function panToLayerIfOffscreen(data) {
  if (!state.map) return;
  const bounds = new google.maps.LatLngBounds();
  data.forEach((f) => f.getGeometry() && f.getGeometry().forEachLatLng((ll) => bounds.extend(ll)));
  if (bounds.isEmpty()) return;
  const view = state.map.getBounds();
  if (view && view.intersects(bounds)) return;
  state.map.panTo(bounds.getCenter());
}

/* ---------- kecamatan yang dilintasi rute KML usulan diberi warna beda ---------- */

// Kontras dengan polyline rute usulan (oranye #f59e0b) dan warna-warna palet
// layer — jangan samakan, supaya poligon terlintas tidak menyatu dengan rute.
const KEC_LINTAS_COLOR = "#e11d74";

function _routeSamplePoints(maxPts = 80) {
  const pts = [];
  // + usulan yang dicentang (multi-select di panel Jelajahi, usulan-inpres.js)
  [...(state.browseUsulanPolylines || []), ...usulanMultiPolylines()].forEach((pl) => {
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
// Legenda KAPLIN (import_kaplin_ka.py) -- nilai warna sama persis dgn skrip.
const KAPLIN_UTILISASI_LEGEND = [
  ["#2e9e5b", "Utilisasi rendah (< 60%)"], ["#e0a800", "Utilisasi sedang (60–85%)"],
  ["#d64545", "Utilisasi tinggi (≥ 85%)"], ["#8a94a6", "Data kapasitas tidak tersedia"],
];
const KAPLIN_KORIDOR_LEGEND = [
  ["#0072B2", "Jakarta – Cirebon"], ["#009E73", "Cirebon – Semarang"], ["#E69F00", "Cirebon – Yogyakarta"],
  ["#D55E00", "Semarang – Surabaya"], ["#CC79A7", "Bandung – Kroya"],
];
const KAPLIN_LABEL_MIN_ZOOM = 9;
// Legenda Klaster/Subklaster (import_subklaster_to_postgis.py) -- nilai warna sama persis dgn KLASTER_WARNA skrip.
const KLASTER_BUCKET = "KLASTER SUBKLASTER";
const KLASTER_LEGEND = [
  ["#E6B800", "Klaster Tanaman Pangan"], ["#009E73", "Klaster Perkebunan Tebu"],
  ["#D55E00", "Klaster Perkebunan Sawit"], ["#CC79A7", "Klaster Peternakan"],
];
// Legenda RTRW Papua Selatan (import_rtrw_papua_selatan_jaringan_to_postgis.py) -- per layer, warna sama dgn GAYA skrip.
const RTRW_PAPSEL_LEGEND = {
  "JARINGAN JALAN RTRW": [
    ["#C62828", "Jalan Arteri Primer"], ["#EF6C00", "Jalan Kolektor Primer (eksisting)"],
    ["#FFB74D", "Jalan Kolektor Primer (rencana)"], ["#B39DDB", "Jalan Khusus (rencana)"],
  ],
  "Alur Pelayaran (RTRW Struktur Ruang)": [
    ["#1565C0", "Alur pelayaran umum & perlintasan"], ["#00ACC1", "Alur pelayaran sungai & danau"],
    ["#0D47A1", "Alur pelayaran masuk pelabuhan"],
  ],
};
// Legenda Perlintasan KA per BTP (import_perlintasan_btp_to_postgis.py) -- warna sama persis dgn WARNA skrip.
const PERLINTASAN_BTP_LAYER = "Perlintasan KA (Data BTP)";
const PERLINTASAN_BTP_LEGEND = [
  ["#1565C0", "Dijaga PT KAI"], ["#00897B", "Dijaga Pemda/Dishub"],
  ["#F9A825", "Dijaga swadaya/swasta/lainnya"], ["#E53935", "Tidak dijaga (resmi)"],
  ["#6A1B9A", "Liar"], ["#9E9E9E", "Tidak sebidang"], ["#424242", "Ditutup"],
  ["#BDBDBD", "Status tidak tercatat"],
];
const arusFilter = { pulau: "", provinsi: "", arah: "keduanya", antarPulau: false };

/* ---------- Ikon titik per jenis (bandara = pesawat, pelabuhan = jangkar, dst.) ----------
   Titik digambar sbg glyph berwarna (tanpa lingkaran latar) dgn halo putih
   supaya tetap terbaca di atas basemap. Warnanya = warna layer / _warna /
   warna status (Stasiun KA, Perlintasan BTP), jadi legenda warna yang sudah
   ada tetap berlaku; bentuk glyph menunjukkan JENIS titik.
   Path glyph: Material Design Icons (viewBox 24x24), kecuali kapalPenumpang. */
const POINT_GLYPHS = {
  kapalPenumpang: "M10 3h2.6v3.6H10zM13.4 4.2H16v2.4h-2.6zM7.5 7.4h9.5v3H7.5zM4.5 11.2h15v3h-15zM2 15h20l-3.2 6H5.2z",
  pesawat: "M21 16v-2l-8-5V3.5c0-.83-.67-1.5-1.5-1.5S10 2.67 10 3.5V9l-8 5v2l8-2.5V19l-2 1.5V22l3.5-1 3.5 1v-1.5L13 19v-5.5l8 2.5z",
  jangkar: "M12 2a3 3 0 0 0-3 3c0 1.27.8 2.4 2 2.83V10H8v2h3v6.92c-1.84-.29-3.47-1.35-4.47-2.92H8v-2H3v5h2v-1.7C6.58 19.61 9.18 21 12 21s5.42-1.39 7-3.7V19h2v-5h-5v2h1.47c-1 1.57-2.63 2.63-4.47 2.92V12h3v-2h-3V7.82C14.2 7.4 15 6.27 15 5a3 3 0 0 0-3-3zm0 2a1 1 0 1 1 0 2 1 1 0 0 1 0-2z",
  kapal: "M20 21c-1.39 0-2.78-.47-4-1.32-2.44 1.71-5.56 1.71-8 0C6.78 20.53 5.39 21 4 21H2v2h2c1.38 0 2.74-.35 4-.99 2.52 1.29 5.48 1.29 8 0 1.26.65 2.62.99 4 .99h2v-2h-2zM3.95 19H4c1.6 0 3.02-.88 4-2 .98 1.12 2.4 2 4 2s3.02-.88 4-2c.98 1.12 2.4 2 4 2h.05l1.89-6.68c.08-.26.06-.54-.06-.78s-.34-.42-.6-.5L20 10.62V6c0-1.1-.9-2-2-2h-3V1H9v3H6c-1.1 0-2 .9-2 2v4.62l-1.29.42c-.26.08-.48.26-.6.5s-.15.52-.06.78L3.95 19zM6 6h12v3.97L12 8 6 9.97V6z",
  kereta: "M12 2c-4 0-8 .5-8 4v9.5C4 17.43 5.57 19 7.5 19L6 20.5v.5h2.23l2-2H14l2 2h2v-.5L16.5 19c1.93 0 3.5-1.57 3.5-3.5V6c0-3.5-3.58-4-8-4zM7.5 17c-.83 0-1.5-.67-1.5-1.5S6.67 14 7.5 14s1.5.67 1.5 1.5S8.33 17 7.5 17zm3.5-7H6V6h5v4zm2 0V6h5v4h-5zm3.5 7c-.83 0-1.5-.67-1.5-1.5s.67-1.5 1.5-1.5 1.5.67 1.5 1.5-.67 1.5-1.5 1.5z",
  bus: "M4 16c0 .88.39 1.67 1 2.22V20c0 .55.45 1 1 1h1c.55 0 1-.45 1-1v-1h8v1c0 .55.45 1 1 1h1c.55 0 1-.45 1-1v-1.78c.61-.55 1-1.34 1-2.22V6c0-3.5-3.58-4-8-4s-8 .5-8 4v10zm3.5 1c-.83 0-1.5-.67-1.5-1.5S6.67 14 7.5 14s1.5.67 1.5 1.5S8.33 17 7.5 17zm9 0c-.83 0-1.5-.67-1.5-1.5s.67-1.5 1.5-1.5 1.5.67 1.5 1.5-.67 1.5-1.5 1.5zm1.5-6H6V6h12v5z",
  truk: "M20 8h-3V4H3c-1.1 0-2 .9-2 2v11h2c0 1.66 1.34 3 3 3s3-1.34 3-3h6c0 1.66 1.34 3 3 3s3-1.34 3-3h2v-5l-3-4zM6 18.5c-.83 0-1.5-.67-1.5-1.5s.67-1.5 1.5-1.5 1.5.67 1.5 1.5-.67 1.5-1.5 1.5zm13.5-9l1.96 2.5H17V9.5h2.5zm-1.5 9c-.83 0-1.5-.67-1.5-1.5s.67-1.5 1.5-1.5 1.5.67 1.5 1.5-.67 1.5-1.5 1.5z",
  perlintasan: "M4.6 3.2 12 10.6l7.4-7.4 1.4 1.4-7.4 7.4 7.4 7.4-1.4 1.4-7.4-7.4-7.4 7.4-1.4-1.4 7.4-7.4-7.4-7.4z",
  jembatan: "M2 13h20v2h-2v5h-2v-5H6v5H4v-5H2zM2 11c3-5.33 17-5.33 20 0v1H2z",
  peringatan: "M1 21h22L12 2 1 21zm12-3h-2v-2h2v2zm0-4h-2v-4h2v4z",
  medis: "M19 3H5c-1.1 0-1.99.9-1.99 2L3 19c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm-1 11h-4v4h-4v-4H6v-4h4V6h4v4h4v4z",
  sar: "M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zm0 4.5a5.5 5.5 0 1 1 0 11 5.5 5.5 0 0 1 0-11zM10.5 2.2h3v4.4h-3zM10.5 17.4h3v4.4h-3zM2.2 10.5h4.4v3H2.2zM17.4 10.5h4.4v3h-4.4z",
  sekolah: "M5 13.18v4L12 21l7-3.82v-4L12 17l-7-3.82zM12 3L1 9l11 6 9-4.91V17h2V9L12 3z",
  gedung: "M12 7V3H2v18h20V7H10zM6 19H4v-2h2v2zm0-4H4v-2h2v2zm0-4H4V9h2v2zm0-4H4V5h2v2zm4 12H8v-2h2v2zm0-4H8v-2h2v2zm0-4H8V9h2v2zm0-4H8V5h2v2zm10 12h-8v-2h2v-2h-2v-2h2v-2h-2V9h8v10zm-2-8h-2v2h2v-2zm0 4h-2v2h2v-2z",
  gudang: "M22 21V7L12 3 2 7v14h5v-9h10v9h5zm-11-2H9v2h2v-2zm2-3h-2v2h2v-2zm2 3h-2v2h2v-2z",
  bintang: "M12 17.27L18.18 21l-1.64-7.03L22 9.24l-7.19-.61L12 2 9.19 8.63 2 9.24l5.46 4.73L5.82 21z",
  jalan: "M11 2h2v3h6l2 2.5L19 10h-6v12h-2V12H5l-2-2.5L5 7h6z",
  titik: "M12 7a5 5 0 1 0 0 10 5 5 0 0 0 0-10z",
};
// Aturan glyph per nama bucket+layer (urutan penting: yang lebih spesifik dulu).
const POINT_GLYPH_RULES = [
  [/BPSDM/, "sekolah"],
  [/PERLINTASAN|TITIK POTONG|JPL/, "perlintasan"],
  [/JEMBATAN/, "jembatan"],
  [/STASIUN/, "kereta"],
  [/GUDANG/, "gudang"],
  [/BATAS BTP/, "gedung"],
  [/BLACKSPOT|RAWAN KECELAKAAN/, "peringatan"],
  [/PSC/, "medis"],
  [/BASARNAS|KANTOR SAR|POS SAR/, "sar"],
  [/PENYEBERANGAN|PENYEBRANGAN|::PP$/, "kapal"],
  [/ANGKUTAN.*LAUT/, "kapal"],
  [/BANDARA|UDARA|MASKAPAI/, "pesawat"],
  [/TERSUS|TUKS/, "gudang"],
  [/PELABUHAN PENUMPANG|ANGKUTAN PENUMPANG LAUT/, "kapalPenumpang"],
  [/PELABUHAN/, "jangkar"],
  [/TERMINAL/, "bus"],
  [/ANGKUTAN DARAT BARANG/, "truk"],
  [/KSPN/, "bintang"],
  [/JALAN|STA_|TRACK/, "jalan"],
];
// Layer RTRW "Simpul Transportasi" mencampur bandara/pelabuhan/terminal -> per fitur dari atribut Jenis.
const RTRW_JENIS_GLYPH_RULES = [
  [/BANDAR UDARA/, "pesawat"], [/PENYEBERANGAN/, "kapal"], [/PELABUHAN|PENDARATAN IKAN|TERMINAL (KHUSUS|UMUM)/, "jangkar"],
  [/TERMINAL PENUMPANG/, "bus"], [/TERMINAL BARANG|TIMBANG/, "truk"], [/JEMBATAN/, "jembatan"],
];

function pointGlyphFor(key) {
  const meta = state.mapLayers.meta[key] || {};
  const nama = `${meta.provinsi || ""}::${mapLayerRawName(key)}`.toUpperCase();
  const hit = POINT_GLYPH_RULES.find(([re]) => re.test(nama));
  return hit ? hit[1] : "titik";
}

function pointGlyphForFeature(layerGlyph, feature) {
  const jenis = feature.getProperty("Jenis");
  if (!jenis) return layerGlyph;
  const hit = RTRW_JENIS_GLYPH_RULES.find(([re]) => re.test(String(jenis).toUpperCase()));
  return hit ? hit[1] : layerGlyph;
}

/* Bandara: lencana bulat bergradasi + pesawat putih miring (lebih menonjol dari
   glyph polos). Warna per sumber layer supaya layer bandara yang aktif bersamaan
   tetap terbedakan: Kemenhub = biru, RBI/Simpul Transportasi = abu, lainnya
   (Titik Udara perintis, Maskapai, bandar udara RTRW) = ungu tua. */
const BANDARA_WARNA = {
  biru: { atas: "#60a5fa", bawah: "#1d4ed8" },
  abu: { atas: "#9ca3af", bawah: "#4b5563" },
  unguTua: { atas: "#7c3aed", bawah: "#3b0764" },
};

function bandaraWarnaLayer(key) {
  const meta = state.mapLayers.meta[key] || {};
  if (meta.provinsi === "BANDARA KEMENHUB") return BANDARA_WARNA.biru.bawah;
  if (meta.provinsi === "BANDARA" || /^Bandara/i.test(meta.layer || "")) return BANDARA_WARNA.abu.bawah;
  return BANDARA_WARNA.unguTua.bawah;
}

function bandaraBadgeSvg(color) {
  const tone = Object.values(BANDARA_WARNA).find((t) => t.bawah === color) || { atas: color, bawah: color };
  return `<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 32 32">`
    + `<defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1">`
    + `<stop offset="0" stop-color="${tone.atas}"/><stop offset="1" stop-color="${tone.bawah}"/></linearGradient>`
    + `<filter id="s" x="-30%" y="-30%" width="160%" height="160%"><feDropShadow dx="0" dy="1.2" stdDeviation="1.2" flood-color="#0f172a" flood-opacity="0.45"/></filter></defs>`
    + `<circle cx="16" cy="15.5" r="12.5" fill="url(#g)" stroke="#ffffff" stroke-width="2.2" filter="url(#s)"/>`
    + `<circle cx="16" cy="15.5" r="9.6" fill="none" stroke="#ffffff" stroke-opacity="0.35" stroke-width="0.8"/>`
    + `<path d="${POINT_GLYPHS.pesawat}" fill="#ffffff" transform="translate(16 15.5) rotate(45) scale(0.66) translate(-12 -12)"/>`
    + `</svg>`;
}

const _pointIconUrlCache = {};
function pointIconUrl(glyph, color, opacity = 1) {
  const ck = `${glyph}|${color}|${opacity}`;
  if (!_pointIconUrlCache[ck] && glyph === "pesawat") {
    _pointIconUrlCache[ck] = "data:image/svg+xml;charset=UTF-8,"
      + encodeURIComponent(bandaraBadgeSvg(color).replace("<svg ", `<svg opacity="${opacity}" `));
  }
  if (!_pointIconUrlCache[ck]) {
    const d = POINT_GLYPHS[glyph] || POINT_GLYPHS.titik;
    // path pertama = halo putih (stroke tebal), path kedua = glyph berwarna di atasnya
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="26" height="26" viewBox="-1 -1 26 26" opacity="${opacity}">`
      + `<path d="${d}" fill="#ffffff" stroke="#ffffff" stroke-width="3" stroke-linejoin="round"/>`
      + `<path d="${d}" fill="${color}" fill-rule="evenodd"/>`
      + `</svg>`;
    _pointIconUrlCache[ck] = "data:image/svg+xml;charset=UTF-8," + encodeURIComponent(svg);
  }
  return _pointIconUrlCache[ck];
}

// fillColor/scale ikut disimpan supaya print-map.js (yang membaca icon.fillColor/scale) tetap dapat warnanya.
function pointIcon(glyph, color, opacity, size = 24) {
  if (glyph === "pesawat") size = Math.round(size * 1.2); // lencana bandara sedikit lebih besar
  return {
    url: pointIconUrl(glyph, color, opacity),
    scaledSize: new google.maps.Size(size, size),
    anchor: new google.maps.Point(size / 2, size / 2),
    labelOrigin: new google.maps.Point(size / 2, -6),
    fillColor: color, scale: 4,
  };
}

// Simbol legenda per jenis geometri layer: titik = ikon jenisnya, garis = garis
// patah, poligon = kotak berisi + tepi. null kalau layer belum punya fitur.
function layerLegendSymbolHtml(key, color, size = 18) {
  const data = state.mapLayers.active[key];
  let type = "";
  if (data) data.forEach((f) => { if (!type) type = f.getGeometry()?.getType() || ""; });
  if (!type) return null;
  const img = (src) => `<img src="${src}" width="${size}" height="${size}" alt="" style="flex:none;vertical-align:middle">`;
  if (/Point/.test(type)) {
    const glyph = pointGlyphFor(key);
    return img(pointIconUrl(glyph, glyph === "pesawat" ? bandaraWarnaLayer(key) : color));
  }
  const svg = /Polygon/.test(type)
    ? `<rect x="3" y="3" width="18" height="18" rx="2" fill="${color}" fill-opacity="0.45" stroke="${color}" stroke-width="2"/>`
    : `<polyline points="2,19 8,9 14,15 22,4" fill="none" stroke="${color}" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/>`;
  return img("data:image/svg+xml;charset=UTF-8," + encodeURIComponent(
    `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24">${svg}</svg>`));
}

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

/* ---------- Hierarki jalan (deck 20261007 slide 3) ----------
   Tol merah, Nasional hijau, Provinsi biru, Kab/Kota kuning, Desa/Lingkungan
   abu-abu; garis jalan diberi zIndex DI ATAS poligon overlay (batas
   kecamatan dsb.), yg dulu menenggelamkan jaringan jalan (slide 2). zIndex
   tetap di bawah garis usulan (20-30) & rute (10), jadi keduanya tetap di atas.
   Layer jalan kab/kota (203 layer, atribut beragam) diklasifikasi per ruas:
   kolom status (Status/STATUS_JAL/...) dulu, lalu kolom fungsi RBI
   (REMARK/Fungsi/...) utk memisahkan jalan desa/lingkungan/setapak; sisanya
   dianggap jalan kab/kota (layer itu memang layer jalan kab/kota). */
const JALAN_KELAS = {
  tol: { warna: "#dc2626", lebar: 4, z: 7, teks: "Jalan Tol" },
  nasional: { warna: "#16a34a", lebar: 3.4, z: 6, teks: "Jalan Nasional" },
  provinsi: { warna: "#2563eb", lebar: 2.8, z: 5, teks: "Jalan Provinsi" },
  kabkota: { warna: "#eab308", lebar: 2.2, z: 4, teks: "Jalan Kabupaten/Kota" },
  desa: { warna: "#9ca3af", lebar: 1.4, z: 3, teks: "Jalan Desa/Lingkungan" },
};
const JALAN_KELAS_URUT = ["tol", "nasional", "provinsi", "kabkota", "desa"];
// "Koridor hasil analisis" (layer PETA KORIDOR) -- ungu/magenta. Deck meminta
// garis putus-putus, tetapi google.maps.Data tidak mendukung pola garis.
const KORIDOR_GAYA = { warna: "#c026d3", lebar: 2.8, z: 8, teks: "Koridor hasil analisis (PETA KORIDOR)" };

const AWP1_LAYER = "Koridor AWP-1";
const AWP1_WARNA = "#ec4899";

function jalanLayerJenis(key) {
  const meta = state.mapLayers.meta[key] || {};
  const raw = mapLayerRawName(key);
  if (meta.provinsi === "JALAN TOL") return "tol";
  if (meta.provinsi === "JALAN NASIONAL") return "nasional";
  if (meta.provinsi === "JALAN PROVINSI") return "provinsi";
  if (/^JALAN/i.test(raw) && raw !== "JARINGAN JALAN RTRW") return "kab";
  return null;
}

const _JALAN_KOLOM_STATUS = /^(status|sts|status_?jal\w*|wewenang|kewenangan)$/i;
const _JALAN_KOLOM_FUNGSI = /^(remark|fungsi\w*|klas\w*|kelas_?fungsi)$/i;
function jalanKelasDariStatus(v) {
  const t = String(v).trim().toLowerCase();
  if (!t || t === "-" || t === "0") return null;
  if (/\btol\b/.test(t)) return "tol";
  if (/nasional|negara/.test(t) || t === "n") return "nasional";
  if (/prov|prop/.test(t) || t === "p") return "provinsi";
  if (/non ?sk|lingkungan|desa|perum|setapak/.test(t)) return "desa";
  if (/kab|kota/.test(t) || t === "k") return "kabkota";
  return null;
}
const _jalanKelasCache = new WeakMap();
function jalanKelasFitur(feature, jenisLayer) {
  if (jenisLayer !== "kab") return jenisLayer;
  if (_jalanKelasCache.has(feature)) return _jalanKelasCache.get(feature);
  let kelas = null;
  let desaDariFungsi = false;
  feature.forEachProperty((v, k) => {
    if (kelas || v === null || v === undefined || typeof v === "object") return;
    if (_JALAN_KOLOM_STATUS.test(k)) kelas = jalanKelasDariStatus(v);
    else if (_JALAN_KOLOM_FUNGSI.test(k) && /setapak|jalan lain|^lain|lingkungan|desa/i.test(String(v))) desaDariFungsi = true;
  });
  kelas = kelas || (desaDariFungsi ? "desa" : "kabkota");
  _jalanKelasCache.set(feature, kelas);
  return kelas;
}

// Kelas jalan yang benar-benar ada di layer aktif (urut hierarki) -- utk legenda layar & cetak.
function jalanKelasDiLayer(key) {
  const jenis = jalanLayerJenis(key);
  const data = state.mapLayers.active[key];
  if (!jenis || !data) return [];
  const ada = new Set();
  data.forEach((f) => {
    const t = f.getGeometry()?.getType() || "";
    if (/LineString/.test(t)) ada.add(jalanKelasFitur(f, jenis));
  });
  return JALAN_KELAS_URUT.filter((k) => ada.has(k));
}

function applyLayerStyle(key) {
  const data = state.mapLayers.active[key];
  if (!data) return;
  const color = mapLayerColor(mapLayerRawName(key));
  const opacity = state.mapLayers.opacity[key] ?? 1;
  const isArus = mapLayerRawName(key).startsWith(ARUS_LAYER_PREFIX);
  const layerGlyph = pointGlyphFor(key);
  const glyphPerJenis = state.mapLayers.meta[key]?.provinsi === "RTRW";
  const jenisJalan = jalanLayerJenis(key);
  const isKoridor = mapLayerRawName(key) === "PETA KORIDOR";
  const isAwp1 = mapLayerRawName(key) === AWP1_LAYER;
  data.setStyle((feature) => {
    if (isArus && !arusFeatureVisible(feature)) return { visible: false };
    if (feature.getProperty("DILINTASI_RUTE") === "YA") {
      return {
        fillColor: KEC_LINTAS_COLOR, fillOpacity: 0.28 * opacity,
        // zIndex 1: di atas poligon biasa (0), di bawah garis jalan (3-8) supaya jaringan jalan tetap terbaca
        strokeColor: KEC_LINTAS_COLOR, strokeWeight: 2.6, strokeOpacity: opacity, zIndex: 1,
      };
    }
    const type = feature.getGeometry().getType();
    if ((type === "Point" || type === "MultiPoint") && feature.getProperty("_label")) {
      // titik dgn label (stasiun KAPLIN): nama tampil di atas titik mulai zoom tertentu
      const zoom = state.map ? state.map.getZoom() : 0;
      return {
        icon: pointIcon(layerGlyph, "#1f2937", opacity, 20),
        label: zoom >= KAPLIN_LABEL_MIN_ZOOM
          ? { text: String(feature.getProperty("_label")), fontSize: "11px", fontWeight: "600", color: "#111827" }
          : null,
        zIndex: 50,
      };
    }
    if (type === "Point" || type === "MultiPoint") {
      // _warna per titik dari server (mis. Perlintasan KA per BTP: warna per status penjagaan)
      const glyph = glyphPerJenis ? pointGlyphForFeature(layerGlyph, feature) : layerGlyph;
      const pointColor = mapLayerRawName(key) === STASIUN_LAYER_NAME
        ? stasiunStatusColor(feature.getProperty(STASIUN_STATUS_FIELD))
        : glyph === "pesawat" ? bandaraWarnaLayer(key)
        : feature.getProperty("_warna") || color;
      return { icon: pointIcon(glyph, pointColor, opacity), zIndex: glyph === "pesawat" ? 40 : undefined };
    }
    if (type === "Polygon" || type === "MultiPolygon") {
      // poligon dgn warna per kategori dari server (mis. Klaster/Subklaster: _warna per klaster)
      const warnaPoligon = feature.getProperty("_warna");
      if (warnaPoligon) {
        return { fillColor: warnaPoligon, fillOpacity: 0.35 * opacity, strokeColor: warnaPoligon, strokeWeight: 1, strokeOpacity: opacity };
      }
      return { fillColor: color, fillOpacity: 0.18 * opacity, strokeColor: color, strokeWeight: 1.2, strokeOpacity: opacity };
    }
    // Layer "Arus Perdagangan Antar Provinsi" (import_arus_irio_provinsi.py):
    // ketebalan garis sudah dihitung server-side (skala log rupiah/ton) di
    // properti "Ketebalan garis (px)"; garis tipis digambar di atas yang tebal.
    const warnaGaris = feature.getProperty("_warna");
    if (jenisJalan && !warnaGaris) {
      const k = JALAN_KELAS[jalanKelasFitur(feature, jenisJalan)];
      return { strokeColor: k.warna, strokeWeight: k.lebar, strokeOpacity: 0.95 * opacity, zIndex: k.z };
    }
    if (isAwp1) {
      // pink (deck slide 3); di atas jalan & PETA KORIDOR (8), di bawah garis usulan (20-30)
      return { strokeColor: warnaGaris || AWP1_WARNA, strokeWeight: Number(feature.getProperty("_lebar")) || 3, strokeOpacity: 0.95 * opacity, zIndex: 9 };
    }
    if (isKoridor && !warnaGaris) {
      return { strokeColor: KORIDOR_GAYA.warna, strokeWeight: KORIDOR_GAYA.lebar, strokeOpacity: 0.95 * opacity, zIndex: KORIDOR_GAYA.z };
    }
    if (warnaGaris) {
      // Koridor Utama = "selubung" lebar semi-transparan DI BAWAH garis petak, supaya warna
      // utilisasi petak tetap terlihat & mudah diklik (klik -> popup atribut petak).
      if (mapLayerRawName(key) === "KAPLIN KORIDOR UTAMA") {
        return { strokeColor: warnaGaris, strokeWeight: 10, strokeOpacity: 0.5 * opacity, zIndex: 5 };
      }
      return { strokeColor: warnaGaris, strokeWeight: Number(feature.getProperty("_lebar")) || 4, strokeOpacity: 0.95 * opacity, zIndex: kaplinZ(feature) };
    }
    const lebarGaris = Number(feature.getProperty("Ketebalan garis (px)"));
    if (lebarGaris > 0) {
      return {
        strokeColor: isArus ? arusLayerColor(key) : color,
        strokeWeight: lebarGaris, strokeOpacity: 0.2 * arusKelas(feature) * opacity,
        zIndex: Math.round(100 - lebarGaris * 5),
      };
    }
    // garis lain (rel, alur, ...): tetap di atas poligon overlay (zIndex 0)
    return { strokeColor: color, strokeWeight: 1.6, strokeOpacity: 0.9 * opacity, zIndex: 2 };
  });
}

// Sheet KAPLIN memuat petak agregat (mis. Jatinegara-Bekasi 14,8 km) SEKALIGUS petak per-stasiun di atas
// rel yang sama: petak yang lebih pendek digambar di atas supaya klik antar dua stasiun membuka petak
// stasiun itu, bukan petak agregat.
function kaplinZ(feature) {
  const km = parseFloat(String(feature.getProperty("Jarak petak (km)") || "").replace(/\./g, "").replace(",", ".")) || 0;
  return 10 + Math.max(0, Math.round(300 - km * 3));
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
  delete state.mapLayers.lod[key];
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
  state.mapLayers.lod = {};
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
