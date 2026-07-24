/* The Next - SiJalan — penampil isi tabel database (tombol "Data" di topbar).
   Tidak bergantung pada Google Maps: di-bind langsung saat DOM siap. */

const dataViewer = {
  tables: null,     // cache daftar tabel dari /api/data/tables
  table: null,      // nama tabel aktif
  label: "",
  offset: 0,
  limit: 50,
  total: 0,
  geo: false,       // tabel aktif bisa difilter provinsi/kabupaten?
  provinsi: "",     // kode_provinsi terpilih ("" = semua)
  kabupaten: "",    // kode_kabupaten terpilih ("" = semua)
  geoProvinces: null, // cache /api/data/geo/provinces (sama utk semua tabel)
  bappenasKriteria: null, // cache /api/bappenas-lokus-a/kriteria
  importKriteria: "", // kriteria terpilih di panel import (khusus tabel bappenas_lokus_a)
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
    // bappenas_lokus_a punya entry point sendiri sekarang (tombol navbar
    // "Lokus Bappenas") -- tidak perlu dobel muncul di menu "Data" generik.
    menu.innerHTML = tables.filter((t) => t.name !== "bappenas_lokus_a")
      .slice().sort((a, b) => a.label.localeCompare(b.label, "id"))
      .map((t) =>
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
  dataViewer.geo = !!(t && t.geo);
  dataViewer.provinsi = "";
  dataViewer.kabupaten = "";
  document.getElementById("dataTableOverlay").hidden = false;
  await dataViewerSetupFilters();
  dataViewerSetupImport();
  await dataViewerFetchPage();
}

function dataViewerSetupImport() {
  const wrap = document.getElementById("dataTableImport");
  const isBappenasLokus = dataViewer.table === "bappenas_lokus_a";
  wrap.hidden = !isBappenasLokus;
  if (!isBappenasLokus) return;
  dataViewer.importKriteria = "";
  document.getElementById("dataTableImportKriteriaLabel").textContent = "Pilih kriteria...";
  document.getElementById("dataTableImportBtn").disabled = true;
}

const DATA_FILTER_ALL_PROV = { kode_provinsi: "", provinsi: "Semua provinsi" };
const DATA_FILTER_ALL_KAB = { kode_kabupaten: "", kabupaten_kota: "Semua kabupaten" };

async function dataViewerSetupFilters() {
  const wrap = document.getElementById("dataTableFilters");
  wrap.hidden = !dataViewer.geo;
  if (!dataViewer.geo) return;
  document.getElementById("dataTableFilterProvinsiLabel").textContent = "Semua provinsi";
  document.getElementById("dataTableFilterKabupatenLabel").textContent = "Semua kabupaten";
  document.getElementById("dataTableFilterKabupatenToggle").disabled = true;
}

async function dataViewerGeoProvinces() {
  if (!dataViewer.geoProvinces) {
    try {
      const res = await fetch("/api/data/geo/provinces");
      dataViewer.geoProvinces = await res.json();
    } catch {
      dataViewer.geoProvinces = [];
    }
  }
  return dataViewer.geoProvinces;
}

async function dataViewerGeoKabupaten(kodeProvinsi) {
  if (!kodeProvinsi) return [];
  try {
    const res = await fetch(`/api/data/geo/kabupaten?provinsi=${encodeURIComponent(kodeProvinsi)}`);
    return await res.json();
  } catch {
    return [];
  }
}

function bindDataViewerGeoFilters() {
  bindMapLayerCombo(
    "dataTableFilterProvinsiField", "dataTableFilterProvinsiToggle",
    "dataTableFilterProvinsiPanel", "dataTableFilterProvinsiLabel",
    async () => {
      const rows = [DATA_FILTER_ALL_PROV, ...(await dataViewerGeoProvinces())];
      fillComboPanel("dataTableFilterProvinsiPanel", "dataTableFilterProvinsiLabel",
        rows, "kode_provinsi", (r) => r.provinsi, dataViewer.provinsi);
    },
    async (value) => {
      dataViewer.provinsi = value;
      dataViewer.kabupaten = "";
      dataViewer.offset = 0;
      const kabToggle = document.getElementById("dataTableFilterKabupatenToggle");
      document.getElementById("dataTableFilterKabupatenLabel").textContent = "Semua kabupaten";
      kabToggle.disabled = !value;
      if (dataViewer.table) dataViewerFetchPage();
    },
  );
  bindMapLayerCombo(
    "dataTableFilterKabupatenField", "dataTableFilterKabupatenToggle",
    "dataTableFilterKabupatenPanel", "dataTableFilterKabupatenLabel",
    async () => {
      const rows = [DATA_FILTER_ALL_KAB, ...(await dataViewerGeoKabupaten(dataViewer.provinsi))];
      fillComboPanel("dataTableFilterKabupatenPanel", "dataTableFilterKabupatenLabel",
        rows, "kode_kabupaten", (r) => r.kabupaten_kota, dataViewer.kabupaten);
    },
    async (value) => {
      dataViewer.kabupaten = value;
      dataViewer.offset = 0;
      if (dataViewer.table) dataViewerFetchPage();
    },
  );
}

async function dataViewerBappenasKriteria() {
  if (!dataViewer.bappenasKriteria) {
    try {
      const res = await fetch("/api/bappenas-lokus-a/kriteria");
      dataViewer.bappenasKriteria = await res.json();
    } catch {
      dataViewer.bappenasKriteria = [];
    }
  }
  return dataViewer.bappenasKriteria;
}

function bindDataViewerImport() {
  bindMapLayerCombo(
    "dataTableImportKriteriaField", "dataTableImportKriteriaToggle",
    "dataTableImportKriteriaPanel", "dataTableImportKriteriaLabel",
    async () => {
      const rows = await dataViewerBappenasKriteria();
      fillComboPanel("dataTableImportKriteriaPanel", "dataTableImportKriteriaLabel",
        rows, "kriteria", (r) => `${r.label} — ${r.total} baris`, dataViewer.importKriteria);
    },
    (value) => {
      dataViewer.importKriteria = value;
      document.getElementById("dataTableImportBtn").disabled = !value;
      // dropdown kriteria dobel fungsi: selain target upload, juga memfilter
      // grid preview ke kriteria terpilih (kosong = semua kriteria).
      if (dataViewer.table === "bappenas_lokus_a") {
        dataViewer.offset = 0;
        dataViewerFetchPage();
      }
    },
  );

  document.getElementById("dataTableImportBtn").addEventListener("click", () => {
    if (!dataViewer.importKriteria) return;
    document.getElementById("dataTableImportFile").click();
  });

  document.getElementById("dataTableImportFile").addEventListener("change", async (e) => {
    const file = e.target.files[0];
    e.target.value = ""; // reset supaya file yang sama bisa dipilih lagi
    if (!file || !dataViewer.importKriteria) return;
    const btn = document.getElementById("dataTableImportBtn");
    btn.disabled = true;
    setStatus(`Mengimpor ${file.name}...`);
    try {
      const formData = new FormData();
      formData.append("file", file);
      const params = new URLSearchParams({ kriteria: dataViewer.importKriteria });
      const res = await fetch(`/api/bappenas-lokus-a/import?${params}`, { method: "POST", body: formData });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Gagal impor");
      toast(`${data.kriteria}: ${data.total} baris dimuat (${data.match_kabupaten} match kabupaten)`);
      dataViewer.bappenasKriteria = null; // cache basi, muat ulang lain kali panel dibuka
      if (dataViewer.table === "bappenas_lokus_a") dataViewerFetchPage();
    } catch (err) {
      toast(err.message, true);
    } finally {
      btn.disabled = !dataViewer.importKriteria;
      setStatus("");
    }
  });
}

async function dataViewerFetchPage() {
  const scroll = document.getElementById("dataTableScroll");
  scroll.innerHTML = '<div class="datatable-loading"><i class="bi bi-hourglass-split"></i> Memuat data...</div>';
  try {
    const params = new URLSearchParams({ limit: dataViewer.limit, offset: dataViewer.offset });
    if (dataViewer.provinsi) params.set("provinsi", dataViewer.provinsi);
    if (dataViewer.kabupaten) params.set("kabupaten", dataViewer.kabupaten);
    if (dataViewer.table === "bappenas_lokus_a" && dataViewer.importKriteria) {
      params.set("kriteria", dataViewer.importKriteria);
    }
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
  // kolom flag biner (TINYINT(1) mis. "pertanian_ada", "kendaraan_estimasi")
  // -> tampilkan sebagai ikon centang/silang, bukan angka 0/1 mentah.
  const boolCols = data.columns.map(isBoolDbCol);
  const cell = (v, j) => {
    if (boolCols[j] && (v === 0 || v === 1)) {
      return `<td class="bool-cell">${boolCellHtml(v)}</td>`;
    }
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

async function dataViewerOpenLokusBappenas() {
  // Entry point navbar terpisah dari menu "Data" -- langsung buka dialog
  // yang sama dgn table=bappenas_lokus_a terpilih (dropdown kriteria di
  // panel import dobel fungsi jadi filter preview grid, lihat bindDataViewerImport).
  try {
    await dataViewerLoadTables();
  } catch (err) {
    toast(err.message, true);
    return;
  }
  dataViewerOpen("bappenas_lokus_a");
}

function bindDataViewer() {
  document.getElementById("btnDataTable").addEventListener("click", dataViewerToggleMenu);
  document.getElementById("btnLokusBappenas").addEventListener("click", dataViewerOpenLokusBappenas);

  document.getElementById("dataTableMenu").addEventListener("click", (e) => {
    const item = e.target.closest("[data-table]");
    if (item) dataViewerOpen(item.dataset.table);
  });

  document.addEventListener("click", (e) => {
    if (!e.target.closest("#dataTableControl")) {
      document.getElementById("dataTableMenu").hidden = true;
    }
  });

  document.getElementById("dataTableExport").addEventListener("click", () => {
    if (!dataViewer.table) return;
    const params = new URLSearchParams();
    if (dataViewer.provinsi) params.set("provinsi", dataViewer.provinsi);
    if (dataViewer.kabupaten) params.set("kabupaten", dataViewer.kabupaten);
    if (dataViewer.table === "bappenas_lokus_a" && dataViewer.importKriteria) {
      params.set("kriteria", dataViewer.importKriteria);
    }
    const qs = params.toString();
    window.location.href = `/api/data/${dataViewer.table}/export/xlsx${qs ? `?${qs}` : ""}`;
  });

  bindDataViewerGeoFilters();
  bindDataViewerImport();

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
