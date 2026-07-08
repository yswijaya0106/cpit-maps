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
        content: `<div class="usulan-info-tooltip"><strong>${escapeHtml(usulan.nama_kegiatan || usulan.nama_ruas)}</strong><br/>${escapeHtml(usulan.jenis_penanganan || "")} · ${formatRupiah(usulan.alokasi_usulan_pemda)}<br/>Panjang KML: ${kmlLengthKm.toFixed(2)} km</div>`,
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
  html += `<div class="adv-loading" id="usulanGeomStatus">Memuat lokasi di peta...</div></div>`;
  detailEl.innerHTML = html;

  detailEl.querySelectorAll(".usulan-note-toggle").forEach((el) => {
    el.addEventListener("click", () => {
      const expanded = el.dataset.expanded === "1";
      el.textContent = expanded ? el.dataset.preview : el.dataset.full;
      el.dataset.expanded = expanded ? "0" : "1";
    });
  });

  await flyToUsulanGeometry(u);
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
      content: `<div class="usulan-info-tooltip"><strong>${escapeHtml(u.nama_kegiatan || u.nama_ruas)}</strong><br/>Panjang KML: ${kmlLengthKm.toFixed(2)} km</div>`,
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
    if (statusEl) statusEl.remove();
  } catch (err) {
    console.error(err);
    if (statusEl) statusEl.textContent = "Gagal memuat geometri KML usulan ini.";
  }
}

function bindUsulanBrowse() {
  loadUsulanProvinsiOptions();
  loadUsulanBrowseList(true);
  bindUsulanProvinsiCombo();

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
