/* The Next - SiJalan — Google Maps bootstrap, geocoding, address search */

function initApp() {
  state.map = new google.maps.Map(document.getElementById("map"), {
    center: { lat: -6.2088, lng: 106.8456 }, // Jakarta
    zoom: 12,
    mapTypeId: google.maps.MapTypeId.SATELLITE,
    disableDefaultUI: false,
    fullscreenControl: false,
    streetViewControl: false,
    styles: mapDarkStyle(),
  });

  state.map.addListener("click", (e) => {
    const pt = { lat: e.latLng.lat(), lng: e.latLng.lng(), label: `${e.latLng.lat().toFixed(5)}, ${e.latLng.lng().toFixed(5)}` };
    if (state.mapTool === "measure-distance" || state.mapTool === "measure-area") {
      handleMeasureClick(pt);
      return;
    }
    if (state.mapTool && state.mapTool !== "add-point") return; // identify/select tools act on feature clicks only, see map-tools.js
    handleMapClick(pt);
  });

  state.hoverInfoWindow = new google.maps.InfoWindow();

  attachAutocomplete(document.getElementById("inputOrigin"), setOrigin);
  attachAutocomplete(document.getElementById("inputDestination"), setDestination);
  document.getElementById("inputOrigin").addEventListener("focus", () => (state.activeField = "origin"));
  document.getElementById("inputDestination").addEventListener("focus", () => (state.activeField = "destination"));

  state.searchInfoWindow = new google.maps.InfoWindow();
  attachAutocomplete(
    document.getElementById("inputMapSearch"),
    showSearchResult,
    { componentRestrictions: { country: "id" } },
  );

  registerOsmMapType();
  bindBasemapToggle();
  applyBasemapProvider(state.mapProvider);

  bindUI();
  initMapLayersControl();
  bindMapToolsToolbar();
  setStatus("Peta siap");
}
window.initApp = initApp;

/* ---------- Basemap toggle: Google Maps <-> OpenStreetMap ----------
   OSM tiles are registered as a plain ImageMapType on the same
   google.maps.Map instance, so Marker/Polyline/InfoWindow/Data overlay/
   Directions/drawing/measure tools all keep working unchanged — only the
   raster tiles underneath switch. */

function getNormalizedOsmTileCoord(coord, zoom) {
  const tileRange = 1 << zoom;
  if (coord.y < 0 || coord.y >= tileRange) return null;
  let x = coord.x % tileRange;
  if (x < 0) x += tileRange;
  return { x, y: coord.y };
}

function registerOsmMapType() {
  const osmMapType = new google.maps.ImageMapType({
    getTileUrl: (coord, zoom) => {
      const norm = getNormalizedOsmTileCoord(coord, zoom);
      if (!norm) return null;
      // Public tile.openstreetmap.org server: fine for light/internal use.
      // Ganti ke tile server berbayar/self-hosted untuk trafik produksi
      // sesuai kebijakan penggunaan OSM (https://operations.osmfoundation.org/policies/tiles/).
      return `https://tile.openstreetmap.org/${zoom}/${norm.x}/${norm.y}.png`;
    },
    tileSize: new google.maps.Size(256, 256),
    minZoom: 0,
    maxZoom: 19,
    name: "OpenStreetMap",
  });
  state.map.mapTypes.set("osm", osmMapType);
}

function applyBasemapProvider(provider) {
  state.mapProvider = provider;
  state.map.setMapTypeId(provider === "osm" ? "osm" : google.maps.MapTypeId.SATELLITE);
  const label = document.getElementById("basemapLabel");
  if (label) label.textContent = provider === "osm" ? "OpenStreetMap" : "Google Maps";
  const attribution = document.getElementById("osmAttribution");
  if (attribution) attribution.hidden = provider !== "osm";
}

function bindBasemapToggle() {
  const btn = document.getElementById("btnBasemapToggle");
  if (!btn) return;
  btn.addEventListener("click", () => {
    applyBasemapProvider(state.mapProvider === "osm" ? "google" : "osm");
  });
}

function mapDarkStyle() {
  return [
    { elementType: "geometry", stylers: [{ color: "#16213a" }] },
    { elementType: "labels.text.stroke", stylers: [{ color: "#16213a" }] },
    { elementType: "labels.text.fill", stylers: [{ color: "#8fa0c9" }] },
    { featureType: "road", elementType: "geometry", stylers: [{ color: "#243254" }] },
    { featureType: "road.highway", elementType: "geometry", stylers: [{ color: "#2f4372" }] },
    { featureType: "water", elementType: "geometry", stylers: [{ color: "#0e1626" }] },
    { featureType: "poi", elementType: "geometry", stylers: [{ color: "#1b2440" }] },
    { featureType: "poi", elementType: "labels", stylers: [{ visibility: "off" }] },
    { featureType: "transit", stylers: [{ visibility: "off" }] },
  ];
}

function placeToPoint(place) {
  if (!place.geometry) return null;
  return {
    lat: place.geometry.location.lat(),
    lng: place.geometry.location.lng(),
    label: place.formatted_address || place.name,
  };
}

function attachAutocomplete(input, cb, extraOptions = {}) {
  const ac = new google.maps.places.Autocomplete(input, {
    fields: ["geometry", "formatted_address", "name"],
    ...extraOptions,
  });
  ac.addListener("place_changed", async () => {
    const place = ac.getPlace();
    let pt = placeToPoint(place);
    if (!pt) {
      // Enter/blur without picking a dropdown suggestion returns a place with
      // just the typed name and no geometry — fall back to a plain geocode.
      pt = await geocodeText(input.value);
    }
    if (pt) cb(pt);
    else toast("Lokasi tidak ditemukan", true);
  });
}

/* ---------- General address search (topbar) ---------- */

function showSearchResult(pt) {
  if (!pt) {
    toast("Lokasi tidak ditemukan", true);
    return;
  }
  if (state.searchMarker) state.searchMarker.setMap(null);

  state.searchMarker = new google.maps.Marker({
    position: { lat: pt.lat, lng: pt.lng },
    map: state.map,
    icon: {
      path: google.maps.SymbolPath.CIRCLE,
      scale: 10,
      fillColor: "#38bdf8",
      fillOpacity: 1,
      strokeColor: "#0f1420",
      strokeWeight: 2,
    },
    zIndex: 30,
  });

  state.searchInfoWindow.setContent(`
    <div class="search-info">
      <div class="search-info-title">${escapeHtml(pt.label)}</div>
      <div class="search-info-actions">
        <button data-act="origin">Jadikan Origin</button>
        <button data-act="destination">Jadikan Tujuan</button>
        <button data-act="waypoint">Tambah Waypoint</button>
      </div>
    </div>
  `);
  state.searchInfoWindow.setPosition({ lat: pt.lat, lng: pt.lng });
  state.searchInfoWindow.open(state.map);
  google.maps.event.addListenerOnce(state.searchInfoWindow, "domready", () => {
    const container = document.querySelector(".search-info");
    if (!container) return;
    container.querySelector('[data-act="origin"]').onclick = () => {
      setOrigin(pt);
      state.searchInfoWindow.close();
    };
    container.querySelector('[data-act="destination"]').onclick = () => {
      setDestination(pt);
      state.searchInfoWindow.close();
    };
    container.querySelector('[data-act="waypoint"]').onclick = () => {
      addWaypoint(pt);
      state.searchInfoWindow.close();
    };
  });

  state.map.panTo({ lat: pt.lat, lng: pt.lng });
  state.map.setZoom(15);
}

/* ---------- Geocoding fallback ----------
   Browser/OS autofill can populate the Origin/Destination text inputs
   directly (bypassing the Places Autocomplete "place_changed" event),
   leaving state.origin/state.destination empty even though the field
   shows text. Resolve any such typed-but-unselected text via Geocoder
   before giving up. */

let _geocoder = null;
function geocodeText(text) {
  if (!text || !text.trim()) return Promise.resolve(null);
  if (!_geocoder) _geocoder = new google.maps.Geocoder();
  return new Promise((resolve) => {
    _geocoder.geocode({ address: text }, (results, status) => {
      if (status === "OK" && results[0]) {
        const loc = results[0].geometry.location;
        resolve({ lat: loc.lat(), lng: loc.lng(), label: results[0].formatted_address });
      } else {
        // status selain ZERO_RESULTS biasanya soal konfigurasi API key (Geocoding
        // API belum di-enable, billing mati, atau referrer restriction) — bukan
        // alamatnya yang salah. Cek Console untuk kode status asli dari Google.
        if (status !== "ZERO_RESULTS") console.warn("Geocoder gagal:", status);
        resolve(null);
      }
    });
  });
}

function reverseGeocode(lat, lng) {
  if (!_geocoder) _geocoder = new google.maps.Geocoder();
  return new Promise((resolve) => {
    _geocoder.geocode({ location: { lat, lng } }, (results, status) => {
      if (status === "OK" && results[0]) resolve(results[0]);
      else resolve(null);
    });
  });
}

function extractAdminComponents(geocodeResult) {
  const comps = geocodeResult.address_components || [];
  const find = (type) => {
    const c = comps.find((c) => c.types.includes(type));
    return c ? c.long_name : null;
  };
  return {
    province: find("administrative_area_level_1"),
    city: find("administrative_area_level_2") || find("locality"),
    district: find("administrative_area_level_3") || find("administrative_area_level_4"),
  };
}

async function ensurePointFromInput(current, inputEl, setter) {
  const typed = inputEl.value.trim();
  // Re-resolve if the field is empty/unset, or the user edited the text
  // without it going through the Places Autocomplete "place_changed" event
  // (e.g. browser autofill, or typing a new address without picking a
  // suggestion) — otherwise a stale point from a previous search is reused.
  if (current && current.label === typed) return current;
  if (!typed) return null;
  const resolved = await geocodeText(typed);
  if (resolved) {
    setter(resolved);
    return resolved;
  }
  return null;
}
