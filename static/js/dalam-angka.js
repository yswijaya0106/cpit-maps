/* The Next - SiJalan — panel topbar "Dalam Angka": cari & pratinjau PDF BPS
   Dalam Angka utk seluruh provinsi/kabupaten/kota. Tidak bergantung pada
   Google Maps -- di-bind langsung saat DOM siap, sama seperti data-viewer.js. */

const dalamAngkaPanel = {
  wilayah: null, // cache /api/dalam-angka/list (semua provinsi + kab/kota)
};

// Tab "Data per Subjek" -- jelajah tabel dinamis BPS Web API per kategori/
// subjek/variabel, terpisah dari katalog publikasi PDF di atas.
const bpsSubjekPanel = {
  loaded: false, // subcat sudah dimuat sekali (jarang berubah, tak perlu reload tiap buka tab)
};

async function dalamAngkaOpen() {
  const overlay = document.getElementById("dalamAngkaOverlay");
  overlay.hidden = false;
  dalamAngkaSwitchTab("publikasi");
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

function dalamAngkaSwitchTab(tab) {
  document.getElementById("dalamAngkaTabPublikasi").classList.toggle("active", tab === "publikasi");
  document.getElementById("dalamAngkaTabSubjek").classList.toggle("active", tab === "subjek");
  document.getElementById("dalamAngkaPublikasiView").hidden = tab !== "publikasi";
  document.getElementById("dalamAngkaSubjekView").hidden = tab !== "subjek";
  document.getElementById("dalamAngkaSearchField").hidden = tab !== "publikasi";
  if (tab === "subjek" && !bpsSubjekPanel.loaded) {
    bpsSubjekPanel.loaded = true;
    bpsSubjekLoadSubcat();
  }
}

function bpsSubjekResetSelect(id, placeholder) {
  const el = document.getElementById(id);
  el.innerHTML = `<option value="">${placeholder}</option>`;
  el.disabled = true;
}

async function bpsSubjekLoadSubcat() {
  const el = document.getElementById("bpsSubjekSubcat");
  try {
    const res = await fetch("/api/bps-subjek/subcat");
    if (!res.ok) throw new Error((await res.json()).detail || "Gagal memuat kategori");
    const items = await res.json();
    el.innerHTML = items.map((s) => `<option value="${s.subcat_id}">${escapeHtml(s.title)}</option>`).join("");
    el.disabled = false;
    if (items.length) bpsSubjekLoadSubject(items[0].subcat_id);
  } catch (err) {
    el.innerHTML = `<option value="">Gagal memuat</option>`;
    toast(err.message, true);
  }
}

async function bpsSubjekLoadSubject(subcatId) {
  bpsSubjekResetSelect("bpsSubjekSubject", "Memuat...");
  bpsSubjekResetSelect("bpsSubjekVar", "— pilih subjek dulu —");
  bpsSubjekResetSelect("bpsSubjekTahun", "—");
  const el = document.getElementById("bpsSubjekSubject");
  try {
    const res = await fetch(`/api/bps-subjek/subject?subcat=${encodeURIComponent(subcatId)}`);
    if (!res.ok) throw new Error((await res.json()).detail || "Gagal memuat subjek");
    const items = await res.json();
    el.innerHTML = items.map((s) => `<option value="${s.sub_id}">${escapeHtml(s.title)}</option>`).join("");
    el.disabled = false;
    if (items.length) bpsSubjekLoadVar(items[0].sub_id);
  } catch (err) {
    el.innerHTML = `<option value="">Gagal memuat</option>`;
    toast(err.message, true);
  }
}

async function bpsSubjekLoadVar(subjectId) {
  bpsSubjekResetSelect("bpsSubjekVar", "Memuat...");
  bpsSubjekResetSelect("bpsSubjekTahun", "—");
  const el = document.getElementById("bpsSubjekVar");
  document.getElementById("bpsSubjekResult").innerHTML =
    `<div class="adv-loading">Pilih variabel untuk melihat data.</div>`;
  try {
    const res = await fetch(`/api/bps-subjek/var?subject=${encodeURIComponent(subjectId)}`);
    if (!res.ok) throw new Error((await res.json()).detail || "Gagal memuat variabel");
    const items = await res.json();
    if (!items.length) {
      el.innerHTML = `<option value="">Tidak ada variabel</option>`;
      return;
    }
    el.innerHTML = items.map((v) => `<option value="${v.var_id}">${escapeHtml(v.title)}</option>`).join("");
    el.disabled = false;
    bpsSubjekLoadTahun(items[0].var_id);
  } catch (err) {
    el.innerHTML = `<option value="">Gagal memuat</option>`;
    toast(err.message, true);
  }
}

async function bpsSubjekLoadTahun(varId) {
  bpsSubjekResetSelect("bpsSubjekTahun", "Memuat...");
  const el = document.getElementById("bpsSubjekTahun");
  document.getElementById("bpsSubjekResult").innerHTML =
    `<div class="adv-loading">Memuat data...</div>`;
  try {
    const res = await fetch(`/api/bps-subjek/${encodeURIComponent(varId)}/tahun`);
    if (!res.ok) throw new Error((await res.json()).detail || "Gagal memuat tahun");
    const items = await res.json(); // urutan dari BPS: terbaru dulu
    if (!items.length) {
      el.innerHTML = `<option value="">Tidak ada tahun</option>`;
      document.getElementById("bpsSubjekResult").innerHTML =
        `<div class="adv-loading">Tidak ada tahun tersedia utk variabel ini.</div>`;
      return;
    }
    el.innerHTML = items.map((t) => `<option value="${t.th_id}">${escapeHtml(t.th)}</option>`).join("");
    el.disabled = false;
    bpsSubjekLoadData(varId, items[0].th_id);
  } catch (err) {
    el.innerHTML = `<option value="">Gagal memuat</option>`;
    toast(err.message, true);
  }
}

async function bpsSubjekLoadData(varId, thId) {
  const resultEl = document.getElementById("bpsSubjekResult");
  resultEl.innerHTML = `<div class="adv-loading">Memuat data...</div>`;
  try {
    const res = await fetch(`/api/bps-subjek/${encodeURIComponent(varId)}/data?th=${encodeURIComponent(thId)}`);
    if (!res.ok) throw new Error((await res.json()).detail || "Gagal memuat data");
    const data = await res.json();
    const rows = data.rows.map((r) => `
      <tr><td>${escapeHtml(r.wilayah || "-")}</td>
        <td class="bps-subjek-nilai">${r.nilai === null ? "-" : Number(r.nilai).toLocaleString("id-ID")}</td></tr>`
    ).join("");
    resultEl.innerHTML = `
      <div class="bps-subjek-meta">
        <strong>${escapeHtml(data.var || "")}</strong>
        ${data.unit && data.unit !== "Tidak Ada Satuan" ? ` (${escapeHtml(data.unit)})` : ""}
        — Tahun ${escapeHtml(String(data.tahun || ""))}
        · ${data.rows.length.toLocaleString("id-ID")} wilayah
        ${data.last_update ? ` · Terakhir diperbarui BPS: ${escapeHtml(data.last_update)}` : ""}
      </div>
      <div class="bps-subjek-table-wrap">
        <table class="bps-subjek-table">
          <thead><tr><th>Wilayah</th><th>Nilai</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>`;
  } catch (err) {
    resultEl.innerHTML = `<div class="adv-loading">${escapeHtml(err.message)}</div>`;
  }
}

function bindDalamAngka() {
  document.getElementById("btnDalamAngka").addEventListener("click", dalamAngkaOpen);

  document.getElementById("dalamAngkaTabPublikasi").addEventListener("click", () => dalamAngkaSwitchTab("publikasi"));
  document.getElementById("dalamAngkaTabSubjek").addEventListener("click", () => dalamAngkaSwitchTab("subjek"));

  document.getElementById("bpsSubjekSubcat").addEventListener("change", (e) => {
    if (e.target.value) bpsSubjekLoadSubject(e.target.value);
  });
  document.getElementById("bpsSubjekSubject").addEventListener("change", (e) => {
    if (e.target.value) bpsSubjekLoadVar(e.target.value);
  });
  document.getElementById("bpsSubjekVar").addEventListener("change", (e) => {
    if (e.target.value) bpsSubjekLoadTahun(e.target.value);
  });
  document.getElementById("bpsSubjekTahun").addEventListener("change", (e) => {
    const varId = document.getElementById("bpsSubjekVar").value;
    if (e.target.value && varId) bpsSubjekLoadData(varId, e.target.value);
  });

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
      if (btn.dataset.action === "preview") {
        // Proxy lewat backend (bukan link BPS mentah) -- iframe cross-origin
        // langsung ke webapi.bps.go.id kena WAF anti-bot-nya secara tidak
        // konsisten, lihat _BPS_DOWNLOAD_UA/dalam_angka_pdf() di app.py.
        const { kode, jenis, tahun, judul } = btn.dataset;
        const params = new URLSearchParams({ kode_wilayah: kode, jenis_wilayah: jenis, tahun });
        openPdfPreviewModal(`/api/dalam-angka/pdf?${params.toString()}`, judul);
      } else {
        const { url } = await dalamAngkaResolveUrl(btn);
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
