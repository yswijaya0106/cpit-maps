/* RouteGIS — penampil isi tabel database (tombol "Data" di topbar).
   Tidak bergantung pada Google Maps: di-bind langsung saat DOM siap. */

const dataViewer = {
  tables: null,     // cache daftar tabel dari /api/data/tables
  table: null,      // nama tabel aktif
  label: "",
  offset: 0,
  limit: 50,
  total: 0,
};

async function dataViewerLoadTables() {
  if (dataViewer.tables) return dataViewer.tables;
  const res = await fetch("/api/data/tables");
  if (!res.ok) throw new Error("Gagal memuat daftar tabel");
  dataViewer.tables = await res.json();
  return dataViewer.tables;
}

async function dataViewerToggleMenu() {
  const menu = document.getElementById("dataTableMenu");
  if (!menu.hidden) {
    menu.hidden = true;
    return;
  }
  try {
    const tables = await dataViewerLoadTables();
    menu.innerHTML = tables.map((t) =>
      `<button type="button" class="datatable-menu-item" data-table="${t.name}">
         <span>${t.label}</span>
         <span class="datatable-menu-count">${t.total.toLocaleString("id-ID")}</span>
       </button>`).join("");
    menu.hidden = false;
  } catch (err) {
    toast(err.message, true);
  }
}

async function dataViewerOpen(tableName) {
  document.getElementById("dataTableMenu").hidden = true;
  const t = (dataViewer.tables || []).find((x) => x.name === tableName);
  dataViewer.table = tableName;
  dataViewer.label = t ? t.label : tableName;
  dataViewer.offset = 0;
  document.getElementById("dataTableOverlay").hidden = false;
  await dataViewerFetchPage();
}

async function dataViewerFetchPage() {
  const scroll = document.getElementById("dataTableScroll");
  scroll.innerHTML = '<div class="datatable-loading"><i class="bi bi-hourglass-split"></i> Memuat data...</div>';
  try {
    const params = new URLSearchParams({ limit: dataViewer.limit, offset: dataViewer.offset });
    const res = await fetch(`/api/data/${dataViewer.table}?${params}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Gagal memuat data");
    dataViewer.total = data.total;
    dataViewerRender(data);
  } catch (err) {
    scroll.innerHTML = `<div class="datatable-loading">${err.message}</div>`;
  }
}

function dataViewerRender(data) {
  document.querySelector("#dataTableTitle span").textContent = data.label;
  document.getElementById("dataTableMeta").textContent =
    `${data.table} — ${data.total.toLocaleString("id-ID")} baris`;

  const esc = (s) => String(s)
    .replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
  // kolom identitas (tahun, kode wilayah, id) bukan besaran — jangan diberi
  // pemisah ribuan ("2.025", "3.673.010" menyesatkan)
  const plainCols = data.columns.map((c) =>
    /(^|_)(tahun|kode|id)($|_)|^kode|_kode$/i.test(c));
  const cell = (v, j) => {
    if (v === null || v === undefined) return '<td class="null">—</td>';
    if (typeof v === "number") {
      return `<td class="num">${esc(plainCols[j] ? String(v) : v.toLocaleString("id-ID"))}</td>`;
    }
    return `<td>${esc(v)}</td>`;
  };
  const head = data.columns.map((c) => `<th>${esc(c)}</th>`).join("");
  const body = data.rows.map((r, i) =>
    `<tr><td class="num rownum">${(data.offset + i + 1).toLocaleString("id-ID")}</td>${r.map(cell).join("")}</tr>`
  ).join("");
  document.getElementById("dataTableScroll").innerHTML =
    `<table class="datatable"><thead><tr><th class="rownum">#</th>${head}</tr></thead><tbody>${body}</tbody></table>`;

  const page = Math.floor(data.offset / data.limit) + 1;
  const pages = Math.max(1, Math.ceil(data.total / data.limit));
  document.getElementById("dataTablePageInfo").textContent = `Halaman ${page} dari ${pages.toLocaleString("id-ID")}`;
  document.getElementById("dataTablePrev").disabled = data.offset <= 0;
  document.getElementById("dataTableNext").disabled = data.offset + data.limit >= data.total;
}

function bindDataViewer() {
  document.getElementById("btnDataTable").addEventListener("click", dataViewerToggleMenu);

  document.getElementById("dataTableMenu").addEventListener("click", (e) => {
    const item = e.target.closest("[data-table]");
    if (item) dataViewerOpen(item.dataset.table);
  });

  document.addEventListener("click", (e) => {
    if (!e.target.closest("#dataTableControl")) {
      document.getElementById("dataTableMenu").hidden = true;
    }
  });

  const overlay = document.getElementById("dataTableOverlay");
  document.getElementById("dataTableClose").addEventListener("click", () => (overlay.hidden = true));
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) overlay.hidden = true;
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !overlay.hidden) overlay.hidden = true;
  });

  document.getElementById("dataTablePrev").addEventListener("click", () => {
    if (!dataViewer.table) return;
    dataViewer.offset = Math.max(0, dataViewer.offset - dataViewer.limit);
    dataViewerFetchPage();
  });
  document.getElementById("dataTableNext").addEventListener("click", () => {
    if (!dataViewer.table) return;
    if (dataViewer.offset + dataViewer.limit < dataViewer.total) {
      dataViewer.offset += dataViewer.limit;
      dataViewerFetchPage();
    }
  });
  document.getElementById("dataTablePageSize").addEventListener("change", (e) => {
    dataViewer.limit = parseInt(e.target.value, 10);
    dataViewer.offset = 0;
    if (dataViewer.table) dataViewerFetchPage();
  });
}

document.addEventListener("DOMContentLoaded", bindDataViewer);
