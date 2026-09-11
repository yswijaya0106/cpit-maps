/* The Next - SiJalan — panel "Skor Urgensitas Penanganan Pelabuhan" (DRAF).
   Fase 1 dari kerangka "Kerangka berpikir lAUT (1).pptx"
   (docs/kajian_implementasi_skor_urgensi_pelabuhan_laut.md), bobot
   antar-parameter MASIH PLACEHOLDER sama rata -- lihat catatan dari
   backend (data.catatan) yang ditampilkan apa adanya di panel ini, jangan
   dihilangkan/diringkas supaya user tidak salah kira ini skor resmi.

   Dataset (pelabuhan_daerah, ~670 pelabuhan laut PP/PR/PL) diambil SEKALI
   saat panel dibuka lalu difilter provinsi di sisi klien -- beda dari
   panel preview IJD (usulan-inpres.js) yang pagination server-side krn
   ~3.000 baris + banyak kolom; di sini jumlah baris jauh lebih kecil dan
   kolomnya ringkas, jadi filter client-side lebih sederhana tanpa
   round-trip server tiap ganti provinsi. */

let pelabuhanUrgensiSemua = [];

async function pelabuhanUrgensiFetch() {
  const scroll = document.getElementById("pelabuhanUrgensiScroll");
  scroll.innerHTML = `
    <div class="datatable-loading">
      <i class="bi bi-hourglass-split"></i> Menghitung skor...
      <div class="datatable-loading-bar"><span></span></div>
    </div>
  `;
  try {
    const res = await fetch("/api/pelabuhan/urgensi-score/preview");
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Gagal memuat skor urgensi pelabuhan");
    pelabuhanUrgensiSemua = data.rows;
    document.getElementById("pelabuhanUrgensiCatatan").innerHTML =
      `<i class="bi bi-exclamation-triangle"></i> ${escapeHtml(data.catatan)}`;
    pelabuhanUrgensiPopulateProvinsi();
    pelabuhanUrgensiRender();
  } catch (err) {
    scroll.innerHTML = `<div class="datatable-loading">${escapeHtml(err.message)}</div>`;
  }
}

function pelabuhanUrgensiPopulateProvinsi() {
  const sel = document.getElementById("pelabuhanUrgensiProvinsi");
  if (sel.dataset.filled) return; // isi sekali saja, provinsi tidak berubah antar fetch
  const provinsiUnik = [...new Set(pelabuhanUrgensiSemua.map((r) => r.provinsi))].sort((a, b) => a.localeCompare(b, "id"));
  for (const p of provinsiUnik) {
    const opt = document.createElement("option");
    opt.value = p;
    opt.textContent = p;
    sel.appendChild(opt);
  }
  sel.dataset.filled = "1";
}

// Kolom tabel preview -- sengaja SAMA PERSIS strukturnya dgn kolom export
// xlsx (PELABUHAN_URGENSI_EXPORT_KOLOM di app.py), MINUS 4 kolom rincian
// kondisi jalan per-kategori (baik/sedang/ringan/berat km) -- sudah
// terwakili oleh "% Mantap", dan di UI kolom sebanyak export (30) bikin
// tabel terlalu lebar utk dibaca; rincian per-kategori itu tetap ada di
// xlsx utk analisis lebih dalam. Kolom "prosa" (wilayah tercakup) dipotong
// dgn tooltip penuh, pola sama sel Narasi AI di preview IJD.
const PELABUHAN_URGENSI_KOLOM = [
  ["Nama Pelabuhan", "nama_pelabuhan", "text"],
  ["Provinsi", "provinsi", "text"],
  ["Kab/Kota", "kabupaten_kota", "text"],
  ["Hirarki", "hirarki_kode", "text"],
  ["Pelabuhan Sehirarki Terdekat", "kedekatan_pelabuhan_terdekat", "text"],
  ["Jarak Terdekat (km)", "kedekatan_jarak_km", "num"],
  ["Ambang Hirarki (km)", "kedekatan_ambang_km", "num"],
  ["Skor Kedekatan", "kedekatan_skor", "num"],
  ["Klasifikasi 3TP", "tiga_tp_kategori", "text"],
  ["Program 3TP", "tiga_tp_program", "prosa"],
  ["Skor 3TP", "tiga_tp_skor", "num"],
  ["RIPN", "ripn", "text"],
  ["Skor Kawasan Strategis", "kawasan_strategis_skor", "num"],
  ["Radius Penduduk (km)", "penduduk_radius_km", "num"],
  ["Wilayah Tercakup", "penduduk_wilayah_tercakup", "prosa"],
  ["Total Penduduk", "penduduk_total", "num"],
  ["Skor Penduduk", "penduduk_skor", "num"],
  ["Ruas IJD Terdekat", "akses_ruas", "text"],
  ["Jarak ke Ruas (km)", "akses_jarak_ruas_km", "num"],
  ["% Mantap Ruas", "akses_pct_mantap", "num"],
  ["Lebar Jalan Ruas (m)", "akses_lebar_jalan_m", "num"],
  ["Skor Akses", "akses_skor", "num"],
  ["Kelengkapan", "kelengkapan", "badge"],
  ["Skor Total (0-100)", "skor_total_0_100", "num"],
];

function pelabuhanUrgensiRender() {
  const provinsi = document.getElementById("pelabuhanUrgensiProvinsi").value;
  const rows = provinsi ? pelabuhanUrgensiSemua.filter((r) => r.provinsi === provinsi) : pelabuhanUrgensiSemua;

  document.getElementById("pelabuhanUrgensiMeta").textContent = `${rows.length.toLocaleString("id-ID")} pelabuhan`;

  const kelengkapanBadge = (k) => {
    const [n] = k.split("/").map(Number);
    const cls = n >= 4 ? "usulan-badge-ok" : "usulan-badge-warn";
    return `<span class="usulan-badge ${cls}">${escapeHtml(k)}</span>`;
  };
  const cell = (v, tipe) => {
    if (v === null || v === undefined || v === "") return '<td class="null">—</td>';
    if (tipe === "num") return `<td class="num">${Number(v).toLocaleString("id-ID")}</td>`;
    if (tipe === "badge") return `<td>${kelengkapanBadge(v)}</td>`;
    // "prosa": daftar "Nama : Angka" satu per baris (dipisah "\n" dari backend,
    // lihat _pelabuhan_urgensi_row_detail) -- ditampilkan UTUH per baris
    // pakai <br>, bukan dipotong+tooltip, supaya rincian wilayah/program
    // langsung kebaca tanpa hover.
    if (tipe === "prosa") return `<td class="checklist-cell"><div>${String(v).split("\n").map((line) => escapeHtml(line)).join("<br>")}</div></td>`;
    return `<td>${escapeHtml(String(v))}</td>`;
  };

  const head = PELABUHAN_URGENSI_KOLOM.map(([label]) => `<th>${escapeHtml(label)}</th>`).join("");
  const body = rows.map((r) => `<tr>${PELABUHAN_URGENSI_KOLOM.map(([, key, tipe]) => cell(r[key], tipe)).join("")}</tr>`).join("");

  document.getElementById("pelabuhanUrgensiScroll").innerHTML = `
    <table class="datatable">
      <thead><tr>${head}</tr></thead>
      <tbody>${body}</tbody>
    </table>
  `;
}

function bindPelabuhanUrgensi() {
  const overlay = document.getElementById("pelabuhanUrgensiOverlay");
  document.getElementById("btnUrgensiPelabuhan").addEventListener("click", () => {
    overlay.hidden = false;
    pelabuhanUrgensiFetch();
  });
  document.getElementById("pelabuhanUrgensiClose").addEventListener("click", () => (overlay.hidden = true));
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) overlay.hidden = true;
  });
  document.getElementById("pelabuhanUrgensiProvinsi").addEventListener("change", pelabuhanUrgensiRender);
  document.getElementById("pelabuhanUrgensiExport").addEventListener("click", () => {
    const provinsi = document.getElementById("pelabuhanUrgensiProvinsi").value;
    const params = provinsi ? `?provinsi=${encodeURIComponent(provinsi)}` : "";
    window.location.href = `/api/pelabuhan/urgensi-score/export/xlsx${params}`;
  });
}

document.addEventListener("DOMContentLoaded", bindPelabuhanUrgensi);
