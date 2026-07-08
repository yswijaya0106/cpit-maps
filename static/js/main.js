/* RouteGIS — reset action & top-level UI wiring */

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

  bindModeGrid();
  bindManualCoord();
  bindExportButtons();
  bindUsulanBrowse();
  bindChatPanel();
}
