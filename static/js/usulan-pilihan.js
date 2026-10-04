/* --- Ringkasan & identitas usulan multi-select (4 Okt 2026) -----------------
   Pelengkap multi-select usulan IJD di usulan-inpres.js (usulanMulti,
   hapusUsulanMulti, renderUsulanMultiBar). Dipanggil lewat satu kait di akhir
   renderUsulanMultiBar(), jadi ikut tersinkron setiap usulan dicentang,
   selesai dimuat, dihapus, atau semua dibersihkan.

   - Ringkasan gabungan di bawah bar "N usulan dipilih": total panjang,
     alokasi, Rp/km, sebaran jenis penanganan & status, kab/kota, peringatan
     usulan bernama sama di kab/kota yang sama, dan daftar bernomor (klik =
     zoom ke usulan itu, x = lepas pilihan).
   - Badge nomor berwarna di tengah garis tiap usulan di peta; nomor yang sama
     muncul di kartu daftar dan di legenda "Layer Aktif".
   - Sorotan silang: hover garis/badge di peta <-> baris ringkasan, kartu
     daftar, dan legenda menebalkan garis & menandai barisnya.
   Nomor = urutan pemilihan; ikut bergeser bila ada pilihan yang dilepas.
   Harus dimuat SESUDAH usulan-inpres.js. */

const usulanPilihan = { marker: new Map(), sorot: null, ringkasTerbuka: true };
const USULAN_PILIHAN_LEGEND_MAKS = 30;

function usulanPilihanNomor() {
  const no = new Map();
  let i = 0;
  usulanMulti.forEach((_, id) => no.set(id, ++i));
  return no;
}

function usulanPilihanNama(u) {
  return u.nama_kegiatan || u.nama_ruas || `#${u.id}`;
}

function usulanPilihanKunciNama(u) {
  const nama = String(u.nama_ruas || u.nama_kegiatan || "").toUpperCase()
    .replace(/^(PENINGKATAN|PEMBANGUNAN|PRESERVASI|REKONSTRUKSI|PERBAIKAN|REHABILITASI|PELEBARAN)\s+(JALAN|JL\.?|RUAS)?\s*/, "")
    .replace(/[^A-Z0-9]/g, "");
  return `${String(u.kabupaten_kota || "").toUpperCase()}|${nama}`;
}

function usulanPilihanBadgeIcon(no, warna) {
  const r = no >= 100 ? 13 : 11;
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${r * 2 + 4}" height="${r * 2 + 4}">
    <circle cx="${r + 2}" cy="${r + 2}" r="${r}" fill="${warna}" stroke="#ffffff" stroke-width="2"/>
    <text x="${r + 2}" y="${r + 6}" text-anchor="middle" font-family="Inter,Arial,sans-serif"
      font-size="${no >= 100 ? 10 : 12}" font-weight="700" fill="#ffffff">${no}</text></svg>`;
  return {
    url: `data:image/svg+xml;charset=UTF-8,${encodeURIComponent(svg)}`,
    anchor: new google.maps.Point(r + 2, r + 2),
  };
}

// Titik tengah garis terpanjang usulan -- tempat badge nomor.
function usulanPilihanTitikTengah(entri) {
  let terpanjang = null;
  entri.polylines.forEach((pl) => {
    const n = pl.getPath().getLength();
    if (!terpanjang || n > terpanjang.getPath().getLength()) terpanjang = pl;
  });
  if (!terpanjang) return null;
  const path = terpanjang.getPath().getArray();
  return path[Math.floor(path.length / 2)];
}

/* ---------- sorotan silang ---------- */

function usulanPilihanSorot(id, aktif) {
  const entri = usulanMulti.get(id);
  if (!entri) return;
  entri.polylines.forEach((pl) => pl.setOptions({ strokeWeight: aktif ? 9 : 5, zIndex: aktif ? 30 : 22 }));
  usulanPilihan.marker.get(id)?.setZIndex(aktif ? 1001 : 900);
  document.querySelectorAll(`[data-pilihan-id="${id}"]`).forEach((el) => el.classList.toggle("sorot", aktif));
  usulanPilihan.sorot = aktif ? id : null;
}

function usulanPilihanBukaInfo(id, latLng) {
  const entri = usulanMulti.get(id);
  if (entri?.polylines.length) google.maps.event.trigger(entri.polylines[0], "click", { latLng });
}

function usulanPilihanZoom(id) {
  const entri = usulanMulti.get(id);
  if (!entri?.bounds || entri.bounds.isEmpty()) return;
  fitBoundsCapped(entri.bounds);
  const titik = usulanPilihanTitikTengah(entri);
  if (titik) usulanPilihanBukaInfo(id, titik);
}

/* ---------- badge nomor di peta ---------- */

function usulanPilihanSyncBadge(nomor) {
  usulanPilihan.marker.forEach((m, id) => {
    if (!usulanMulti.has(id)) {
      m.setMap(null);
      usulanPilihan.marker.delete(id);
    }
  });
  if (!window.google?.maps || !state.map) return;
  usulanMulti.forEach((entri, id) => {
    if (!entri.polylines.length) return; // masih memuat geometri
    if (!entri._pilihanHover) {
      entri._pilihanHover = true;
      entri.polylines.forEach((pl) => {
        pl.addListener("mouseover", () => usulanPilihanSorot(id, true));
        pl.addListener("mouseout", () => usulanPilihanSorot(id, false));
      });
    }
    const no = nomor.get(id);
    let m = usulanPilihan.marker.get(id);
    if (!m) {
      const posisi = usulanPilihanTitikTengah(entri);
      if (!posisi) return;
      m = new google.maps.Marker({ position: posisi, map: state.map, zIndex: 900 });
      m.addListener("click", () => usulanPilihanBukaInfo(id, m.getPosition()));
      m.addListener("mouseover", () => usulanPilihanSorot(id, true));
      m.addListener("mouseout", () => usulanPilihanSorot(id, false));
      usulanPilihan.marker.set(id, m);
    }
    if (m._no !== no) {
      m._no = no;
      m.setIcon(usulanPilihanBadgeIcon(no, entri.warna));
      m.setTitle(`${no}. ${usulanPilihanNama(entri.u)}`);
    }
  });
}

/* ---------- nomor di kartu daftar ---------- */

function usulanPilihanSyncKartu(nomor) {
  document.querySelectorAll("#usulanBrowseList .usulan-browse-card").forEach((card) => {
    const id = card._usulan?.id;
    const entri = usulanMulti.get(id);
    let badge = card.querySelector(".usulan-pilihan-no");
    if (!entri) {
      badge?.remove();
      delete card.dataset.pilihanId;
      card.classList.remove("sorot");
      return;
    }
    card.dataset.pilihanId = id;
    if (!badge) {
      badge = document.createElement("span");
      badge.className = "usulan-pilihan-no";
      card.querySelector(".usulan-multi-check")?.after(badge);
      if (!card._pilihanHover) {
        card._pilihanHover = true;
        card.addEventListener("mouseenter", () => usulanMulti.has(card._usulan?.id) && usulanPilihanSorot(card._usulan.id, true));
        card.addEventListener("mouseleave", () => usulanMulti.has(card._usulan?.id) && usulanPilihanSorot(card._usulan.id, false));
      }
    }
    badge.textContent = nomor.get(id);
    badge.style.background = entri.warna;
  });
}

/* ---------- ringkasan gabungan ---------- */

// Panjang yang ditangani (usulan Pemda) -- dasar Rp/km, sama dgn acuan biaya
// (alokasi Pemda / panjang Pemda). Panjang ruas hanya konteks: satu ruas bisa
// diusulkan beberapa paket (mis. "Paket 1"/"Paket 2"), jadi dijumlah per ruas unik.
function usulanPilihanKmTangani(u) {
  return Number(u.panjang_penanganan_pemda) || 0;
}

function usulanPilihanRingkasHtml(daftar, nomor) {
  const fmtNum = (v, d = 1) => v.toLocaleString("id-ID", { maximumFractionDigits: d });
  const km = daftar.reduce((s, e) => s + usulanPilihanKmTangani(e.u), 0);
  const rp = daftar.reduce((s, e) => s + (Number(e.u.alokasi_usulan_pemda) || 0), 0);
  const ruasUnik = new Map();
  daftar.forEach((e) => {
    const k = e.u.kode_ruas ? `${e.u.kabupaten_kota}|${e.u.kode_ruas}` : usulanPilihanKunciNama(e.u);
    if (!ruasUnik.has(k)) ruasUnik.set(k, e.u);
  });
  const ruasList = [...ruasUnik.values()];
  const kmRuas = ruasList.reduce((s, u) => s + (Number(u.panjang_ruas_km) || 0), 0);
  // kemantapan gabungan ruas unik: (baik + sedang) / panjang ruas, hanya ruas yg data kondisinya ada
  const berKondisi = ruasList.filter((u) => u.kondisi_baik_km != null && u.kondisi_sedang_km != null && Number(u.panjang_ruas_km) > 0);
  const kmKondisi = berKondisi.reduce((s, u) => s + Number(u.panjang_ruas_km), 0);
  const kmMantap = berKondisi.reduce((s, u) => s + Number(u.kondisi_baik_km) + Number(u.kondisi_sedang_km), 0);
  const pctMantap = kmKondisi ? Math.min(100, (kmMantap / kmKondisi) * 100) : null;
  const hitung = (f) => {
    const m = new Map();
    daftar.forEach((e) => { const k = f(e.u) || "-"; m.set(k, (m.get(k) || 0) + 1); });
    return [...m.entries()].sort((a, b) => b[1] - a[1]);
  };
  const jenis = hitung((u) => u.jenis_penanganan);
  const status = hitung((u) => u.seleksi_sistem);
  const kab = new Set(daftar.map((e) => e.u.kabupaten_kota).filter(Boolean));
  const prov = new Set(daftar.map((e) => e.u.provinsi).filter(Boolean));

  // Ruas sama (kab/kota + nama ruas) di >1 usulan: bila nama kegiatannya juga
  // identik -> kemungkinan usulan ganda; bila berbeda (mis. "Paket 1"/"Paket 2")
  // -> ruas yg sama dipecah jadi beberapa paket (informasi, bukan peringatan).
  const kembar = new Map();
  daftar.forEach((e) => {
    const k = usulanPilihanKunciNama(e.u);
    if (!kembar.has(k)) kembar.set(k, []);
    kembar.get(k).push(e.u);
  });
  const ganda = [], paket = [];
  [...kembar.values()].filter((v) => v.length > 1).forEach((v) => {
    const kegiatan = new Set(v.map((u) => String(u.nama_kegiatan || "").trim().toUpperCase()));
    (kegiatan.size < v.length ? ganda : paket).push(v.map((u) => `#${nomor.get(u.id)}`).join(" & "));
  });

  const chips = (arr) => arr.slice(0, 4).map(([k, n]) => `<span class="usulan-pilihan-chip">${escapeHtml(k)} <b>${n}</b></span>`).join("")
    + (arr.length > 4 ? `<span class="usulan-pilihan-chip">+${arr.length - 4} lainnya</span>` : "");

  const baris = daftar.map((e) => {
    const no = nomor.get(e.u.id);
    const kmU = usulanPilihanKmTangani(e.u), rpU = Number(e.u.alokasi_usulan_pemda) || 0;
    const kmRuasU = Number(e.u.panjang_ruas_km) || 0;
    return `<div class="usulan-pilihan-row" data-pilihan-id="${e.u.id}" title="Klik untuk zoom ke usulan ini">
      <span class="usulan-pilihan-no" style="background:${e.warna}">${no}</span>
      <span class="usulan-pilihan-row-nama">${escapeHtml(usulanPilihanNama(e.u))}
        <small>${escapeHtml(e.u.kabupaten_kota || "")} · ditangani ${kmU ? `${fmtNum(kmU, 2)} km` : "- km"}${kmRuasU ? ` dari ruas ${fmtNum(kmRuasU, 2)} km` : ""}</small>
        <small>${formatRupiah(rpU)}${kmU && rpU ? ` · ${fmtNum(rpU / 1e9 / kmU, 2)} Rp M/km` : ""}${e.memuat ? " · memuat..." : ""}</small></span>
      <button type="button" class="usulan-pilihan-lepas" data-lepas="${e.u.id}" title="Lepas dari pilihan"><i class="bi bi-x"></i></button>
    </div>`;
  }).join("");

  return `
    <div class="usulan-pilihan-stat">
      <div title="Panjang yang diusulkan ditangani (Pemda)"><b>${fmtNum(km, 2)}</b> km ditangani</div>
      <div><b>${formatRupiah(rp)}</b></div>
      <div title="Σ alokasi Pemda ÷ Σ panjang penanganan Pemda"><b>${km && rp ? fmtNum(rp / 1e9 / km, 2) : "-"}</b> Rp M/km</div>
      <div><b>${kab.size}</b> kab/kota${prov.size > 1 ? ` · ${prov.size} provinsi` : ""}</div>
      <div title="Ruas yang sama dari beberapa paket dihitung sekali"><b>${ruasList.length}</b> ruas · ${fmtNum(kmRuas, 2)} km</div>
      <div title="(kondisi baik + sedang) ÷ panjang ruas, ruas unik yang data kondisinya ada"><b>${pctMantap == null ? "-" : `${fmtNum(pctMantap, 0)}%`}</b> ruas mantap</div>
    </div>
    <div class="usulan-pilihan-chips">${chips(jenis)}</div>
    <div class="usulan-pilihan-chips">${chips(status)}</div>
    ${ganda.length ? `<div class="usulan-pilihan-peringatan"><i class="bi bi-exclamation-triangle"></i>
      Ruas & nama kegiatan sama: ${ganda.join("; ")} — kemungkinan usulan ganda.</div>` : ""}
    ${paket.length ? `<div class="usulan-pilihan-info"><i class="bi bi-info-circle"></i>
      Ruas sama diusulkan dalam beberapa paket: ${paket.join("; ")}.</div>` : ""}
    <div class="usulan-pilihan-list">${baris}</div>
    <div class="hint usulan-pilihan-catatan">Usulan Pemda (SITIA): Rp M/km = alokasi ÷ panjang penanganan.
      Panjang ruas & kemantapan dihitung per ruas unik (beberapa paket di ruas yang sama dihitung sekali).</div>`;
}

function usulanPilihanRenderRingkas(daftar, nomor) {
  const bar = document.getElementById("usulanMultiBar");
  if (!bar) return;
  let el = document.getElementById("usulanPilihanRingkas");
  if (!el) {
    el = document.createElement("div");
    el.id = "usulanPilihanRingkas";
    el.className = "usulan-pilihan-ringkas";
    bar.after(el);
    el.addEventListener("click", (e) => {
      const lepas = e.target.closest("[data-lepas]");
      if (lepas) {
        e.stopPropagation();
        hapusUsulanMulti(Number(lepas.dataset.lepas));
        return;
      }
      if (e.target.closest(".usulan-pilihan-toggle")) {
        usulanPilihan.ringkasTerbuka = !usulanPilihan.ringkasTerbuka;
        usulanPilihanRender();
        return;
      }
      const row = e.target.closest(".usulan-pilihan-row");
      if (row) usulanPilihanZoom(Number(row.dataset.pilihanId));
    });
    el.addEventListener("mouseover", (e) => {
      const row = e.target.closest(".usulan-pilihan-row");
      if (row && usulanPilihan.sorot !== Number(row.dataset.pilihanId)) usulanPilihanSorot(Number(row.dataset.pilihanId), true);
    });
    el.addEventListener("mouseout", (e) => {
      const row = e.target.closest(".usulan-pilihan-row");
      if (row && !row.contains(e.relatedTarget)) usulanPilihanSorot(Number(row.dataset.pilihanId), false);
    });
  }
  el.hidden = !daftar.length || bar.hidden;
  if (el.hidden) return;
  el.innerHTML = `<button type="button" class="usulan-pilihan-toggle">
      <i class="bi bi-chevron-${usulanPilihan.ringkasTerbuka ? "up" : "down"}"></i> Ringkasan pilihan</button>
    ${usulanPilihan.ringkasTerbuka ? usulanPilihanRingkasHtml(daftar, nomor) : ""}`;
}

/* ---------- legenda "Layer Aktif" ---------- */

function usulanPilihanRenderLegend(daftar, nomor) {
  const list = document.getElementById("mapLegendList");
  if (!list) return;
  let el = document.getElementById("mapLegendPilihan");
  if (!el) {
    el = document.createElement("div");
    el.id = "mapLegendPilihan";
    el.className = "map-legend-pilihan";
    list.after(el);
    el.addEventListener("click", (e) => {
      const lepas = e.target.closest("[data-lepas]");
      if (lepas) { hapusUsulanMulti(Number(lepas.dataset.lepas)); return; }
      const row = e.target.closest("[data-pilihan-id]");
      if (row) usulanPilihanZoom(Number(row.dataset.pilihanId));
    });
    el.addEventListener("mouseover", (e) => {
      const row = e.target.closest("[data-pilihan-id]");
      if (row && usulanPilihan.sorot !== Number(row.dataset.pilihanId)) usulanPilihanSorot(Number(row.dataset.pilihanId), true);
    });
    el.addEventListener("mouseout", (e) => {
      const row = e.target.closest("[data-pilihan-id]");
      if (row && !row.contains(e.relatedTarget)) usulanPilihanSorot(Number(row.dataset.pilihanId), false);
    });
  }
  el.hidden = !daftar.length;
  if (!daftar.length) return;
  const tampil = daftar.slice(0, USULAN_PILIHAN_LEGEND_MAKS);
  el.innerHTML = `<div class="map-legend-pilihan-judul">Usulan IJD dipilih (${daftar.length})</div>`
    + tampil.map((e) => `<div class="map-legend-item" data-pilihan-id="${e.u.id}" title="Klik untuk zoom">
        <span class="usulan-pilihan-no" style="background:${e.warna}">${nomor.get(e.u.id)}</span>
        <span class="map-legend-item-label">${escapeHtml(usulanPilihanNama(e.u))}</span>
        <button type="button" class="map-legend-item-remove" data-lepas="${e.u.id}" title="Lepas dari pilihan"><i class="bi bi-x-lg"></i></button>
      </div>`).join("")
    + (daftar.length > tampil.length ? `<div class="hint">+${daftar.length - tampil.length} usulan lainnya (lihat ringkasan di panel kiri)</div>` : "");
}

/* ---------- titik masuk ---------- */

function usulanPilihanRender() {
  const daftar = [...usulanMulti.values()];
  const nomor = usulanPilihanNomor();
  usulanPilihanSyncBadge(nomor);
  usulanPilihanSyncKartu(nomor);
  usulanPilihanRenderRingkas(daftar, nomor);
  usulanPilihanRenderLegend(daftar, nomor);
}
