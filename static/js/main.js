/* The Next - SiJalan — reset action & top-level UI wiring */

function resetAll() {
  state.origin = null;
  state.destination = null;
  state.waypoints = [];
  state.routes = [];
  state.selectedIndex = 0;
  document.getElementById("inputOrigin").value = "";
  document.getElementById("inputDestination").value = "";
  renderWaypointList();
  updateMarkers();
  clearPolylines();
  clearUsulanPolylines();
  if (state.searchMarker) state.searchMarker.setMap(null);
  state.searchMarker = null;
  state.searchInfoWindow?.close();
  document.getElementById("inputMapSearch").value = "";
  document.getElementById("routeResultsPanel").hidden = true;
  document.getElementById("analysisPanel").hidden = true;
  document.getElementById("advancedPanel").hidden = true;
  clearAdvancedResults();
  document.getElementById("exportPanel").hidden = true;
  resetChat();
  setMapTool(null);
  setStatus("Siap");
  toast("Semua data direset");
}

function bindUI() {
  document.getElementById("btnAddStop").addEventListener("click", () => {
    addWaypoint({ lat: state.map.getCenter().lat(), lng: state.map.getCenter().lng(), label: "Klik peta untuk memilih titik" });
    toast("Waypoint ditambahkan — klik pada peta atau cari alamat untuk menentukan lokasinya");
  });

  document.getElementById("btnFindRoute").addEventListener("click", findRoutes);
  document.getElementById("btnClearAll").addEventListener("click", resetAll);
  document.getElementById("btnAdminRegions").addEventListener("click", analyzeAdminRegions);
  document.getElementById("btnRoadClass").addEventListener("click", analyzeRoadClassification);
  document.getElementById("btnUsulanInpres").addEventListener("click", analyzeUsulanInpres);

  document.getElementById("btnSidebarToggle").addEventListener("click", () => {
    document.getElementById("sidebar").classList.toggle("open");
  });

  // Dropdown "..." mobile (topbar-more) -- nav sekunder (basemap/overlay/
  // Data/Lokus Bappenas/Dalam Angka/Laporan Prioritas), lihat style.css
  // @media max-width:900px.
  document.getElementById("btnTopbarMore").addEventListener("click", (e) => {
    e.stopPropagation();
    document.getElementById("topbarMore").classList.toggle("open");
  });
  // Tutup otomatis HANYA utk tombol yg langsung buka overlay/modal
  // penuh sendiri (btnBasemapToggle cuma toggle state instan) -- BUKAN
  // btnDataTable / maplayer-toggle, yg buka dropdown/panel BERSARANG di
  // dalam topbar-more sendiri; kalau ikut ditutup, panel bersarangnya
  // ikut hilang sebelum sempat kelihatan.
  ["btnBasemapToggle", "btnLokusBappenas", "btnDalamAngka", "btnLaporanPrioritas"].forEach((id) => {
    document.getElementById(id).addEventListener("click", () => {
      document.getElementById("topbarMore").classList.remove("open");
    });
  });
  document.addEventListener("click", (e) => {
    const more = document.getElementById("topbarMore");
    if (more.classList.contains("open") && !more.contains(e.target) && e.target.id !== "btnTopbarMore") {
      more.classList.remove("open");
    }
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") document.getElementById("topbarMore").classList.remove("open");
  });

  bindModeGrid();
  bindManualCoord();
  bindExportButtons();
  bindUsulanBrowse();
  bindChatPanel();
}
