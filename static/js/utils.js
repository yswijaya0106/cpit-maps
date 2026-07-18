/* RouteGIS — generic formatting/DOM helpers shared across modules */

function escapeHtml(str) {
  return String(str).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// Kolom flag biner (TINYINT(1), mis. "pertanian_ada", "kendaraan_estimasi") di
// tabel-tabel database -- dipakai data-viewer.js (viewer "Data") DAN map-tools.js
// (join atribut kecamatan di popup identify) supaya render 0/1 sbg ikon konsisten
// di kedua tempat, bukan cuma salah satu.
const DB_BOOL_COL_RX = /_ada$|_estimasi$/i;
function isBoolDbCol(colName) {
  return DB_BOOL_COL_RX.test(colName);
}
function boolCellHtml(value) {
  return value === 1
    ? '<i class="bi bi-check-circle-fill bool-true" title="Ya"></i>'
    : '<i class="bi bi-x-circle bool-false" title="Tidak"></i>';
}

function formatDuration(minutes) {
  const h = Math.floor(minutes / 60);
  const m = Math.round(minutes % 60);
  return h > 0 ? `${h} jam ${m} mnt` : `${m} mnt`;
}

function formatDelta(value, unit) {
  if (Math.abs(value) < (unit === "km" ? 0.05 : 0.5)) return null;
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(unit === "km" ? 1 : 0)} ${unit}`;
}

function formatRupiah(value) {
  if (value === null || value === undefined) return "-";
  return "Rp " + Number(value).toLocaleString("id-ID");
}

function bearingToCompass(deg) {
  const dirs = ["Utara", "Timur Laut", "Timur", "Tenggara", "Selatan", "Barat Daya", "Barat", "Barat Laut"];
  return dirs[Math.round(deg / 45) % 8];
}

function pickEvenSamples(arr, maxSamples) {
  if (arr.length <= maxSamples) return arr.map((v, i) => ({ value: v, index: i }));
  const step = arr.length / maxSamples;
  const seen = new Set();
  const out = [];
  for (let i = 0; i < maxSamples; i++) {
    const idx = Math.min(arr.length - 1, Math.floor(i * step));
    if (!seen.has(idx)) {
      seen.add(idx);
      out.push({ value: arr[idx], index: idx });
    }
  }
  return out;
}

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
