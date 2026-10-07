/* --- Menu klik kanan layer overlay: label & ukuran dinamis (7 Okt 2026) ------
   Usulan pengguna: "fitur klik kanan show hide label, ukuran label dan ukuran
   icon dinamis". Klik kanan pada fitur di peta, baris layer di legenda, atau
   baris layer aktif di tree Overlay Peta membuka menu kecil:
   - Tampilkan label (on/off) + kolom atribut yang dipakai;
   - Ukuran label (px), ikut mengecil otomatis saat zoom out (skalaIkonZoom);
   - Ukuran ikon (layer titik), sama dgn slider di tree (state.mapLayers.iconScale);
   - Transparansi layer.
   Label titik memakai `label` bawaan google.maps.Data (applyLayerStyle memanggil
   labelTitik). Data layer TIDAK bisa memberi label garis/poligon, jadi labelnya
   digambar sbg Marker teks di titik tengah fitur -- hanya fitur dalam layar,
   maks LABEL_MAKS_PENANDA, dibangun ulang saat peta "idle".
   Kolom label yg dipilih juga jadi bawaan kolom label di dialog Cetak peta.
   Dimuat SESUDAH maps-overlay.js, map-tools.js, print-map.js. */

const LABEL_MAKS_PENANDA = 400;
const labelPenanda = {}; // key -> [google.maps.Marker]

function labelCfg(key) {
  state.mapLayers.labelCfg = state.mapLayers.labelCfg || {};
  return state.mapLayers.labelCfg[key];
}

function labelKolomLayer(key) {
  const data = state.mapLayers.active[key];
  const kolom = new Set();
  let n = 0;
  data?.forEach((f) => {
    if (n++ > 200) return;
    f.forEachProperty((v, k) => { if (!String(k).startsWith("_") && v !== null && v !== "" && typeof v !== "object") kolom.add(k); });
  });
  return [...kolom];
}

function labelTeks(feature, field) {
  const v = feature.getProperty(field);
  if (v === null || v === undefined || v === "") return "";
  const s = String(v).trim();
  return s.length > 40 ? `${s.slice(0, 38)}…` : s;
}

function labelUkuranPx(cfg) {
  return Math.max(8, Math.round((cfg?.ukuran || 12) * (typeof skalaIkonZoom === "function" ? Math.max(0.75, skalaIkonZoom()) : 1)));
}

// Dipanggil applyLayerStyle (maps-overlay.js) utk fitur titik.
function labelTitik(key, feature) {
  const cfg = labelCfg(key);
  if (!cfg || !cfg.aktif || !cfg.field) return null;
  const teks = labelTeks(feature, cfg.field);
  if (!teks) return null;
  return { text: teks, fontSize: `${labelUkuranPx(cfg)}px`, fontWeight: "600", color: "#111827", className: "layer-label-teks" };
}

function labelTitikTengah(geom) {
  const pts = [];
  geom.forEachLatLng((ll) => pts.push(ll));
  if (!pts.length) return null;
  const t = geom.getType();
  if (/LineString/.test(t)) return pts[Math.floor(pts.length / 2)];
  // poligon: pusat kotak batas (cukup utk label; poligon cekung bisa sedikit meleset)
  const b = new google.maps.LatLngBounds();
  pts.forEach((p) => b.extend(p));
  return b.getCenter();
}

// Kotak (piksel dunia, zoom sekarang) label garis/poligon layer LAIN yg sedang tampil.
function labelKotakLain(key) {
  const proj = state.map?.getProjection();
  if (!proj) return [];
  const skalaPx = 2 ** state.map.getZoom();
  const out = [];
  Object.entries(labelPenanda).forEach(([k, daftar]) => {
    if (k === key) return;
    daftar.forEach((m) => {
      const lbl = m.getLabel(); const p = proj.fromLatLngToPoint(m.getPosition());
      const ukuran = parseFloat(lbl.fontSize) || 12, w = lbl.text.length * ukuran * 0.58 + 6, h = ukuran * 1.4;
      out.push([p.x * skalaPx - w / 2, p.y * skalaPx - h / 2, p.x * skalaPx + w / 2, p.y * skalaPx + h / 2]);
    });
  });
  return out;
}

function hapusLabelPenanda(key) {
  (labelPenanda[key] || []).forEach((m) => m.setMap(null));
  delete labelPenanda[key];
}

function gambarLabelPenanda(key) {
  hapusLabelPenanda(key);
  const cfg = labelCfg(key);
  const data = state.mapLayers.active[key];
  if (!cfg || !cfg.aktif || !cfg.field || !data || !state.map) return;
  const bounds = state.map.getBounds();
  const proj = state.map.getProjection();
  const skalaPx = 2 ** state.map.getZoom();
  const ukuran = labelUkuranPx(cfg);
  // Penghindar tumpang-tindih: kotak label di piksel dunia; label yg menimpa label
  // lain dilewati (muncul saat zoom in). Termasuk kotak label garis/poligon layer
  // lain yg sudah tergambar, supaya antar-layer juga tidak menumpuk.
  const terpakai = labelKotakLain(key);
  const bentrok = (k) => terpakai.some((t) => k[0] < t[2] && k[2] > t[0] && k[1] < t[3] && k[3] > t[1]);
  const penanda = [];
  const ikonKosong = { url: "data:image/svg+xml;charset=UTF-8,%3Csvg xmlns='http://www.w3.org/2000/svg' width='1' height='1'/%3E", scaledSize: new google.maps.Size(1, 1) };
  data.forEach((f) => {
    if (penanda.length >= LABEL_MAKS_PENANDA) return;
    const g = f.getGeometry();
    if (!g || /Point/.test(g.getType())) return;
    const pos = labelTitikTengah(g);
    if (!pos || (bounds && !bounds.contains(pos))) return;
    const teks = labelTeks(f, cfg.field);
    if (!teks) return;
    if (proj) {
      const p = proj.fromLatLngToPoint(pos);
      const x = p.x * skalaPx, y = p.y * skalaPx, w = teks.length * ukuran * 0.58 + 6, h = ukuran * 1.4;
      const kotak = [x - w / 2, y - h / 2, x + w / 2, y + h / 2];
      if (bentrok(kotak)) return;
      terpakai.push(kotak);
    }
    penanda.push(new google.maps.Marker({
      position: pos, map: state.map, clickable: false, icon: ikonKosong, zIndex: 950,
      label: { text: teks, fontSize: `${labelUkuranPx(cfg)}px`, fontWeight: "600", color: "#111827", className: "layer-label-teks" },
    }));
  });
  labelPenanda[key] = penanda;
}

function terapkanLabel(key) {
  applyLayerStyle(key);        // label titik
  gambarLabelPenanda(key);     // label garis/poligon
}

function bindLabelRefresh() {
  if (state._labelRefreshBound || !state.map) return;
  state._labelRefreshBound = true;
  state.map.addListener("idle", () => {
    Object.keys(state.mapLayers.labelCfg || {}).forEach((key) => {
      if (state.mapLayers.active[key] && labelCfg(key)?.aktif) gambarLabelPenanda(key);
    });
  });
}

/* ---------- menu ---------- */

function tutupMenuLayer() {
  document.getElementById("layerContextMenu")?.remove();
}

function bukaMenuLayer(key, x, y) {
  if (!state.mapLayers.active[key]) return;
  tutupMenuLayer();
  bindLabelRefresh();
  const kolom = labelKolomLayer(key);
  const cfg = labelCfg(key) || { aktif: false, field: printGuessLabelField(kolom), ukuran: 12 };
  const titik = typeof layerAdaTitik === "function" && layerAdaTitik(key);
  const skala = (state.mapLayers.iconScale || {})[key] ?? 1;
  const opacity = state.mapLayers.opacity[key] ?? 1;
  const menu = document.createElement("div");
  menu.id = "layerContextMenu";
  menu.className = "layer-context-menu";
  menu.innerHTML = `
    <div class="layer-context-judul">${escapeHtml(mapLayerDisplayLabel(key))}</div>
    <label class="layer-context-baris"><input type="checkbox" data-aksi="label" ${cfg.aktif ? "checked" : ""} ${kolom.length ? "" : "disabled"}> Tampilkan label</label>
    <label class="layer-context-baris">Kolom
      <select data-aksi="kolom">${kolom.map((k) => `<option value="${escapeHtml(k)}" ${k === cfg.field ? "selected" : ""}>${escapeHtml(k)}</option>`).join("")}</select></label>
    <label class="layer-context-baris">Ukuran label <input type="range" data-aksi="ukuran" min="8" max="22" step="1" value="${cfg.ukuran}"><span data-nilai="ukuran">${cfg.ukuran}px</span></label>
    ${titik ? `<label class="layer-context-baris">Ukuran ikon <input type="range" data-aksi="ikon" min="0.3" max="1.6" step="0.05" value="${skala}"><span data-nilai="ikon">${Math.round(skala * 100)}%</span></label>` : ""}
    <label class="layer-context-baris">Transparansi <input type="range" data-aksi="opacity" min="0" max="1" step="0.05" value="${opacity}"><span data-nilai="opacity">${Math.round(opacity * 100)}%</span></label>
    <div class="layer-context-catatan">Ukuran label & ikon juga menyesuaikan zoom otomatis.</div>`;
  document.body.append(menu);
  const lebar = menu.offsetWidth, tinggi = menu.offsetHeight;
  menu.style.left = `${Math.min(x, window.innerWidth - lebar - 8)}px`;
  menu.style.top = `${Math.min(y, window.innerHeight - tinggi - 8)}px`;

  const simpan = (ubah) => {
    state.mapLayers.labelCfg = state.mapLayers.labelCfg || {};
    state.mapLayers.labelCfg[key] = { ...(labelCfg(key) || cfg), ...ubah };
    terapkanLabel(key);
  };
  menu.addEventListener("input", (e) => {
    const aksi = e.target.dataset.aksi;
    const v = e.target.type === "checkbox" ? e.target.checked : e.target.value;
    if (aksi === "label") simpan({ aktif: v });
    else if (aksi === "kolom") simpan({ field: v });
    else if (aksi === "ukuran") { simpan({ ukuran: Number(v) }); menu.querySelector('[data-nilai="ukuran"]').textContent = `${v}px`; }
    else if (aksi === "ikon") {
      setLayerIconScale(key, Number(v));
      menu.querySelector('[data-nilai="ikon"]').textContent = `${Math.round(v * 100)}%`;
      sinkronSliderTree(key, ".maplayer-iconsize", v);
    } else if (aksi === "opacity") {
      setLayerOpacity(key, Number(v));
      menu.querySelector('[data-nilai="opacity"]').textContent = `${Math.round(v * 100)}%`;
      sinkronSliderTree(key, ".maplayer-opacity", v);
    }
  });
  menu.addEventListener("change", (e) => { if (e.target.dataset.aksi === "kolom") simpan({ field: e.target.value }); });
}

function sinkronSliderTree(key, selector, nilai) {
  const cb = typeof listCheckboxFor === "function" ? listCheckboxFor(key) : null;
  const el = cb?.closest(".maplayer-item")?.querySelector(selector);
  if (el) el.value = nilai;
}

function bindMenuLayerGlobal() {
  document.addEventListener("mousedown", (e) => {
    if (!e.target.closest("#layerContextMenu")) tutupMenuLayer();
  });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") tutupMenuLayer(); });
  // Klik kanan pada baris legenda / tree (delegasi; baris dibuat ulang tiap render).
  document.addEventListener("contextmenu", (e) => {
    const legenda = e.target.closest("#mapLegendList .map-legend-item");
    const tree = e.target.closest(".maplayer-item");
    let key = null;
    if (legenda) key = legenda.querySelector(".map-legend-item-remove")?.dataset.key;
    else if (tree) {
      const cb = tree.querySelector('input[type="checkbox"]');
      if (cb?.checked) key = mapLayerKey(cb.dataset.provinsi, cb.dataset.kabupaten, cb.dataset.layer);
    }
    if (!key || !state.mapLayers.active[key]) return;
    e.preventDefault();
    bukaMenuLayer(key, e.clientX, e.clientY);
  });
}

document.addEventListener("DOMContentLoaded", bindMenuLayerGlobal);
