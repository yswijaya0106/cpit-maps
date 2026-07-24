/* The Next - SiJalan — Usulan Inpres Jalan/Jembatan: match-along-route, geometry overlay, browse & detail panel */

const USULAN_MARKER_COLORS = ["#f59e0b", "#ec4899", "#8b5cf6", "#06b6d4", "#84cc16", "#f97316"];

function sumPathLengthKm(paths) {
  const meters = paths.reduce((sum, path) => sum + google.maps.geometry.spherical.computeLength(path), 0);
  return meters / 1000;
}

async function analyzeUsulanInpres() {
  const route = state.routes[state.selectedIndex];
  const content = document.getElementById("usulanInpresContent");
  if (!route) return;

  clearUsulanPolylines();
  content.innerHTML = `<div class="adv-loading">Mencari usulan Inpres Jalan/Jembatan (SITIA Bina Marga) di sepanjang rute...</div>`;

  const samples = pickEvenSamples(route.coordinates, 8);
  const regions = [];
  for (const { value } of samples) {
    const [lat, lng] = value;
    const result = await reverseGeocode(lat, lng);
    if (!result) continue;
    const admin = extractAdminComponents(result);
    if (!admin.province && !admin.city) continue;
    const key = `${admin.province}|${admin.city}`;
    if (regions.some((r) => r._key === key)) continue;
    regions.push({ provinsi: admin.province, kabupaten_kota: admin.city, _key: key });
  }

  if (!regions.length) {
    content.innerHTML = `<div class="adv-error">Tidak dapat menentukan wilayah administratif untuk mencocokkan usulan Inpres.</div>`;
    return;
  }

  let data;
  try {
    const res = await fetch("/api/usulan-inpres/nearby", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ regions: regions.map(({ provinsi, kabupaten_kota }) => ({ provinsi, kabupaten_kota })) }),
    });
    if (!res.ok) throw new Error(await res.text());
    data = await res.json();
  } catch (err) {
    console.error(err);
    content.innerHTML = `<div class="adv-error">Gagal mengambil data usulan Inpres: ${escapeHtml(String(err))}</div>`;
    return;
  }

  if (!data.usulan.length) {
    content.innerHTML = `<div class="adv-error">Tidak ada usulan Inpres Jalan/Jembatan yang tercatat di wilayah yang dilalui rute ini.</div>`;
    state.lastUsulanNearby = null;
    return;
  }

  state.lastUsulanNearby = data.usulan.map((u) => ({
    nama: u.nama_kegiatan || u.nama_ruas,
    kabupaten_kota: u.kabupaten_kota,
    provinsi: u.provinsi,
    jenis_penanganan: u.jenis_penanganan,
    panjang_ruas_km: u.panjang_ruas_km,
    prioritas: u.prioritas,
    seleksi_sistem: u.seleksi_sistem,
    alokasi_usulan_pemda: u.alokasi_usulan_pemda,
  }));

  let html = `<p class="hint">${data.usulan.length} usulan ditemukan di ${data.regions_matched} wilayah yang dilalui rute (data usulan Bina Marga Inpres No. 11/2025, belum tentu final dianggarkan).</p>`;
  html += `<div class="adv-result-list" id="usulanInpresList">`;
  data.usulan.forEach((u, i) => {
    const statusClass = u.seleksi_sistem === "LULUS" ? "usulan-badge-ok" : "usulan-badge-warn";
    html += `<div class="adv-usulan-card" data-idx="${i}">
      <div class="adv-usulan-head">
        <span class="usulan-badge ${statusClass}">${escapeHtml(u.seleksi_sistem || "-")}</span>
        <span class="adv-usulan-title">${escapeHtml(u.nama_kegiatan || u.nama_ruas)}</span>
      </div>
      <div class="adv-region-meta">${escapeHtml(u.kabupaten_kota || "")}, ${escapeHtml(u.provinsi || "")} · ${escapeHtml(u.jenis_penanganan || "-")} · Prioritas #${u.prioritas ?? "-"}</div>
      <div class="adv-region-meta">Panjang: ${u.panjang_ruas_km ?? "-"} km · Anggaran usulan: ${formatRupiah(u.alokasi_usulan_pemda)}</div>
      ${u.has_geometry
        ? `<button class="btn btn-sm btn-ghost btn-usulan-show" data-idx="${i}"><i class="bi bi-map"></i> Tampilkan di peta</button>
           <a class="btn btn-sm btn-ghost" href="/api/usulan-inpres/${u.id}/export/shp"><i class="bi bi-file-earmark-zip"></i> Export SHP</a>`
        : `<span class="hint">Tidak ada data geometri (KML)</span>`}
    </div>`;
  });
  html += `</div>`;
  content.innerHTML = html;

  content.querySelectorAll(".btn-usulan-show").forEach((btn) => {
    btn.addEventListener("click", () => showUsulanGeometry(data.usulan[Number(btn.dataset.idx)], btn));
  });
}

async function showUsulanGeometry(usulan, btn) {
  btn.disabled = true;
  const originalText = btn.innerHTML;
  btn.innerHTML = "Memuat...";
  try {
    const res = await fetch(`/api/usulan-inpres/${usulan.id}/geometry`);
    if (!res.ok) throw new Error(await res.text());
    const geojson = await res.json();

    const lineStrings = geojson.type === "MultiLineString" ? geojson.coordinates : [geojson.coordinates];
    const color = USULAN_MARKER_COLORS[state.usulanPolylines.length % USULAN_MARKER_COLORS.length];
    if (!state.usulanBounds) state.usulanBounds = new google.maps.LatLngBounds();

    const paths = lineStrings.map((coords) => coords.map(([lng, lat]) => ({ lat, lng })));
    const kmlLengthKm = sumPathLengthKm(paths);

    paths.forEach((path) => {
      const pl = new google.maps.Polyline({
        path,
        strokeColor: color,
        strokeOpacity: 0.9,
        strokeWeight: 5,
        icons: [{ icon: { path: "M 0,-1 0,1", strokeOpacity: 1, scale: 3 }, offset: "0", repeat: "12px" }],
        map: state.map,
        zIndex: 20,
      });
      const info = new google.maps.InfoWindow({
        content: `<div class="usulan-info-tooltip"><strong>${escapeHtml(usulan.nama_kegiatan || usulan.nama_ruas)}</strong><br/>ID: ${usulan.id}<br/>${escapeHtml(usulan.jenis_penanganan || "")} · ${formatRupiah(usulan.alokasi_usulan_pemda)}<br/>Panjang KML: ${kmlLengthKm.toFixed(2)} km</div>`,
      });
      pl.addListener("click", (e) => {
        info.setPosition(e.latLng);
        info.open(state.map);
      });
      state.usulanPolylines.push(pl);
      path.forEach((p) => state.usulanBounds.extend(p));
    });

    fitBoundsCapped(state.usulanBounds);
    btn.innerHTML = `<i class="bi bi-check2"></i> Ditampilkan`;
  } catch (err) {
    console.error(err);
    toast("Gagal memuat geometri usulan", true);
    btn.disabled = false;
    btn.innerHTML = originalText;
  }
}

/* ---------- Jelajahi Usulan Inpres (browse & detail) ---------- */

function clearBrowseUsulanPolylines() {
  state.browseUsulanPolylines.forEach((pl) => pl.setMap(null));
  state.browseUsulanPolylines = [];
  if (typeof updateKecamatanLintasan === "function") updateKecamatanLintasan();
}

async function loadUsulanProvinsiOptions() {
  const panel = document.getElementById("usulanProvinsiPanel");
  try {
    const res = await fetch("/api/usulan-inpres/provinsi");
    if (!res.ok) throw new Error(await res.text());
    const rows = await res.json();
    rows.forEach((r) => {
      const opt = document.createElement("div");
      opt.className = "usulan-combo-option";
      opt.dataset.value = r.provinsi;
      opt.textContent = `${r.provinsi} (${r.jumlah})`;
      panel.appendChild(opt);
    });
  } catch (err) {
    console.error(err);
  }
}

// Kabupaten/kota tergantung provinsi yang sedang dipilih -- dipanggil ulang
// tiap kali provinsi berganti (termasuk "Semua Provinsi", lalu menampilkan
// seluruh kabupaten nasional).
async function loadUsulanKabupatenOptions(provinsi) {
  const panel = document.getElementById("usulanKabupatenPanel");
  const label = document.getElementById("usulanKabupatenLabel");
  panel.querySelectorAll(".usulan-combo-option:not([data-value=''])").forEach((el) => el.remove());
  panel.querySelector('.usulan-combo-option[data-value=""]').classList.add("selected");
  label.textContent = "Semua Kabupaten/Kota";
  state.usulanBrowse.kabupaten_kota = "";
  try {
    const params = provinsi ? `?provinsi=${encodeURIComponent(provinsi)}` : "";
    const res = await fetch(`/api/usulan-inpres/kabupaten${params}`);
    if (!res.ok) throw new Error(await res.text());
    const rows = await res.json();
    rows.forEach((r) => {
      const opt = document.createElement("div");
      opt.className = "usulan-combo-option";
      opt.dataset.value = r.kabupaten_kota;
      opt.textContent = `${r.kabupaten_kota} (${r.jumlah})`;
      panel.appendChild(opt);
    });
  } catch (err) {
    console.error(err);
  }
}

function bindUsulanComboField(fieldId, toggleId, panelId, labelId, onSelect) {
  const field = document.getElementById(fieldId);
  const toggle = document.getElementById(toggleId);
  const panel = document.getElementById(panelId);
  const label = document.getElementById(labelId);

  toggle.addEventListener("click", (e) => {
    e.stopPropagation();
    const willOpen = panel.hidden;
    panel.hidden = !willOpen;
    field.classList.toggle("open", willOpen);
  });

  panel.addEventListener("click", (e) => {
    const opt = e.target.closest(".usulan-combo-option");
    if (!opt) return;
    panel.querySelectorAll(".usulan-combo-option.selected").forEach((el) => el.classList.remove("selected"));
    opt.classList.add("selected");
    label.textContent = opt.textContent;
    panel.hidden = true;
    field.classList.remove("open");
    onSelect(opt.dataset.value);
  });

  document.addEventListener("click", (e) => {
    if (!panel.hidden && !field.contains(e.target)) {
      panel.hidden = true;
      field.classList.remove("open");
    }
  });
}

function bindUsulanProvinsiCombo() {
  bindUsulanComboField("usulanProvinsiField", "usulanProvinsiToggle", "usulanProvinsiPanel", "usulanProvinsiLabel", (value) => {
    state.usulanBrowse.provinsi = value;
    loadUsulanKabupatenOptions(value);
    loadUsulanBrowseList(true);
  });
  bindUsulanComboField("usulanKabupatenField", "usulanKabupatenToggle", "usulanKabupatenPanel", "usulanKabupatenLabel", (value) => {
    state.usulanBrowse.kabupaten_kota = value;
    loadUsulanBrowseList(true);
  });
}

async function loadUsulanBrowseList(reset) {
  const listEl = document.getElementById("usulanBrowseList");
  const moreWrap = document.getElementById("usulanBrowseMore");
  const b = state.usulanBrowse;

  if (reset) {
    b.offset = 0;
    listEl.innerHTML = `<div class="adv-loading">Memuat data usulan...</div>`;
  }

  const params = new URLSearchParams({ limit: b.limit, offset: b.offset });
  if (b.provinsi) params.set("provinsi", b.provinsi);
  if (b.kabupaten_kota) params.set("kabupaten_kota", b.kabupaten_kota);
  if (b.q) params.set("q", b.q);

  let data;
  try {
    const res = await fetch(`/api/usulan-inpres?${params}`);
    if (!res.ok) throw new Error(await res.text());
    data = await res.json();
  } catch (err) {
    console.error(err);
    listEl.innerHTML = `<div class="adv-error">Gagal memuat data usulan: ${escapeHtml(String(err))}</div>`;
    return;
  }

  b.total = data.total;
  if (reset) listEl.innerHTML = "";

  if (!data.usulan.length && reset) {
    listEl.innerHTML = `<div class="adv-error">Tidak ada usulan yang cocok dengan filter ini.</div>`;
  } else {
    data.usulan.forEach((u) => {
      const card = document.createElement("div");
      card.className = "usulan-browse-card";
      card.dataset.id = u.id;
      const statusClass = u.seleksi_sistem === "LULUS" ? "usulan-badge-ok" : "usulan-badge-warn";
      card.innerHTML = `
        <div class="adv-usulan-head">
          <span class="usulan-badge ${statusClass}">${escapeHtml(u.seleksi_sistem || "-")}</span>
          <span class="adv-usulan-title">${escapeHtml(u.nama_kegiatan || u.nama_ruas)}</span>
        </div>
        <div class="adv-region-meta">${escapeHtml(u.kabupaten_kota || "")}, ${escapeHtml(u.provinsi || "")} · ${escapeHtml(u.jenis_penanganan || "-")} · Prioritas #${u.prioritas ?? "-"}</div>
        <div class="adv-region-meta">${u.panjang_ruas_km ?? "-"} km · ${formatRupiah(u.alokasi_usulan_pemda)}${u.has_geometry ? "" : " · tanpa data KML"}</div>
      `;
      card.addEventListener("click", () => {
        listEl.querySelectorAll(".usulan-browse-card.selected").forEach((el) => el.classList.remove("selected"));
        card.classList.add("selected");
        loadUsulanDetail(u.id);
      });
      listEl.appendChild(card);
    });
  }

  const loaded = b.offset + data.usulan.length;
  moreWrap.hidden = loaded >= b.total;
  b.offset = loaded;
}

async function loadUsulanDetail(id) {
  const detailEl = document.getElementById("usulanBrowseDetail");
  detailEl.innerHTML = `<div class="adv-loading">Memuat atribut usulan...</div>`;
  clearBrowseUsulanPolylines();

  let u;
  try {
    const res = await fetch(`/api/usulan-inpres/${id}`);
    if (!res.ok) throw new Error(await res.text());
    u = await res.json();
  } catch (err) {
    console.error(err);
    detailEl.innerHTML = `<div class="adv-error">Gagal memuat detail usulan: ${escapeHtml(String(err))}</div>`;
    return;
  }

  const rows = [
    ["Kode Ruas", u.kode_ruas],
    ["Status Ruas", u.status_ruas],
    ["Jenis Penanganan", u.jenis_penanganan],
    ["Panjang Ruas", u.panjang_ruas_km != null ? `${u.panjang_ruas_km} km` : "-"],
    ["Lebar Jalan", u.lebar_jalan_m != null ? `${u.lebar_jalan_m} m` : "-"],
    ["Anggaran Usulan (Pemda)", formatRupiah(u.alokasi_usulan_pemda)],
    ["Prioritas", u.prioritas],
    ["Seleksi Sistem", u.seleksi_sistem],
    ["Verifikasi Balai", u.verifikasi_balai],
    ["Kapasitas Fiskal", u.kapasitas_fiskal],
    ["Tematik Kawasan", u.tematik_kawasan_pemda],
    ["Kondisi Baik", u.kondisi_baik_km != null ? `${u.kondisi_baik_km} km` : "-"],
    ["Kondisi Sedang", u.kondisi_sedang_km != null ? `${u.kondisi_sedang_km} km` : "-"],
    ["Kondisi Ringan", u.kondisi_ringan_km != null ? `${u.kondisi_ringan_km} km` : "-"],
    ["Kondisi Berat", u.kondisi_berat_km != null ? `${u.kondisi_berat_km} km` : "-"],
    ["Kondisi Jembatan", u.kondisi_jembatan],
    ["Catatan RC DED (Balai)", u.catatan_rc_ded_balai, true],
    ["Catatan RC FS (Balai)", u.catatan_rc_fs_balai, true],
    ["Catatan RC Lahan (Balai)", u.catatan_rc_lahan_balai, true],
    ["Catatan RC Dokling (Balai)", u.catatan_rc_dokling_balai, true],
    ["Catatan RAB (Balai)", u.catatan_rab_balai, true],
    ["Keterangan", u.keterangan, true],
  ];

  const NOTE_PREVIEW_LEN = 60;

  let html = `<div class="usulan-detail-card">
    <div class="adv-usulan-title">${escapeHtml(u.nama_kegiatan || u.nama_ruas)}</div>
    <div class="adv-region-meta">${escapeHtml(u.kabupaten_kota || "")}, ${escapeHtml(u.provinsi || "")}</div>
    <table class="usulan-detail-table">`;
  rows.forEach(([label, value, isLong]) => {
    if (value === null || value === undefined || value === "") return;
    const text = String(value);
    if (isLong && text.length > NOTE_PREVIEW_LEN) {
      const preview = escapeHtml(text.slice(0, NOTE_PREVIEW_LEN)) + "…";
      html += `<tr><th>${escapeHtml(label)}</th><td><span class="usulan-note-toggle" data-preview="${escapeHtml(text.slice(0, NOTE_PREVIEW_LEN))}…" data-full="${escapeHtml(text)}" title="${escapeHtml(text)}">${preview}</span></td></tr>`;
    } else {
      html += `<tr><th>${escapeHtml(label)}</th><td>${escapeHtml(text)}</td></tr>`;
    }
  });
  html += `</table>`;

  if (u.kml_original_url || u.kml_ijd_url) {
    html += `<div class="usulan-doc-links usulan-kml-links">`;
    if (u.kml_original_url) {
      html += `<a href="${escapeHtml(u.kml_original_url)}" target="_blank" rel="noopener"><i class="bi bi-file-earmark-code"></i> KML Original</a>`;
    }
    if (u.kml_ijd_url) {
      html += `<a href="${escapeHtml(u.kml_ijd_url)}" target="_blank" rel="noopener"><i class="bi bi-file-earmark-code"></i> KML + Data IJD</a>`;
    }
    html += `<a href="/api/usulan-inpres/${u.id}/export/shp"><i class="bi bi-file-earmark-zip"></i> Export SHP</a>`;
    html += `</div>`;
  }

  if (u.dokumen && u.dokumen.length) {
    html += `<div class="usulan-doc-links">`;
    u.dokumen.forEach((d) => {
      html += `<a href="${escapeHtml(d.url)}" target="_blank" rel="noopener">${escapeHtml(d.jenis_dokumen.replace(/_/g, " "))}</a>`;
    });
    html += `</div>`;
  }
  html += `<div class="usulan-dalam-angka" id="usulanDalamAngka"></div>`;
  html += `<div class="usulan-ijd-score" id="usulanIjdScore"><div class="adv-loading">Menghitung skor prioritisasi IJD...</div></div>`;
  html += `<div class="usulan-ijd-score" id="usulanSkorNasional"></div>`;
  html += `<div class="usulan-ijd-score" id="usulanNpr"></div>`;
  html += `<div class="usulan-ijd-score" id="usulanPenilaianBappenas"></div>`;
  html += `<div class="adv-loading" id="usulanGeomStatus">Memuat lokasi di peta...</div></div>`;
  detailEl.innerHTML = html;

  detailEl.querySelectorAll(".usulan-note-toggle").forEach((el) => {
    el.addEventListener("click", () => {
      const expanded = el.dataset.expanded === "1";
      el.textContent = expanded ? el.dataset.preview : el.dataset.full;
      el.dataset.expanded = expanded ? "0" : "1";
    });
  });

  loadDalamAngka(u.id);
  loadIjdScore(u.id);
  loadSkorNasional(u.id);
  loadNpr(u.id);
  loadPenilaianBappenas(u.id);
  await flyToUsulanGeometry(u);
}

async function loadDalamAngka(id) {
  const el = document.getElementById("usulanDalamAngka");
  if (!el) return;
  let d;
  try {
    const res = await fetch(`/api/usulan-inpres/${id}/dalam-angka`);
    if (!res.ok) throw new Error(await res.text());
    d = await res.json();
  } catch (err) {
    console.error(err);
    return; // gagal senyap -- bukan bagian inti detail usulan
  }
  if (!d.tersedia || !d.publikasi || !d.publikasi.length) return;

  let html = `<div class="usulan-dalam-angka-title"><i class="bi bi-file-earmark-pdf"></i> Dalam Angka (BPS)</div>`;
  d.publikasi.forEach((p) => {
    html += `<div class="usulan-dalam-angka-item">
      <span class="tahun-badge">${escapeHtml(String(p.tahun))}</span>
      <span>${escapeHtml(p.judul)}</span>
      <button type="button" data-action="preview" data-url="${escapeHtml(p.url)}" data-judul="${escapeHtml(p.judul)}">
        <i class="bi bi-eye"></i> Pratinjau</button>
      <button type="button" data-action="newtab" data-url="${escapeHtml(p.url)}">
        <i class="bi bi-box-arrow-up-right"></i> Tab Baru</button>
    </div>`;
  });
  el.innerHTML = html;

  el.querySelectorAll('button[data-action="preview"]').forEach((btn) => {
    btn.addEventListener("click", () => openPdfPreviewModal(btn.dataset.url, btn.dataset.judul));
  });
  el.querySelectorAll('button[data-action="newtab"]').forEach((btn) => {
    btn.addEventListener("click", () => window.open(btn.dataset.url, "_blank", "noopener"));
  });
}

async function loadPenilaianBappenas(id, generate = false) {
  const el = document.getElementById("usulanPenilaianBappenas");
  if (!el) return;
  try {
    if (generate) {
      el.innerHTML = `<div class="adv-loading"><i class="bi bi-hourglass-split"></i> Menyusun draf penilaian dengan AI...</div>`;
    }
    const res = await fetch(`/api/usulan-inpres/${id}/penilaian-bappenas`,
      generate ? { method: "POST" } : undefined);
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Gagal");
    el.innerHTML = renderPenilaianBappenasHtml(id, data);
  } catch (err) {
    console.error(err);
    el.innerHTML = `<div class="ijd-score-head">
        <span class="ijd-score-title"><i class="bi bi-stars"></i> Draf Penilaian Bappenas (AI)</span>
      </div>
      <div class="adv-error">${escapeHtml(String(err.message || err))}</div>
      <button type="button" class="btn btn-ghost btn-sm" onclick="loadPenilaianBappenas(${id}, true)">Coba lagi</button>`;
  }
}

function renderPenilaianBappenasHtml(id, data) {
  let html = `<div class="ijd-score-head">
    <span class="ijd-score-title"><i class="bi bi-stars"></i> Draf Penilaian Bappenas (AI)</span>
  </div>`;
  if (!data.tersedia) {
    html += `<p class="hint">Belum ada draf penilaian untuk usulan ini.</p>
      <button type="button" class="btn btn-ghost btn-sm" onclick="loadPenilaianBappenas(${id}, true)">
        <i class="bi bi-stars"></i> Buat draf penilaian (AI)</button>`;
    return html;
  }
  const aspek = (label, poin, narasi, narasiAi) => `
    <div class="ijd-bar-row">
      <div class="ijd-bar-label">${escapeHtml(label)}
        <span class="usulan-badge usulan-badge-ok ijd-badge">poin ${poin} / 2</span></div>
    </div>
    <p class="usulan-penilaian-narasi">${narasi ? checklistHtml(narasi) : "-"}</p>` +
    (narasiAi ? `
    <p class="hint usulan-penilaian-ai-label"><i class="bi bi-stars"></i> Narasi AI</p>
    <p class="usulan-penilaian-narasi usulan-penilaian-narasi-ai">${escapeHtml(narasiAi)}</p>` : "");
  html += aspek("A. Prioritas & Nilai Strategis", data.aspek_a_poin, data.aspek_a_narasi);
  html += aspek("B. Daya Ungkit Ekonomi & Sektoral", data.aspek_b_poin, data.aspek_b_narasi, data.aspek_b_narasi_ai);
  html += `<div class="ijd-bar-row"><div class="ijd-bar-label">Kesimpulan
      <span class="usulan-badge usulan-badge-ok ijd-badge">total ${data.total_poin} / 4</span></div></div>
    <p class="usulan-penilaian-narasi">${escapeHtml(data.kesimpulan || "-")}</p>
    <p class="hint ijd-score-note">Draf dihasilkan AI (${escapeHtml(data.provider || "?")} · ${escapeHtml(data.model || "?")},
      ${escapeHtml(String(data.generated_at || ""))}) mengikuti format sheet "Output Penilaian" —
      BUKAN penilaian resmi Bappenas.</p>
    <button type="button" class="btn btn-ghost btn-sm" onclick="loadPenilaianBappenas(${id}, true)">
      <i class="bi bi-arrow-clockwise"></i> Generate ulang</button>`;
  return html;
}

async function loadSkorNasional(id) {
  const el = document.getElementById("usulanSkorNasional");
  if (!el) return;
  try {
    const res = await fetch(`/api/usulan-inpres/${id}/skor-prioritas-nasional`);
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    const totalLabel = data.skor_total != null
      ? `${data.skor_total.toFixed(1)} · peringkat ${data.peringkat_nasional} dari ${data.jumlah_ternilai} usulan ternilai`
      : "Belum dapat dihitung — usulan belum punya urutan prioritas kompetensi.";
    let html = `<div class="ijd-score-head">
      <span class="ijd-score-title"><i class="bi bi-trophy"></i> Skor Prioritas Nasional (perkiraan)</span>
      <span class="ijd-score-total">${escapeHtml(totalLabel)}</span>
    </div>`;
    data.komponen.forEach((k) => {
      const ada = k.nilai != null;
      const pct = ada ? Math.max(0, Math.min(100, Math.round(k.nilai))) : 0;
      html += `<div class="ijd-bar-row" title="${escapeHtml(k.keterangan)}">
        <div class="ijd-bar-label">${escapeHtml(k.kode)}. ${escapeHtml(k.label)} <span class="hint">(${k.bobot_pct}%)</span></div>
        <div class="ijd-bar-value">
          ${ada ? `<div class="adv-bar-track"><div class="adv-bar-fill" style="width:${pct}%"></div></div>` : ""}
          <span class="usulan-badge ${ada ? "usulan-badge-ok" : "usulan-badge-warn"} ijd-badge">${ada ? k.nilai.toFixed(0) : "Belum ada"}</span>
        </div>
      </div>`;
    });
    html += `<p class="hint ijd-score-note">${escapeHtml(data.catatan)}</p>`;
    el.innerHTML = html;
  } catch (err) {
    console.error(err);
    el.innerHTML = `<div class="adv-error">Gagal menghitung skor prioritas nasional.</div>`;
  }
}

async function loadIjdScore(id) {
  const el = document.getElementById("usulanIjdScore");
  if (!el) return;
  try {
    const res = await fetch(`/api/usulan-inpres/${id}/ijd-score`);
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    el.innerHTML = renderIjdScoreHtml(data);
  } catch (err) {
    console.error(err);
    el.innerHTML = `<div class="adv-error">Gagal menghitung skor prioritisasi IJD.</div>`;
  }
}

function renderIjdScoreHtml(data) {
  const totalLabel = data.skor_ternormalisasi_100 != null
    ? `${data.skor_ternormalisasi_100.toFixed(1)} / 100 · dari ${data.bobot_tersedia.toFixed(0)} dari 100 bobot parameter yang datanya tersedia`
    : "Tidak dapat dihitung — belum ada parameter yang datanya tersedia.";

  let html = `<div class="ijd-score-head">
    <span class="ijd-score-title"><i class="bi bi-bar-chart-line"></i> Skor Prioritisasi Teknokratik IJD (perkiraan, kaidah ${escapeHtml(String(data.tahun_berlaku))})</span>
    <span class="ijd-score-total">${escapeHtml(totalLabel)}</span>
  </div>`;

  data.komponen.forEach((k) => {
    const pct = k.tersedia ? Math.max(0, Math.min(100, Math.round(k.nilai))) : 0;
    const badgeClass = k.tersedia ? "usulan-badge-ok" : "usulan-badge-warn";
    const badgeText = k.tersedia ? k.nilai.toFixed(0) : "Belum tersedia";
    html += `<div class="ijd-bar-row" title="${escapeHtml(k.keterangan)}">
      <div class="ijd-bar-label">${escapeHtml(k.kode)}. ${escapeHtml(k.label)} <span class="hint">(bobot ${k.bobot_maks})</span></div>
      <div class="ijd-bar-value">
        ${k.tersedia ? `<div class="adv-bar-track"><div class="adv-bar-fill" style="width:${pct}%"></div></div>` : ""}
        <span class="usulan-badge ${badgeClass} ijd-badge">${escapeHtml(badgeText)}</span>
      </div>
    </div>`;
  });

  html += `<p class="hint ijd-score-note">${escapeHtml(data.catatan)}</p>`;
  return html;
}

async function loadNpr(id) {
  const el = document.getElementById("usulanNpr");
  if (!el) return;
  try {
    const res = await fetch(`/api/usulan-inpres/${id}/npr`);
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    el.innerHTML = renderNprHtml(data);
  } catch (err) {
    console.error(err);
    el.innerHTML = `<div class="adv-error">Gagal menghitung NPR.</div>`;
  }
}

function renderNprBarRows(sub) {
  let html = "";
  sub.komponen.forEach((k) => {
    const pct = k.tersedia ? Math.max(0, Math.min(100, Math.round(k.nilai))) : 0;
    const badgeClass = k.tersedia ? "usulan-badge-ok" : "usulan-badge-warn";
    const badgeText = k.tersedia ? k.nilai.toFixed(0) : "Belum tersedia";
    html += `<div class="ijd-bar-row" title="${escapeHtml(k.keterangan)}">
      <div class="ijd-bar-label">${escapeHtml(k.label)} <span class="hint">(bobot ${k.bobot_maks})</span></div>
      <div class="ijd-bar-value">
        ${k.tersedia ? `<div class="adv-bar-track"><div class="adv-bar-fill" style="width:${pct}%"></div></div>` : ""}
        <span class="usulan-badge ${badgeClass} ijd-badge">${escapeHtml(badgeText)}</span>
      </div>
    </div>`;
  });
  return html;
}

function renderNprHtml(data) {
  const totalLabel = data.npr != null
    ? `NPR ${data.npr.toFixed(1)} / 100 · ${escapeHtml(data.kategori)}`
    : "Tidak dapat dihitung — belum ada parameter yang datanya tersedia.";
  let html = `<div class="ijd-score-head">
    <span class="ijd-score-title"><i class="bi bi-graph-up-arrow"></i> NPR — Nilai Prioritas Ruas (metodologi alternatif, eksperimental)</span>
    <span class="ijd-score-total">${escapeHtml(totalLabel)}</span>
  </div>`;
  const si = data.skor_intensitas, sc = data.skor_cakupan;
  html += `<p class="hint">Skor Intensitas (bobot ${Math.round(data.bobot_si_sc.SI * 100)}%)` +
    (si.skor_ternormalisasi_100 != null ? ` — ${si.skor_ternormalisasi_100.toFixed(1)}/100` : " — belum dapat dihitung") + `</p>`;
  html += renderNprBarRows(si);
  html += `<p class="hint">Skor Cakupan (bobot ${Math.round(data.bobot_si_sc.SC * 100)}%)` +
    (sc.skor_ternormalisasi_100 != null ? ` — ${sc.skor_ternormalisasi_100.toFixed(1)}/100` : " — belum dapat dihitung") + `</p>`;
  html += renderNprBarRows(sc);
  html += `<p class="hint ijd-score-note">${escapeHtml(data.catatan)}</p>`;
  return html;
}

async function flyToUsulanGeometry(u) {
  const statusEl = document.getElementById("usulanGeomStatus");

  if (!u.kml_original_url) {
    if (statusEl) {
      const approx = await geocodeText(`${u.kabupaten_kota || ""}, ${u.provinsi || ""}`);
      if (approx) {
        state.map.panTo({ lat: approx.lat, lng: approx.lng });
        state.map.setZoom(11);
        statusEl.textContent = "Usulan ini tidak memiliki data KML — peta diarahkan ke perkiraan wilayah kabupaten/kota.";
      } else {
        statusEl.textContent = "Usulan ini tidak memiliki data geometri (KML).";
      }
    }
    return;
  }

  try {
    const res = await fetch(`/api/usulan-inpres/${u.id}/geometry`);
    if (!res.ok) throw new Error(await res.text());
    const geojson = await res.json();

    const lineStrings = geojson.type === "MultiLineString" ? geojson.coordinates : [geojson.coordinates];
    const bounds = new google.maps.LatLngBounds();

    const paths = lineStrings.map((coords) => coords.map(([lng, lat]) => ({ lat, lng })));
    const kmlLengthKm = sumPathLengthKm(paths);
    const info = new google.maps.InfoWindow({
      content: `<div class="usulan-info-tooltip"><strong>${escapeHtml(u.nama_kegiatan || u.nama_ruas)}</strong><br/>ID: ${u.id}<br/>Panjang KML: ${kmlLengthKm.toFixed(2)} km</div>`,
    });

    paths.forEach((path) => {
      const pl = new google.maps.Polyline({
        path,
        strokeColor: "#f59e0b",
        strokeOpacity: 0.95,
        strokeWeight: 6,
        map: state.map,
        zIndex: 25,
      });
      pl.addListener("click", (e) => {
        info.setPosition(e.latLng);
        info.open(state.map);
      });
      state.browseUsulanPolylines.push(pl);
      path.forEach((p) => bounds.extend(p));
    });

    fitBoundsCapped(bounds);
    if (typeof updateKecamatanLintasan === "function") updateKecamatanLintasan();
    if (statusEl) statusEl.remove();
  } catch (err) {
    console.error(err);
    if (statusEl) statusEl.textContent = "Gagal memuat geometri KML usulan ini.";
  }
}

async function importUsulanXlsx(file) {
  const btn = document.getElementById("btnUsulanImport");
  btn.disabled = true;
  btn.innerHTML = '<i class="bi bi-hourglass-split"></i> Mengimpor...';
  try {
    const form = new FormData();
    form.append("file", file);
    const res = await fetch("/api/usulan-inpres/import", { method: "POST", body: form });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Import gagal");
    toast(`Import ${data.filename}: ${data.inserted} baru, ${data.updated} di-update (total ${data.total_usulan} usulan).`);
    loadUsulanProvinsiOptions();
    loadUsulanBrowseList(true);
  } catch (err) {
    toast(`Import gagal: ${err.message}`, true);
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<i class="bi bi-upload"></i> Import XLSX';
  }
}

function bindUsulanImportExport() {
  const fileInput = document.getElementById("usulanImportFile");
  document.getElementById("btnUsulanImport").addEventListener("click", () => fileInput.click());
  fileInput.addEventListener("change", () => {
    if (fileInput.files.length) importUsulanXlsx(fileInput.files[0]);
    fileInput.value = ""; // agar file yang sama bisa dipilih ulang
  });
  document.getElementById("btnUsulanExport").addEventListener("click", () => {
    window.location.href = "/api/usulan-inpres/export/xlsx";
  });
  document.getElementById("btnUsulanExportIjdScore").addEventListener("click", () => {
    // Ikut filter provinsi yang lagi aktif di panel Jelajahi — kosong = nasional.
    // Tampilkan preview dulu (bukan langsung unduh) supaya isinya bisa dicek.
    ijdPreviewOpen(state.usulanBrowse.provinsi || "");
  });
  document.getElementById("btnUsulanExportNpr").addEventListener("click", () => {
    nprPreviewOpen(state.usulanBrowse.provinsi || "");
  });
}

/* --- Preview "Output Penilaian" (Skor IJD) sebelum export xlsx --------- */

// ijdPreview.provinsi: ARRAY nama provinsi (kosong = nasional) -- multi-select
// + search, 22 Jul 2026 (sebelumnya string tunggal diwarisi dari filter
// panel "Jelajahi Usulan Inpres"; sekarang berdiri sendiri di dalam modal
// ini, lihat bindIjdPreviewProvinsiCombo).
const ijdPreview = { provinsi: [], offset: 0, limit: 50, total: 0 };
let ijdProvinsiOptionsCache = null; // [{provinsi, jumlah}], dimuat sekali
let ijdProvinsiPending = new Set(); // seleksi kerja selagi panel combo terbuka

function ijdPreviewUpdateProvinsiLabel() {
  const label = document.getElementById("ijdPreviewProvinsiLabel");
  const n = ijdPreview.provinsi.length;
  if (n === 0) label.textContent = "Semua provinsi (Nasional)";
  else if (n <= 2) label.textContent = ijdPreview.provinsi.join(", ");
  else label.textContent = `${n} provinsi dipilih`;
}

function ijdPreviewUpdateNarasiButton() {
  const btnNarasi = document.getElementById("ijdPreviewNarasiAi");
  // Backend tetap mewajibkan provinsi per panggilan (kuota LLM terkendali per
  // batch) -- tanpa filter provinsi, tombol ini memproses nasional dengan
  // loop per provinsi di sisi frontend (lihat ijdPreviewProsesNarasiAi),
  // bukan satu panggilan raksasa; dgn multi-select, loop per provinsi yg
  // DIPILIH (bukan ambil daftar semua provinsi dari API).
  btnNarasi.disabled = false;
  btnNarasi.title = ijdPreview.provinsi.length
    ? `Generate narasi AI Aspek B untuk usulan ${ijdPreview.provinsi.join(", ")} yang belum punya narasi`
    : "Generate narasi AI Aspek B untuk SEMUA provinsi (diproses satu per satu, bisa lama)";
}

async function ijdPreviewOpen(provinsi) {
  ijdPreview.provinsi = provinsi ? [provinsi] : [];
  ijdPreview.offset = 0;
  ijdPreviewUpdateProvinsiLabel();
  ijdPreviewUpdateNarasiButton();
  document.getElementById("ijdPreviewOverlay").hidden = false;
  await ijdPreviewFetchPage();
}

async function ijdPreviewProsesNarasiAi() {
  const btn = document.getElementById("ijdPreviewNarasiAi");
  const force = document.getElementById("ijdPreviewNarasiForce").checked;
  const progress = document.getElementById("ijdPreviewNarasiProgress");
  const progressFill = document.getElementById("ijdPreviewNarasiProgressFill");
  const progressText = document.getElementById("ijdPreviewNarasiProgressText");

  // Mode nasional (tanpa filter provinsi): ambil daftar provinsi lalu proses
  // satu-satu -- backend-nya tetap dipanggil per provinsi persis seperti mode
  // biasa, cuma di-loop otomatis di sini supaya kuota LLM per panggilan tetap
  // terkendali (bukan satu batch nasional 3000+ usulan).
  let daftarProvinsi = ijdPreview.provinsi.slice();
  if (!daftarProvinsi.length) {
    if (!confirm("Proses narasi AI untuk SEMUA provinsi? Ini bisa memakan waktu lama dan memanggil LLM berkali-kali.")) return;
    try {
      const res = await fetch("/api/usulan-inpres/provinsi");
      const rows = await res.json();
      if (!res.ok) throw new Error(rows.detail || "Gagal memuat daftar provinsi");
      daftarProvinsi = rows.map((r) => r.provinsi);
    } catch (err) {
      toast(err.message, true);
      return;
    }
  }

  btn.disabled = true;
  btn.innerHTML = '<i class="bi bi-arrow-repeat spin"></i> Memproses…';
  progress.hidden = false;
  let totalSemua = 0;
  try {
    for (let pIdx = 0; pIdx < daftarProvinsi.length; pIdx++) {
      const provinsi = daftarProvinsi[pIdx];
      const prefix = daftarProvinsi.length > 1
        ? `[${pIdx + 1}/${daftarProvinsi.length} ${provinsi}] `
        : "";
      let total = 0;
      let totalTarget = null; // diisi dari respons pertama (diproses + sisa)
      let afterId = 0;
      progressFill.style.width = "0%";
      progressText.textContent = `${prefix}Menyiapkan…`;
      // Backend memproses SATU batch (±20 usulan, 1 panggilan LLM) per request;
      // loop di sini sampai sisa 0 supaya ada progres dan tidak kena timeout.
      // force=true (checkbox "Timpa narasi lama") memproses ULANG semua usulan
      // provinsi ini walau sudah punya narasi -- backend pakai kursor id
      // (next_after_id) supaya tiap panggilan maju, bukan mengulang batch
      // pertama selamanya.
      for (;;) {
        const params = new URLSearchParams({ provinsi });
        if (force) {
          params.set("force", "true");
          params.set("after_id", afterId);
        }
        const res = await fetch(`/api/usulan-inpres/penilaian-bappenas/bulk?${params}`, { method: "POST" });
        const data = await res.json();
        if (!res.ok) throw new Error(`${provinsi}: ${data.detail || "Gagal memproses narasi AI"}`);
        total += data.diproses;
        totalSemua += data.diproses;
        if (totalTarget === null) totalTarget = data.diproses + data.sisa;
        afterId = data.next_after_id ?? afterId;
        const pct = totalTarget ? Math.round((total / totalTarget) * 100) : 0;
        progressFill.style.width = `${pct}%`;
        progressText.textContent = `${prefix}${total.toLocaleString("id-ID")} dari ${totalTarget.toLocaleString("id-ID")} (${pct}%)`;
        btn.innerHTML = `<i class="bi bi-arrow-repeat spin"></i> ${prefix}sisa ${data.sisa}`;
        if (data.sisa <= 0) break;
      }
    }
    toast(totalSemua
      ? `Narasi AI Aspek B selesai: ${totalSemua.toLocaleString("id-ID")} usulan diproses${daftarProvinsi.length > 1 ? ` di ${daftarProvinsi.length} provinsi` : ""}.`
      : force
        ? "Tidak ada usulan untuk diproses."
        : "Semua usulan sudah punya narasi AI Aspek B — centang \"Timpa narasi lama\" untuk memproses ulang.");
    await ijdPreviewFetchPage();
  } catch (err) {
    toast(err.message, true);
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<i class="bi bi-stars"></i> Proses Narasi AI';
    progress.hidden = true;
  }
}

async function ijdPreviewFetchPage() {
  const scroll = document.getElementById("ijdPreviewScroll");
  scroll.innerHTML = '<div class="datatable-loading"><i class="bi bi-hourglass-split"></i> Menghitung skor...</div>';
  try {
    const params = new URLSearchParams({ limit: ijdPreview.limit, offset: ijdPreview.offset });
    ijdPreview.provinsi.forEach((p) => params.append("provinsi", p));
    const res = await fetch(`/api/usulan-inpres/ijd-score/preview?${params}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Gagal memuat preview");
    ijdPreview.total = data.total;
    ijdPreviewRender(data);
  } catch (err) {
    scroll.innerHTML = `<div class="datatable-loading">${escapeHtml(err.message)}</div>`;
  }
}

// Ubah marker checklist teks polos dari backend ([Poin N] / [v] / [ ]) jadi
// badge + ikon centang — dipakai sel Aspek A/B di preview dan panel detail.
// Escape dulu, baru substitusi, supaya markup hasil substitusi tidak ikut
// ter-escape dan sisa teksnya tetap aman.
function checklistHtml(text) {
  return escapeHtml(text)
    .replace(/\[Poin (\d+)\]/g, '<span class="usulan-badge usulan-badge-ok ijd-badge">Poin $1</span>')
    .replace(/\[v\]/g, '<i class="bi bi-check-square-fill bool-true"></i>')
    .replace(/\[ \]/g, '<i class="bi bi-square bool-false"></i>');
}

function ijdPreviewRender(data) {
  document.getElementById("ijdPreviewTitle").textContent = data.label;
  document.getElementById("ijdPreviewMeta").textContent =
    `${data.total.toLocaleString("id-ID")} usulan`;

  const head = data.columns.map((c) => `<th>${escapeHtml(c)}</th>`).join("");
  // Kolom "No." / "ID": angka identitas, bukan kuantitas -- tanpa pemisah ribuan.
  const noSeparatorCols = new Set(data.columns.map((c, i) => (c === "No." || c === "ID" ? i : -1)).filter((i) => i >= 0));
  const cell = (v, i) => {
    if (v === null || v === undefined || v === "") return '<td class="null">—</td>';
    if (typeof v === "number") return `<td class="num">${noSeparatorCols.has(i) ? v : v.toLocaleString("id-ID")}</td>`;
    const s = String(v);
    // Sel checklist Aspek A/B: marker jadi ikon + tiap butir di baris sendiri.
    if (/\[Poin \d+\]|\[v\]|\[ \]/.test(s)) return `<td class="checklist-cell"><div>${checklistHtml(s)}</div></td>`;
    // Teks prosa panjang (Narasi AI, Kesimpulan): tampil terpotong,
    // teks lengkap di tooltip (title) saat hover.
    if (s.length > 220) return `<td class="prose-cell" title="${escapeHtml(s)}">${escapeHtml(s.slice(0, 200))}…</td>`;
    return `<td>${escapeHtml(s)}</td>`;
  };
  const body = data.rows.map((r) => `<tr>${r.map(cell).join("")}</tr>`).join("");
  document.getElementById("ijdPreviewScroll").innerHTML =
    `<table class="datatable"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;

  const page = Math.floor(data.offset / data.limit) + 1;
  const pages = Math.max(1, Math.ceil(data.total / data.limit));
  document.getElementById("ijdPreviewPageInfo").textContent = `Halaman ${page} dari ${pages.toLocaleString("id-ID")}`;
  document.getElementById("ijdPreviewPrev").disabled = data.offset <= 0;
  document.getElementById("ijdPreviewNext").disabled = data.offset + data.limit >= data.total;
}

function bindIjdPreview() {
  const overlay = document.getElementById("ijdPreviewOverlay");
  document.getElementById("ijdPreviewClose").addEventListener("click", () => (overlay.hidden = true));
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) overlay.hidden = true;
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !overlay.hidden) overlay.hidden = true;
  });

  document.getElementById("ijdPreviewPrev").addEventListener("click", () => {
    ijdPreview.offset = Math.max(0, ijdPreview.offset - ijdPreview.limit);
    ijdPreviewFetchPage();
  });
  document.getElementById("ijdPreviewNext").addEventListener("click", () => {
    if (ijdPreview.offset + ijdPreview.limit < ijdPreview.total) {
      ijdPreview.offset += ijdPreview.limit;
      ijdPreviewFetchPage();
    }
  });
  document.getElementById("ijdPreviewPageSize").addEventListener("change", (e) => {
    ijdPreview.limit = parseInt(e.target.value, 10);
    ijdPreview.offset = 0;
    ijdPreviewFetchPage();
  });
  document.getElementById("ijdPreviewExport").addEventListener("click", () => {
    const params = new URLSearchParams();
    ijdPreview.provinsi.forEach((p) => params.append("provinsi", p));
    window.location.href = `/api/usulan-inpres/ijd-score/export/xlsx?${params}`;
  });
  document.getElementById("ijdPreviewNarasiAi").addEventListener("click", ijdPreviewProsesNarasiAi);
  bindIjdPreviewProvinsiCombo();
}

// Combo multi-select + search provinsi, khusus modal Preview Export Skor IJD
// (22 Jul 2026, sebelumnya cuma mewarisi 1 provinsi dari filter panel
// "Jelajahi Usulan Inpres") -- daftar provinsi dimuat sekali (cache), dicek/
// dicentang bebas di panel (ijdProvinsiPending), baru diterapkan ke
// ijdPreview.provinsi & memicu fetch ulang saat tombol "Terapkan" diklik.
async function ijdPreviewLoadProvinsiOptions() {
  // Cache HANYA kalau isinya beneran array terisi -- array kosong dari
  // percobaan gagal sebelumnya sengaja TIDAK di-cache (beda dari pola cache
  // lain di file ini) supaya buka-panel berikutnya otomatis coba fetch
  // ulang, bukan macet permanen kalau kegagalan pertama cuma sesaat.
  if (ijdProvinsiOptionsCache && ijdProvinsiOptionsCache.length) return ijdProvinsiOptionsCache;
  try {
    const res = await fetch("/api/usulan-inpres/provinsi");
    const rows = await res.json();
    if (!res.ok) throw new Error(rows.detail || "Gagal memuat daftar provinsi");
    if (!Array.isArray(rows) || !rows.length) throw new Error("Respons daftar provinsi kosong/tidak terduga");
    ijdProvinsiOptionsCache = rows;
  } catch (err) {
    console.error("ijdPreviewLoadProvinsiOptions:", err);
    toast(`Gagal memuat daftar provinsi: ${err.message}`, true);
    ijdProvinsiOptionsCache = [];
  }
  return ijdProvinsiOptionsCache;
}

function ijdPreviewRenderProvinsiOptions(filterText) {
  const wrap = document.getElementById("ijdPreviewProvinsiOptions");
  const rows = ijdProvinsiOptionsCache || [];
  if (!rows.length) {
    wrap.innerHTML = '<div class="ijd-provinsi-empty">Gagal memuat daftar provinsi — coba tutup &amp; buka lagi panel ini.</div>';
    return;
  }
  const q = (filterText || "").trim().toUpperCase();
  const filtered = q ? rows.filter((r) => r.provinsi.toUpperCase().includes(q)) : rows;
  if (!filtered.length) {
    wrap.innerHTML = '<div class="ijd-provinsi-empty">Tidak ada provinsi cocok.</div>';
    return;
  }
  wrap.innerHTML = filtered.map((r) => {
    const checked = ijdProvinsiPending.has(r.provinsi);
    return `<label class="ijd-provinsi-option">
      <input type="checkbox" value="${escapeHtml(r.provinsi)}" ${checked ? "checked" : ""} />
      <span>${escapeHtml(r.provinsi)}</span>
      <span class="datatable-menu-count">${r.jumlah}</span>
    </label>`;
  }).join("");
}

function bindIjdPreviewProvinsiCombo() {
  const field = document.getElementById("ijdPreviewProvinsiField");
  const toggle = document.getElementById("ijdPreviewProvinsiToggle");
  const panel = document.getElementById("ijdPreviewProvinsiPanel");
  const search = document.getElementById("ijdPreviewProvinsiSearch");
  const optionsWrap = document.getElementById("ijdPreviewProvinsiOptions");

  toggle.addEventListener("click", async (e) => {
    e.stopPropagation();
    const willOpen = panel.hidden;
    if (willOpen) {
      await ijdPreviewLoadProvinsiOptions();
      ijdProvinsiPending = new Set(ijdPreview.provinsi);
      search.value = "";
      ijdPreviewRenderProvinsiOptions("");
    }
    panel.hidden = !willOpen;
    field.classList.toggle("open", willOpen);
    if (willOpen) search.focus();
  });

  search.addEventListener("input", () => ijdPreviewRenderProvinsiOptions(search.value));
  search.addEventListener("click", (e) => e.stopPropagation());

  optionsWrap.addEventListener("click", (e) => {
    const opt = e.target.closest(".ijd-provinsi-option");
    if (!opt) return;
    e.preventDefault();
    const cb = opt.querySelector("input");
    if (ijdProvinsiPending.has(cb.value)) ijdProvinsiPending.delete(cb.value);
    else ijdProvinsiPending.add(cb.value);
    cb.checked = ijdProvinsiPending.has(cb.value);
  });

  document.getElementById("ijdPreviewProvinsiClear").addEventListener("click", (e) => {
    e.stopPropagation();
    ijdProvinsiPending.clear();
    ijdPreviewRenderProvinsiOptions(search.value);
  });

  document.getElementById("ijdPreviewProvinsiApply").addEventListener("click", (e) => {
    e.stopPropagation();
    ijdPreview.provinsi = Array.from(ijdProvinsiPending).sort();
    ijdPreview.offset = 0;
    ijdPreviewUpdateProvinsiLabel();
    ijdPreviewUpdateNarasiButton();
    panel.hidden = true;
    field.classList.remove("open");
    ijdPreviewFetchPage();
  });

  document.addEventListener("click", (e) => {
    if (!panel.hidden && !field.contains(e.target)) {
      panel.hidden = true;
      field.classList.remove("open");
    }
  });
}

document.addEventListener("DOMContentLoaded", bindIjdPreview);

/* --- Preview "NPR" (Nilai Prioritas Ruas, eksperimental) sebelum export
   xlsx -- pola SAMA PERSIS dgn ijdPreview di atas, tanpa fitur Narasi AI
   (belum ada utk NPR, lihat kajian §6/§7 Fase 5). --------------------- */

const nprPreview = { provinsi: "", offset: 0, limit: 50, total: 0 };

async function nprPreviewOpen(provinsi) {
  nprPreview.provinsi = provinsi || "";
  nprPreview.offset = 0;
  document.getElementById("nprPreviewOverlay").hidden = false;
  await nprPreviewFetchPage();
}

async function nprPreviewFetchPage() {
  const scroll = document.getElementById("nprPreviewScroll");
  scroll.innerHTML = '<div class="datatable-loading"><i class="bi bi-hourglass-split"></i> Menghitung NPR...</div>';
  try {
    const params = new URLSearchParams({ limit: nprPreview.limit, offset: nprPreview.offset });
    if (nprPreview.provinsi) params.set("provinsi", nprPreview.provinsi);
    const res = await fetch(`/api/usulan-inpres/npr/preview?${params}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Gagal memuat preview");
    nprPreview.total = data.total;
    nprPreviewRender(data);
  } catch (err) {
    scroll.innerHTML = `<div class="datatable-loading">${escapeHtml(err.message)}</div>`;
  }
}

function nprPreviewRender(data) {
  document.getElementById("nprPreviewTitle").textContent = data.label;
  document.getElementById("nprPreviewMeta").textContent =
    `${data.total.toLocaleString("id-ID")} usulan`;

  const head = data.columns.map((c) => `<th>${escapeHtml(c)}</th>`).join("");
  // Kolom "No." / "ID": angka identitas, bukan kuantitas -- tanpa pemisah ribuan.
  const noSeparatorCols = new Set(data.columns.map((c, i) => (c === "No." || c === "ID" ? i : -1)).filter((i) => i >= 0));
  const cell = (v, i) => {
    if (v === null || v === undefined || v === "") return '<td class="null">—</td>';
    if (typeof v === "number") return `<td class="num">${noSeparatorCols.has(i) ? v : v.toLocaleString("id-ID")}</td>`;
    return `<td>${escapeHtml(String(v))}</td>`;
  };
  const body = data.rows.map((r) => `<tr>${r.map(cell).join("")}</tr>`).join("");
  document.getElementById("nprPreviewScroll").innerHTML =
    `<table class="datatable"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;

  const page = Math.floor(data.offset / data.limit) + 1;
  const pages = Math.max(1, Math.ceil(data.total / data.limit));
  document.getElementById("nprPreviewPageInfo").textContent = `Halaman ${page} dari ${pages.toLocaleString("id-ID")}`;
  document.getElementById("nprPreviewPrev").disabled = data.offset <= 0;
  document.getElementById("nprPreviewNext").disabled = data.offset + data.limit >= data.total;
}

function bindNprPreview() {
  const overlay = document.getElementById("nprPreviewOverlay");
  document.getElementById("nprPreviewClose").addEventListener("click", () => (overlay.hidden = true));
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) overlay.hidden = true;
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !overlay.hidden) overlay.hidden = true;
  });

  document.getElementById("nprPreviewPrev").addEventListener("click", () => {
    nprPreview.offset = Math.max(0, nprPreview.offset - nprPreview.limit);
    nprPreviewFetchPage();
  });
  document.getElementById("nprPreviewNext").addEventListener("click", () => {
    if (nprPreview.offset + nprPreview.limit < nprPreview.total) {
      nprPreview.offset += nprPreview.limit;
      nprPreviewFetchPage();
    }
  });
  document.getElementById("nprPreviewPageSize").addEventListener("change", (e) => {
    nprPreview.limit = parseInt(e.target.value, 10);
    nprPreview.offset = 0;
    nprPreviewFetchPage();
  });
  document.getElementById("nprPreviewExport").addEventListener("click", () => {
    const params = new URLSearchParams();
    if (nprPreview.provinsi) params.set("provinsi", nprPreview.provinsi);
    window.location.href = `/api/usulan-inpres/npr/export/xlsx?${params}`;
  });
}

document.addEventListener("DOMContentLoaded", bindNprPreview);

/* --- Dashboard Skor IJD Prioritisasi Teknokratik (A-E) -- reuse
   laporanKpiTile/laporanHBar/laporanDonut (didefinisikan di bawah, tapi
   `function` di-hoist jadi aman dipanggil dari sini) yang tadinya dibuat
   utk Dashboard Laporan Prioritas. Ditambahkan 21 Jul 2026. ------------ */

async function ijdDashboardOpen() {
  const overlay = document.getElementById("ijdDashboardOverlay");
  const view = document.getElementById("ijdDashboardView");
  overlay.hidden = false;
  view.innerHTML = '<div class="laporan-distribusi-empty"><i class="bi bi-hourglass-split"></i> Memuat dashboard...</div>';
  try {
    const params = new URLSearchParams();
    if (state.usulanBrowse.provinsi) params.set("provinsi", state.usulanBrowse.provinsi);
    const res = await fetch(`/api/usulan-inpres/ijd-score/dashboard?${params}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Gagal memuat dashboard");
    ijdDashboardRender(data);
  } catch (err) {
    view.innerHTML = `<div class="laporan-distribusi-empty">${escapeHtml(err.message)}</div>`;
  }
}

function ijdDashboardRender(data) {
  document.getElementById("ijdDashboardMeta").textContent =
    `${(data.provinsi || "Nasional")} · ${data.n_usulan.toLocaleString("id-ID")} usulan · kaidah ${data.tahun}`;

  const kpis = `<div class="laporan-kpi-row">
    ${laporanKpiTile("Jumlah Usulan", data.n_usulan.toLocaleString("id-ID"))}
    ${laporanKpiTile("Rata-rata Skor Tertimbang", `${data.avg_total} / ${data.maks_total}`, "jumlah kontribusi A-E yang tersedia, belum direnormalisasi")}
    ${laporanKpiTile("Tanpa Data Sama Sekali", data.n_tanpa_data.toLocaleString("id-ID"), "belum ada satu pun komponen A-E tersedia")}
    ${laporanKpiTile("Rata-rata NPR", data.avg_npr != null ? `${data.avg_npr} / 100` : "-", `eksperimental · ${data.n_dengan_npr.toLocaleString("id-ID")}/${data.n_usulan.toLocaleString("id-ID")} usulan bisa dihitung`)}
  </div>`;

  const top10Html = `<div class="laporan-chart-block">
    <div class="laporan-chart-title"><i class="bi bi-trophy"></i> Peringkat 10 Usulan — Skor NPR Tertinggi</div>
    <div class="laporan-chart-sub">NPR (Nilai Prioritas Ruas, eksperimental/belum policy resmi) -- basis sama dgn ranking di export Skor IJD, BUKAN skor_tertimbang A-E -- lihat catatan di bawah</div>
    ${laporanHBar(data.top10.filter((it) => it.npr != null).map((it) => ({ ...it, nama: it.nama_ruas })), {
      valueKey: "npr",
      maxLabelFn: (it) => `${it.nama_ruas} (${it.kabupaten_kota}): NPR ${it.npr} — skor teknokratis A-E ${it.total} dari ${it.n_komponen_tersedia}/5 komponen`,
      barLabelFn: (it) => `${it.npr}`,
    })}
  </div>`;

  const komposisiHtml = `<div class="laporan-chart-block">
    <div class="laporan-chart-title"><i class="bi bi-pie-chart"></i> Komposisi Kategori Prioritas</div>
    <div class="laporan-chart-sub">Tinggi &gt;50, Sedang &gt;25, Rendah &gt;0, dari skala ${data.maks_total}</div>
    ${laporanDonut(data.komposisi, data.n_usulan)}
  </div>`;

  const cakupanHtml = `<div class="laporan-chart-block">
    <div class="laporan-chart-title"><i class="bi bi-bar-chart-steps"></i> Cakupan Komponen A-E</div>
    <div class="laporan-chart-sub">% usulan yang punya data utk komponen itu</div>
    ${laporanHBar(data.cakupan_komponen, {
      valueKey: "count",
      maxLabelFn: (it) => `${it.label}: ${it.count} usulan (${it.pct}%)`,
      barLabelFn: (it) => `${it.pct}%`,
    })}
  </div>`;

  const komposisiNprHtml = `<div class="laporan-chart-block">
    <div class="laporan-chart-title"><i class="bi bi-bar-chart-steps"></i> Komposisi Kategori NPR</div>
    <div class="laporan-chart-sub">NPR eksperimental/belum policy resmi — "Belum Tersedia" beda dari "Belum Prioritas" (NPR &lt; 50 tapi terhitung)</div>
    ${laporanHBar(data.komposisi_npr, {
      valueKey: "count",
      maxLabelFn: (it) => `${it.label}: ${it.count} usulan (${it.pct}%)`,
      barLabelFn: (it) => `${it.pct}%`,
    })}
  </div>`;

  document.getElementById("ijdDashboardView").innerHTML =
    kpis + top10Html + komposisiHtml + komposisiNprHtml + cakupanHtml +
    `<p class="hint">${escapeHtml(data.catatan)}</p>`;
}

function bindIjdDashboard() {
  document.getElementById("btnIjdDashboard").addEventListener("click", ijdDashboardOpen);
  const overlay = document.getElementById("ijdDashboardOverlay");
  document.getElementById("ijdDashboardClose").addEventListener("click", () => (overlay.hidden = true));
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) overlay.hidden = true;
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !overlay.hidden) overlay.hidden = true;
  });
}

document.addEventListener("DOMContentLoaded", bindIjdDashboard);

/* --- Laporan Daerah Prioritas per Kabupaten/Kota (checklist Aspek A/B,
   docs/docs/laporan-validator.md) -- pola sama persis dgn ijdPreview di
   atas (view dulu sebelum export), bedanya wajib pilih provinsi dulu
   (laporan ini per-provinsi, tidak ada mode nasional). ------------------ */

const laporanPrioritas = {
  provinsi: "", offset: 0, limit: 50, total: 0, tab: "checklist",
  distribusi: null, dashboard: null,
};

function laporanPrioritasOpen() {
  laporanPrioritas.provinsi = "";
  laporanPrioritas.offset = 0;
  laporanPrioritas.distribusi = null;
  laporanPrioritas.dashboard = null;
  document.getElementById("laporanPrioritasProvinsiLabel").textContent = "Pilih provinsi...";
  document.getElementById("laporanPrioritasExport").disabled = true;
  document.getElementById("laporanPrioritasScroll").innerHTML =
    '<div class="datatable-loading">Pilih provinsi untuk melihat laporan.</div>';
  document.getElementById("laporanPrioritasTitle").textContent = "Laporan Daerah Prioritas";
  document.getElementById("laporanPrioritasMeta").textContent = "";
  document.getElementById("laporanDistribusiCharts").innerHTML =
    '<div class="laporan-distribusi-empty" id="laporanDistribusiEmpty">Pilih provinsi untuk melihat distribusi skor.</div>';
  document.getElementById("laporanPrioritasDashboardView").innerHTML =
    '<div class="laporan-distribusi-empty">Pilih provinsi untuk melihat dashboard.</div>';
  laporanPrioritasSwitchTab("checklist");
  document.getElementById("laporanPrioritasOverlay").hidden = false;
}

function laporanPrioritasSwitchTab(tab) {
  laporanPrioritas.tab = tab;
  document.getElementById("laporanTabChecklist").classList.toggle("active", tab === "checklist");
  document.getElementById("laporanTabDistribusi").classList.toggle("active", tab === "distribusi");
  document.getElementById("laporanTabDashboard").classList.toggle("active", tab === "dashboard");
  document.getElementById("laporanPrioritasChecklistView").hidden = tab !== "checklist";
  document.getElementById("laporanPrioritasDistribusiView").hidden = tab !== "distribusi";
  document.getElementById("laporanPrioritasDashboardView").hidden = tab !== "dashboard";
  if (tab === "distribusi" && laporanPrioritas.provinsi && !laporanPrioritas.distribusi) {
    laporanPrioritasFetchDistribusi();
  }
  if (tab === "dashboard" && laporanPrioritas.provinsi && !laporanPrioritas.dashboard) {
    laporanPrioritasFetchDashboard();
  }
}

async function laporanPrioritasFetchDistribusi() {
  const view = document.getElementById("laporanDistribusiCharts");
  view.innerHTML = '<div class="laporan-distribusi-empty"><i class="bi bi-hourglass-split"></i> Memuat distribusi...</div>';
  try {
    // Lebar rentang selalu ikut input "Lebar Rentang" (default 2, bisa
    // diubah + tombol "Proses" utk reload) -- BUKAN dinamis otomatis dari
    // backend, sesuai permintaan user 21 Jul 2026 (kontrol manual lebih
    // diutamakan drpd auto-calc ceil(maks/6) yg tetap tersedia di backend
    // kalau param step diomit).
    const step = document.getElementById("laporanDistribusiStep").value || 2;
    const params = new URLSearchParams({ provinsi: laporanPrioritas.provinsi, step });
    const res = await fetch(`/api/laporan-daerah-prioritas/distribusi?${params}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Gagal memuat distribusi skor");
    laporanPrioritas.distribusi = data;
    laporanPrioritasRenderDistribusi(data);
  } catch (err) {
    view.innerHTML = `<div class="laporan-distribusi-empty">${escapeHtml(err.message)}</div>`;
  }
}

// Histogram batang tunggal (1 hue) per rentang 2 poin -- jumlah checklist
// yang tercentang per kabupaten/kota (bukan skor IJD 0-100). Setiap "item"
// di sini = 1 induk kriteria dari docs/docs/laporan-validator.md (sub-item
// digabung, lihat _LAPORAN_GROUP_A/_B di app.py), maks 15 (Aspek A) / 12
// (Aspek B) poin -- skala dinamis dari data.maks_a/maks_b, bukan hardcode.
// Nama kabupaten/kota ditampilkan di daftar terpisah di bawah histogram
// (bukan disisipkan ke tiap kolom batang -- kolom tinggi tetap 160px
// beranchor-bawah, kalau nama diselipkan di situ untuk rentang berisi
// belasan kabupaten layoutnya akan meluap/rusak). Tiap rentang jadi satu
// baris "label (N): nama1, nama2, ...", rentang kosong dilewati.
function laporanChartBlock(title, sub, buckets, maks) {
  const nonZero = buckets.filter((b) => b.count > 0);
  const maxCount = Math.max(1, ...nonZero.map((b) => b.count));
  const bars = nonZero.map((b) => {
    const h = Math.round((b.count / maxCount) * 100);
    return `<div class="laporan-bar-col" title="${b.count} kabupaten/kota — skor ${b.label} dari ${maks}">
      <span class="laporan-bar-count">${b.count}</span>
      <div class="laporan-bar" style="height:${h}%"></div>
      <span class="laporan-bar-label">${escapeHtml(b.label)}</span>
    </div>`;
  }).join("");
  // Nama kabupaten KLIK-ABLE (drill-down ke kriteria yang match, lihat
  // laporanKabDrillDown) -- kode_kab dititip di data-attr, bukan cuma nama
  // (nama bisa ambigu/duplikat antar provinsi).
  const detailRows = buckets.filter((b) => b.count > 0).map((b) =>
    `<div class="laporan-bucket-row">
      <span class="laporan-bucket-label">Skor ${escapeHtml(b.label)} (${b.count} kab/kota)</span>
      <span class="laporan-bucket-names">${b.kabupaten.map((m) =>
        `<button type="button" class="laporan-kab-link" data-kode-kab="${m.kode_kab}">${escapeHtml(m.nama)}</button>`
      ).join(", ")}</span>
    </div>`).join("");
  return `<div class="laporan-chart-block">
    <div class="laporan-chart-title">${escapeHtml(title)}</div>
    <div class="laporan-chart-sub">${escapeHtml(sub)}</div>
    <div class="laporan-histogram">${bars}</div>
    <div class="laporan-bucket-detail">${detailRows}</div>
  </div>`;
}

function laporanPrioritasRenderDistribusi(data) {
  const view = document.getElementById("laporanDistribusiCharts");
  view.innerHTML =
    laporanChartBlock(
      "Aspek A — Prioritas dan Nilai Strategis",
      `Jumlah kabupaten/kota per rentang total kriteria tercentang (maks ${data.maks_a}), dari ${data.n_kabupaten} kabupaten/kota`,
      data.aspek_a, data.maks_a,
    ) +
    laporanChartBlock(
      "Aspek B — Daya Ungkit Ekonomi dan Kinerja Sektoral",
      `Jumlah kabupaten/kota per rentang total kriteria tercentang (maks ${data.maks_b}), dari ${data.n_kabupaten} kabupaten/kota`,
      data.aspek_b, data.maks_b,
    ) +
    `<div class="laporan-chart-block" id="laporanKabDrillDown" hidden></div>`;
}

// Drill-down: klik nama kabupaten di tab Distribusi Skor -> tampilkan
// kriteria checklist Aspek A/B mana saja yang match utk kabupaten itu
// (data sama dgn tab Checklist, tapi discoped ke 1 baris). Event delegation
// krn tombolnya di-render ulang tiap fetch (laporanPrioritasRenderDistribusi).
async function laporanKabDrillDown(kodeKab, nama) {
  const el = document.getElementById("laporanKabDrillDown");
  if (!el) return;
  el.hidden = false;
  el.innerHTML = `<div class="laporan-chart-title"><i class="bi bi-hourglass-split"></i> Memuat detail ${escapeHtml(nama)}...</div>`;
  el.scrollIntoView({ behavior: "smooth", block: "nearest" });
  try {
    const res = await fetch(`/api/laporan-daerah-prioritas/detail/${kodeKab}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Gagal memuat detail");
    // Aspek A tetap checklist ada/tidak ("cocok" boolean). Aspek B kini
    // skor 4-kelas (25/50/75/100) sejak 21 Jul 2026, bukan lagi ada/tidak
    // -- tampilkan Nilai-nya (badge berwarna sesuai besaran), item tanpa
    // data (nilai null) ditandai "Belum tersedia" abu-abu, BUKAN
    // disembunyikan (konsisten pola "belum tersedia bukan 0").
    const listA = (items) => items.filter((i) => i.cocok).map((i) =>
      `<div class="laporan-drilldown-item"><i class="bi bi-check-square-fill bool-true"></i> ${escapeHtml(i.label)}</div>`
    ).join("") || `<div class="hint">Tidak ada kriteria yang tercentang.</div>`;
    const listB = (items) => items.map((i) => {
      const badgeClass = i.nilai == null ? "usulan-badge-warn" : "usulan-badge-ok";
      const badgeText = i.nilai == null ? "Belum tersedia" : i.nilai;
      return `<div class="laporan-drilldown-item laporan-drilldown-item-skor">
        <span>${escapeHtml(i.label)}</span>
        <span class="usulan-badge ${badgeClass} ijd-badge">${badgeText}</span>
      </div>`;
    }).join("");
    el.innerHTML = `
      <div class="laporan-chart-title"><i class="bi bi-geo-alt-fill"></i> ${escapeHtml(data.nama)} — Kriteria yang Match</div>
      <div class="laporan-chart-2col">
        <div>
          <div class="laporan-chart-sub">Aspek A — Prioritas dan Nilai Strategis</div>
          ${listA(data.aspek_a)}
        </div>
        <div>
          <div class="laporan-chart-sub">Aspek B — Daya Ungkit Ekonomi dan Kinerja Sektoral (skor 4-kelas)</div>
          ${listB(data.aspek_b)}
        </div>
      </div>`;
  } catch (err) {
    el.innerHTML = `<div class="adv-error">${escapeHtml(String(err.message || err))}</div>`;
  }
}

/* --- Dashboard (tab ketiga): ringkasan siap-pakai utk pengambil kebijakan
   -- KPI, peringkat kabupaten/kota, komposisi kategori prioritas (donut),
   cakupan tiap kriteria (bar list), + perbandingan antar provinsi kalau
   scope-nya "Seluruh Indonesia". Semua dari 1 endpoint (sudah diagregasi
   di backend, JS di sini murni render). ------------------------------- */

async function laporanPrioritasFetchDashboard() {
  const view = document.getElementById("laporanPrioritasDashboardView");
  view.innerHTML = '<div class="laporan-distribusi-empty"><i class="bi bi-hourglass-split"></i> Memuat dashboard...</div>';
  try {
    const res = await fetch(`/api/laporan-daerah-prioritas/dashboard?provinsi=${laporanPrioritas.provinsi}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Gagal memuat dashboard");
    laporanPrioritas.dashboard = data;
    laporanPrioritasRenderDashboard(data);
  } catch (err) {
    view.innerHTML = `<div class="laporan-distribusi-empty">${escapeHtml(err.message)}</div>`;
  }
}

function laporanKpiTile(label, value, sub) {
  return `<div class="laporan-kpi-tile">
    <div class="laporan-kpi-value">${escapeHtml(String(value))}</div>
    <div class="laporan-kpi-label">${escapeHtml(label)}</div>
    ${sub ? `<div class="laporan-kpi-sub">${escapeHtml(sub)}</div>` : ""}
  </div>`;
}

// Bar list horizontal generik -- dipakai peringkat kabupaten/kota, cakupan
// kriteria, dan perbandingan provinsi (3 kebutuhan beda, 1 bentuk visual
// konsisten: magnitude tunggal per kategori, 1 hue, label langsung).
function laporanHBar(items, opts) {
  const { valueKey, maxLabelFn, barLabelFn } = opts;
  const maxVal = Math.max(1, ...items.map((it) => it[valueKey]));
  return `<div class="laporan-hbar-list">${items.map((it) => {
    const pct = Math.max(2, Math.round((it[valueKey] / maxVal) * 100));
    return `<div class="laporan-hbar-row" title="${escapeHtml(maxLabelFn(it))}">
      <span class="laporan-hbar-label">${escapeHtml(it.nama || it.label)}</span>
      <div class="laporan-hbar-track"><div class="laporan-hbar-fill" style="width:${pct}%"></div></div>
      <span class="laporan-hbar-value">${escapeHtml(barLabelFn(it))}</span>
    </div>`;
  }).join("")}</div>`;
}

const LAPORAN_KOMPOSISI_COLOR = {
  "Tinggi": "#4f7cff", "Sedang": "#7d9dff", "Rendah": "#b0c2ff", "Tidak ada data": "#4b5570",
};

function laporanDonut(komposisi, total) {
  let acc = 0;
  const stops = komposisi.filter((k) => k.count > 0).map((k) => {
    const start = (acc / total) * 100;
    acc += k.count;
    const end = (acc / total) * 100;
    return `${LAPORAN_KOMPOSISI_COLOR[k.label]} ${start}% ${end}%`;
  }).join(", ");
  const legend = komposisi.map((k) => `<div class="laporan-legend-row">
    <span class="laporan-legend-swatch" style="background:${LAPORAN_KOMPOSISI_COLOR[k.label]}"></span>
    <span class="laporan-legend-label">${escapeHtml(k.label)}</span>
    <span class="laporan-legend-value">${k.count} (${total ? Math.round(k.count / total * 100) : 0}%)</span>
  </div>`).join("");
  return `<div class="laporan-donut-wrap">
    <div class="laporan-donut" style="background:conic-gradient(${stops || "#4b5570 0% 100%"})">
      <div class="laporan-donut-hole"><span>${total}</span><small>kab/kota</small></div>
    </div>
    <div class="laporan-legend">${legend}</div>
  </div>`;
}

function laporanPrioritasRenderDashboard(data) {
  const view = document.getElementById("laporanPrioritasDashboardView");
  const kpis = `<div class="laporan-kpi-row">
    ${laporanKpiTile("Kabupaten/Kota", data.n_kabupaten.toLocaleString("id-ID"))}
    ${laporanKpiTile("Rata-rata Skor Gabungan", `${data.avg_total} / ${data.maks_total}`, `Aspek A ${data.avg_a}/${data.maks_a} · Aspek B ${data.avg_b}/${data.maks_b}`)}
    ${laporanKpiTile("Tanpa Data Sama Sekali", data.n_tanpa_data.toLocaleString("id-ID"), "skor 0 di kedua aspek")}
  </div>`;

  const top10Html = `<div class="laporan-chart-block">
    <div class="laporan-chart-title"><i class="bi bi-trophy"></i> Peringkat 10 Kabupaten/Kota — Skor Gabungan Tertinggi</div>
    <div class="laporan-chart-sub">Basis pertimbangan awal daerah prioritas pembangunan jalan (skor Aspek A + Aspek B, maks ${data.maks_total})</div>
    ${laporanHBar(data.top10, {
      valueKey: "total",
      maxLabelFn: (it) => `${it.nama}: total ${it.total} (A=${it.total_a}, B=${it.total_b})`,
      barLabelFn: (it) => `${it.total}`,
    })}
  </div>`;

  const komposisiHtml = `<div class="laporan-chart-block">
    <div class="laporan-chart-title"><i class="bi bi-pie-chart"></i> Komposisi Kategori Prioritas</div>
    <div class="laporan-chart-sub">Pembagian kabupaten/kota berdasar skor gabungan (Tinggi &gt;${Math.round(data.maks_total * 0.5)}, Sedang &gt;${Math.round(data.maks_total * 0.25)}, Rendah &gt;0, dari total ${data.maks_total})</div>
    ${laporanDonut(data.komposisi, data.n_kabupaten)}
  </div>`;

  const cakupanHtml = `<div class="laporan-chart-block laporan-chart-2col">
    <div>
      <div class="laporan-chart-title"><i class="bi bi-bar-chart-steps"></i> Cakupan Kriteria — Aspek A</div>
      <div class="laporan-chart-sub">% kabupaten/kota yang tercentang tiap kriteria</div>
      ${laporanHBar(data.cakupan_a, {
        valueKey: "count",
        maxLabelFn: (it) => `${it.label}: ${it.count} kab/kota (${it.pct}%)`,
        barLabelFn: (it) => `${it.pct}%`,
      })}
    </div>
    <div>
      <div class="laporan-chart-title"><i class="bi bi-bar-chart-steps"></i> Cakupan Kriteria — Aspek B</div>
      <div class="laporan-chart-sub">% kabupaten/kota yang tercentang tiap kriteria</div>
      ${laporanHBar(data.cakupan_b, {
        valueKey: "count",
        maxLabelFn: (it) => `${it.label}: ${it.count} kab/kota (${it.pct}%)`,
        barLabelFn: (it) => `${it.pct}%`,
      })}
    </div>
  </div>`;

  const provinsiHtml = data.provinsi ? `<div class="laporan-chart-block">
    <div class="laporan-chart-title"><i class="bi bi-map"></i> Perbandingan Rata-rata Skor Antar Provinsi</div>
    <div class="laporan-chart-sub">Rata-rata skor gabungan per kabupaten/kota, diurutkan tertinggi — 10 provinsi teratas</div>
    ${laporanHBar(data.provinsi.slice(0, 10), {
      valueKey: "avg_total",
      maxLabelFn: (it) => `${it.nama}: rata-rata ${it.avg_total} dari ${it.n_kabupaten} kab/kota`,
      barLabelFn: (it) => `${it.avg_total}`,
    })}
  </div>` : "";

  view.innerHTML = kpis + top10Html + komposisiHtml + cakupanHtml + provinsiHtml;
}

async function laporanPrioritasFetchPage() {
  if (!laporanPrioritas.provinsi) return;
  const scroll = document.getElementById("laporanPrioritasScroll");
  scroll.innerHTML = '<div class="datatable-loading"><i class="bi bi-hourglass-split"></i> Memuat laporan...</div>';
  try {
    const params = new URLSearchParams({
      provinsi: laporanPrioritas.provinsi,
      limit: laporanPrioritas.limit,
      offset: laporanPrioritas.offset,
    });
    const res = await fetch(`/api/laporan-daerah-prioritas/preview?${params}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Gagal memuat laporan");
    laporanPrioritas.total = data.total;
    laporanPrioritasRender(data);
  } catch (err) {
    scroll.innerHTML = `<div class="datatable-loading">${escapeHtml(err.message)}</div>`;
  }
}

function laporanPrioritasRender(data) {
  document.getElementById("laporanPrioritasTitle").textContent = data.label;
  document.getElementById("laporanPrioritasMeta").textContent =
    `${data.total.toLocaleString("id-ID")} kabupaten/kota`;

  // Baris grup di atas nama kolom -- identitas (Kode/Nama Kab) menyatu
  // visual dgn Aspek A (sama spt merge A1:Q1 di export xlsx), Aspek B
  // kolom sisanya, warna merah spt export supaya konsisten.
  const groupRow =
    `<th class="laporan-group-a" colspan="${2 + data.n_aspek_a}">Aspek Prioritas dan Nilai Strategis</th>` +
    `<th class="laporan-group-b" colspan="${data.n_aspek_b}">Aspek Daya Ungkit Ekonomi dan Kinerja Sektoral</th>`;
  const head = data.columns.map((c, i) =>
    `<th class="${i < 2 ? "laporan-id-col" : "laporan-check-col"}">${escapeHtml(c)}</th>`).join("");
  // Aspek A tetap checklist ada/tidak ("✓"/kosong). Aspek B (kolom mulai
  // 2+n_aspek_a) kini skor 4-kelas (25/50/75/100), bukan lagi ✓ -- tampilkan
  // angkanya sbg badge, "—" cuma utk yang genuinely belum tersedia (string
  // kosong dari backend). Sejak 21 Jul 2026.
  const aspekBStart = 2 + data.n_aspek_a;
  const cell = (v, i) => {
    if (i < 2) return `<td class="laporan-id-col">${escapeHtml(String(v ?? ""))}</td>`;
    if (i < aspekBStart) {
      return v === "✓"
        ? '<td class="laporan-check-col checkmark-cell"><i class="bi bi-check-square-fill bool-true"></i></td>'
        : '<td class="laporan-check-col null">—</td>';
    }
    return v === "" || v == null
      ? '<td class="laporan-check-col null">—</td>'
      : `<td class="laporan-check-col"><span class="usulan-badge usulan-badge-ok ijd-badge">${escapeHtml(String(v))}</span></td>`;
  };
  const body = data.rows.map((r) => `<tr>${r.map(cell).join("")}</tr>`).join("");
  document.getElementById("laporanPrioritasScroll").innerHTML =
    `<table class="datatable laporan-prioritas-table">
       <thead><tr>${groupRow}</tr><tr>${head}</tr></thead>
       <tbody>${body}</tbody>
     </table>`;

  const page = Math.floor(data.offset / data.limit) + 1;
  const pages = Math.max(1, Math.ceil(data.total / data.limit));
  document.getElementById("laporanPrioritasPageInfo").textContent = `Halaman ${page} dari ${pages.toLocaleString("id-ID")}`;
  document.getElementById("laporanPrioritasPrev").disabled = data.offset <= 0;
  document.getElementById("laporanPrioritasNext").disabled = data.offset + data.limit >= data.total;
}

function bindLaporanPrioritas() {
  document.getElementById("btnLaporanPrioritas").addEventListener("click", laporanPrioritasOpen);

  const overlay = document.getElementById("laporanPrioritasOverlay");
  document.getElementById("laporanPrioritasClose").addEventListener("click", () => (overlay.hidden = true));
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) overlay.hidden = true;
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !overlay.hidden) overlay.hidden = true;
  });

  document.getElementById("laporanTabChecklist").addEventListener("click", () => laporanPrioritasSwitchTab("checklist"));
  document.getElementById("laporanTabDistribusi").addEventListener("click", () => laporanPrioritasSwitchTab("distribusi"));
  document.getElementById("laporanTabDashboard").addEventListener("click", () => laporanPrioritasSwitchTab("dashboard"));

  // Drill-down tab Distribusi Skor: tombol nama kabupaten di-render ulang
  // tiap fetch, jadi delegasikan listener-nya ke view (bukan bind per-tombol).
  document.getElementById("laporanPrioritasDistribusiView").addEventListener("click", (e) => {
    const btn = e.target.closest(".laporan-kab-link");
    if (btn) laporanKabDrillDown(btn.dataset.kodeKab, btn.textContent);
  });
  document.getElementById("laporanDistribusiProses").addEventListener("click", () => {
    if (laporanPrioritas.provinsi) laporanPrioritasFetchDistribusi();
  });
  document.getElementById("laporanDistribusiStep").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && laporanPrioritas.provinsi) laporanPrioritasFetchDistribusi();
  });

  bindMapLayerCombo(
    "laporanPrioritasProvinsiField", "laporanPrioritasProvinsiToggle",
    "laporanPrioritasProvinsiPanel", "laporanPrioritasProvinsiLabel",
    async () => {
      // kode_provinsi=0 -> "Seluruh Indonesia" (tanpa filter provinsi,
      // backend agregat ke ~514 kab/kota nasional sekaligus).
      const rows = [{ kode_provinsi: 0, provinsi: "Seluruh Indonesia" }, ...(await dataViewerGeoProvinces())];
      fillComboPanel("laporanPrioritasProvinsiPanel", "laporanPrioritasProvinsiLabel",
        rows, "kode_provinsi", (r) => r.provinsi, laporanPrioritas.provinsi);
    },
    async (value) => {
      laporanPrioritas.provinsi = value;
      laporanPrioritas.offset = 0;
      laporanPrioritas.distribusi = null;
      laporanPrioritas.dashboard = null;
      document.getElementById("laporanPrioritasExport").disabled = false;
      laporanPrioritasFetchPage();
      if (laporanPrioritas.tab === "distribusi") laporanPrioritasFetchDistribusi();
      if (laporanPrioritas.tab === "dashboard") laporanPrioritasFetchDashboard();
    },
  );

  document.getElementById("laporanPrioritasPrev").addEventListener("click", () => {
    laporanPrioritas.offset = Math.max(0, laporanPrioritas.offset - laporanPrioritas.limit);
    laporanPrioritasFetchPage();
  });
  document.getElementById("laporanPrioritasNext").addEventListener("click", () => {
    if (laporanPrioritas.offset + laporanPrioritas.limit < laporanPrioritas.total) {
      laporanPrioritas.offset += laporanPrioritas.limit;
      laporanPrioritasFetchPage();
    }
  });
  document.getElementById("laporanPrioritasPageSize").addEventListener("change", (e) => {
    laporanPrioritas.limit = parseInt(e.target.value, 10);
    laporanPrioritas.offset = 0;
    laporanPrioritasFetchPage();
  });
  document.getElementById("laporanPrioritasExport").addEventListener("click", () => {
    if (!laporanPrioritas.provinsi) return;
    window.location.href = `/api/laporan-daerah-prioritas/export/xlsx?provinsi=${laporanPrioritas.provinsi}`;
  });
}

document.addEventListener("DOMContentLoaded", bindLaporanPrioritas);

function bindUsulanBrowse() {
  loadUsulanProvinsiOptions();
  loadUsulanKabupatenOptions("");
  loadUsulanBrowseList(true);
  bindUsulanProvinsiCombo();
  bindUsulanImportExport();

  let searchTimer = null;
  document.getElementById("usulanSearchInput").addEventListener("input", (e) => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      state.usulanBrowse.q = e.target.value.trim();
      loadUsulanBrowseList(true);
    }, 400);
  });

  document.getElementById("btnUsulanLoadMore").addEventListener("click", () => loadUsulanBrowseList(false));
}
