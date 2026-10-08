/* The Next - SiJalan — asisten chat analitik: jawaban markdown, kartu tabel/
   grafik/peta/laporan dari dataset hasil analisis (chat_dataset.py), unduhan
   Excel/CSV/GeoJSON/Word. Konteks rute aktif tetap dikirim spt sebelumnya. */

/* ---------- Konteks aplikasi (chip di atas kotak input) ----------
   Dulu konteks rute dikirim diam-diam setiap pertanyaan. Sekarang tiap bagian
   (rute, usulan yg dibuka, layer aktif) tampil sbg chip yg bisa dilepas (✕);
   yg dilepas tidak dikirim. Kunci chip memuat identitasnya (mis. usulan:123),
   jadi membuka usulan lain memunculkan chip baru lagi. */

function chatKonteksBagian() {
  const bagian = [];
  const route = state.routes[state.selectedIndex];
  if (route) {
    const data = {
      rute: { nama: route.route_name, mode_transportasi: route.transport_mode, jarak_km: route.distance_km, durasi_menit: route.duration_min },
    };
    if (state.lastAdminRegions) data.wilayah_administratif_dilalui = state.lastAdminRegions;
    if (state.lastRoadClass) data.klasifikasi_jalan_osm = state.lastRoadClass;
    if (state.lastUsulanNearby) data.usulan_inpres_di_sekitar_rute = state.lastUsulanNearby;
    bagian.push({ kunci: `rute:${route.route_name || ""}:${route.distance_km}`, ikon: "bi-signpost-split",
      label: `Rute ${route.distance_km != null ? `${route.distance_km} km` : "aktif"}`, data });
  }
  const u = state.usulanDilihat;
  if (u?.id != null && document.getElementById("usulanBrowseDetail")?.innerHTML.trim()) {
    bagian.push({ kunci: `usulan:${u.id}`, ikon: "bi-geo-alt", label: `Usulan #${u.id}${u.nama ? ` ${u.nama}` : ""}`,
      data: { usulan_dibuka: { id: u.id, nama: u.nama, provinsi: u.provinsi, kabupaten_kota: u.kabupaten } } });
  }
  const aktif = Object.keys(state.mapLayers?.active || {});
  if (aktif.length) {
    const layer = aktif.slice(-8).map((k) => {
      const m = state.mapLayers.meta[k] || {};
      return { nama: typeof mapLayerDisplayLabel === "function" ? mapLayerDisplayLabel(k) : m.layer,
        kelompok: m.provinsi, kabupaten: m.kabupaten, layer: m.layer };
    });
    bagian.push({ kunci: `layer:${aktif.join("|")}`, ikon: "bi-layers",
      label: aktif.length === 1 ? `Layer: ${layer[0].nama}` : `${aktif.length} layer aktif`,
      judul: layer.map((l) => l.nama).join("\n"), data: { layer_peta_aktif: layer } });
  }
  return bagian;
}

function buildChatContext() {
  const mati = state.chat.konteksMati || new Set();
  const bagian = chatKonteksBagian().filter((b) => !mati.has(b.kunci));
  if (!bagian.length) return null;
  return Object.assign({}, ...bagian.map((b) => b.data));
}

function renderChatKonteks() {
  const el = document.getElementById("chatKonteks");
  if (!el) return;
  const mati = state.chat.konteksMati || new Set();
  const bagian = chatKonteksBagian();
  el.hidden = !bagian.length;
  el.innerHTML = bagian.length
    ? `<span class="chat-konteks-label" title="Yang sedang Anda lihat di layar dan ikut dikirim ke asisten. Klik chip untuk melepas / menyertakan lagi.">Konteks:</span>`
      + bagian.map((b) => `<button type="button" class="chat-konteks-chip${mati.has(b.kunci) ? " mati" : ""}" data-kunci="${escapeHtml(b.kunci)}"
          title="${escapeHtml((b.judul || b.label) + (mati.has(b.kunci) ? "\n(tidak dikirim — klik untuk menyertakan)" : "\n(klik untuk tidak mengirim)"))}">
          <i class="bi ${b.ikon}"></i><span>${escapeHtml(b.label)}</span><i class="bi ${mati.has(b.kunci) ? "bi-plus" : "bi-x"}"></i></button>`).join("")
    : "";
  el.querySelectorAll(".chat-konteks-chip").forEach((c) => {
    c.onclick = () => {
      const k = c.dataset.kunci;
      if (mati.has(k)) mati.delete(k); else mati.add(k);
      state.chat.konteksMati = mati;
      renderChatKonteks();
    };
  });
}

/* ---------- Markdown ---------- */

/* Markdown ringan (cadangan kalau marked/DOMPurify dari CDN gagal dimuat):
   bold/italic/kode inline, daftar bernomor/poin, paragraf. escapeHtml()
   dijalankan LEBIH DULU, jadi HTML mentah dari model tidak pernah dieksekusi. */
function renderMarkdownLite(text) {
  const inline = (s) => s
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, "$1<em>$2</em>")
    .replace(/`([^`]+?)`/g, "<code>$1</code>");

  const lines = escapeHtml(text).split("\n");
  const html = [];
  // Model sering nulis "1. **X**:" lalu poin "- ..." di baris berikutnya sbg
  // RINCIAN nomor itu -- dilacak dua tingkat supaya jadi <ul> bersarang, bukan
  // menutup <ol> (bug 27 Jul 2026: panel skor IJD 5 komponen semua tampil "1.").
  let topList = null;
  let topLiOpen = false;
  let subList = null;

  const closeSub = () => { if (subList) { html.push(`</${subList}>`); subList = null; } };
  const closeTopLi = () => { closeSub(); if (topLiOpen) { html.push("</li>"); topLiOpen = false; } };
  const closeTop = () => { closeTopLi(); if (topList) { html.push(`</${topList}>`); topList = null; } };

  for (const raw of lines) {
    const line = raw.trim();
    if (!line) continue;
    const ol = line.match(/^\d+[.)]\s+(.*)/);
    const ul = line.match(/^[-*]\s+(.*)/);

    if (ol) {
      closeTopLi();
      if (topList !== "ol") { closeTop(); html.push("<ol>"); topList = "ol"; }
      html.push(`<li>${inline(ol[1])}`);
      topLiOpen = true;
    } else if (ul && topList === "ol" && topLiOpen) {
      if (!subList) { html.push("<ul>"); subList = "ul"; }
      html.push(`<li>${inline(ul[1])}</li>`);
    } else if (ul) {
      closeTopLi();
      if (topList !== "ul") { closeTop(); html.push("<ul>"); topList = "ul"; }
      html.push(`<li>${inline(ul[1])}</li>`);
    } else {
      closeTop();
      html.push(`<p>${inline(line)}</p>`);
    }
  }
  closeTop();
  return html.join("");
}

let chatMarkdownReady = false;
function renderMarkdown(text) {
  // marked (GFM: tabel, judul, daftar, kode) + DOMPurify: HTML hasil model
  // selalu disanitasi sebelum masuk DOM. Tanpa pustaka itu -> versi ringan.
  if (window.marked && window.DOMPurify) {
    if (!chatMarkdownReady) {
      window.marked.setOptions({ gfm: true, breaks: true });
      window.DOMPurify.addHook("afterSanitizeAttributes", (node) => {
        if (node.tagName === "A") { node.setAttribute("target", "_blank"); node.setAttribute("rel", "noopener"); }
      });
      chatMarkdownReady = true;
    }
    return window.DOMPurify.sanitize(window.marked.parse(text || ""));
  }
  return renderMarkdownLite(text || "");
}

/* ---------- Dataset (hasil analisis tersimpan di server) ---------- */

const chatDatasetCache = new Map(); // `${id}:${limit}` -> Promise(data)
let chatCharts = []; // instance Chart.js aktif -- di-destroy tiap render ulang (canvas lama dibuang)

function chatFetchDataset(id, limit = 100) {
  const key = `${id}:${limit}`;
  if (!chatDatasetCache.has(key)) {
    chatDatasetCache.set(key, fetch(`/api/chat/dataset/${encodeURIComponent(id)}?limit=${limit}`).then(async (res) => {
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || "Dataset tidak tersedia");
      return res.json();
    }));
  }
  return chatDatasetCache.get(key);
}

function chatFmt(v) {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "number") return v.toLocaleString("id-ID", { maximumFractionDigits: 3 });
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

function chatExportLinks(id, berlokasi) {
  const base = `/api/chat/dataset/${encodeURIComponent(id)}/export?format=`;
  return `<a class="chat-dl" href="${base}xlsx"><i class="bi bi-file-earmark-excel"></i> Excel</a>
    <a class="chat-dl" href="${base}csv"><i class="bi bi-filetype-csv"></i> CSV</a>
    ${berlokasi ? `<a class="chat-dl" href="${base}geojson"><i class="bi bi-geo-alt"></i> GeoJSON</a>` : ""}`;
}

/* ---------- Kartu hasil di dalam pesan ---------- */

function chatCardHtml(action, msgIdx, actIdx) {
  const a = action.argumen || {};
  const key = `${msgIdx}-${actIdx}`;
  if (action.nama === "tampilkan_tabel") {
    return `<div class="chat-card" data-card="tabel" data-key="${key}" data-id="${escapeHtml(a.dataset_id)}">
      <div class="chat-card-head"><i class="bi bi-table"></i> <span>${escapeHtml(a.judul || "Tabel hasil")}</span>
        <small>${(a.jumlah_baris ?? 0).toLocaleString("id-ID")} baris</small></div>
      <div class="chat-card-body chat-table-wrap"><div class="chat-card-loading">Memuat tabel…</div></div>
      <div class="chat-card-foot">${chatExportLinks(a.dataset_id, a.berlokasi)}</div>
    </div>`;
  }
  if (action.nama === "buat_grafik") {
    return `<div class="chat-card" data-card="grafik" data-key="${key}">
      <div class="chat-card-head"><i class="bi bi-bar-chart-line"></i> <span>${escapeHtml(a.judul || "Grafik")}</span></div>
      <div class="chat-card-body chat-chart-wrap"><canvas></canvas></div>
      <div class="chat-card-foot"><button type="button" class="chat-dl" data-act="png"><i class="bi bi-image"></i> Unduh PNG</button>
        ${chatExportLinks(a.dataset_id, false)}</div>
    </div>`;
  }
  if (action.nama === "tampilkan_di_peta") {
    return `<div class="chat-card chat-card-inline" data-card="peta" data-key="${key}" data-id="${escapeHtml(a.dataset_id)}">
      <i class="bi bi-map"></i> <span><strong>${escapeHtml(a.judul || "Hasil")}</strong> — ${(a.jumlah_fitur ?? 0).toLocaleString("id-ID")} fitur di peta</span>
      <button type="button" class="chat-dl" data-act="zoom"><i class="bi bi-zoom-in"></i> Zoom</button>
      <button type="button" class="chat-dl" data-act="toggle"><i class="bi bi-eye-slash"></i> <span>Sembunyikan</span></button>
    </div>`;
  }
  if (action.nama === "unduh_laporan") {
    return `<div class="chat-card chat-card-inline">
      <i class="bi bi-file-earmark-word"></i> <span><strong>${escapeHtml(a.nama_berkas || "Laporan.docx")}</strong>${a.lampiran ? ` · ${a.lampiran} lampiran tabel` : ""}</span>
      <a class="chat-dl chat-dl-primary" href="/api/chat/file/${encodeURIComponent(a.file_id)}"><i class="bi bi-download"></i> Unduh Word</a>
    </div>`;
  }
  return "";
}

// Semua dataset yg dibuat saat menjawab, termasuk query antara yg tidak
// ditampilkan sbg tabel -- supaya metode (SQL) & datanya tetap bisa dicek/unduh.
function chatDataListHtml(actions) {
  const ds = actions.filter((x) => x.nama === "dataset_tersedia").map((x) => x.argumen || {});
  if (!ds.length) return "";
  return `<details class="chat-datalist"><summary><i class="bi bi-database"></i> Data &amp; query (${ds.length})</summary>
    ${ds.map((d) => `<div class="chat-datalist-item">
      <div><strong>${escapeHtml(d.judul || "Hasil query")}</strong> · ${(d.jumlah_baris ?? 0).toLocaleString("id-ID")} baris
        <a class="chat-dl" href="/api/chat/dataset/${encodeURIComponent(d.dataset_id)}/export?format=xlsx"><i class="bi bi-file-earmark-excel"></i> Excel</a></div>
      <pre>${escapeHtml(d.sql || "")}</pre></div>`).join("")}
  </details>`;
}

function chatHydrateCards(listEl) {
  listEl.querySelectorAll('.chat-card[data-card="tabel"]').forEach(async (card) => {
    const body = card.querySelector(".chat-card-body");
    try {
      const d = await chatFetchDataset(card.dataset.id, 100);
      const lebih = d.total > d.rows.length ? `<div class="chat-table-note">Menampilkan ${d.rows.length} dari ${d.total.toLocaleString("id-ID")} baris — unduh Excel untuk data lengkap.</div>` : "";
      body.innerHTML = `<table class="chat-table"><thead><tr>${d.columns.map((c) => `<th>${escapeHtml(c)}</th>`).join("")}</tr></thead>
        <tbody>${d.rows.map((r) => `<tr>${r.map((v) => `<td class="${typeof v === "number" ? "num" : ""}">${escapeHtml(chatFmt(v))}</td>`).join("")}</tr>`).join("")}</tbody></table>${lebih}`;
    } catch (err) {
      body.innerHTML = `<div class="chat-card-loading">${escapeHtml(err.message)}</div>`;
    }
  });

  listEl.querySelectorAll('.chat-card[data-card="grafik"]').forEach(async (card) => {
    const [mi, ai] = card.dataset.key.split("-").map(Number);
    const a = state.chat.messages[mi]?.actions?.[ai]?.argumen;
    if (!a) return;
    const canvas = card.querySelector("canvas");
    card.querySelector('[data-act="png"]').onclick = () => {
      const link = document.createElement("a");
      link.href = canvas.toDataURL("image/png");
      link.download = `${(a.judul || "grafik").replace(/[^\w]+/g, "_")}.png`;
      link.click();
    };
    if (!window.Chart) { card.querySelector(".chat-card-body").textContent = "Pustaka grafik gagal dimuat."; return; }
    try {
      const d0 = await chatFetchDataset(a.dataset_id, 1000);
      const idx = (c) => d0.columns.indexOf(c);
      // urutan & batas kategori dari tool buat_grafik ("10 terbesar" dst) -- dataset asli tidak diubah
      let rows = d0.rows.slice();
      const iSort = idx(a.kolom_nilai[0]);
      if (a.urutan === "desc" || a.urutan === "asc") {
        const arah = a.urutan === "desc" ? -1 : 1;
        rows.sort((x, y) => arah * ((Number(x[iSort]) || 0) - (Number(y[iSort]) || 0)));
      }
      if (a.maks_kategori) rows = rows.slice(0, a.maks_kategori);
      const d = { ...d0, rows };
      const iLabel = idx(a.kolom_label);
      const palet = ["#4f7cff", "#22d3a5", "#ffb648", "#ff5c7c", "#a78bfa", "#38bdf8", "#f472b6", "#84cc16"];
      const teks = getComputedStyle(document.documentElement).getPropertyValue("--text-dim").trim() || "#94a3c4";
      let cfg;
      if (a.jenis === "scatter") {
        const iy = idx(a.kolom_nilai[0]);
        cfg = { type: "scatter", data: { datasets: [{ label: `${a.kolom_nilai[0]} vs ${a.kolom_label}`, backgroundColor: palet[0],
          data: d.rows.map((r) => ({ x: Number(r[iLabel]), y: Number(r[iy]) })) }] } };
      } else {
        const labels = d.rows.map((r) => chatFmt(r[iLabel]));
        const datasets = a.kolom_nilai.map((k, j) => ({
          label: k, data: d.rows.map((r) => (r[idx(k)] == null ? null : Number(r[idx(k)]))),
          backgroundColor: a.jenis === "pie" ? labels.map((_, i) => palet[i % palet.length]) : palet[j % palet.length],
          borderColor: palet[j % palet.length], borderWidth: a.jenis === "line" ? 2 : 0, tension: 0.25,
        }));
        cfg = { type: a.jenis, data: { labels, datasets } };
      }
      cfg.options = {
        responsive: true, maintainAspectRatio: false, animation: false,
        plugins: { legend: { labels: { color: teks, boxWidth: 12 } } },
        scales: a.jenis === "pie" ? {} : {
          x: { ticks: { color: teks, maxRotation: 60, autoSkip: true }, grid: { color: "rgba(148,163,196,.12)" } },
          y: { ticks: { color: teks }, grid: { color: "rgba(148,163,196,.12)" } },
        },
      };
      chatCharts.push(new window.Chart(canvas, cfg));
    } catch (err) {
      card.querySelector(".chat-card-body").textContent = err.message;
    }
  });

  listEl.querySelectorAll('.chat-card[data-card="peta"]').forEach((card) => {
    const layer = state.chatLayers?.[card.dataset.id];
    const toggle = card.querySelector('[data-act="toggle"]');
    const sync = () => {
      const tampil = layer && layer.data.getMap();
      toggle.querySelector("i").className = tampil ? "bi bi-eye-slash" : "bi bi-eye";
      toggle.querySelector("span").textContent = tampil ? "Sembunyikan" : "Tampilkan";
    };
    sync();
    toggle.onclick = () => { if (!layer) return; layer.data.setMap(layer.data.getMap() ? null : state.map); sync(); chatLayerBerubah(); };
    card.querySelector('[data-act="zoom"]').onclick = () => { if (layer && layer.bounds && !layer.bounds.isEmpty()) state.map.fitBounds(layer.bounds, 60); };
  });
}

/* ---------- Layer peta dari dataset ---------- */

const CHAT_LAYER_PALET = ["#e11d48", "#2563eb", "#16a34a", "#f59e0b", "#9333ea", "#0891b2", "#db2777", "#65a30d", "#ea580c", "#475569"];

async function chatTampilkanDiPeta(a) {
  if (!state.map || !a.dataset_id) return;
  state.chatLayers = state.chatLayers || {};
  // Hasil peta chat sebelumnya disembunyikan (masih bisa ditampilkan lagi dari kartunya):
  // dulu menumpuk -- "10 rute teratas" tergambar di atas SEMUA rute dari pertanyaan sebelumnya.
  Object.values(state.chatLayers).forEach((l) => l.data.setMap(null));
  const q = new URLSearchParams({ kolom_geometri: a.kolom_geometri || "", kolom_lat: a.kolom_lat || "", kolom_lon: a.kolom_lon || "" });
  const res = await fetch(`/api/chat/dataset/${encodeURIComponent(a.dataset_id)}/geojson?${q}`);
  if (!res.ok) { toast("Gagal menampilkan hasil analisis di peta", true); return; }
  const fc = await res.json();
  const data = new google.maps.Data({ map: state.map });
  data.addGeoJson({ type: "FeatureCollection", features: fc.features });
  const warnaKat = {};
  const warnaOf = (f) => {
    if (!a.kolom_warna) return CHAT_LAYER_PALET[0];
    const k = String(f.getProperty(a.kolom_warna) ?? "—");
    if (!(k in warnaKat)) warnaKat[k] = CHAT_LAYER_PALET[Object.keys(warnaKat).length % CHAT_LAYER_PALET.length];
    return warnaKat[k];
  };
  data.setStyle((f) => {
    const c = warnaOf(f);
    const t = f.getGeometry().getType();
    if (t === "Point" || t === "MultiPoint") {
      return { icon: { path: google.maps.SymbolPath.CIRCLE, scale: 6, fillColor: c, fillOpacity: 0.95, strokeColor: "#fff", strokeWeight: 1.5 }, zIndex: 60 };
    }
    return { strokeColor: c, strokeWeight: 3, strokeOpacity: 0.95, fillColor: c, fillOpacity: 0.25, zIndex: 55 };
  });
  const info = new google.maps.InfoWindow();
  data.addListener("click", (e) => {
    const rows = [];
    e.feature.forEachProperty((v, k) => rows.push(`<tr><th>${escapeHtml(k)}</th><td>${escapeHtml(chatFmt(v))}</td></tr>`));
    const judul = a.kolom_label ? e.feature.getProperty(a.kolom_label) : a.judul;
    info.setContent(`<div class="chat-map-info"><strong>${escapeHtml(chatFmt(judul))}</strong><table>${rows.join("")}</table></div>`);
    info.setPosition(e.latLng);
    info.open(state.map);
  });
  const bounds = new google.maps.LatLngBounds();
  const jenisN = { titik: 0, garis: 0, poligon: 0 };
  data.forEach((f) => {
    const g = f.getGeometry();
    if (!g) return;
    g.forEachLatLng((ll) => bounds.extend(ll));
    warnaOf(f); // isi warnaKat utk legenda
    const t = g.getType();
    jenisN[/Point/.test(t) ? "titik" : /Polygon/.test(t) ? "poligon" : "garis"]++;
  });
  if (!bounds.isEmpty()) state.map.fitBounds(bounds, 60);
  state.chatLayers[a.dataset_id] = {
    data, bounds, judul: a.judul || "Hasil analisis asisten", kolomWarna: a.kolom_warna || null,
    kolomLabel: a.kolom_label || null, warnaKat, warna: CHAT_LAYER_PALET[0],
    jenis: Object.entries(jenisN).sort((x, y) => y[1] - x[1])[0][0], jumlah: fc.features.length,
  };
  renderChatMessages();
  chatLayerBerubah();
}

// Layer hasil chat ikut di Legend — Layer Aktif & Cetak Peta (map-tools.js / print-map.js)
function chatLayerBerubah() {
  if (typeof updateMapLegend === "function") updateMapLegend();
}

function chatLayerTampil() {
  return Object.entries(state.chatLayers || {}).filter(([, l]) => l.data.getMap());
}

function chatSembunyikanLayer(id) {
  const l = state.chatLayers?.[id];
  if (!l) return;
  l.data.setMap(null);
  renderChatMessages();
  chatLayerBerubah();
}

/* ---------- Render pesan ---------- */

function renderChatMessages() {
  const listEl = document.getElementById("chatMessages");
  if (!listEl) return;
  chatCharts.forEach((c) => c.destroy());
  chatCharts = [];
  listEl.innerHTML = state.chat.messages.map((m, i) => {
    if (m.role !== "assistant") return `<div class="chat-msg chat-msg-user">${escapeHtml(m.text)}</div>`;
    const actions = m.actions || [];
    const cards = actions.map((a, j) => chatCardHtml(a, i, j)).join("");
    const contoh = m.contoh ? `<div class="chat-examples">${m.contoh.map((t) => `<button type="button" class="chat-example">${escapeHtml(t)}</button>`).join("")}</div>` : "";
    return `<div class="chat-msg chat-msg-assistant"><div class="chat-md">${renderMarkdown(m.text)}</div>${cards}${chatDataListHtml(actions)}${contoh}${chatMetaHtml(m.meta, i)}</div>`;
  }).join("");
  if (state.chat.busy) {
    listEl.innerHTML += `<div class="chat-msg chat-msg-assistant chat-msg-loading"><span class="chat-spinner"></span> Menganalisis data… analisis besar bisa perlu 1–2 menit.</div>`;
  }
  chatHydrateCards(listEl);
  listEl.querySelectorAll(".chat-example").forEach((b) => { b.onclick = () => sendChatMessage(b.textContent); });
  listEl.querySelectorAll(".chat-nilai").forEach((b) => {
    b.onclick = () => chatKirimNilai(Number(b.dataset.msg), Number(b.dataset.nilai));
  });
  listEl.scrollTop = listEl.scrollHeight;
  renderChatKonteks();
}

// Baris kecil "dijawab oleh <model>" di bawah jawaban (meta dari /api/chat).
// Model cadangan = provider di depannya gagal (mis. kredit Claude habis) --
// dulu terjadi diam-diam, kini terlihat beserta alasannya di tooltip.
function chatMetaHtml(meta, idx) {
  if (!meta || !meta.model) return "";
  // 👍/👎 (Tahap 4b): masuk chat_log, bahan scripts/belajar_catatan_chat.py.
  const nilai = meta.chat_log_id
    ? ` <span class="chat-nilai-grup">${[[1, "bi-hand-thumbs-up", "Jawaban membantu"], [-1, "bi-hand-thumbs-down", "Jawaban salah / kurang tepat"]]
      .map(([v, ikon, judul]) => `<button type="button" class="chat-nilai${meta.nilai === v ? " aktif" : ""}" data-msg="${idx}" data-nilai="${v}" title="${judul}"><i class="bi ${ikon}${meta.nilai === v ? "-fill" : ""}"></i></button>`).join("")}</span>`
    : "";
  const alasan = (meta.gagal_sebelumnya || []).map((g) => `${g.provider}: ${g.alasan}`).join("\n");
  const cadangan = meta.cadangan
    ? ` <span class="chat-meta-cadangan" title="${escapeHtml("Provider utama gagal:\n" + alasan)}">model cadangan</span>`
    : "";
  const durasi = meta.durasi_detik != null ? ` · ${String(meta.durasi_detik).replace(".", ",")} dtk` : "";
  const revisi = meta.direvisi ? ` · <span title="Jawaban pertama tidak lolos pemeriksaan otomatis (mis. query kosong, grafik belum dibuat) lalu diperbaiki">diperiksa ulang</span>` : "";
  return `<div class="chat-meta">dijawab oleh ${escapeHtml(meta.model)}${durasi}${revisi}${cadangan}${nilai}</div>`;
}

async function chatKirimNilai(idx, nilai) {
  const m = state.chat.messages[idx];
  if (!m || !m.meta || !m.meta.chat_log_id) return;
  if (m.meta.nilai === nilai) nilai = 0; // klik ulang = batal
  let komentar = null;
  if (nilai === -1) {
    komentar = window.prompt("Apa yang salah atau kurang dari jawaban ini? (opsional)", "");
    if (komentar === null) return; // dibatalkan
  }
  try {
    const res = await fetch("/api/chat/umpan-balik", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chat_log_id: m.meta.chat_log_id, nilai, komentar, jawaban: nilai === -1 ? m.text : null }),
    });
    if (!res.ok) throw new Error((await res.json()).detail || res.statusText);
    m.meta.nilai = nilai || null;
    renderChatMessages();
    chatSimpan();
    if (nilai === -1) toast("Terima kasih, masukan dicatat untuk perbaikan asisten.");
  } catch (err) {
    toast(`Gagal mengirim penilaian: ${err.message || err}`, true);
  }
}

// Panel status provider (admin): hasil GET /api/chat/status-provider dirender
// sebagai pesan lokal (flag `lokal`, tidak dikirim ke model sbg riwayat).
async function chatTampilkanStatusProvider() {
  if (state.chat.busy) return;
  state.chat.busy = true;
  renderChatMessages();
  let teks;
  try {
    const res = await fetch("/api/chat/status-provider?paksa=1");
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Gagal memuat status");
    const baris = data.providers.map((p, i) =>
      `| ${i + 1} | ${p.provider} | ${p.model} | ${p.ok ? "✅ aktif" : "❌ " + (p.alasan || "gagal")} |`).join("\n");
    teks = `**Status provider AI** (urutan prioritas, diuji ${new Date(data.diuji_pada).toLocaleString("id-ID")})\n\n`
      + `| # | Provider | Model | Status |\n|---|---|---|---|\n${baris}\n\n`
      + (data.provider_aktif ? `Chat saat ini dijawab oleh **${data.provider_aktif}**.` : "**Tidak ada provider yang aktif.**");
  } catch (err) {
    teks = `Gagal memuat status provider: ${err.message || err}`;
  }
  state.chat.messages.push({ role: "assistant", text: teks, lokal: true });
  state.chat.busy = false;
  renderChatMessages();
}

// Riwayat yg dikirim ke backend: teks + catatan dataset yang sudah dibuat,
// supaya model bisa merujuknya lagi ("ekspor hasil tadi ke Word"), + blok
// <memori> (tool/SQL/cuplikan hasil, dari backend) utk CHAT_MEMORI_GILIRAN
// jawaban terakhir. Percakapan panjang dipotong ke CHAT_MAKS_RIWAYAT pesan
// terakhir supaya model tetap fokus & token tidak membengkak.
const CHAT_MAKS_RIWAYAT = 20;
const CHAT_MEMORI_GILIRAN = 3;
function chatHistoryPayload() {
  let msgs = state.chat.messages.filter((m) => !m.contoh && !m.lokal).slice(-CHAT_MAKS_RIWAYAT);
  while (msgs.length && msgs[0].role !== "user") msgs = msgs.slice(1); // API Claude: pesan pertama harus user
  const asisten = msgs.filter((m) => m.role === "assistant");
  const denganMemori = new Set(asisten.slice(-CHAT_MEMORI_GILIRAN));
  return msgs.map((m) => {
    const ds = (m.actions || []).filter((a) => a.nama === "dataset_tersedia").map((a) => a.argumen);
    const catatan = ds.length
      ? "\n\n[Dataset dari jawaban ini: " + ds.map((d) => `${d.dataset_id} = "${d.judul}" (${d.jumlah_baris} baris; kolom: ${(d.kolom || []).join(", ")})`).join("; ") + "]"
      : "";
    const memori = m.memori && denganMemori.has(m) ? `\n\n<memori>\n${m.memori}\n</memori>` : "";
    return { role: m.role, text: (m.text || "") + catatan + memori };
  });
}

// Percakapan disimpan per tab (sessionStorage): tidak hilang saat reload
// (mis. setelah login), hilang saat tab ditutup / "Percakapan baru".
const CHAT_SIMPAN_KUNCI = "chatPercakapan";
function chatSimpan() {
  try {
    const msgs = state.chat.messages.filter((m) => !m.contoh);
    if (!msgs.length) { sessionStorage.removeItem(CHAT_SIMPAN_KUNCI); return; }
    const json = JSON.stringify(msgs);
    if (json.length < 2_000_000) sessionStorage.setItem(CHAT_SIMPAN_KUNCI, json);
  } catch (e) { /* storage penuh/diblokir: percakapan berlaku sampai reload */ }
}
function chatMuat() {
  try {
    const msgs = JSON.parse(sessionStorage.getItem(CHAT_SIMPAN_KUNCI) || "null");
    return Array.isArray(msgs) && msgs.length ? msgs : null;
  } catch (e) { return null; }
}

async function sendChatMessage(text) {
  if (!text.trim() || state.chat.busy) return;

  state.chat.messages.push({ role: "user", text: text.trim() });
  state.chat.busy = true;
  renderChatMessages();

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages: chatHistoryPayload(), context: buildChatContext() }),
    });
    if (!res.ok) {
      let detail = "";
      try { detail = (await res.json()).detail || ""; } catch (_) { /* bukan JSON */ }
      throw new Error(detail || `HTTP ${res.status}`);
    }
    const data = await res.json();
    state.chat.messages.push({ role: "assistant", text: data.reply, actions: data.actions || [], meta: data.meta, memori: data.memori || "" });
    (data.actions || []).forEach(runChatAction);
  } catch (err) {
    console.error(err);
    const detail = String(err.message || "");
    state.chat.messages.push({
      role: "assistant", lokal: true,
      text: detail.startsWith("Semua provider LLM gagal")
        ? `Maaf, asisten sedang tidak tersedia. ${detail}`
        : "Maaf, terjadi kesalahan saat menghubungi asisten. Coba lagi.",
    });
  } finally {
    state.chat.busy = false;
    renderChatMessages();
    chatSimpan();
    // Setelah jawaban pertama, sorot tombol "Chat baru" sekali: tanda bisa mulai topik baru
    if (state.chat.messages.filter((m) => m.role === "user").length === 1) {
      const b = document.getElementById("chatBaru");
      if (b) { b.classList.remove("sorot"); void b.offsetWidth; b.classList.add("sorot"); }
    }
  }
}

/* Aksi yang dieksekusi di FRONTEND atas perintah model, lewat data.actions
   dari /api/chat. Key di sini HARUS sinkron dengan nama aksi yang dikirim
   backend (CLIENT_ACTION_TOOLS / tool hibrida di chat_providers.py). Aksi yg
   hanya berupa kartu (tampilkan_tabel, buat_grafik, unduh_laporan,
   dataset_tersedia) dirender renderChatMessages, tanpa efek samping di sini. */
const CHAT_CLIENT_ACTIONS = {
  tampilkan_usulan_di_peta: (args) => {
    if (!args || args.id == null) return;
    if (typeof loadUsulanDetail !== "function") return;
    loadUsulanDetail(args.id);
    document.getElementById("usulanBrowseDetail")?.scrollIntoView({ behavior: "smooth", block: "center" });
  },
  tampilkan_layer_peta_overlay: (args) => {
    if (!args || !args.provinsi || args.layer == null) return;
    if (typeof showMapLayer !== "function") return;
    showMapLayer(args.provinsi, args.kabupaten ?? "", args.layer);
  },
  tampilkan_di_peta: (args) => { chatTampilkanDiPeta(args || {}).catch((e) => console.error(e)); },
  // analisis_kabupaten (chat_providers.py): ruas usulan IJD kab/kota itu dipilih (multi-select) & peta di-zoom.
  tampilkan_usulan_kabupaten: (args) => { chatTampilkanUsulanKabupaten(args || {}).catch((e) => console.error(e)); },
  zoom_ke_bbox: (args) => {
    if (!state.map || args.barat == null) return;
    state.map.fitBounds(new google.maps.LatLngBounds({ lat: args.selatan, lng: args.barat }, { lat: args.utara, lng: args.timur }));
  },
};

async function chatTampilkanUsulanKabupaten(args) {
  if (!args.kabupaten_kota || typeof toggleUsulanMulti !== "function") return;
  const res = await fetch(`/api/usulan-inpres?kabupaten_kota=${encodeURIComponent(args.kabupaten_kota)}&limit=200`);
  if (!res.ok) return;
  const data = await res.json();
  const antrean = (data.usulan || []).filter((u) => u.has_geometry);
  const pekerja = Array.from({ length: 6 }, async () => {
    while (antrean.length) await toggleUsulanMulti(antrean.shift(), true);
  });
  await Promise.all(pekerja);
}

function runChatAction(action) {
  const fn = CHAT_CLIENT_ACTIONS[action?.nama];
  if (fn) fn(action.argumen || {});
}

const CHAT_GREETING = "Halo! Saya bisa menganalisis **seluruh data** aplikasi ini — usulan IJD, BPS, pelabuhan, bandara, " +
  "kereta api, Basarnas, koridor, dan layer peta — lalu menyajikannya sebagai **tabel, grafik, peta**, dan " +
  "**unduhan Excel/Word**. Tanya bebas, atau coba contoh di bawah:";
/* Contoh prompt DINAMIS: dulu 4 kalimat tetap. Sekarang (1) contoh kontekstual
   dari apa yg sedang dibuka user -- usulan yg dilihat, layer overlay aktif, rute
   aktif -- didahulukan, lalu (2) sisanya diacak dari CHAT_CONTOH_POOL dengan
   {prov} diisi provinsi usulan yg dilihat, atau provinsi acak. Dibangun ulang
   setiap panel dibuka selama percakapan belum dimulai. */
const CHAT_PROVINSI = [
  "Aceh", "Sumatera Utara", "Sumatera Barat", "Riau", "Jambi", "Sumatera Selatan", "Bengkulu", "Lampung",
  "Kepulauan Bangka Belitung", "Kepulauan Riau", "Jawa Barat", "Jawa Tengah", "DI Yogyakarta", "Jawa Timur",
  "Banten", "Bali", "Nusa Tenggara Barat", "Nusa Tenggara Timur", "Kalimantan Barat", "Kalimantan Tengah",
  "Kalimantan Selatan", "Kalimantan Timur", "Kalimantan Utara", "Sulawesi Utara", "Sulawesi Tengah",
  "Sulawesi Selatan", "Sulawesi Tenggara", "Gorontalo", "Sulawesi Barat", "Maluku", "Maluku Utara",
  "Papua", "Papua Barat", "Papua Selatan", "Papua Tengah", "Papua Pegunungan", "Papua Barat Daya",
];
const CHAT_CONTOH_POOL = [
  "Analisa semua pelabuhan dan bandara di {prov} beserta koridor IJD dan Kantor SAR terdekat, tampilkan di peta",
  "Buat grafik 10 kabupaten/kota di {prov} dengan usulan IJD 2026 terbanyak beserta total panjang ruasnya",
  "Buat grafik 10 provinsi dengan usulan IJD 2026 terbanyak beserta total panjang ruasnya",
  "Susun laporan Word kondisi jalan nasional (IRI) per provinsi",
  "Bagaimana kondisi kemantapan jalan nasional (IRI) di {prov}? Tampilkan ruas terburuk dalam tabel",
  "Stasiun kereta api mana saja di Jawa Barat dan bagaimana utilisasi kapasitas lintasnya?",
  "Petak jalan KA mana di Sumatera yang kapasitas lintasnya paling padat? Tampilkan di peta",
  "Tampilkan 10 usulan IJD 2026 dengan skor NPR tertinggi di {prov} dalam tabel dan ekspor ke Excel",
  "Bandara di {prov} mana yang permintaan penumpangnya melebihi kapasitas terminal?",
  "Berapa jumlah usulan IJD per jenis penanganan di {prov}? Buat grafik batang",
  "Kantor SAR mana yang waktu respon operasinya paling lama? Buat tabel dan grafik",
  "Analisis Kabupaten Bandung: jaringan jalan, usulan IJD, dan konektivitasnya",
  "Bandingkan tren penumpang dan bongkar muat barang pelabuhan di {prov} beberapa tahun terakhir",
  "Kabupaten/kota mana di {prov} yang tidak dilalui koridor IJD sama sekali?",
  "Rangkum data kecelakaan lalu lintas di {prov} 2020-2025 dalam grafik tren",
];

function chatAcak(arr) {
  const a = arr.slice();
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

function chatContohDinamis(jumlah = 4) {
  const kontekstual = [];
  const u = state.usulanDilihat;
  if (u?.id != null) {
    const nama = u.nama ? `"${u.nama}"` : `#${u.id}`;
    kontekstual.push(`Hitung skor IJD usulan ${nama} (id ${u.id}) dan jelaskan komponen yang belum tersedia`);
    kontekstual.push(`Bandara, pelabuhan, dan koridor IJD apa yang terdekat dari usulan ${nama} (id ${u.id})? Tampilkan di peta`);
  }
  if (state.routes?.[state.selectedIndex]) {
    kontekstual.push("Usulan IJD apa saja di sekitar rute ini, dan bagaimana kondisi jalannya?");
  }
  const aktif = Object.keys(state.mapLayers?.active || {});
  if (aktif.length && typeof mapLayerDisplayLabel === "function") {
    const key = aktif[aktif.length - 1];
    const m = state.mapLayers.meta[key] || {};
    const lokasi = [m.kabupaten, m.provinsi].filter(Boolean).join(", ");
    kontekstual.push(`Ringkas isi layer "${mapLayerDisplayLabel(key)}"${lokasi ? ` (${lokasi})` : ""} dalam tabel dan grafik`);
  }

  const prov = u?.provinsi || CHAT_PROVINSI[Math.floor(Math.random() * CHAT_PROVINSI.length)];
  const hasil = chatAcak(kontekstual).slice(0, Math.min(2, jumlah));
  for (const t of chatAcak(CHAT_CONTOH_POOL)) {
    if (hasil.length >= jumlah) break;
    const isi = t.replaceAll("{prov}", prov);
    if (!hasil.includes(isi)) hasil.push(isi);
  }
  return hasil;
}

// Segarkan contoh hanya selama percakapan belum dimulai (cuma sapaan).
function refreshChatContoh() {
  const msgs = state.chat.messages;
  if (msgs.length !== 1 || !msgs[0].contoh || state.chat.busy) return;
  msgs[0].contoh = chatContohDinamis();
  renderChatMessages();
}

function resetChat() {
  state.chat.messages = [{ role: "assistant", text: CHAT_GREETING, contoh: chatContohDinamis() }];
  state.chat.busy = false;
  state.chat.konteksMati = new Set();
  Object.values(state.chatLayers || {}).forEach((l) => l.data.setMap(null));
  state.chatLayers = {};
  renderChatMessages();
  chatSimpan();
  chatLayerBerubah();
}

// Tombol "Percakapan baru": riwayat & layer hasil chat dibersihkan, asisten
// mulai dari nol (tidak membawa topik/wilayah percakapan sebelumnya).
function chatPercakapanBaru() {
  if (state.chat.busy) return;
  const adaIsi = state.chat.messages.some((m) => m.role === "user");
  resetChat();
  if (adaIsi) toast("Percakapan baru dimulai — asisten tidak lagi membawa konteks percakapan sebelumnya.");
  document.getElementById("chatInput")?.focus();
}

function bindChatPanel() {
  const toggleBtn = document.getElementById("btnChatToggle");
  const panel = document.getElementById("chatPanel");
  const closeBtn = document.getElementById("chatClose");
  const wideBtn = document.getElementById("chatWide");
  const form = document.getElementById("chatForm");
  const input = document.getElementById("chatInput");
  const summaryBtn = document.getElementById("btnChatSummary");

  const statusBtn = document.getElementById("chatStatusBtn");
  statusBtn?.addEventListener("click", chatTampilkanStatusProvider);
  document.getElementById("chatBaru")?.addEventListener("click", chatPercakapanBaru);
  input.addEventListener("focus", renderChatKonteks); // konteks bisa berubah selama panel terbuka

  toggleBtn.addEventListener("click", () => {
    panel.hidden = !panel.hidden;
    if (!panel.hidden) {
      chatSembunyikanInfoAi(true);
      // Admin saja (backend _require_admin); dicek saat dibuka krn state.auth bisa berubah (login/logout).
      if (statusBtn) statusBtn.hidden = state.auth.required && state.auth.role !== "admin";
      refreshChatContoh();
      input.focus();
    }
  });
  closeBtn.addEventListener("click", () => (panel.hidden = true));
  wideBtn?.addEventListener("click", () => {
    const lebar = panel.classList.toggle("is-wide");
    wideBtn.querySelector("i").className = lebar ? "bi bi-fullscreen-exit" : "bi bi-arrows-fullscreen";
    renderChatMessages(); // grafik digambar ulang sesuai lebar baru
  });

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const text = input.value;
    input.value = "";
    input.style.height = "";
    sendChatMessage(text);
  });
  // Enter = kirim, Shift+Enter = baris baru (prompt analisis sering panjang)
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      form.requestSubmit();
    }
  });
  input.addEventListener("input", () => {
    input.style.height = "";
    input.style.height = `${Math.min(input.scrollHeight, 140)}px`;
  });

  summaryBtn.addEventListener("click", () => {
    if (!state.routes[state.selectedIndex]) {
      toast("Cari rute dulu sebelum minta ringkasan", true);
      return;
    }
    sendChatMessage("Tolong buatkan ringkasan singkat mengenai rute ini berdasarkan data yang tersedia.");
  });

  const tersimpan = chatMuat();
  if (tersimpan) {
    // Kartu tabel/grafik dimuat ulang dari dataset server; layer peta hasil chat tidak dipulihkan.
    state.chat.messages = [{ role: "assistant", text: CHAT_GREETING, contoh: [] }, ...tersimpan];
    state.chat.konteksMati = new Set();
    renderChatMessages();
  } else {
    resetChat();
  }
}

/* ---------- Pengumuman fitur Asisten AI (sekali per pengguna per browser) ----------
   Dipanggil setAppMode() (state.js) saat pengguna masuk ke aplikasi -- jadi
   tampil setelah login pertama, bukan di halaman pembuka/form login. */
function chatInfoAiKunci() {
  return `infoAsistenAi:${state.auth.username || "_"}`;
}

function chatTampilkanInfoAi() {
  const el = document.getElementById("chatInfoAi");
  if (!el || !document.getElementById("chatPanel")?.hidden) return;
  try { if (localStorage.getItem(chatInfoAiKunci())) return; } catch (e) { /* storage diblokir: tetap tampilkan */ }
  el.hidden = false;
  document.getElementById("btnChatToggle")?.classList.add("fab-sorot");
}

function chatSembunyikanInfoAi(simpan) {
  const el = document.getElementById("chatInfoAi");
  if (!el || el.hidden) return;
  el.hidden = true;
  document.getElementById("btnChatToggle")?.classList.remove("fab-sorot");
  if (simpan) { try { localStorage.setItem(chatInfoAiKunci(), "1"); } catch (e) { /* abaikan */ } }
}

function bindChatInfoAi() {
  document.getElementById("chatInfoAiCoba")?.addEventListener("click", () => {
    chatSembunyikanInfoAi(true);
    const panel = document.getElementById("chatPanel");
    if (panel?.hidden) document.getElementById("btnChatToggle")?.click();
  });
  document.getElementById("chatInfoAiTutup")?.addEventListener("click", () => chatSembunyikanInfoAi(true));
}
