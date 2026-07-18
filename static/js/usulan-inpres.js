/* RouteGIS — Usulan Inpres Jalan/Jembatan: match-along-route, geometry overlay, browse & detail panel */

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

function bindUsulanProvinsiCombo() {
  const field = document.getElementById("usulanProvinsiField");
  const toggle = document.getElementById("usulanProvinsiToggle");
  const panel = document.getElementById("usulanProvinsiPanel");
  const label = document.getElementById("usulanProvinsiLabel");

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
    state.usulanBrowse.provinsi = opt.dataset.value;
    loadUsulanBrowseList(true);
  });

  document.addEventListener("click", (e) => {
    if (!panel.hidden && !field.contains(e.target)) {
      panel.hidden = true;
      field.classList.remove("open");
    }
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
  html += `<div class="usulan-ijd-score" id="usulanIjdScore"><div class="adv-loading">Menghitung skor prioritisasi IJD...</div></div>`;
  html += `<div class="usulan-ijd-score" id="usulanSkorNasional"></div>`;
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

  loadIjdScore(u.id);
  loadSkorNasional(u.id);
  loadPenilaianBappenas(u.id);
  await flyToUsulanGeometry(u);
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
    <p class="usulan-penilaian-narasi">${escapeHtml(narasi || "-")}</p>` +
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
}

/* --- Preview "Output Penilaian" (Skor IJD) sebelum export xlsx --------- */

const ijdPreview = { provinsi: "", offset: 0, limit: 50, total: 0 };

async function ijdPreviewOpen(provinsi) {
  ijdPreview.provinsi = provinsi || "";
  ijdPreview.offset = 0;
  // Proses bulk narasi AI HANYA per provinsi (kuota LLM terkendali) —
  // tanpa filter provinsi tombolnya dimatikan, bukan disembunyikan,
  // supaya user tahu fiturnya ada dan apa syaratnya.
  const btnNarasi = document.getElementById("ijdPreviewNarasiAi");
  btnNarasi.disabled = !ijdPreview.provinsi;
  btnNarasi.title = ijdPreview.provinsi
    ? `Generate narasi AI Aspek B untuk usulan ${ijdPreview.provinsi} yang belum punya narasi`
    : "Hanya bisa per provinsi — pilih filter provinsi di panel Jelajahi dulu";
  document.getElementById("ijdPreviewOverlay").hidden = false;
  await ijdPreviewFetchPage();
}

async function ijdPreviewProsesNarasiAi() {
  if (!ijdPreview.provinsi) return;
  const btn = document.getElementById("ijdPreviewNarasiAi");
  btn.disabled = true;
  btn.innerHTML = '<i class="bi bi-hourglass-split"></i> Memproses…';
  let total = 0;
  try {
    // Backend memproses SATU batch (±10 usulan, 1 panggilan LLM) per request;
    // loop di sini sampai sisa 0 supaya ada progres dan tidak kena timeout.
    for (;;) {
      const res = await fetch(
        `/api/usulan-inpres/penilaian-bappenas/bulk?provinsi=${encodeURIComponent(ijdPreview.provinsi)}`,
        { method: "POST" });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Gagal memproses narasi AI");
      total += data.diproses;
      if (data.sisa <= 0) break;
      btn.innerHTML = `<i class="bi bi-hourglass-split"></i> Memproses… (sisa ${data.sisa})`;
    }
    toast(total
      ? `Narasi AI Aspek B selesai: ${total} usulan diproses.`
      : "Semua usulan provinsi ini sudah punya narasi AI Aspek B.");
    await ijdPreviewFetchPage();
  } catch (err) {
    toast(err.message, true);
  } finally {
    btn.disabled = !ijdPreview.provinsi;
    btn.innerHTML = '<i class="bi bi-stars"></i> Proses Narasi AI';
  }
}

async function ijdPreviewFetchPage() {
  const scroll = document.getElementById("ijdPreviewScroll");
  scroll.innerHTML = '<div class="datatable-loading"><i class="bi bi-hourglass-split"></i> Menghitung skor...</div>';
  try {
    const params = new URLSearchParams({ limit: ijdPreview.limit, offset: ijdPreview.offset });
    if (ijdPreview.provinsi) params.set("provinsi", ijdPreview.provinsi);
    const res = await fetch(`/api/usulan-inpres/ijd-score/preview?${params}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Gagal memuat preview");
    ijdPreview.total = data.total;
    ijdPreviewRender(data);
  } catch (err) {
    scroll.innerHTML = `<div class="datatable-loading">${escapeHtml(err.message)}</div>`;
  }
}

function ijdPreviewRender(data) {
  document.getElementById("ijdPreviewTitle").textContent = data.label;
  document.getElementById("ijdPreviewMeta").textContent =
    `${data.total.toLocaleString("id-ID")} usulan`;

  const head = data.columns.map((c) => `<th>${escapeHtml(c)}</th>`).join("");
  const cell = (v) => {
    if (v === null || v === undefined || v === "") return '<td class="null">—</td>';
    if (typeof v === "number") return `<td class="num">${v.toLocaleString("id-ID")}</td>`;
    return `<td>${escapeHtml(String(v))}</td>`;
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
    if (ijdPreview.provinsi) params.set("provinsi", ijdPreview.provinsi);
    window.location.href = `/api/usulan-inpres/ijd-score/export/xlsx?${params}`;
  });
  document.getElementById("ijdPreviewNarasiAi").addEventListener("click", ijdPreviewProsesNarasiAi);
}

document.addEventListener("DOMContentLoaded", bindIjdPreview);

function bindUsulanBrowse() {
  loadUsulanProvinsiOptions();
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
