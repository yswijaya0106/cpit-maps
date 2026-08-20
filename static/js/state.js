/* The Next - SiJalan — shared app state */

const ROUTE_COLORS = ["#4f7cff", "#22d3a5", "#ffb648", "#ff5c7c", "#a78bfa", "#38bdf8"];

const state = {
  map: null,
  mapProvider: "osm", // "google" | "osm" — basemap aktif, default OpenStreetMap
  mapTheme: "light",  // "dark" | "light" — tema warna roadmap Google Maps
  origin: null,       // {lat, lng, label}
  destination: null,
  waypoints: [],       // [{lat, lng, label}]
  mode: "DRIVING",
  markers: { origin: null, destination: null, waypoints: [] },
  polylines: [],
  routes: [],          // computed route metadata objects
  selectedIndex: 0,
  activeField: null,   // "origin" | "destination" | <waypoint index> | null — which field the next map click should fill
  usulanPolylines: [], // overlay layer: geometri usulan Inpres yang ditampilkan di peta
  usulanBounds: null,  // akumulasi bounds semua usulan yang sudah ditampilkan, supaya klik berikutnya tidak "menyembunyikan" yang sebelumnya
  usulanBrowse: { provinsi: "", kabupaten_kota: "", q: "", offset: 0, limit: 50, total: 0, moda: "IJD" },
  browseUsulanPolylines: [], // geometri usulan yang sedang dilihat di panel "Jelajahi Usulan Inpres"
  mapLayers: { active: {}, colors: {}, opacity: {}, labels: {}, meta: {} },
  // overlay peta referensi (SHP) dari folder Maps/ — bisa multi-provinsi/kabupaten aktif
  // sekaligus, jadi active/opacity/meta dikunci pakai layerKey = "provinsi::kabupaten::layer"
  // (bukan cuma nama layer mentah, supaya layer bernama sama di kabupaten berbeda tidak
  // tabrakan): active[layerKey] = google.maps.Data, meta[layerKey] = {provinsi,kabupaten,layer}.
  // colors/labels tetap dikunci nama layer mentah (meta[key].layer) supaya layer bertipe
  // sama tetap konsisten warnanya lintas kabupaten.
  mapTool: null,        // "identify" | "select" | "measure-distance" | "measure-area" | null
  measure: { path: [], overlay: null },
  selectedFeatures: [], // [{layer, feature}] — hasil tool "select" pada layer overlay
  lastAdminRegions: null,  // hasil analisis wilayah administratif rute terpilih, untuk konteks chat
  lastRoadClass: null,     // hasil analisis klasifikasi jalan (OSM) rute terpilih, untuk konteks chat
  lastUsulanNearby: null,  // hasil pencarian usulan Inpres di sepanjang rute, untuk konteks chat
  chat: {
    messages: [{
      role: "assistant",
      text: "Halo! Cari rute lalu tanya saya tentang jarak, wilayah yang dilalui, klasifikasi jalan, atau usulan Inpres di sekitarnya.",
    }],
    busy: false,
  }, // riwayat percakapan asisten Gemini
  auth: { username: null, role: null, required: false }, // hasil GET /api/auth/me, lihat applyAuthRestrictions()
};

// role 'admin' vs 'user' (tabel users, lihat auth.py/_require_admin di app.py)
// -- 'user' cuma boleh melihat data, tidak boleh import xlsx usulan IJD.
// Kalau auth nonaktif (state.auth.required===false, mis. dev lokal tanpa
// tabel users), tombol TIDAK disembunyikan & form login TIDAK ditampilkan
// -- backend juga tidak menegakkan _require_admin/auth_middleware dalam
// kondisi itu, jadi UI harus konsisten dgn itu. Dipanggil ulang tiap kali
// state.auth berubah (login/logout) ATAU tiap kali kode lain nge-toggle
// .hidden tombol yg sama (mis. ganti moda Udara/Darat/Laut) supaya
// pembatasan tidak ketiban timpa.
function applyAuthRestrictions() {
  const btn = document.getElementById("btnUsulanImport");
  if (btn) btn.hidden = state.auth.required && state.auth.role !== "admin";

  const userBadge = document.getElementById("topbarUser");
  const usernameEl = document.getElementById("topbarUsername");
  if (userBadge) {
    userBadge.hidden = !state.auth.username;
    if (usernameEl) usernameEl.textContent = state.auth.username ? `${state.auth.username} (${state.auth.role})` : "";
  }

  const overlay = document.getElementById("loginOverlay");
  if (overlay) overlay.hidden = !(state.auth.required && !state.auth.username);
}

async function initAuth() {
  try {
    // cache: "no-store" -- GET biasa bisa disajikan browser dari cache HTTP
    // walau habis location.reload(), bikin status login kelihatan "nyangkut"
    // (mis. setelah logout, /api/auth/me masih balikin sesi lama).
    const res = await fetch("/api/auth/me", { cache: "no-store" });
    if (res.ok) {
      const data = await res.json();
      // API balikin "auth_required" (lihat GET /api/auth/me di app.py) --
      // dipetakan ke "required" di sini spy nama field internal konsisten
      // dgn sisa state.auth.
      state.auth = { username: data.username, role: data.role, required: data.auth_required };
    }
  } catch (err) {
    console.error(err);
  }
  applyAuthRestrictions();
}

async function handleLoginSubmit(e) {
  e.preventDefault();
  const username = document.getElementById("loginUsername").value.trim();
  const password = document.getElementById("loginPassword").value;
  const errEl = document.getElementById("loginError");
  const btn = document.getElementById("btnLoginSubmit");
  errEl.hidden = true;
  btn.disabled = true;
  try {
    const res = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Login gagal");
    // Reload paling sederhana & aman drpd re-init manual tiap panel yg
    // sudah terlanjur fetch data (401) sebelum login selesai.
    location.reload();
  } catch (err) {
    errEl.textContent = err.message || String(err);
    errEl.hidden = false;
    btn.disabled = false;
  }
}

async function handleLogout() {
  try {
    await fetch("/api/auth/logout", { method: "POST" });
  } catch (err) {
    console.error(err);
  }
  location.reload();
}

document.addEventListener("DOMContentLoaded", () => {
  initAuth();
  document.getElementById("loginForm")?.addEventListener("submit", handleLoginSubmit);
  document.getElementById("btnLogout")?.addEventListener("click", handleLogout);
});

function toast(msg, isError = false) {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.hidden = false;
  el.classList.toggle("error", isError);
  clearTimeout(toast._t);
  toast._t = setTimeout(() => (el.hidden = true), 3800);
}

function setStatus(msg) {
  document.getElementById("topbarStatus").textContent = msg;
}
