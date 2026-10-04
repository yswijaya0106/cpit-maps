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
  mapLayers: { active: {}, colors: {}, opacity: {}, labels: {}, meta: {}, lod: {} },
  // overlay peta referensi (SHP) dari folder Maps/ — bisa multi-provinsi/kabupaten aktif
  // sekaligus, jadi active/opacity/meta dikunci pakai layerKey = "provinsi::kabupaten::layer"
  // (bukan cuma nama layer mentah, supaya layer bernama sama di kabupaten berbeda tidak
  // tabrakan): active[layerKey] = google.maps.Data, meta[layerKey] = {provinsi,kabupaten,layer}.
  // colors/labels tetap dikunci nama layer mentah (meta[key].layer) supaya layer bertipe
  // sama tetap konsisten warnanya lintas kabupaten.
  // lod[layerKey] = { lod, tersedia, memuat } -- tingkat detail geometri yang sedang
  // tampil (lihat mapLayerLodForZoom/refreshMapLayerLod di maps-overlay.js).
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
  appMode: null, // "sijalan" | "sikon" -- dipilih di halaman pembuka (#modeOverlay), lihat setAppMode()
  loginMode: null, // aplikasi yg dipilih sebelum login (form login tampil hanya bila terisi)
};

// SiJalan vs Sikon (deck "20261002 Preparation, Implementation and Validation
// of IJD" hal. 5): SiJalan = penilaian IJD (moda IJD saja), Sikon = semua
// sektor, data IJD tanpa penilaian. Role 'umum' hanya boleh Sikon -- backend
// menolak endpoint penilaian utk role itu (_PATH_PENILAIAN di app.py), UI di
// sini hanya menyembunyikan supaya konsisten.
const APP_MODE_LABEL = { sijalan: "SiJalan", sikon: "Sikon" };
const PENILAIAN_BUTTONS = ["btnUsulanExportIjdScore", "btnIjdDashboard", "btnUsulanExportNpr"];

function aksesPenilaianRole() {
  return !(state.auth.required && state.auth.role === "umum");
}

function aksesPenilaian() {
  return aksesPenilaianRole() && state.appMode !== "sikon";
}

function setAppMode(mode) {
  if (mode === "sijalan" && !aksesPenilaianRole()) return;
  state.appMode = mode;
  try { sessionStorage.setItem("appMode", mode); } catch (e) { /* storage diblokir: mode berlaku sampai reload */ }
  document.getElementById("modeOverlay").hidden = true;
  // Panel detail usulan yg sedang terbuka bisa berisi blok penilaian dari mode sebelumnya
  const detail = document.getElementById("usulanBrowseDetail");
  if (detail) detail.innerHTML = "";
  if (typeof usulanAppModeChanged === "function") usulanAppModeChanged();
  applyAuthRestrictions();
}

function perluLogin() {
  return state.auth.required && !state.auth.username;
}

// Halaman pembuka (mockup deck hal. 5): tampil SEBELUM login -- tombol tiap
// kartu "Login" membuka form login utk aplikasi itu. Sudah login (atau auth
// nonaktif): tombol "Masuk" langsung pindah aplikasi.
function bukaPilihanMode() {
  const login = perluLogin();
  document.getElementById("modeSijalanLock").hidden = login || aksesPenilaianRole();
  document.getElementById("modeCardSijalan").disabled = !login && !aksesPenilaianRole();
  document.querySelectorAll(".mode-btn-label").forEach((s) => (s.textContent = login ? "Login" : "Masuk"));
  document.querySelectorAll(".mode-card").forEach((c) =>
    c.classList.toggle("active", !!state.appMode && c.classList.contains(`mode-card-${state.appMode}`)));
  document.getElementById("modeOverlay").hidden = false;
}

function pilihMode(mode) {
  if (!perluLogin()) {
    setAppMode(mode);
    return;
  }
  // Mode diingat di sessionStorage -> dipakai initAppMode setelah login me-reload halaman
  try { sessionStorage.setItem("appMode", mode); } catch (e) { /* abaikan */ }
  state.loginMode = mode;
  document.getElementById("loginBrandMode").textContent = APP_MODE_LABEL[mode];
  document.getElementById("loginOverlay").classList.toggle("login-sikon", mode === "sikon");
  document.getElementById("loginModeLabel").textContent = mode === "sijalan" ? "Dashboard IJD" : "Dashboard Konektivitas";
  document.getElementById("loginModeLabel").hidden = false;
  document.getElementById("modeOverlay").hidden = true;
  applyAuthRestrictions();
  document.getElementById("loginUsername").focus();
}

// Dipanggil setelah status login diketahui: pakai mode yg tersimpan di sesi
// tab ini, kalau belum ada (atau belum login) tampilkan halaman pembuka.
function initAppMode() {
  if (perluLogin()) {
    bukaPilihanMode();
    return;
  }
  let simpan = null;
  try { simpan = sessionStorage.getItem("appMode"); } catch (e) { /* abaikan */ }
  if (simpan === "sijalan" && !aksesPenilaianRole()) {
    simpan = null;
    toast("Akun Anda (umum) hanya dapat membuka Sikon.", true);
  }
  if (APP_MODE_LABEL[simpan]) setAppMode(simpan);
  else bukaPilihanMode();
}

// role 'admin' vs 'user' vs 'umum' (tabel users, lihat auth.py/_require_admin di app.py)
// -- 'user' cuma boleh melihat data, tidak boleh import xlsx usulan IJD;
// 'umum' juga tidak melihat hasil penilaian IJD (lihat aksesPenilaian()).
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
  // Form login hanya setelah aplikasi dipilih di halaman pembuka (pilihMode)
  if (overlay) overlay.hidden = !(perluLogin() && state.loginMode);

  // Penilaian IJD: hanya MENYEMBUNYIKAN (tidak pernah memunculkan) tombol
  // toolbar usulan -- yg memunculkan adalah usulanToolbarSync() sesuai moda,
  // yang lalu memanggil fungsi ini lagi.
  const akses = aksesPenilaian();
  if (!akses) PENILAIAN_BUTTONS.forEach((id) => { const b = document.getElementById(id); if (b) b.hidden = true; });
  const lap = document.getElementById("btnLaporanPrioritas");
  if (lap) lap.hidden = !akses;
  const acuan = document.querySelector('[data-biaya-tab="acuan"]');
  if (acuan) acuan.hidden = !akses;
  const brand = document.getElementById("brandMode");
  if (brand && state.appMode) brand.textContent = APP_MODE_LABEL[state.appMode];
  const sw = document.getElementById("btnModeSwitch");
  if (sw) sw.hidden = !state.appMode;
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
  initAppMode();
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
  try { sessionStorage.removeItem("appMode"); } catch (e) { /* abaikan */ }
  location.reload();
}

document.addEventListener("DOMContentLoaded", () => {
  initAuth();
  document.getElementById("loginForm")?.addEventListener("submit", handleLoginSubmit);
  document.getElementById("btnLogout")?.addEventListener("click", handleLogout);
  document.querySelectorAll("[data-app-mode]").forEach((b) => b.addEventListener("click", () => pilihMode(b.dataset.appMode)));
  document.getElementById("btnModeSwitch")?.addEventListener("click", bukaPilihanMode);
  document.addEventListener("keydown", (e) => {
    const ov = document.getElementById("modeOverlay");
    if (e.key === "Escape" && ov && !ov.hidden && state.appMode) ov.hidden = true; // batal ganti aplikasi
  });
  document.getElementById("btnLoginKembali")?.addEventListener("click", () => {
    state.loginMode = null;
    applyAuthRestrictions();
    bukaPilihanMode();
  });
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
