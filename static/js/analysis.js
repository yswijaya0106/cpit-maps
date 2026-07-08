/* RouteGIS — analisis lanjutan: wilayah administratif & klasifikasi jalan */

async function analyzeAdminRegions() {
  const route = state.routes[state.selectedIndex];
  const content = document.getElementById("adminRegionsContent");
  if (!route) return;

  content.innerHTML = `<div class="adv-loading">Menganalisis wilayah administratif via Google Geocoding...</div>`;

  const samples = pickEvenSamples(route.coordinates, 12);
  const regions = [];

  for (const { value, index } of samples) {
    const [lat, lng] = value;
    const result = await reverseGeocode(lat, lng);
    if (!result) continue;
    const admin = extractAdminComponents(result);
    const key = `${admin.province}|${admin.city}`;
    if (regions.length && regions[regions.length - 1]._key === key) continue;
    regions.push({ ...admin, _key: key, index });
  }

  if (!regions.length) {
    content.innerHTML = `<div class="adv-error">Tidak dapat menentukan wilayah administratif untuk rute ini.</div>`;
    state.lastAdminRegions = null;
    return;
  }

  state.lastAdminRegions = regions.map((r) => ({ province: r.province, city: r.city, district: r.district }));

  let html = `<div class="adv-result-list">`;
  regions.forEach((r, i) => {
    const label = [r.city, r.province].filter(Boolean).join(", ") || "Tidak diketahui";
    html += `<div class="adv-region-row">
      <span class="adv-region-idx">${i + 1}</span>
      <span class="adv-region-name">${escapeHtml(label)}${r.district ? `<div class="adv-region-meta">${escapeHtml(r.district)}</div>` : ""}</span>
    </div>`;
  });
  html += `</div>`;
  content.innerHTML = html;
}

async function analyzeRoadClassification() {
  const route = state.routes[state.selectedIndex];
  const content = document.getElementById("roadClassContent");
  if (!route) return;

  content.innerHTML = `<div class="adv-loading">Mengambil data jaringan jalan dari OpenStreetMap (Overpass API)...</div>`;

  try {
    const res = await fetch("/api/analyze/road-classification", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ coordinates: route.coordinates }),
    });
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();

    if (!data.summary || !data.summary.length) {
      content.innerHTML = `<div class="adv-error">Tidak ada data jalan OSM yang cocok dengan rute ini.</div>`;
      state.lastRoadClass = null;
      return;
    }

    state.lastRoadClass = data.summary;

    let html = `<div class="adv-result-list">`;
    data.summary.forEach((s) => {
      html += `<div class="adv-bar-row">
        <div class="adv-bar-label"><span>${escapeHtml(s.road_type)}</span><span>${s.distance_km.toFixed(2)} km (${s.percentage}%)</span></div>
        <div class="adv-bar-track"><div class="adv-bar-fill" style="width:${s.percentage}%"></div></div>
      </div>`;
    });
    html += `</div>`;
    html += `<p class="hint">Klasifikasi berdasarkan tag <em>highway</em> OpenStreetMap terdekat dari rute — perkiraan, bukan data legal resmi Kementerian PUPR.</p>`;
    content.innerHTML = html;
  } catch (err) {
    console.error(err);
    content.innerHTML = `<div class="adv-error">Gagal menganalisis klasifikasi jalan: ${escapeHtml(String(err))}</div>`;
  }
}
