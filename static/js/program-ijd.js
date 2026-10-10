/* --- Riwayat Program IJD 2023-2026 (3 Okt 2026) ---------------------------
   Modal "Riwayat Program IJD" (tombol #btnProgramIjd, toolbar Jelajahi Usulan
   moda IJD). Sumber: program_ijd_riwayat (DPP final R1) via /api/program-ijd/*.
   Mengikuti arahan deck Bappenas "20261002 Preparation, Implementation and
   Validation of IJD": peta 3 level Indonesia -> provinsi -> kab/kota (hal. 4),
   Barat-Timur & pulau (hal. 15-16), ruas berulang (hal. 17-18), kab/kota tanpa
   IJD (hal. 19-20), rekap tahunan (hal. 22-33), histori kemantapan jalan
   (hal. 2 Tahap 3; sumber usulan SITIA, /api/usulan-riwayat/kemantapan). Memakai helper dari
   usulan-inpres.js (laporanKpiTile, laporanHBar, biayaFmt) dan utils.js
   (escapeHtml) -- file ini harus dimuat sesudahnya. */

const pijd = {
  level: "provinsi", kodeProv: null, namaProv: "", data: null, map: null,
  tooltip: null, kab: null, dimuat: {}, berulang: null,
};

// Ramp sequential satu hue (biru), 5 kelas. Basemap terang: makin besar makin
// gelap; basemap gelap: dibalik (makin besar makin terang).
const PIJD_RAMP_TERANG = ["#b7d3f6", "#6da7ec", "#2a78d6", "#184f95", "#0d366b"];
const PIJD_RAMP_GELAP = ["#104281", "#256abf", "#5598e7", "#9ec5f4", "#d6e6fb"];
const PIJD_WARNA_BARAT = "#3987e5";
const PIJD_WARNA_TIMUR = "#d95926";

const PIJD_METRIK = {
  alokasi_m: { label: "Total alokasi", fmt: (v) => pijdRp(v) },
  panjang_km: { label: "Panjang jalan", fmt: (v) => `${biayaFmt(v)} km` },
  n_kegiatan: { label: "Jumlah kegiatan", fmt: (v) => `${(v || 0).toLocaleString("id-ID")} kegiatan` },
  // Indikator deck 20261007 slide 4. kelas "tetap" = ambang kemantapan; "kuartil"
  // = 4 kelas kuartil wilayah yg tampil. Nilai null = tidak ada data (abu-abu).
  kemantapan_pct: {
    kolom: "% Mantap", label: "Kemantapan jalan daerah 2026", kelas: "tetap", fmt: (v) => pijdPct(v),
    ambang: [40, 67, 80], warna: ["#dc2626", "#f97316", "#86efac", "#166534"],
    teks: ["Mantap < 40%", "Mantap 40–<67%", "Mantap 67–<80%", "Mantap ≥ 80%"],
  },
  alokasi_tipikal: {
    kolom: "Rp M/km", label: "Alokasi tipikal (Σ alokasi ÷ Σ panjang)", kelas: "kuartil", fmt: (v) => `${biayaFmt(v)} Rp M/km`,
    warna: ["#dbeafe", "#93c5fd", "#2563eb", "#1e3a8a"],
  },
  kepadatan_jalan: {
    kolom: "km/km²", label: "Kepadatan jalan (Σ panjang ÷ luas)", kelas: "kuartil",
    fmt: (v) => (v == null ? "–" : `${v.toLocaleString("id-ID", { maximumFractionDigits: 3 })} km/km²`),
    warna: ["#fef3c7", "#fdba74", "#d97706", "#78350f"],
  },
  kerapatan_jalan: {
    kolom: "km/1rb jiwa", label: "Kerapatan jalan (Σ panjang ÷ penduduk × 1.000)", kelas: "kuartil",
    fmt: (v) => (v == null ? "–" : `${v.toLocaleString("id-ID", { maximumFractionDigits: 2 })} km/1.000 jiwa`),
    warna: ["#ede9fe", "#c4b5fd", "#8b5cf6", "#4c1d95"],
  },
};

// Batas kuartil (Q1, Q2, Q3) dari nilai non-null -> 4 kelas.
function pijdKuartil(nilai) {
  const v = nilai.filter((x) => x != null && Number.isFinite(x)).sort((a, b) => a - b);
  if (!v.length) return [];
  const q = (p) => {
    const i = (v.length - 1) * p, lo = Math.floor(i), hi = Math.ceil(i);
    return v[lo] + (v[hi] - v[lo]) * (i - lo);
  };
  return [q(0.25), q(0.5), q(0.75)];
}

// Indeks kelas (0..3) utk metrik indikator; -1 = tidak ada data.
function pijdKelasIndikator(m, v, batas) {
  if (v == null) return -1;
  const b = m.kelas === "tetap" ? m.ambang : batas;
  let i = 0;
  while (i < b.length && (m.kelas === "tetap" ? v >= b[i] : v > b[i])) i++;
  return i;
}

function pijdRp(m) {
  if (m == null) return "–";
  return m >= 1000 ? `Rp ${(m / 1000).toLocaleString("id-ID", { maximumFractionDigits: 2 })} T`
    : `Rp ${m.toLocaleString("id-ID", { maximumFractionDigits: 1 })} M`;
}

function pijdPct(v) {
  return v == null ? "–" : `${v.toLocaleString("id-ID", { maximumFractionDigits: 1 })}%`;
}

function pijdLoading(el) {
  el.innerHTML = `<div class="laporan-distribusi-empty"><i class="bi bi-hourglass-split"></i> Memuat...
    <div class="datatable-loading-bar"><span></span></div></div>`;
}

async function pijdFetch(url) {
  const res = await fetch(url);
  const d = await res.json();
  if (!res.ok) throw new Error(d.detail || "Gagal memuat data Program IJD");
  return d;
}

/* ---------------- Tab Peta: Indonesia -> Provinsi -> Kab/Kota ---------------- */

function pijdRamp() {
  return state.mapTheme === "dark" ? PIJD_RAMP_GELAP : PIJD_RAMP_TERANG;
}

function pijdWarnaNol() {
  return state.mapTheme === "dark" ? "#3a4258" : "#d4d8e0";
}

// Batas kelas kuantil dari nilai > 0 (wilayah tanpa kegiatan diwarnai abu-abu
// terpisah, bukan kelas terendah).
function pijdKelas(nilai) {
  const v = nilai.filter((x) => x > 0).sort((a, b) => a - b);
  if (!v.length) return [];
  const batas = [];
  for (let i = 1; i < 5; i++) batas.push(v[Math.min(v.length - 1, Math.floor((i * v.length) / 5))]);
  return [...new Set(batas)];
}

function pijdIndeksKelas(x, batas) {
  let i = 0;
  while (i < batas.length && x > batas[i]) i++;
  return Math.min(i, 4);
}

// Peta tematik: SEMUA label basemap dimatikan (nama kota/provinsi negara tetangga
// beraksara lokal, nama laut, dll. bersaing dgn choropleth). Nama negara digambar
// sendiri oleh pijdLabelNegara() di atas poligon -- label basemap Google selalu
// berada DI BAWAH layer Data, sehingga "Indonesia" tertutup warna provinsi.
function pijdMapStyle() {
  const gelap = state.mapTheme !== "light";
  return mapStyleForTheme(state.mapTheme).concat([
    { elementType: "labels", stylers: [{ visibility: "off" }] },
    { featureType: "administrative.country", elementType: "geometry.stroke",
      stylers: [{ color: gelap ? "#6b7fa8" : "#94a3b8" }, { weight: 1 }] },
  ]);
}

// [nama, lat, lng, utama?] -- titik label diletakkan di laut/daratan yg tidak
// tertutup poligon bila perlu (Indonesia di Laut Jawa).
const PIJD_LABEL_NEGARA = [
  ["INDONESIA", -5.2, 111.2, true], ["Malaysia", 4.2, 101.9], ["Malaysia", 5.0, 117.0], ["Singapura", 1.6, 104.3],
  ["Brunei", 4.9, 114.6], ["Timor Leste", -8.75, 125.9], ["Papua Nugini", -6.4, 144.6], ["Australia", -24, 134],
  ["Filipina", 12.3, 122.6], ["Thailand", 15.6, 101.0], ["Vietnam", 14.2, 108.3], ["Kamboja", 12.6, 104.9],
  ["Laos", 19.6, 102.6], ["Myanmar", 21.0, 96.0], ["Sri Lanka", 7.8, 80.7], ["India", 21.0, 78.5],
  ["Tiongkok", 26.0, 110.0], ["Taiwan", 23.7, 121.0],
];

function pijdLabelNegara() {
  class LabelNegara extends google.maps.OverlayView {
    constructor(teks, pos, utama) {
      super();
      this.pos = new google.maps.LatLng(pos[0], pos[1]);
      this.div = document.createElement("div");
      this.div.className = `pijd-label-negara${utama ? " utama" : ""}`;
      this.div.textContent = teks;
    }
    onAdd() { this.getPanes().floatPane.appendChild(this.div); } // floatPane: di atas layer Data
    draw() {
      const p = this.getProjection().fromLatLngToDivPixel(this.pos);
      if (p) { this.div.style.left = `${p.x}px`; this.div.style.top = `${p.y}px`; }
    }
    onRemove() { this.div.remove(); }
  }
  PIJD_LABEL_NEGARA.forEach(([teks, lat, lng, utama]) => new LabelNegara(teks, [lat, lng], utama).setMap(pijd.map));
}

function pijdInitMap() {
  if (pijd.map) return true;
  if (!window.google?.maps) return false;
  pijd.map = new google.maps.Map(document.getElementById("pijdMap"), {
    center: { lat: -2.5, lng: 118 }, zoom: 5, mapTypeId: "roadmap",
    styles: pijdMapStyle(), disableDefaultUI: true, zoomControl: true,
    gestureHandling: "greedy", clickableIcons: false,
  });
  pijdLabelNegara();
  pijd.tooltip = document.createElement("div");
  pijd.tooltip.className = "pijd-tooltip";
  pijd.tooltip.hidden = true;
  document.getElementById("pijdMap").appendChild(pijd.tooltip);

  pijd.map.data.addListener("mouseover", (e) => {
    pijd.map.data.overrideStyle(e.feature, { strokeWeight: 2.5, strokeColor: "#ffffff", zIndex: 2 });
  });
  pijd.map.data.addListener("mouseout", (e) => {
    pijd.map.data.revertStyle(e.feature);
    pijd.tooltip.hidden = true;
  });
  pijd.map.data.addListener("mousemove", (e) => pijdTooltip(e));
  pijd.map.data.addListener("click", (e) => {
    const kode = e.feature.getProperty("kode");
    if (pijd.level === "provinsi") pijdDrill(kode, e.feature.getProperty("nama"));
    else pijdKegiatan(kode, e.feature.getProperty("nama"));
  });
  return true;
}

function pijdTooltipIndikator(f) {
  const metrik = document.getElementById("pijdMetrik").value;
  const m = PIJD_METRIK[metrik];
  if (!m.kelas) return "";
  const ix = f.getProperty(`indeks_${metrik}`);
  return `<div><b>${escapeHtml(m.label.split(" (")[0])}:</b> ${escapeHtml(m.fmt(f.getProperty(metrik)))}${ix != null
    ? ` · indeks ${ix.toLocaleString("id-ID", { maximumFractionDigits: 2 })}` : ""}</div>`;
}

function pijdTooltip(e) {
  const f = e.feature;
  const box = document.getElementById("pijdMap").getBoundingClientRect();
  const ev = e.domEvent;
  if (!ev) return;
  const n = f.getProperty("n_kegiatan") || 0;
  pijd.tooltip.innerHTML = `<b>${escapeHtml(f.getProperty("nama") || f.getProperty("nama_batas") || "")}</b>
    ${n ? `<div>${pijdRp(f.getProperty("alokasi_m"))} · ${biayaFmt(f.getProperty("panjang_km"))} km</div>
      <div class="hint">${n.toLocaleString("id-ID")} kegiatan${f.getProperty("n_kab") ? ` · ${f.getProperty("n_kab")} kab/kota` : ""}
      ${f.getProperty("rp_per_km_semua") != null ? ` · ${biayaFmt(f.getProperty("rp_per_km_semua"))} Rp M/km` : ""}</div>
      <div class="hint">Klik untuk ${pijd.level === "provinsi" ? "melihat kab/kota" : "melihat daftar kegiatan"}</div>`
    : `<div class="hint">Tidak ada kegiatan IJD pada filter ini</div>`}${pijdTooltipIndikator(f)}`;
  pijd.tooltip.hidden = false;
  let x = ev.clientX - box.left + 14, y = ev.clientY - box.top + 14;
  if (x + 270 > box.width) x -= 290;
  if (y + 90 > box.height) y -= 100;
  pijd.tooltip.style.left = `${x}px`;
  pijd.tooltip.style.top = `${y}px`;
}

async function pijdLoadPeta() {
  const side = document.getElementById("pijdSide");
  pijdLoading(side);
  if (!pijdInitMap()) {
    side.innerHTML = `<div class="laporan-distribusi-empty">Google Maps belum termuat — peta tidak bisa ditampilkan.</div>`;
    return;
  }
  const params = new URLSearchParams({
    level: pijd.level, tahun: document.getElementById("pijdTahun").value,
    kategori: document.getElementById("pijdKategori").value,
  });
  if (pijd.level === "kabupaten") params.set("kode_provinsi", pijd.kodeProv);
  try {
    pijd.data = await pijdFetch(`/api/program-ijd/peta?${params}`);
    pijdGambarPeta(true);
  } catch (err) {
    side.innerHTML = `<div class="laporan-distribusi-empty">${escapeHtml(err.message)}</div>`;
  }
}

function pijdGambarPeta(fit) {
  const d = pijd.data;
  if (!d) return;
  const metrik = document.getElementById("pijdMetrik").value;
  const map = pijd.map;
  map.data.forEach((f) => map.data.remove(f));
  const fitur = map.data.addGeoJson({ type: "FeatureCollection", features: d.features });
  const m = PIJD_METRIK[metrik];
  const warnaNol = pijdWarnaNol();
  if (m.kelas) {
    const batas = m.kelas === "kuartil" ? pijdKuartil(d.wilayah.map((w) => w[metrik])) : m.ambang;
    map.data.setStyle((f) => {
      const k = pijdKelasIndikator(m, f.getProperty(metrik), batas);
      return {
        fillColor: k < 0 ? warnaNol : m.warna[k], fillOpacity: k < 0 ? 0.5 : 0.85,
        strokeColor: state.mapTheme === "dark" ? "#0f1420" : "#ffffff", strokeWeight: 0.8, cursor: "pointer",
      };
    });
    if (fit && fitur.length) {
      const b = new google.maps.LatLngBounds();
      fitur.forEach((f) => f.getGeometry().forEachLatLng((ll) => b.extend(ll)));
      map.fitBounds(b, 10);
    }
    pijdRenderSide(batas, metrik);
    return;
  }
  const batas = pijdKelas(d.features.map((f) => f.properties[metrik] || 0));
  const ramp = pijdRamp();
  map.data.setStyle((f) => {
    const v = f.getProperty(metrik) || 0;
    return {
      fillColor: v > 0 ? ramp[pijdIndeksKelas(v, batas)] : warnaNol,
      fillOpacity: v > 0 ? 0.85 : 0.5,
      strokeColor: state.mapTheme === "dark" ? "#0f1420" : "#ffffff",
      strokeWeight: 0.8, cursor: "pointer",
    };
  });
  if (fit && fitur.length) {
    const b = new google.maps.LatLngBounds();
    fitur.forEach((f) => f.getGeometry().forEachLatLng((ll) => b.extend(ll)));
    map.fitBounds(b, 10);
  }
  pijdRenderSide(batas, metrik);
}

function pijdLegendIndikator(batas, metrik) {
  const m = PIJD_METRIK[metrik];
  const nas = pijd.data?.nasional?.[metrik];
  let teks = m.teks;
  if (m.kelas === "kuartil") {
    teks = batas.length ? [`≤ ${m.fmt(batas[0])} (Q1)`, `${m.fmt(batas[0])} – ${m.fmt(batas[1])} (Q2)`,
      `${m.fmt(batas[1])} – ${m.fmt(batas[2])} (Q3)`, `> ${m.fmt(batas[2])} (Q4)`] : [];
  }
  const rows = teks.map((t, i) => `<div class="pijd-legend-row"><span class="pijd-swatch" style="background:${m.warna[i]}"></span>${escapeHtml(t)}</div>`);
  rows.push(`<div class="pijd-legend-row"><span class="pijd-swatch" style="background:${pijdWarnaNol()}"></span>Tidak ada data</div>`);
  return `<div class="pijd-legend"><div><b>${escapeHtml(m.label)}</b> · ${m.kelas === "kuartil" ? "kelas kuartil wilayah yang tampil" : "ambang kemantapan"}</div>${rows.join("")}
    <div class="hint">Nasional: ${escapeHtml(m.fmt(nas))}. Indeks = nilai wilayah ÷ nasional (1,0 = setara nasional).</div></div>`;
}

function pijdLegend(batas, metrik) {
  if (PIJD_METRIK[metrik].kelas) return pijdLegendIndikator(batas, metrik);
  const fmt = PIJD_METRIK[metrik].fmt;
  const ramp = pijdRamp();
  const rows = [];
  let bawah = null;
  for (let i = 0; i <= batas.length; i++) {
    const atas = batas[i];
    const label = i === 0 ? `≤ ${fmt(atas)}` : atas == null ? `> ${fmt(bawah)}` : `${fmt(bawah)} – ${fmt(atas)}`;
    rows.push(`<div class="pijd-legend-row"><span class="pijd-swatch" style="background:${ramp[i]}"></span>${escapeHtml(label)}</div>`);
    bawah = atas;
  }
  if (!batas.length) rows.length = 0;
  rows.push(`<div class="pijd-legend-row"><span class="pijd-swatch" style="background:${pijdWarnaNol()}"></span>Tidak ada kegiatan</div>`);
  return `<div class="pijd-legend"><div><b>${escapeHtml(PIJD_METRIK[metrik].label)}</b> · kelas kuantil</div>${rows.join("")}</div>`;
}

function pijdRenderSide(batas, metrik) {
  const d = pijd.data;
  const side = document.getElementById("pijdSide");
  const tahun = document.getElementById("pijdTahun").selectedOptions[0].textContent;
  const adaIjd = d.wilayah.filter((w) => w.n_kegiatan > 0).length;
  const unitWil = pijd.level === "provinsi" ? "provinsi" : "kab/kota";
  const crumb = pijd.level === "provinsi"
    ? `<div class="pijd-crumb"><b><i class="bi bi-globe-asia-australia"></i> Indonesia</b></div>`
    : `<div class="pijd-crumb"><button type="button" id="pijdKeIndonesia"><i class="bi bi-globe-asia-australia"></i> Indonesia</button>
        <i class="bi bi-chevron-right"></i><b>${escapeHtml(pijd.namaProv)}</b></div>`;
  const kpis = `<div class="laporan-kpi-row">
    ${laporanKpiTile("Total alokasi", pijdRp(d.total.alokasi_m), tahun)}
    ${laporanKpiTile("Panjang jalan", `${biayaFmt(d.total.panjang_km)} km`, d.total.jembatan_m ? `+ jembatan ${biayaFmt(d.total.jembatan_m)} m` : "")}
    ${laporanKpiTile("Kegiatan", d.total.n_kegiatan.toLocaleString("id-ID"), `${adaIjd} ${unitWil} menerima`)}
  </div>`;
  const mInd = PIJD_METRIK[metrik].kelas ? PIJD_METRIK[metrik] : null;
  const fmtIndeks = (v) => (v == null ? "" : `<div class="hint">indeks ${v.toLocaleString("id-ID", { maximumFractionDigits: 2 })}</div>`);
  const angkaRingkas = (v) => (v == null ? "–" : v.toLocaleString("id-ID", { maximumFractionDigits: metrik === "kepadatan_jalan" ? 3 : 2 }));
  const kolomAkhir = (w) => (mInd ? `${angkaRingkas(w[metrik])}${fmtIndeks(w[`indeks_${metrik}`])}` : biayaFmt(w.rp_per_km_semua));
  const urut = [...d.wilayah].sort((a, b) => (b[metrik] ?? -Infinity) - (a[metrik] ?? -Infinity));
  const rows = urut.map((w) => `<tr class="pijd-row" data-kode="${w.kode}" data-nama="${escapeHtml(w.nama)}">
      <td>${escapeHtml(w.nama)}${w.ada_poligon ? "" : ' <span class="pijd-pill" title="Tidak ada poligon di layer batas wilayah">tanpa peta</span>'}
        ${w.fiskal ? `<div class="hint">Fiskal ${escapeHtml(w.fiskal)}</div>` : ""}</td>
      <td class="num">${w.n_kegiatan ? pijdRp(w.alokasi_m) : "–"}</td>
      <td class="num">${w.n_kegiatan ? biayaFmt(w.panjang_km) : "–"}</td>
      <td class="num">${w.n_kegiatan || "–"}</td>
      <td class="num">${kolomAkhir(w)}</td></tr>`).join("");
  const tp = d.tingkat_provinsi;
  const tpRow = tp ? `<tr class="pijd-row" data-kode="" data-nama="Kegiatan usulan provinsi">
      <td><i>Kegiatan usulan provinsi</i><div class="hint">tanpa kab/kota, tidak diwarnai di peta</div></td>
      <td class="num">${pijdRp(tp.alokasi_m)}</td><td class="num">${biayaFmt(tp.panjang_km)}</td>
      <td class="num">${tp.n_kegiatan}</td><td class="num">–</td></tr>` : "";
  side.innerHTML = crumb + kpis + pijdLegend(batas, metrik) + `
    <div class="laporan-chart-sub">${pijd.level === "provinsi" ? "Klik provinsi (peta atau tabel) untuk turun ke kab/kota."
      : "Klik kab/kota untuk melihat daftar kegiatannya."}</div>
    <div id="pijdSideBody"><table class="pijd-table"><thead><tr><th>${pijd.level === "provinsi" ? "Provinsi" : "Kab/Kota"}</th>
      <th class="num">Alokasi</th><th class="num">km</th><th class="num">Keg.</th>${mInd ? `<th class="num" title="${escapeHtml(mInd.label)}">${escapeHtml(mInd.kolom)}</th>` : '<th class="num" title="Σ alokasi ÷ Σ panjang jalan, termasuk alokasi jembatan">Rp M/km</th>'}</tr></thead>
      <tbody>${tpRow}${rows}</tbody></table></div>
    <p class="hint">${escapeHtml(d.catatan)}</p>`;
  document.getElementById("pijdKeIndonesia")?.addEventListener("click", pijdKeIndonesia);
  side.querySelectorAll(".pijd-row").forEach((tr) => tr.addEventListener("click", () => {
    const kode = tr.dataset.kode ? Number(tr.dataset.kode) : null;
    if (pijd.level === "provinsi") pijdDrill(kode, tr.dataset.nama);
    else pijdKegiatan(kode, tr.dataset.nama);
  }));
}

function pijdDrill(kode, nama) {
  if (!kode) return;
  pijd.level = "kabupaten";
  pijd.kodeProv = kode;
  pijd.namaProv = nama;
  pijdLoadPeta();
}

function pijdKeIndonesia() {
  pijd.level = "provinsi";
  pijd.kodeProv = null;
  pijd.namaProv = "";
  pijdLoadPeta();
}

// Level 3: daftar kegiatan satu kab/kota (kode null = kegiatan usulan provinsi)
async function pijdKegiatan(kode, nama) {
  const body = document.getElementById("pijdSideBody");
  if (!body) return;
  pijdLoading(body);
  const params = new URLSearchParams({
    kode_provinsi: pijd.kodeProv, tahun: document.getElementById("pijdTahun").value,
    kategori: document.getElementById("pijdKategori").value,
  });
  if (kode) params.set("kode_kabupaten", kode);
  try {
    const d = await pijdFetch(`/api/program-ijd/kegiatan?${params}`);
    const rows = d.kegiatan.map((k) => `<tr><td class="num">${k.tahun}</td>
      <td>${escapeHtml(k.nama_kegiatan || "")}<div class="hint">${escapeHtml(k.kategori || "")}${k.tematik ? ` · ${escapeHtml(k.tematik)}` : ""}</div>
        ${k.catatan_data ? `<div class="hint" style="color:var(--warn)"><i class="bi bi-exclamation-triangle"></i> ${escapeHtml(k.catatan_data)}</div>` : ""}</td>
      <td class="num">${biayaFmt(Number(k.panjang_jalan_km))}${Number(k.panjang_jembatan_m) ? `<div class="hint">${biayaFmt(Number(k.panjang_jembatan_m))} m jbt</div>` : ""}</td>
      <td class="num">${biayaFmt(Number(k.alokasi_m))}</td></tr>`).join("");
    body.innerHTML = `<div class="pijd-crumb"><button type="button" id="pijdKembaliTabel"><i class="bi bi-arrow-left"></i> Semua kab/kota</button></div>
      <div class="laporan-chart-title">${escapeHtml(nama)} — ${d.kegiatan.length} kegiatan</div>
      <table class="pijd-table"><thead><tr><th>Tahun</th><th class="num">Kegiatan</th><th class="num">km</th><th class="num">Rp M</th></tr></thead>
      <tbody>${rows || '<tr><td colspan="4">Tidak ada kegiatan pada filter ini.</td></tr>'}</tbody></table>`;
    document.getElementById("pijdKembaliTabel").addEventListener("click", () => pijdGambarPeta(false));
  } catch (err) {
    body.innerHTML = `<div class="laporan-distribusi-empty">${escapeHtml(err.message)}</div>`;
  }
}

/* ---------------- Tab Barat-Timur & Pulau ---------------- */

// Filter "Tahun" bersama utk tab Barat-Timur, Ruas Berulang, Tanpa IJD, Histori
// Kemantapan ("" = gabungan 2023-2026).
function pijdTahunUmum() {
  return document.getElementById("pijdTahunUmum").value;
}
function pijdTahunLabel() {
  return pijdTahunUmum() || "2023–2026";
}

async function pijdLoadRingkasan() {
  const th = pijdTahunUmum();
  pijd.ringkasan = pijd.ringkasan || {};
  if (!pijd.ringkasan[th]) {
    pijd.ringkasan[th] = await pijdFetch(`/api/program-ijd/ringkasan${th ? `?tahun=${th}` : ""}`);
  }
  return pijd.ringkasan[th];
}

async function pijdRenderWilayah() {
  const view = document.getElementById("pijdWilayahView");
  pijdLoading(view);
  try {
    const d = await pijdLoadRingkasan();
    const B = d.wilayah.Barat, T = d.wilayah.Timur;
    const a = B[0], z = B[B.length - 1];
    const kum = (s) => s.reduce((x, t) => x + t.alokasi_t, 0);
    const kumB = kum(B), kumT = kum(T);
    const fmtT = (v) => `Rp ${v.toLocaleString("id-ID", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} T`;
    const tunggal = B.length === 1; // filter satu tahun: tanpa "a → z" dan kolom Δ
    const porsiTile = (nama, s, sub) => laporanKpiTile(tunggal ? `Porsi ${nama} ${a.tahun}` : `Porsi ${nama} ${a.tahun} → ${z.tahun}`,
      tunggal ? pijdPct(s[0].porsi_pct) : `${pijdPct(s[0].porsi_pct)} → ${pijdPct(s[s.length - 1].porsi_pct)}`, sub);
    const kpis = `<div class="laporan-kpi-row">
      ${laporanKpiTile(`Total ${pijdTahunLabel()}`, fmtT(d.total_t), `${d.n_kegiatan.toLocaleString("id-ID")} kegiatan`)}
      ${porsiTile("Barat", B, "Sumatera, Jawa, Bali")}
      ${porsiTile("Timur", T, "Nusa Tenggara, Kalimantan, Sulawesi, Maluku, Papua")}
      ${tunggal ? "" : laporanKpiTile("Kumulatif Barat : Timur", `${pijdPct(Math.round((kumB / (kumB + kumT)) * 1000) / 10)} : ${pijdPct(Math.round((kumT / (kumB + kumT)) * 1000) / 10)}`, fmtT(kumB + kumT))}
    </div>`;
    const thDelta = tunggal ? "" : `<th class="num">Δ ${a.tahun}→${z.tahun}</th>`;
    const stacks = B.map((b, i) => {
      const t = T[i];
      return `<div class="pijd-stack-row"><span>${b.tahun}</span>
        <div class="pijd-stack" title="${b.tahun}: Barat ${fmtT(b.alokasi_t)} (${pijdPct(b.porsi_pct)}) · Timur ${fmtT(t.alokasi_t)} (${pijdPct(t.porsi_pct)})">
          <span style="flex:${b.porsi_pct};background:${PIJD_WARNA_BARAT};color:#fff">Barat ${pijdPct(b.porsi_pct)}</span>
          <span style="flex:${t.porsi_pct};background:${PIJD_WARNA_TIMUR};color:#fff">Timur ${pijdPct(t.porsi_pct)}</span></div></div>`;
    }).join("");
    const legend = `<div style="margin-bottom:8px"><span class="pijd-key"><span class="pijd-swatch" style="background:${PIJD_WARNA_BARAT}"></span>Barat</span>
      <span class="pijd-key"><span class="pijd-swatch" style="background:${PIJD_WARNA_TIMUR}"></span>Timur</span></div>`;
    const tabelWil = `<div class="biaya-tabel-wrap"><table class="biaya-usulan-table"><thead><tr><th>Wilayah</th>
      ${B.map((t) => `<th class="num">${t.tahun}</th>`).join("")}${thDelta}</tr></thead><tbody>
      ${["Barat", "Timur"].map((w) => {
        const s = d.wilayah[w];
        const delta = s[0].alokasi_t ? Math.round((s[s.length - 1].alokasi_t / s[0].alokasi_t - 1) * 1000) / 10 : null;
        return `<tr><td>${w}<div class="hint">kegiatan · km</div></td>${s.map((t) => `<td class="num">${fmtT(t.alokasi_t)}
          <div class="hint">${t.n_kegiatan} · ${t.panjang_km.toLocaleString("id-ID")}</div></td>`).join("")}
          ${tunggal ? "" : `<td class="num">${delta != null ? `${delta > 0 ? "+" : ""}${delta.toLocaleString("id-ID")}%` : "–"}</td>`}</tr>`;
      }).join("")}</tbody></table></div>`;
    const wilHtml = `<div class="laporan-chart-block">
      <div class="laporan-chart-title"><i class="bi bi-compass"></i> Porsi Alokasi Barat–Timur per Tahun</div>
      <div class="laporan-chart-sub">Porsi = alokasi wilayah ÷ total tahun yang sama. Sensitivitas: bila Kalimantan dimasukkan ke Barat,
        porsi Barat ${d.sensitivitas_kalimantan_barat.map((s) => `${s.tahun} ${pijdPct(s.barat_pct)}`).join(" · ")}.</div>
      ${legend}${stacks}${tabelWil}</div>`;

    const pulauBar = laporanHBar([...d.pulau].sort((x, y) => y.total_t - x.total_t).map((p) => ({ ...p, nama: `${p.pulau} (${p.wilayah[0]})` })), {
      valueKey: "total_t",
      maxLabelFn: (p) => `${p.pulau}: ${fmtT(p.total_t)} (${Math.round((p.total_t / d.total_t) * 100)}% total)`,
      barLabelFn: (p) => `${fmtT(p.total_t)} · ${pijdPct(Math.round((p.total_t / d.total_t) * 1000) / 10)}`,
    });
    const pulauRows = d.pulau.map((p) => {
      const s = p.seri;
      const delta = s[0].alokasi_t ? Math.round((s[s.length - 1].alokasi_t / s[0].alokasi_t - 1) * 100) : null;
      return `<tr><td>${escapeHtml(p.pulau)} <span class="pijd-pill">${p.wilayah}</span></td>
        ${s.map((t) => `<td class="num">${t.alokasi_t.toLocaleString("id-ID", { minimumFractionDigits: 2 })}</td>`).join("")}
        ${tunggal ? "" : `<td class="num">${delta != null ? biayaPctBadge(delta) : "–"}</td>`}</tr>`;
    }).join("");
    const pulauHtml = `<div class="laporan-chart-block">
      <div class="laporan-chart-title"><i class="bi bi-bar-chart"></i> Alokasi per Pulau</div>
      <div class="laporan-chart-sub">Total ${pijdTahunLabel()} (B = Barat, T = Timur); tabel dalam Rp triliun${tunggal ? "" : " per tahun"}</div>
      ${pulauBar}
      <div class="biaya-tabel-wrap"><table class="biaya-usulan-table"><thead><tr><th>Pulau</th>${B.map((t) => `<th class="num">${t.tahun}</th>`).join("")}
        ${thDelta}</tr></thead><tbody>${pulauRows}</tbody></table></div></div>`;
    view.innerHTML = kpis + wilHtml + pulauHtml + `<p class="hint">${escapeHtml(d.catatan)}</p>`;
  } catch (err) {
    view.innerHTML = `<div class="laporan-distribusi-empty">${escapeHtml(err.message)}</div>`;
  }
}

/* ---------------- Tab Ruas Berulang ---------------- */

async function pijdRenderBerulang() {
  const view = document.getElementById("pijdBerulangView");
  pijdLoading(view);
  try {
    const r = await pijdLoadRingkasan();
    const d = r.ruas_berulang;
    const pf = d.per_frekuensi, bt = d.berturut;
    const kpis = `<div class="laporan-kpi-row">
      ${laporanKpiTile("Ruas Dialokasikan ≥ 2 Tahun", d.n.toLocaleString("id-ID"), `4×: ${pf[4]} · 3×: ${pf[3]} · 2×: ${pf[2]}`)}
      ${laporanKpiTile(pijdTahunUmum() ? `Alokasi ${pijdTahunUmum()} Ruas Berulang` : "Alokasi Ruas Berulang",
        `Rp ${d.alokasi_t.toLocaleString("id-ID")} T`, `${pijdPct(d.porsi_pct)} dari total ${pijdTahunLabel()}`)}
      ${laporanKpiTile("Berturut-turut", `${bt[4] + bt[3] + bt[2]} / ${d.n}`, `tanpa jeda tahun (4×: ${bt[4]}, 3×: ${bt[3]}, 2×: ${bt[2]})`)}
    </div>`;
    const tot = d.silang_fiskal.reduce((s, r) => s + r["4"] + r["3"] + r["2"], 0);
    const silang = d.silang_fiskal.filter((r) => r.fiskal !== "Tidak ada data" || r["4"] + r["3"] + r["2"]).map((r) => {
      const n = r["4"] + r["3"] + r["2"];
      return `<tr><td>${escapeHtml(r.fiskal)}</td><td class="num">${r["4"]}</td><td class="num">${r["3"]}</td><td class="num">${r["2"]}</td>
        <td class="num"><b>${n}</b></td><td class="num">${pijdPct(tot ? Math.round((n / tot) * 1000) / 10 : 0)}</td></tr>`;
    }).join("");
    const silangHtml = `<div class="laporan-chart-block">
      <div class="laporan-chart-title"><i class="bi bi-grid-3x3"></i> Frekuensi × Kapasitas Fiskal Daerah (jumlah ruas)</div>
      <div class="laporan-chart-sub">Fiskal kab/kota pengusul (kegiatan usulan provinsi: fiskal provinsi), kategori SITIA</div>
      <div class="biaya-tabel-wrap"><table class="biaya-usulan-table"><thead><tr><th>Fiskal daerah</th><th class="num">4 kali</th><th class="num">3 kali</th>
        <th class="num">2 kali</th><th class="num">Total</th><th class="num">% total</th></tr></thead><tbody>${silang}</tbody></table></div></div>`;
    pijd.berulang = d.daftar;
    const daftarHtml = `<div class="laporan-chart-block">
      <div class="laporan-chart-title"><i class="bi bi-list-ol"></i> Daftar Ruas Berulang</div>
      ${pijdTahunUmum() ? `<div class="laporan-chart-sub">Ruas yang dialokasikan pada ${pijdTahunUmum()} dan juga pada tahun lain;
        frekuensi & kolom Total dihitung atas 2023–2026.</div>` : ""}
      <div class="biaya-filter-row" style="padding:0 0 8px;border:0"><label>Frekuensi
        <select id="pijdBerulangFrek"><option value="3">≥ 3 kali</option><option value="4">4 kali</option>
        <option value="2">Semua (≥ 2 kali)</option></select></label></div>
      <div id="pijdBerulangTabel"></div></div>`;
    view.innerHTML = kpis + silangHtml + daftarHtml + `<p class="hint">${escapeHtml(r.catatan)}</p>`;
    const sel = document.getElementById("pijdBerulangFrek");
    sel.addEventListener("change", pijdRenderBerulangTabel);
    pijdRenderBerulangTabel();
  } catch (err) {
    view.innerHTML = `<div class="laporan-distribusi-empty">${escapeHtml(err.message)}</div>`;
  }
}

function pijdRenderBerulangTabel() {
  const min = Number(document.getElementById("pijdBerulangFrek").value);
  const daftar = pijd.berulang.filter((b) => (min === 4 ? b.frekuensi === 4 : b.frekuensi >= min));
  const rows = daftar.map((b) => `<tr><td>${escapeHtml(b.nama_kegiatan)}<div class="hint">${escapeHtml(b.kategori.join(", "))}</div></td>
    <td>${escapeHtml(b.kab_kota || "")}<div class="hint">${escapeHtml(b.provinsi || "")}</div></td>
    <td>${b.tahun.map((t) => `<span class="pijd-pill">${t}</span>`).join("")}${b.berturut ? "" : '<div class="hint">ada jeda tahun</div>'}</td>
    <td>${escapeHtml(b.fiskal)}</td><td class="num">${biayaFmt(b.total_alokasi_m)}</td></tr>`).join("");
  document.getElementById("pijdBerulangTabel").innerHTML = `<div class="biaya-tabel-wrap"><table class="biaya-usulan-table">
    <thead><tr><th>Kegiatan (nama terakhir)</th><th>Kab/Kota</th><th>Tahun</th><th>Fiskal</th><th class="num">Total 2023–2026 (Rp M)</th></tr></thead>
    <tbody>${rows || '<tr><td colspan="5">Tidak ada.</td></tr>'}</tbody></table></div>
    <p class="hint">${daftar.length} ruas. Perlu ditelaah apakah pendanaan berulang adalah penanganan bertahap yang direncanakan atau penanganan yang tidak bertahan.</p>`;
}

/* ---------------- Tab Kab/Kota Tanpa IJD ---------------- */

async function pijdRenderNihil() {
  const view = document.getElementById("pijdNihilView");
  pijdLoading(view);
  try {
    const r = await pijdLoadRingkasan();
    const d = r.tanpa_ijd;
    const n = d.daftar.length;
    const kuat = d.daftar.filter((k) => k.fiskal === "Tinggi" || k.fiskal === "Sangat Tinggi").length;
    const kpis = `<div class="laporan-kpi-row">
      ${laporanKpiTile(`Kab/Kota Tanpa IJD ${pijdTahunLabel()}`, `${n} dari ${d.n_kab_lingkup}`, "DKI Jakarta di luar lingkup")}
      ${laporanKpiTile("Berfiskal Tinggi / Sangat Tinggi", `${kuat} (${pijdPct(n ? Math.round((kuat / n) * 1000) / 10 : 0)})`, "kapasitas fiskal relatif kuat")}
      ${laporanKpiTile("Berfiskal Rendah / Sangat Rendah", d.daftar.filter((k) => /Rendah/.test(k.fiskal)).length, "patut dicermati penyebabnya")}
    </div>`;
    const pct = d.per_fiskal.filter((f) => f.n_kab).map((f) => ({ ...f, nama: `${f.fiskal} (${f.n_nihil}/${f.n_kab})`, pct: Math.round((f.n_nihil / f.n_kab) * 1000) / 10 }));
    const barHtml = `<div class="laporan-chart-block">
      <div class="laporan-chart-title"><i class="bi bi-bar-chart"></i> Persentase Kab/Kota Tanpa IJD di Tiap Kategori Fiskal</div>
      <div class="laporan-chart-sub">jumlah tanpa IJD ÷ jumlah kab/kota pada kategori itu</div>
      ${laporanHBar(pct, { valueKey: "pct", maxLabelFn: (f) => `${f.fiskal}: ${f.n_nihil} dari ${f.n_kab}`, barLabelFn: (f) => `${f.pct.toLocaleString("id-ID")}%` })}</div>`;
    const rows = d.daftar.map((k) => `<tr><td>${escapeHtml(k.kab_kota)}</td><td>${escapeHtml(k.provinsi)}</td><td>${escapeHtml(k.fiskal)}</td></tr>`).join("");
    const tabel = `<div class="laporan-chart-block">
      <div class="laporan-chart-title"><i class="bi bi-list-ul"></i> Daftar (urut kategori fiskal)</div>
      <div class="biaya-tabel-wrap"><table class="biaya-usulan-table"><thead><tr><th>Kab/Kota</th><th>Provinsi</th><th>Fiskal</th></tr></thead>
      <tbody>${rows}</tbody></table></div>
      <p class="hint">Riwayat Program hanya memuat usulan yang DIALOKASIKAN; daerah yang mengusulkan tetapi tidak pernah lolos
        (mis. Kab. Waropen menurut deck) perlu dicek di tab "Riwayat Lolos Kompetensi" pada Tren Biaya Konstruksi.</p></div>`;
    view.innerHTML = kpis + barHtml + tabel + `<p class="hint">${escapeHtml(r.catatan)}</p>`;
  } catch (err) {
    view.innerHTML = `<div class="laporan-distribusi-empty">${escapeHtml(err.message)}</div>`;
  }
}

/* ---------------- Tab Rekap Tahunan ---------------- */

async function pijdRenderRekap() {
  const view = document.getElementById("pijdRekapView");
  pijdLoading(view);
  const tahun = document.getElementById("pijdRekapTahun").value;
  const selProv = document.getElementById("pijdRekapProv");
  const params = new URLSearchParams({ tahun });
  if (selProv.value) params.set("kode_provinsi", selProv.value);
  try {
    const d = await pijdFetch(`/api/program-ijd/rekap?${params}`);
    const dipilih = selProv.value;
    selProv.innerHTML = `<option value="">— pilih provinsi —</option>` + [...d.provinsi]
      .sort((a, b) => (a.kode_provinsi || 0) - (b.kode_provinsi || 0))
      .map((p) => `<option value="${p.kode_provinsi}">${escapeHtml(p.provinsi)}</option>`).join("");
    selProv.value = d.provinsi.some((p) => String(p.kode_provinsi) === dipilih) ? dipilih : "";
    const t = d.total;
    const kpis = `<div class="laporan-kpi-row">
      ${laporanKpiTile("Provinsi", t.n_provinsi, `program ${tahun}`)}
      ${laporanKpiTile("Kab/Kota", t.n_kab, `+ ${t.n_kegiatan_tingkat_provinsi} kegiatan usulan provinsi`)}
      ${laporanKpiTile("Kegiatan", t.n_kegiatan.toLocaleString("id-ID"), "")}
      ${laporanKpiTile("Alokasi", `Rp ${t.alokasi_t.toLocaleString("id-ID")} T`, "")}
      ${laporanKpiTile("Panjang", `${biayaFmt(t.panjang_km)} km`, `jembatan ${biayaFmt(t.jembatan_m)} m`)}
    </div>`;
    const kat = d.kategori.map((k) => `<tr><td>${escapeHtml(k.kategori[0].toUpperCase() + k.kategori.slice(1))}</td><td class="num">${k.n_kegiatan}</td>
      <td class="num">${biayaFmt(k.panjang_km)}</td><td class="num">${biayaFmt(k.jembatan_m)}</td><td class="num">${pijdRp(k.alokasi_m)}</td></tr>`).join("");
    const katHtml = `<div class="laporan-chart-block"><div class="laporan-chart-title"><i class="bi bi-tools"></i> Preservasi vs Pembangunan</div>
      <div class="biaya-tabel-wrap"><table class="biaya-usulan-table"><thead><tr><th>Kategori</th><th class="num">Kegiatan</th><th class="num">Jalan (km)</th>
      <th class="num">Jembatan (m)</th><th class="num">Alokasi</th></tr></thead><tbody>${kat}</tbody></table></div></div>`;
    const temHtml = `<div class="laporan-chart-block"><div class="laporan-chart-title"><i class="bi bi-pie-chart"></i> Komposisi Tematik</div>
      <div class="laporan-chart-sub">Label = alokasi (porsi alokasi) · porsi jumlah kegiatan di tooltip</div>
      ${laporanHBar(d.tematik.map((x) => ({ ...x, nama: x.tematik })), {
        valueKey: "alokasi_m",
        maxLabelFn: (x) => `${x.tematik}: ${x.n_kegiatan} kegiatan (${pijdPct(x.porsi_kegiatan_pct)}) · ${x.detail.map(([k, n]) => `${k} (${n})`).join("; ")}`,
        barLabelFn: (x) => `${pijdRp(x.alokasi_m)} (${pijdPct(x.porsi_alokasi_pct)}) · ${x.n_kegiatan} keg.`,
      })}</div>`;
    const provRows = d.provinsi.map((p) => `<tr><td>${escapeHtml(p.provinsi)}</td><td class="num">${pijdRp(p.alokasi_m)}</td>
      <td class="num">${p.n_kegiatan}</td><td class="num">${p.n_kab}</td><td class="num">${biayaFmt(p.panjang_km)}</td>
      <td class="num">${biayaFmt(p.jembatan_m)}</td><td class="num">${biayaFmt(p.rp_per_km_semua)}</td><td class="num">${biayaFmt(p.rp_per_km_jalan)}</td></tr>`).join("");
    const provHtml = `<div class="laporan-chart-block"><div class="laporan-chart-title"><i class="bi bi-table"></i> Per Provinsi</div>
      <div class="laporan-chart-sub">Rp M/km (semua) = Σ alokasi ÷ Σ km termasuk alokasi jembatan (rumus deck hal. 26);
        (jalan) = hanya kegiatan dengan panjang jalan &gt; 0. Bedanya besar di provinsi dengan banyak jembatan (mis. Jawa Timur).</div>
      <div class="biaya-tabel-wrap"><table class="biaya-usulan-table"><thead><tr><th>Provinsi</th><th class="num">Alokasi</th><th class="num">Kegiatan</th>
      <th>Kab/Kota</th><th class="num">Jalan (km)</th><th class="num">Jembatan (m)</th><th class="num">Rp M/km (semua)</th><th class="num">Rp M/km (jalan)</th></tr></thead>
      <tbody>${provRows}</tbody></table></div></div>`;
    const kabTabel = (judul, xs) => `<div class="laporan-chart-block"><div class="laporan-chart-title">${judul}</div>
      <div class="biaya-tabel-wrap"><table class="biaya-usulan-table"><thead><tr><th>Kab/Kota</th><th>Provinsi</th><th class="num">Kegiatan</th>
      <th class="num">Alokasi (Rp M)</th><th class="num">Jalan (km)</th><th class="num">Jembatan (m)</th></tr></thead><tbody>
      ${xs.map((k) => `<tr><td>${escapeHtml(k.kab_kota || "")}</td><td>${escapeHtml(k.provinsi || "")}</td><td class="num">${k.n_kegiatan}</td>
        <td class="num">${biayaFmt(k.alokasi_m)}</td><td class="num">${biayaFmt(k.panjang_km)}</td><td class="num">${biayaFmt(k.jembatan_m)}</td></tr>`).join("")}
      </tbody></table></div></div>`;
    const anom = d.anomali.length ? `<div class="laporan-chart-block"><div class="laporan-chart-title"><i class="bi bi-exclamation-triangle"></i>
      Catatan Data (${d.anomali.length})</div><div class="laporan-chart-sub">Ditandai importer, tidak dibuang dari total</div>
      <div class="biaya-tabel-wrap"><table class="biaya-usulan-table"><thead><tr><th class="num">Kegiatan</th><th>Kab/Kota</th><th class="num">Rp M</th><th class="num">km</th><th>Catatan</th></tr></thead><tbody>
      ${d.anomali.map((a) => `<tr><td>${escapeHtml(a.nama_kegiatan || "")}</td><td>${escapeHtml(a.kab_kota || "")}<div class="hint">${escapeHtml(a.provinsi || "")}</div></td>
        <td class="num">${biayaFmt(a.alokasi_m)}</td><td class="num">${biayaFmt(a.panjang_km)}</td><td>${escapeHtml(a.catatan || "")}</td></tr>`).join("")}
      </tbody></table></div></div>` : "";
    view.innerHTML = (d.rincian ? pijdRincianProvinsi(d.rincian, tahun) : "") + kpis + katHtml + temHtml + provHtml
      + kabTabel('<i class="bi bi-sort-down"></i> 20 Kab/Kota dengan Kegiatan Terbanyak', d.kab_terbanyak)
      + kabTabel('<i class="bi bi-sort-up"></i> 20 Kab/Kota dengan Kegiatan Paling Sedikit', d.kab_tersedikit)
      + anom + `<p class="hint">${escapeHtml(d.catatan)}</p>`;
  } catch (err) {
    view.innerHTML = `<div class="laporan-distribusi-empty">${escapeHtml(err.message)}</div>`;
  }
}

// Rincian kab/kota satu provinsi (deck hal. 33): alokasi, kegiatan & alokasi
// jalan vs jembatan, rata-rata per kegiatan, komposisi tematik.
function pijdRincianProvinsi(r, tahun) {
  const kab = r.kab;
  const nKeg = kab.reduce((s, k) => s + k.n_kegiatan, 0);
  const alok = kab.reduce((s, k) => s + k.alokasi_m, 0);
  const nJbt = kab.reduce((s, k) => s + k.n_jembatan, 0);
  const kpis = `<div class="laporan-kpi-row">
    ${laporanKpiTile(`Alokasi ${escapeHtml(r.provinsi || "")} ${tahun}`, pijdRp(alok), `${kab.filter((k) => k.kab_kota !== "Kegiatan usulan provinsi").length} kab/kota`)}
    ${laporanKpiTile("Kegiatan", nKeg, `jalan ${nKeg - nJbt} · jembatan ${nJbt}`)}
    ${laporanKpiTile("Rata-rata per kegiatan", pijdRp(nKeg ? alok / nKeg : null), "")}
  </div>`;
  const alokBar = laporanHBar(kab.map((k) => ({ ...k, nama: k.kab_kota })), {
    valueKey: "alokasi_m",
    maxLabelFn: (k) => `${k.kab_kota}: jalan ${pijdRp(k.alokasi_jalan_m)}, jembatan ${pijdRp(k.alokasi_jembatan_m)}`,
    barLabelFn: (k) => `${pijdRp(k.alokasi_m)}${k.alokasi_jembatan_m ? ` (jbt ${pijdRp(k.alokasi_jembatan_m)})` : ""}`,
  });
  const rataBar = laporanHBar([...kab].sort((a, b) => b.rata_per_kegiatan_m - a.rata_per_kegiatan_m).map((k) => ({ ...k, nama: k.kab_kota })), {
    valueKey: "rata_per_kegiatan_m",
    maxLabelFn: (k) => `${k.kab_kota}: ${pijdRp(k.alokasi_m)} ÷ ${k.n_kegiatan} kegiatan`,
    barLabelFn: (k) => `${pijdRp(k.rata_per_kegiatan_m)} · ${k.n_kegiatan} keg.`,
  });
  const temBar = laporanHBar(r.tematik.map((x) => ({ ...x, nama: x.tematik })), {
    valueKey: "n_kegiatan",
    maxLabelFn: (x) => `${x.tematik}: ${x.n_kegiatan} kegiatan`,
    barLabelFn: (x) => `${x.n_kegiatan} keg. (${pijdPct(nKeg ? Math.round((x.n_kegiatan / nKeg) * 1000) / 10 : 0)})`,
  });
  const rows = kab.map((k) => `<tr><td>${escapeHtml(k.kab_kota)}</td>
    <td class="num">${k.n_jalan}</td><td class="num">${k.n_jembatan}</td>
    <td class="num">${biayaFmt(k.alokasi_jalan_m)}</td><td class="num">${biayaFmt(k.alokasi_jembatan_m)}</td>
    <td class="num">${biayaFmt(k.rata_per_kegiatan_m)}</td>
    <td>${k.tematik.map(([t, n]) => `<span class="pijd-pill">${escapeHtml(t)} ${n}</span>`).join("")}</td></tr>`).join("");
  const blok = (ikon, judul, isi, sub = "") => `<div class="laporan-chart-block"><div class="laporan-chart-title"><i class="bi ${ikon}"></i> ${judul}</div>
    ${sub ? `<div class="laporan-chart-sub">${sub}</div>` : ""}${isi}</div>`;
  return `<div class="pijd-rincian">
    <div class="laporan-chart-title" style="font-size:14px;margin-bottom:8px"><i class="bi bi-geo-alt"></i> Rincian Kabupaten/Kota — ${escapeHtml(r.provinsi || "")} ${tahun}</div>
    ${kpis}
    ${blok("bi-bar-chart", "Total Alokasi per Kabupaten/Kota", alokBar, "Label = total; bagian jembatan dalam kurung")}
    ${blok("bi-calculator", "Rata-rata Alokasi per Kegiatan", rataBar)}
    ${blok("bi-pie-chart", "Komposisi Tematik (Jumlah Kegiatan)", temBar)}
    ${blok("bi-table", "Kegiatan dan Alokasi: Jalan vs Jembatan", `<div class="biaya-tabel-wrap"><table class="biaya-usulan-table"><thead><tr>
      <th>Kab/Kota</th><th class="num">Keg. jalan</th><th class="num">Keg. jembatan</th><th class="num">Alokasi jalan (Rp M)</th>
      <th class="num">Alokasi jembatan (Rp M)</th><th class="num">Rata-rata/keg. (Rp M)</th><th>Tematik</th></tr></thead><tbody>${rows}</tbody></table></div>`,
      "Kegiatan jembatan = kegiatan dengan panjang jembatan &gt; 0 (di sumber tidak pernah bersamaan dengan panjang jalan)")}
    </div><hr class="pijd-sep">`;
}

/* ---------------- Tab Histori Kemantapan (deck hal. 2, Tahap 3) ---------------- */

// Badge Δ poin % mantap: naik = membaik (hijau), turun = memburuk (merah) --
// kebalikan biayaPctBadge, di mana naik = biaya lebih mahal.
function pijdDeltaBadge(d) {
  if (d == null) return "–";
  const cls = d >= pijd.kemantapan.ambang_poin ? "naik" : d <= -pijd.kemantapan.ambang_poin ? "turun" : "tetap";
  return `<span class="pijd-delta ${cls}">${d > 0 ? "+" : ""}${d.toLocaleString("id-ID")} poin</span>`;
}

function pijdArahStack(g) {
  if (!g.n) return '<div class="hint">Tidak ada ruas.</div>';
  const seg = (n, cls, label) => n ? `<span class="pijd-arah-${cls}" style="flex:${n}" title="${label}: ${n} ruas">${label} ${n}</span>` : "";
  return `<div class="pijd-stack">${seg(g.naik, "naik", "Membaik")}${seg(g.tetap, "tetap", "Tetap")}${seg(g.turun, "turun", "Memburuk")}</div>`;
}

async function pijdRenderKemantapan() {
  const view = document.getElementById("pijdKemantapanView");
  pijdLoading(view);
  try {
    const d = pijd.kemantapan || (pijd.kemantapan = await pijdFetch("/api/usulan-riwayat/kemantapan"));
    // Filter tahun (client-side): KPI & tabel provinsi hanya tahun itu; perubahan &
    // daftar = ruas teramati ≥ 2 tahun yang salah satu pengamatannya tahun itu.
    const thPilih = pijdTahunUmum();
    if (thPilih && !d.tahun.includes(Number(thPilih))) {
      view.innerHTML = `<div class="laporan-distribusi-empty">Tidak ada data kondisi untuk ${thPilih}: ekspor SITIA ${thPilih}
        tidak memuat kolom kondisi, histori dimulai ${d.tahun[0]}.</div>`;
      return;
    }
    const pakaiTh = (t) => !thPilih || Number(t) === Number(thPilih);
    pijd.kmtDaftar = thPilih ? d.daftar.filter((x) => x.pct_mantap[thPilih] != null) : d.daftar;
    const nas = d.nasional.filter((t) => pakaiTh(t.tahun));
    const kpis = `<div class="laporan-kpi-row">
      ${nas.map((t) => laporanKpiTile(`% Mantap ${t.tahun}`, pijdPct(t.pct_mantap),
        `${t.n_ruas.toLocaleString("id-ID")} ruas usulan · ${biayaFmt(t.panjang_km)} km`)).join("")}
      ${laporanKpiTile("Ruas teramati ≥ 2 tahun", pijd.kmtDaftar.length.toLocaleString("id-ID"),
        thPilih ? `termasuk pengamatan ${thPilih}` : "dasar perbandingan perubahan")}
    </div>`;
    const kelompok = (xs) => {
      const ds = xs.map((x) => x.delta_poin).sort((a, b) => a - b);
      const n = ds.length;
      return { n, naik: xs.filter((x) => x.arah === "naik").length, tetap: xs.filter((x) => x.arah === "tetap").length,
        turun: xs.filter((x) => x.arah === "turun").length,
        median_delta: n ? Math.round(((ds[(n - 1) >> 1] + ds[n >> 1]) / 2) * 10) / 10 : null };
    };
    const kel = (judul, g) => `<div class="pijd-stack-row pijd-arah-row"><span>${judul}<div class="hint">${g.n} ruas · median ${pijdDeltaBadge(g.median_delta)}</div></span>
      ${pijdArahStack(g)}</div>`;
    const p = thPilih
      ? { didanai: kelompok(pijd.kmtDaftar.filter((x) => x.didanai_di_antara)),
          tidak_didanai: kelompok(pijd.kmtDaftar.filter((x) => !x.didanai_di_antara)) }
      : d.perubahan;
    const arahHtml = `<div class="laporan-chart-block">
      <div class="laporan-chart-title"><i class="bi bi-arrow-down-up"></i> Perubahan % Mantap Ruas yang Sama: Didanai IJD vs Tidak</div>
      <div class="laporan-chart-sub">Selisih % mantap tahun pengamatan terakhir − pertama. Membaik/memburuk = berubah ≥ ${d.ambang_poin} poin.
        "Didanai" = dapat IJD pada tahun pertama s.d. sebelum tahun terakhir pengamatan.</div>
      <div style="margin-bottom:8px"><span class="pijd-key"><span class="pijd-swatch pijd-arah-naik"></span>Membaik</span>
        <span class="pijd-key"><span class="pijd-swatch pijd-arah-tetap"></span>Tetap</span>
        <span class="pijd-key"><span class="pijd-swatch pijd-arah-turun"></span>Memburuk</span></div>
      ${kel("Didanai IJD", p.didanai)}${kel("Tidak didanai", p.tidak_didanai)}</div>`;
    const th = d.tahun.filter(pakaiTh);
    const provRows = d.provinsi.map((pr) => {
      const s = pr.seri.filter((t) => pakaiTh(t.tahun));
      return `<tr><td>${escapeHtml(pr.provinsi)}</td>${s.map((t) => `<td class="num">${pijdPct(t.pct_mantap)}<div class="hint">${t.n_ruas} ruas</div></td>`).join("")}</tr>`;
    }).join("");
    const nasRow = `<tr><td><b>Nasional</b></td>${nas.map((t) => `<td class="num"><b>${pijdPct(t.pct_mantap)}</b><div class="hint">${t.n_ruas} ruas</div></td>`).join("")}</tr>`;
    const provHtml = `<div class="laporan-chart-block">
      <div class="laporan-chart-title"><i class="bi bi-table"></i> % Mantap Ruas Usulan per Provinsi</div>
      <div class="laporan-chart-sub">Σ (baik + sedang) ÷ Σ panjang ruas, atas ruas yang diusulkan pada tahun itu. Himpunan ruas berbeda tiap tahun,
        jadi baris ini menggambarkan kondisi ruas yang diusulkan, bukan perubahan ruas yang sama.</div>
      <div class="biaya-tabel-wrap"><table class="biaya-usulan-table"><thead><tr><th>Provinsi</th>
        ${th.map((t) => `<th class="num">${t}</th>`).join("")}</tr></thead><tbody>${nasRow}${provRows}</tbody></table></div></div>`;
    const daftarHtml = `<div class="laporan-chart-block">
      <div class="laporan-chart-title"><i class="bi bi-list-ol"></i> Daftar Ruas Teramati ≥ 2 Tahun</div>
      <div class="biaya-filter-row" style="padding:0 0 8px;border:0">
        <label>Pendanaan <select id="pijdKmtDana"><option value="ya">Didanai IJD</option><option value="tidak">Tidak didanai</option>
          <option value="semua">Semua</option></select></label>
        <label>Arah <select id="pijdKmtArah"><option value="semua">Semua</option><option value="turun">Memburuk</option>
          <option value="tetap">Tetap</option><option value="naik">Membaik</option></select></label>
        <label>Provinsi <select id="pijdKmtProv"><option value="">Semua</option>
          ${d.provinsi.map((pr) => `<option>${escapeHtml(pr.provinsi)}</option>`).join("")}</select></label>
      </div>
      <div id="pijdKmtTabel"></div></div>`;
    view.innerHTML = kpis + arahHtml + provHtml + daftarHtml + `<p class="hint">${escapeHtml(d.catatan)}</p>`;
    ["pijdKmtDana", "pijdKmtArah", "pijdKmtProv"].forEach((id) =>
      document.getElementById(id).addEventListener("change", pijdRenderKemantapanTabel));
    pijdRenderKemantapanTabel();
  } catch (err) {
    view.innerHTML = `<div class="laporan-distribusi-empty">${escapeHtml(err.message)}</div>`;
  }
}

function pijdRenderKemantapanTabel() {
  const d = pijd.kemantapan;
  const dana = document.getElementById("pijdKmtDana").value;
  const arah = document.getElementById("pijdKmtArah").value;
  const prov = document.getElementById("pijdKmtProv").value;
  const xs = pijd.kmtDaftar.filter((x) => (dana === "semua" || x.didanai_di_antara === (dana === "ya"))
    && (arah === "semua" || x.arah === arah) && (!prov || x.provinsi === prov));
  const BATAS = 300;
  const rows = xs.slice(0, BATAS).map((x) => `<tr><td>${escapeHtml(x.nama_ruas || "")}<div class="hint">${escapeHtml(x.status_ruas || "")} · ${biayaFmt(x.panjang_ruas_km)} km</div></td>
    <td>${escapeHtml(x.kabupaten_kota || "")}<div class="hint">${escapeHtml(x.provinsi || "")}</div></td>
    ${d.tahun.map((t) => `<td class="num">${x.pct_mantap[t] != null ? pijdPct(x.pct_mantap[t]) : "–"}</td>`).join("")}
    <td class="num">${pijdDeltaBadge(x.delta_poin)}</td>
    <td>${x.tahun_didanai.length ? x.tahun_didanai.map((t) => `<span class="pijd-pill">${t}</span>`).join("") : "–"}</td></tr>`).join("");
  document.getElementById("pijdKmtTabel").innerHTML = `<div class="biaya-tabel-wrap"><table class="biaya-usulan-table">
    <thead><tr><th>Ruas</th><th>Kab/Kota</th>${d.tahun.map((t) => `<th class="num">${t}</th>`).join("")}<th class="num">Δ</th><th>Tahun didanai</th></tr></thead>
    <tbody>${rows || `<tr><td colspan="${d.tahun.length + 4}">Tidak ada.</td></tr>`}</tbody></table></div>
    <p class="hint">${xs.length.toLocaleString("id-ID")} ruas${xs.length > BATAS ? `, ditampilkan ${BATAS} pertama (urut Δ terendah)` : ""}.
      Ruas yang didanai tetapi memburuk perlu ditelaah: penanganan belum bertahan, segmen lain dari ruas yang sama, atau isian kondisi tidak konsisten.</p>`;
}

/* ---------------- Tab & binding ---------------- */

const PIJD_TAB_TAHUN_UMUM = ["wilayah", "berulang", "nihil", "kemantapan"];

// Ganti tahun: render ulang tab aktif, tab lain dimuat ulang saat dibuka.
function pijdGantiTahunUmum() {
  PIJD_TAB_TAHUN_UMUM.forEach((t) => { pijd.dimuat[t] = false; });
  if (PIJD_TAB_TAHUN_UMUM.includes(pijd.tab)) pijdSetTab(pijd.tab);
}

function pijdSetTab(tab) {
  document.querySelectorAll("[data-pijd-tab]").forEach((b) => b.classList.toggle("active", b.dataset.pijdTab === tab));
  document.getElementById("pijdPetaFilter").hidden = tab !== "peta";
  document.getElementById("pijdPetaView").hidden = tab !== "peta";
  document.getElementById("pijdRekapFilter").hidden = tab !== "rekap";
  document.getElementById("pijdUmumFilter").hidden = !PIJD_TAB_TAHUN_UMUM.includes(tab);
  pijd.tab = tab;
  const views = { wilayah: pijdRenderWilayah, berulang: pijdRenderBerulang, nihil: pijdRenderNihil, rekap: pijdRenderRekap,
    kemantapan: pijdRenderKemantapan };
  for (const t of Object.keys(views)) {
    document.getElementById(`pijd${t[0].toUpperCase()}${t.slice(1)}View`).hidden = tab !== t;
  }
  if (views[tab] && !pijd.dimuat[tab]) {
    pijd.dimuat[tab] = true;
    views[tab]();
  }
}

function bindProgramIjd() {
  const overlay = document.getElementById("programIjdOverlay");
  if (!overlay) return;
  const tutup = () => (overlay.hidden = true);
  document.getElementById("btnProgramIjd").addEventListener("click", () => {
    overlay.hidden = false;
    if (!pijd.data) pijdLoadPeta();
  });
  document.querySelectorAll("[data-pijd-tab]").forEach((b) => b.addEventListener("click", () => pijdSetTab(b.dataset.pijdTab)));
  document.getElementById("pijdTahun").addEventListener("change", pijdLoadPeta);
  document.getElementById("pijdKategori").addEventListener("change", pijdLoadPeta);
  document.getElementById("pijdMetrik").addEventListener("change", () => pijdGambarPeta(false));
  document.getElementById("pijdRekapTahun").addEventListener("change", pijdRenderRekap);
  document.getElementById("pijdRekapProv").addEventListener("change", pijdRenderRekap);
  document.getElementById("pijdTahunUmum").addEventListener("change", pijdGantiTahunUmum);
  document.getElementById("programIjdClose").addEventListener("click", tutup);
  overlay.addEventListener("click", (e) => { if (e.target === overlay) tutup(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !overlay.hidden) tutup(); });
}

document.addEventListener("DOMContentLoaded", bindProgramIjd);
