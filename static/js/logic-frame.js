/* --- Logic Frame IJD + Pagu Provinsi (4 Okt 2026) ---------------------------
   Modal "Logic Frame" (tombol #btnLogicFrame, toolbar Jelajahi Usulan moda IJD).
   Deck Bappenas "20261002 Preparation, Implementation and Validation of IJD"
   hal. 4: keluaran sistem berupa Logic Frame -- hubungan input data, proses
   analisis, dan output. Rangkaian & status input disusun backend
   (GET /api/logic-frame, dibaca langsung dari DB); file ini hanya menggambar
   tiga kolom dan menyorot keterkaitan saat kartu diklik. Tab Pagu Provinsi =
   tampilan GET /api/pagu-provinsi (sebelumnya hanya API). Memakai helper dari
   usulan-inpres.js (biayaFmt) dan state.js (aksesPenilaian) -- dimuat sesudahnya. */

const lf = { data: null, pilih: null, paguDimuat: false };

const LF_STATUS = {
  tersedia: { label: "Tersedia", ikon: "bi-check-circle-fill" },
  parsial: { label: "Parsial", ikon: "bi-circle-half" },
  kosong: { label: "Kosong", ikon: "bi-exclamation-circle" },
  belum: { label: "Belum ada sumber", ikon: "bi-x-circle" },
};

// Aksi kartu output: buka tampilan yang sudah ada (modal ini ditutup dulu)
const LF_AKSI = {
  "ijd-preview": () => document.getElementById("btnUsulanExportIjdScore").click(),
  "ijd-dashboard": () => document.getElementById("btnIjdDashboard").click(),
  "lokasi-prioritas": () => document.getElementById("btnLaporanPrioritas").click(),
  "program-ijd": () => document.getElementById("btnProgramIjd").click(),
};

function lfAngka(n) {
  return n == null ? "–" : n.toLocaleString("id-ID");
}

async function lfFetch(url) {
  const res = await fetch(url);
  const d = await res.json();
  if (!res.ok) throw new Error(d.detail || "Gagal memuat data");
  return d;
}

function lfLoading(el) {
  el.innerHTML = `<div class="laporan-distribusi-empty"><i class="bi bi-hourglass-split"></i> Memuat...
    <div class="datatable-loading-bar"><span></span></div></div>`;
}

/* ---------------- Tab Logic Frame ---------------- */

async function lfLoadFrame() {
  const view = document.getElementById("lfFrameView");
  lfLoading(view);
  try {
    lf.data = await lfFetch("/api/logic-frame");
    lf.pilih = null;
    lfRenderFrame();
  } catch (err) {
    view.innerHTML = `<div class="laporan-distribusi-empty">${escapeHtml(err.message)}</div>`;
  }
}

function lfRenderFrame() {
  const d = lf.data;
  const akses = aksesPenilaian();
  const kelompok = [...new Set(d.input.map((i) => i.kelompok))];
  const inputHtml = kelompok.map((k) => `<div class="lf-group"><div class="lf-group-title">${escapeHtml(k)}</div>
    ${d.input.filter((i) => i.kelompok === k).map((i) => {
      const st = LF_STATUS[i.status];
      const angka = i.n == null ? "" : i.n_dari ? `${lfAngka(i.n)} / ${lfAngka(i.n_dari)} usulan` : `${lfAngka(i.n)} baris`;
      return `<div class="lf-node lf-in lf-st-${i.status}" data-lf-id="${i.id}" tabindex="0" role="button"
          title="${escapeHtml([i.tabel, i.catatan].filter(Boolean).join(" · "))}">
        <span class="lf-node-label">${escapeHtml(i.label)}</span>
        <span class="lf-node-meta"><i class="bi ${st.ikon}"></i> ${st.label}${angka ? ` · ${angka}` : ""}</span></div>`;
    }).join("")}</div>`).join("");

  const tahap = [...new Set(d.proses.map((p) => p.tahap))];
  const prosesHtml = tahap.map((t) => `<div class="lf-group"><div class="lf-group-title">${escapeHtml(t)}</div>
    ${d.proses.filter((p) => p.tahap === t).map((p) => {
      const pct = p.cakupan != null && p.cakupan_dari ? Math.round((p.cakupan / p.cakupan_dari) * 100) : null;
      return `<div class="lf-node lf-pr" data-lf-id="${p.id}" tabindex="0" role="button">
        <span class="lf-node-label">${escapeHtml(p.label)}</span>
        ${p.bobot ? `<span class="lf-node-meta">${escapeHtml(p.bobot)}</span>` : ""}
        ${pct != null ? `<span class="lf-bar" title="${lfAngka(p.cakupan)} dari ${lfAngka(p.cakupan_dari)} usulan dapat dihitung">
          <span style="width:${pct}%"></span></span><span class="lf-node-meta">Cakupan data ${pct}% (${lfAngka(p.cakupan)} / ${lfAngka(p.cakupan_dari)} usulan)</span>` : ""}
        ${p.catatan ? `<span class="lf-node-note">${escapeHtml(p.catatan)}</span>` : ""}</div>`;
    }).join("")}</div>`).join("");

  const outputHtml = `<div class="lf-group"><div class="lf-group-title">Keluaran</div>
    ${d.output.map((o) => {
      const terkunci = o.penilaian && !akses;
      return `<div class="lf-node lf-out" data-lf-id="out-${o.id}" tabindex="0" role="button">
        <span class="lf-node-label">${escapeHtml(o.label)}</span>
        ${terkunci ? '<span class="lf-node-meta"><i class="bi bi-lock-fill"></i> Hanya di SiJalan untuk akun berwenang</span>'
          : `<button type="button" class="btn btn-ghost btn-xs lf-buka" data-lf-aksi="${o.aksi}"><i class="bi bi-box-arrow-up-right"></i> Buka</button>`}
      </div>`;
    }).join("")}</div>`;

  const nBelum = d.input.filter((i) => i.status === "belum" || i.status === "kosong").length;
  const nParsial = d.input.filter((i) => i.status === "parsial").length;
  document.getElementById("logicFrameMeta").textContent =
    `Kaidah ${d.tahun} · ${d.input.length} input (${nParsial} parsial, ${nBelum} belum tersedia) · ${d.proses.length} proses · ${d.output.length} keluaran`;
  document.getElementById("lfFrameView").innerHTML = `
    <p class="hint">Klik sebuah kartu untuk menyorot keterkaitannya: input mana yang dipakai sebuah proses, dan proses mana yang menghasilkan sebuah keluaran.</p>
    <div class="lf-grid">
      <section class="lf-col"><h4><span class="lf-step">1</span> Input data <small>Persiapan</small></h4>${inputHtml}</section>
      <div class="lf-arrow" aria-hidden="true"><i class="bi bi-chevron-right"></i></div>
      <section class="lf-col"><h4><span class="lf-step">2</span> Proses analisis <small>Implementasi</small></h4>${prosesHtml}</section>
      <div class="lf-arrow" aria-hidden="true"><i class="bi bi-chevron-right"></i></div>
      <section class="lf-col"><h4><span class="lf-step">3</span> Output <small>Implementasi &amp; Monev</small></h4>${outputHtml}
        <div class="lf-feedback"><i class="bi bi-arrow-repeat"></i> Umpan balik: hasil monev dan evaluasi menjadi masukan
          penyempurnaan data dan kriteria pada siklus IJD berikutnya.</div></section>
    </div>
    <p class="hint">${escapeHtml(d.catatan)}</p>`;

  const view = document.getElementById("lfFrameView");
  view.querySelectorAll(".lf-node").forEach((el) => {
    const pilih = () => lfSorot(el.dataset.lfId);
    el.addEventListener("click", pilih);
    el.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pilih(); } });
  });
  view.querySelectorAll(".lf-buka").forEach((b) => b.addEventListener("click", (e) => {
    e.stopPropagation();
    lfJalankanAksi(b.dataset.lfAksi);
  }));
}

// Sorot node terpilih + semua yang terhubung (input <-> proses <-> output)
function lfSorot(id) {
  const d = lf.data;
  const view = document.getElementById("lfFrameView");
  if (lf.pilih === id) {
    lf.pilih = null;
    view.querySelector(".lf-grid").classList.remove("lf-fokus");
    view.querySelectorAll(".lf-node").forEach((n) => n.classList.remove("lf-hi", "lf-sel"));
    return;
  }
  lf.pilih = id;
  const terkait = new Set([id]);
  const prosesDari = (pid) => d.proses.find((p) => p.id === pid);
  if (id.startsWith("out-")) {
    const o = d.output.find((x) => `out-${x.id}` === id);
    o.proses.forEach((pid) => { terkait.add(pid); (prosesDari(pid)?.input || []).forEach((i) => terkait.add(i)); });
  } else if (prosesDari(id)) {
    prosesDari(id).input.forEach((i) => terkait.add(i));
    d.output.filter((o) => o.proses.includes(id)).forEach((o) => terkait.add(`out-${o.id}`));
  } else {
    d.proses.filter((p) => p.input.includes(id)).forEach((p) => {
      terkait.add(p.id);
      d.output.filter((o) => o.proses.includes(p.id)).forEach((o) => terkait.add(`out-${o.id}`));
    });
  }
  view.querySelector(".lf-grid").classList.add("lf-fokus");
  view.querySelectorAll(".lf-node").forEach((n) => {
    n.classList.toggle("lf-hi", terkait.has(n.dataset.lfId));
    n.classList.toggle("lf-sel", n.dataset.lfId === id);
  });
}

function lfJalankanAksi(aksi) {
  if (aksi === "pagu") {
    lfSetTab("pagu");
    return;
  }
  document.getElementById("logicFrameOverlay").hidden = true;
  LF_AKSI[aksi]?.();
}

/* ---------------- Tab Pagu Provinsi ---------------- */

async function lfLoadPagu() {
  const view = document.getElementById("lfPaguView");
  lfLoading(view);
  const t = parseFloat(String(document.getElementById("lfPaguAlokasi").value).replace(",", "."));
  const params = new URLSearchParams();
  if (t > 0) params.set("alokasi_nasional", Math.round(t * 1e12));
  try {
    const d = await lfFetch(`/api/pagu-provinsi?${params}`);
    const adaRp = d.alokasi_nasional_rp > 0;
    const pct = (v) => (v == null ? "–" : `${v.toLocaleString("id-ID", { maximumFractionDigits: 2 })}%`);
    const maxPangsa = Math.max(...d.provinsi.map((p) => p.pangsa_final_pct || 0), 1);
    const rows = d.provinsi.map((p, i) => `<tr><td class="num">${i + 1}</td><td>${escapeHtml(p.provinsi)}</td>
      <td class="num">${biayaFmt(p.jalan_daerah_km)}</td><td class="num">${pct(p.tidak_mantap_pct)}</td>
      <td class="num">${biayaFmt(p.lahan_sawah_km2)}</td><td>${escapeHtml(p.kapasitas_fiskal || "–")}</td>
      <td class="num">${p.bobot_tersedia}</td>
      <td class="lf-pagu-bar"><span style="width:${((p.pangsa_final_pct || 0) / maxPangsa) * 100}%"></span><b>${pct(p.pangsa_final_pct)}</b></td>
      ${adaRp ? `<td class="num">${p.pagu_rp ? (p.pagu_rp / 1e9).toLocaleString("id-ID", { maximumFractionDigits: 1 }) : "–"}</td>` : ""}</tr>`).join("");
    const pending = Object.entries(d.komponen_belum_tersedia || {}).map(([k, v]) => `<li><b>${escapeHtml(k)}</b>: ${escapeHtml(v)}</li>`).join("");
    view.innerHTML = `<div class="laporan-chart-block">
      <div class="laporan-chart-title"><i class="bi bi-pie-chart"></i> Pagu Indikatif per Provinsi (perkiraan, parsial)</div>
      <div class="laporan-chart-sub">Komponen dinyatakan sebagai pangsa nasional lalu dibobot: A1 panjang jalan daerah 20, A2 ketidakmantapan 30,
        A3 lahan sawah 20 (proksi kawasan pangan), A4 kapasitas fiskal 15. Pangsa akhir dinormalisasi ke bobot yang tersedia.
        ${adaRp ? "" : "Isi alokasi nasional di atas untuk melihat nilai rupiah per provinsi."}</div>
      ${pending ? `<ul class="hint">${pending}</ul>` : ""}
      <div class="biaya-tabel-wrap"><table class="biaya-usulan-table"><thead><tr><th class="num">#</th><th>Provinsi</th>
        <th class="num">Jalan daerah (km)</th><th class="num">Tidak mantap</th><th class="num">Lahan sawah (km²)</th><th>Fiskal</th>
        <th class="num">Bobot tersedia</th><th>Pangsa pagu</th>${adaRp ? '<th class="num">Pagu (Rp M)</th>' : ""}</tr></thead>
        <tbody>${rows}</tbody></table></div></div>
      <p class="hint">${escapeHtml(d.catatan)}</p>`;
  } catch (err) {
    view.innerHTML = `<div class="laporan-distribusi-empty">${escapeHtml(err.message)}</div>`;
  }
}

/* ---------------- Tab & binding ---------------- */

function lfSetTab(tab) {
  document.querySelectorAll("[data-lf-tab]").forEach((b) => b.classList.toggle("active", b.dataset.lfTab === tab));
  document.getElementById("lfFrameView").hidden = tab !== "frame";
  document.getElementById("lfPaguView").hidden = tab !== "pagu";
  document.getElementById("lfPaguFilter").hidden = tab !== "pagu";
  if (tab === "pagu" && !lf.paguDimuat) {
    lf.paguDimuat = true;
    lfLoadPagu();
  }
}

function bindLogicFrame() {
  const overlay = document.getElementById("logicFrameOverlay");
  if (!overlay) return;
  const tutup = () => (overlay.hidden = true);
  document.getElementById("btnLogicFrame").addEventListener("click", () => {
    overlay.hidden = false;
    // Pagu = hasil penilaian: tab disembunyikan di Sikon / akun umum
    const pagu = aksesPenilaian();
    document.getElementById("lfTabPagu").hidden = !pagu;
    lfSetTab("frame");
    lfLoadFrame();
  });
  document.querySelectorAll("[data-lf-tab]").forEach((b) => b.addEventListener("click", () => lfSetTab(b.dataset.lfTab)));
  document.getElementById("lfPaguHitung").addEventListener("click", lfLoadPagu);
  document.getElementById("lfPaguAlokasi").addEventListener("keydown", (e) => { if (e.key === "Enter") lfLoadPagu(); });
  document.getElementById("logicFrameClose").addEventListener("click", tutup);
  overlay.addEventListener("click", (e) => { if (e.target === overlay) tutup(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !overlay.hidden) tutup(); });
}

document.addEventListener("DOMContentLoaded", bindLogicFrame);
