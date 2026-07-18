/* RouteGIS — shared app state */

const ROUTE_COLORS = ["#4f7cff", "#22d3a5", "#ffb648", "#ff5c7c", "#a78bfa", "#38bdf8"];

const state = {
  map: null,
  mapProvider: "google", // "google" | "osm" — basemap aktif, default Google Maps
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
  usulanBrowse: { provinsi: "", q: "", offset: 0, limit: 50, total: 0 },
  browseUsulanPolylines: [], // geometri usulan yang sedang dilihat di panel "Jelajahi Usulan Inpres"
  mapLayers: { active: {}, colors: {}, opacity: {}, labels: {}, meta: {}, selectedProvinsi: null, selectedKabupaten: null },
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
};

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
