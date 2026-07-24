/* The Next - SiJalan — panel topbar "Dalam Angka": cari & pratinjau PDF BPS
   Dalam Angka utk seluruh provinsi/kabupaten/kota. Tidak bergantung pada
   Google Maps -- di-bind langsung saat DOM siap, sama seperti data-viewer.js. */

const dalamAngkaPanel = {
  wilayah: null, // cache /api/dalam-angka/list (semua provinsi + kab/kota)
};

async function dalamAngkaOpen() {
  const overlay = document.getElementById("dalamAngkaOverlay");
  overlay.hidden = false;
  document.getElementById("dalamAngkaSearch").value = "";
  await dalamAngkaLoad();
  dalamAngkaRender("");
  document.getElementById("dalamAngkaSearch").focus();
}

async function dalamAngkaLoad() {
  if (dalamAngkaPanel.wilayah) return;
  const listEl = document.getElementById("dalamAngkaList");
  listEl.innerHTML = `<div class="adv-loading">Memuat daftar wilayah...</div>`;
  try {
    const res = await fetch("/api/dalam-angka/list");
    if (!res.ok) throw new Error(await res.text());
    dalamAngkaPanel.wilayah = await res.json();
  } catch (err) {
    listEl.innerHTML = "";
    toast(err.message, true);
  }
}

function dalamAngkaRender(query) {
  const listEl = document.getElementById("dalamAngkaList");
  const metaEl = document.getElementById("dalamAngkaMeta");
  const all = dalamAngkaPanel.wilayah || [];
  const q = query.trim().toLowerCase();
  const filtered = q
    ? all.filter((w) => w.nama_wilayah.toLowerCase().includes(q))
    : all;

  metaEl.textContent = `${filtered.length.toLocaleString("id-ID")} dari ${all.length.toLocaleString("id-ID")} wilayah`;

  if (!filtered.length) {
    listEl.innerHTML = `<div class="adv-loading">Tidak ada wilayah yang cocok.</div>`;
    return;
  }

  listEl.innerHTML = filtered.map((w) => {
    const jenisLabel = w.jenis_wilayah === "PROVINSI" ? "Provinsi" : "Kabupaten/Kota";
    const items = w.publikasi.map((p) => `
      <div class="usulan-dalam-angka-item">
        <span class="tahun-badge">${escapeHtml(String(p.tahun))}</span>
        <span>${escapeHtml(p.judul)}</span>
        <button type="button" data-action="preview" data-kode="${w.kode_wilayah}"
          data-jenis="${w.jenis_wilayah}" data-tahun="${p.tahun}" data-judul="${escapeHtml(p.judul)}">
          <i class="bi bi-eye"></i> Pratinjau</button>
        <button type="button" data-action="newtab" data-kode="${w.kode_wilayah}"
          data-jenis="${w.jenis_wilayah}" data-tahun="${p.tahun}">
          <i class="bi bi-box-arrow-up-right"></i> Tab Baru</button>
      </div>`).join("");
    return `<div class="dalam-angka-wilayah">
      <div class="dalam-angka-wilayah-title">${escapeHtml(w.nama_wilayah)}
        <span class="datatable-menu-count">${jenisLabel}</span></div>
      ${items}
    </div>`;
  }).join("");
}

async function dalamAngkaResolveUrl(btn) {
  const { kode, jenis, tahun } = btn.dataset;
  const params = new URLSearchParams({ kode_wilayah: kode, jenis_wilayah: jenis, tahun });
  const res = await fetch(`/api/dalam-angka/preview?${params.toString()}`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

function bindDalamAngka() {
  document.getElementById("btnDalamAngka").addEventListener("click", dalamAngkaOpen);

  const overlay = document.getElementById("dalamAngkaOverlay");
  document.getElementById("dalamAngkaClose").addEventListener("click", () => (overlay.hidden = true));
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) overlay.hidden = true;
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !overlay.hidden) overlay.hidden = true;
  });

  let debounce;
  document.getElementById("dalamAngkaSearch").addEventListener("input", (e) => {
    clearTimeout(debounce);
    const value = e.target.value;
    debounce = setTimeout(() => dalamAngkaRender(value), 120);
  });

  document.getElementById("dalamAngkaList").addEventListener("click", async (e) => {
    const btn = e.target.closest("button[data-action]");
    if (!btn) return;
    btn.disabled = true;
    try {
      const { url, judul } = await dalamAngkaResolveUrl(btn);
      if (btn.dataset.action === "preview") {
        openPdfPreviewModal(url, judul || btn.dataset.judul);
      } else {
        window.open(url, "_blank", "noopener");
      }
    } catch (err) {
      toast(err.message, true);
    } finally {
      btn.disabled = false;
    }
  });
}

document.addEventListener("DOMContentLoaded", bindDalamAngka);
