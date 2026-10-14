/* --- Preview & Export Skor CER AWP-1 (Analisis Skoring Jalan AWP-1, eksperimental)
   Bahan reviu pemilihan koridor, pola sama dgn Preview Export Skor IJD
   (usulan-inpres.js): filter provinsi multi-select, pilihan urut CER/TOT,
   header kolom dua baris (grup + judul). Backend: /api/cer-awp1/*,
   logika kolom/xlsx di cer_awp1.py. ------------------------------------- */

const cerPreview = { provinsi: [], urut: "cer", offset: 0, limit: 50, total: 0 };
let cerProvinsiOptionsCache = null; // [{provinsi, jumlah}]
let cerProvinsiPending = new Set();

function cerPreviewParams(extra = {}) {
  const params = new URLSearchParams({ urut: cerPreview.urut, ...extra });
  cerPreview.provinsi.forEach((p) => params.append("provinsi", p));
  return params;
}

function cerPreviewUpdateProvinsiLabel() {
  const label = document.getElementById("cerPreviewProvinsiLabel");
  const n = cerPreview.provinsi.length;
  if (n === 0) label.textContent = "Semua provinsi (Nasional)";
  else if (n <= 2) label.textContent = cerPreview.provinsi.join(", ");
  else label.textContent = `${n} provinsi dipilih`;
}

async function cerPreviewOpen() {
  cerPreview.offset = 0;
  cerPreviewUpdateProvinsiLabel();
  document.getElementById("cerPreviewOverlay").hidden = false;
  await cerPreviewFetchPage();
}

async function cerPreviewFetchPage() {
  const scroll = document.getElementById("cerPreviewScroll");
  scroll.innerHTML = `
    <div class="datatable-loading">
      <i class="bi bi-hourglass-split"></i> Memuat skor CER...
      <div class="datatable-loading-bar"><span></span></div>
    </div>
  `;
  try {
    const res = await fetch(`/api/cer-awp1/preview?${cerPreviewParams({ limit: cerPreview.limit, offset: cerPreview.offset })}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Gagal memuat preview");
    cerPreview.total = data.total;
    cerPreviewRender(data);
  } catch (err) {
    scroll.innerHTML = `<div class="datatable-loading">${escapeHtml(err.message)}</div>`;
  }
}

function cerPreviewRender(data) {
  const rk = data.ringkasan;
  document.getElementById("cerPreviewTitle").textContent = data.label;
  document.getElementById("cerPreviewMeta").textContent = `${data.total.toLocaleString("id-ID")} koridor`;
  const median = rk.median_cer == null ? "—" : rk.median_cer.toLocaleString("id-ID", { maximumFractionDigits: 2 });
  document.getElementById("cerPreviewCatatan").innerHTML =
    `<i class="bi bi-info-circle"></i> Model <b>eksperimental</b>, terpisah dari skor IJD A–E dan NPR. ` +
    `TOT = besarnya manfaat, CER = manfaat per biaya (bukan satu ranking tunggal). ` +
    `Median CER ${median}; ${rk.cer_di_atas_50.toLocaleString("id-ID")} koridor CER &gt; 50; ` +
    `${rk.nol_km.toLocaleString("id-ID")} koridor panjang kondisi 0 km; ` +
    `${rk.tanpa_geometri.toLocaleString("id-ID")} tanpa geometri peta. Rumus &amp; catatan lengkap ada di sheet "Keterangan" file Excel.`;

  // Baris grup: sel digabung (colspan) utk kolom berurutan dgn grup sama.
  const grupCells = [];
  data.grup.forEach((g, i) => {
    if (i > 0 && g === data.grup[i - 1]) grupCells[grupCells.length - 1].span += 1;
    else grupCells.push({ g, span: 1 });
  });
  const grupRow = grupCells.map((c) => `<th colspan="${c.span}">${escapeHtml(c.g)}</th>`).join("");
  const head = data.columns.map((c) => `<th>${escapeHtml(c)}</th>`).join("");
  // Kolom identitas/peringkat: tanpa pemisah ribuan.
  const noSeparatorCols = new Set(
    data.columns.map((c, i) => (c === "No." || c.startsWith("ID ") || c.startsWith("Peringkat") ? i : -1)).filter((i) => i >= 0),
  );
  const cell = (v, i) => {
    if (v === null || v === undefined || v === "") return '<td class="null">—</td>';
    if (typeof v === "number") return `<td class="num">${noSeparatorCols.has(i) ? v : v.toLocaleString("id-ID")}</td>`;
    const s = String(v);
    if (s.length > 80) return `<td title="${escapeHtml(s)}">${escapeHtml(s.slice(0, 78))}…</td>`;
    return `<td>${escapeHtml(s)}</td>`;
  };
  const body = data.rows.map((r) => `<tr>${r.map(cell).join("")}</tr>`).join("");
  const scroll = document.getElementById("cerPreviewScroll");
  scroll.innerHTML =
    `<table class="datatable cer-datatable"><thead><tr class="cer-grup-row">${grupRow}</tr><tr>${head}</tr></thead>` +
    `<tbody>${body}</tbody></table>`;
  // Dua baris header sticky: baris judul menempel tepat di bawah baris grup.
  const tinggiGrup = scroll.querySelector("tr.cer-grup-row").offsetHeight;
  scroll.querySelectorAll("thead tr:nth-child(2) th").forEach((th) => (th.style.top = `${tinggiGrup}px`));

  const page = Math.floor(data.offset / data.limit) + 1;
  const pages = Math.max(1, Math.ceil(data.total / data.limit));
  document.getElementById("cerPreviewPageInfo").textContent = `Halaman ${page} dari ${pages.toLocaleString("id-ID")}`;
  document.getElementById("cerPreviewPrev").disabled = data.offset <= 0;
  document.getElementById("cerPreviewNext").disabled = data.offset + data.limit >= data.total;
}

async function cerPreviewLoadProvinsiOptions() {
  // Array kosong (gagal) sengaja tidak di-cache, supaya buka panel berikutnya coba lagi.
  if (cerProvinsiOptionsCache && cerProvinsiOptionsCache.length) return cerProvinsiOptionsCache;
  try {
    const res = await fetch("/api/cer-awp1/provinsi");
    const rows = await res.json();
    if (!res.ok) throw new Error(rows.detail || "Gagal memuat daftar provinsi");
    cerProvinsiOptionsCache = Array.isArray(rows) ? rows : [];
  } catch (err) {
    toast(`Gagal memuat daftar provinsi: ${err.message}`, true);
    cerProvinsiOptionsCache = [];
  }
  return cerProvinsiOptionsCache;
}

function cerPreviewRenderProvinsiOptions(filterText) {
  const wrap = document.getElementById("cerPreviewProvinsiOptions");
  const rows = cerProvinsiOptionsCache || [];
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
  wrap.innerHTML = filtered.map((r) => `<label class="ijd-provinsi-option">
      <input type="checkbox" value="${escapeHtml(r.provinsi)}" ${cerProvinsiPending.has(r.provinsi) ? "checked" : ""} />
      <span>${escapeHtml(r.provinsi)}</span>
      <span class="datatable-menu-count">${r.jumlah}</span>
    </label>`).join("");
}

function bindCerPreviewProvinsiCombo() {
  const field = document.getElementById("cerPreviewProvinsiField");
  const toggle = document.getElementById("cerPreviewProvinsiToggle");
  const panel = document.getElementById("cerPreviewProvinsiPanel");
  const search = document.getElementById("cerPreviewProvinsiSearch");
  const tutup = () => {
    panel.hidden = true;
    field.classList.remove("open");
  };

  toggle.addEventListener("click", async (e) => {
    e.stopPropagation();
    const willOpen = panel.hidden;
    if (willOpen) {
      await cerPreviewLoadProvinsiOptions();
      cerProvinsiPending = new Set(cerPreview.provinsi);
      search.value = "";
      cerPreviewRenderProvinsiOptions("");
    }
    panel.hidden = !willOpen;
    field.classList.toggle("open", willOpen);
    if (willOpen) search.focus();
  });
  search.addEventListener("input", () => cerPreviewRenderProvinsiOptions(search.value));
  search.addEventListener("click", (e) => e.stopPropagation());

  document.getElementById("cerPreviewProvinsiOptions").addEventListener("click", (e) => {
    const opt = e.target.closest(".ijd-provinsi-option");
    if (!opt) return;
    e.preventDefault();
    const cb = opt.querySelector("input");
    if (cerProvinsiPending.has(cb.value)) cerProvinsiPending.delete(cb.value);
    else cerProvinsiPending.add(cb.value);
    cb.checked = cerProvinsiPending.has(cb.value);
  });
  document.getElementById("cerPreviewProvinsiClear").addEventListener("click", (e) => {
    e.stopPropagation();
    cerProvinsiPending.clear();
    cerPreviewRenderProvinsiOptions(search.value);
  });
  document.getElementById("cerPreviewProvinsiApply").addEventListener("click", (e) => {
    e.stopPropagation();
    cerPreview.provinsi = Array.from(cerProvinsiPending).sort();
    cerPreview.offset = 0;
    cerPreviewUpdateProvinsiLabel();
    tutup();
    cerPreviewFetchPage();
  });
  document.addEventListener("click", (e) => {
    if (!panel.hidden && !field.contains(e.target)) tutup();
  });
}

function bindCerPreview() {
  const overlay = document.getElementById("cerPreviewOverlay");
  document.getElementById("btnUsulanExportCer").addEventListener("click", cerPreviewOpen);
  document.getElementById("cerPreviewClose").addEventListener("click", () => (overlay.hidden = true));
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) overlay.hidden = true;
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !overlay.hidden) overlay.hidden = true;
  });

  document.getElementById("cerPreviewPrev").addEventListener("click", () => {
    cerPreview.offset = Math.max(0, cerPreview.offset - cerPreview.limit);
    cerPreviewFetchPage();
  });
  document.getElementById("cerPreviewNext").addEventListener("click", () => {
    if (cerPreview.offset + cerPreview.limit < cerPreview.total) {
      cerPreview.offset += cerPreview.limit;
      cerPreviewFetchPage();
    }
  });
  document.getElementById("cerPreviewPageSize").addEventListener("change", (e) => {
    cerPreview.limit = parseInt(e.target.value, 10);
    cerPreview.offset = 0;
    cerPreviewFetchPage();
  });
  document.getElementById("cerPreviewUrut").addEventListener("change", (e) => {
    cerPreview.urut = e.target.value;
    cerPreview.offset = 0;
    cerPreviewFetchPage();
  });
  document.getElementById("cerPreviewExport").addEventListener("click", () => {
    window.location.href = `/api/cer-awp1/export/xlsx?${cerPreviewParams()}`;
  });
  bindCerPreviewProvinsiCombo();
}

document.addEventListener("DOMContentLoaded", bindCerPreview);
