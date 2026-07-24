/* The Next - SiJalan — travel mode selection & Google Directions route computation */

function bindModeGrid() {
  document.querySelectorAll(".mode-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (btn.classList.contains("active")) return;
      document.querySelectorAll(".mode-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      state.mode = btn.dataset.mode;

      // If a route was already searched, recompute it immediately for the
      // new mode instead of leaving the old mode's route on screen.
      if (state.origin && state.destination) {
        findRoutes();
      }
    });
  });
}

function googleTravelMode(mode) {
  // Google Directions has no motorcycle profile; fall back to DRIVING.
  if (mode === "MOTORCYCLE") return google.maps.TravelMode.DRIVING;
  return google.maps.TravelMode[mode];
}

function directionsRequest(origin, destination, waypoints, travelMode, provideAlternatives, avoidTolls) {
  const svc = new google.maps.DirectionsService();
  return new Promise((resolve, reject) => {
    svc.route(
      {
        origin: { lat: origin.lat, lng: origin.lng },
        destination: { lat: destination.lat, lng: destination.lng },
        waypoints: waypoints.map((w) => ({ location: { lat: w.lat, lng: w.lng }, stopover: true })),
        travelMode,
        provideRouteAlternatives: provideAlternatives,
        avoidTolls: !!avoidTolls,
        optimizeWaypoints: false,
      },
      (result, status) => {
        if (status === "OK") resolve(result);
        else reject(status);
      }
    );
  });
}

function stripHtml(html) {
  const tmp = document.createElement("div");
  tmp.innerHTML = html;
  // Google nests secondary notes ("Closed Sundays...", "Pass by...") in child
  // <div>s alongside the main instruction text — drop them so road_name only
  // keeps the actual maneuver/street text.
  tmp.querySelectorAll("div").forEach((el) => el.remove());
  return (tmp.textContent || tmp.innerText || "").trim();
}

function buildRouteMeta(legs, coordinates, summary, modeLabel, altIndex, tollVariant) {
  let totalDistM = 0;
  let totalDurS = 0;
  const segments = [];
  let segId = 0;

  legs.forEach((leg) => {
    totalDistM += leg.distance ? leg.distance.value : 0;
    totalDurS += leg.duration ? leg.duration.value : 0;
    leg.steps.forEach((step) => {
      const start = step.start_location;
      const end = step.end_location;
      const bearing = google.maps.geometry.spherical.computeHeading(start, end);
      segments.push({
        segment_id: segId++,
        road_name: stripHtml(step.instructions).slice(0, 120),
        road_type: "",
        distance_km: step.distance ? step.distance.value / 1000 : 0,
        duration_min: step.duration ? step.duration.value / 60 : 0,
        bearing: (bearing + 360) % 360,
        start_lat: start.lat(),
        start_lng: start.lng(),
        end_lat: end.lat(),
        end_lng: end.lng(),
      });
    });
  });

  const fullText = segments.map((s) => s.road_name).join(" ").toLowerCase();
  const isToll = /\btol\b|\btoll\b/.test(fullText) || (summary || "").toLowerCase().includes("tol");

  const label = tollVariant === "no-toll" ? "Tanpa Tol" : tollVariant === "toll" ? "Dengan Tol" : `Alternatif ${altIndex + 1}`;

  return {
    route_id: `R${Date.now()}-${altIndex}-${tollVariant || "std"}`,
    route_name: `${summary || label} (${label})`,
    via: summary || "",
    variant_label: label,
    alternative: altIndex + 1,
    transport_mode: modeLabel,
    distance_km: totalDistM / 1000,
    duration_min: totalDurS / 60,
    waypoint_count: legs.length - 1,
    segment_count: segments.length,
    is_toll: isToll,
    tollVariant: tollVariant || "std",
    coordinates,
    segments,
  };
}

/* Google Directions does not return alternative routes when
   intermediate waypoints are present (documented API limitation).
   Workaround: request each leg (origin->stop1, stop1->stop2, ...,
   stopN->destination) independently with alternatives, then combine
   the per-leg options into a handful of full-trip combinations. */

function legDurationSec(route) {
  return route.legs[0] && route.legs[0].duration ? route.legs[0].duration.value : 0;
}

async function computeWaypointRouteCombos(points, travelMode, avoidTolls, wantAlternatives) {
  const legOptions = [];
  for (let i = 0; i < points.length - 1; i++) {
    const res = await directionsRequest(points[i], points[i + 1], [], travelMode, wantAlternatives, avoidTolls);
    const sorted = [...res.routes].sort((a, b) => legDurationSec(a) - legDurationSec(b));
    legOptions.push(sorted);
  }

  const baseIndices = legOptions.map(() => 0);
  const comboIndexSets = [baseIndices];

  if (wantAlternatives) {
    const candidates = [];
    legOptions.forEach((opts, legIdx) => {
      if (opts.length > 1) {
        candidates.push({ legIdx, delta: legDurationSec(opts[1]) - legDurationSec(opts[0]) });
      }
    });
    candidates.sort((a, b) => a.delta - b.delta);
    candidates.slice(0, 3).forEach(({ legIdx }) => {
      const idxSet = baseIndices.slice();
      idxSet[legIdx] = 1;
      comboIndexSets.push(idxSet);
    });
  }

  return comboIndexSets.map((idxSet) => {
    const chosen = idxSet.map((choice, legIdx) => legOptions[legIdx][choice]);
    const legs = chosen.map((r) => r.legs[0]);
    const coordinates = chosen.flatMap((r) => r.overview_path.map((p) => [p.lat(), p.lng()]));
    const summary = [...new Set(chosen.map((r) => r.summary).filter(Boolean))].join(" + ");
    return { legs, coordinates, summary };
  });
}

async function findRoutes() {
  setStatus("Memeriksa titik lokasi...");
  const origin = await ensurePointFromInput(state.origin, document.getElementById("inputOrigin"), setOrigin);
  const destination = await ensurePointFromInput(state.destination, document.getElementById("inputDestination"), setDestination);

  if (!origin || !destination) {
    toast("Tentukan titik Origin dan Destination terlebih dahulu", true);
    setStatus("Siap");
    return;
  }

  const waypointInputs = document.querySelectorAll("#waypointList input");
  for (let i = 0; i < state.waypoints.length; i++) {
    const input = waypointInputs[i];
    if (input && input.value.trim() !== state.waypoints[i].label) {
      const resolved = await geocodeText(input.value);
      if (resolved) state.waypoints[i] = resolved;
    }
  }

  setStatus("Menghitung rute...");
  clearPolylines();
  state.routes = [];

  const travelMode = googleTravelMode(state.mode);
  const provideAlternatives = document.getElementById("toggleAlternatives").checked;
  const compareTolls = document.getElementById("toggleCompareTolls").checked;

  try {
    const results = [];

    if (state.waypoints.length === 0) {
      const primary = await directionsRequest(state.origin, state.destination, [], travelMode, provideAlternatives, false);
      primary.routes.forEach((r, i) => {
        const coords = r.overview_path.map((p) => [p.lat(), p.lng()]);
        results.push(buildRouteMeta(r.legs, coords, r.summary, state.mode, i, compareTolls ? "toll" : null));
      });

      if (compareTolls) {
        const noToll = await directionsRequest(state.origin, state.destination, [], travelMode, false, true);
        noToll.routes.forEach((r, i) => {
          const coords = r.overview_path.map((p) => [p.lat(), p.lng()]);
          results.push(buildRouteMeta(r.legs, coords, r.summary, state.mode, results.length + i, "no-toll"));
        });
      }
    } else {
      const points = [state.origin, ...state.waypoints, state.destination];

      const primaryCombos = await computeWaypointRouteCombos(points, travelMode, false, provideAlternatives);
      primaryCombos.forEach((combo, i) => {
        results.push(buildRouteMeta(combo.legs, combo.coordinates, combo.summary, state.mode, i, compareTolls ? "toll" : null));
      });

      if (compareTolls) {
        const noTollCombos = await computeWaypointRouteCombos(points, travelMode, true, provideAlternatives);
        noTollCombos.forEach((combo, i) => {
          results.push(buildRouteMeta(combo.legs, combo.coordinates, combo.summary, state.mode, results.length + i, "no-toll"));
        });
      }
    }

    state.routes = results;
    state.selectedIndex = 0;
    drawPolylines();
    renderRouteList();
    renderAnalysis();
    document.getElementById("routeResultsPanel").hidden = false;
    document.getElementById("analysisPanel").hidden = false;
    document.getElementById("advancedPanel").hidden = false;
    document.getElementById("exportPanel").hidden = false;
    clearAdvancedResults();
    clearUsulanPolylines();
    setStatus(`${results.length} rute ditemukan`);
  } catch (err) {
    console.error(err);
    toast(`Gagal menghitung rute: ${err}`, true);
    setStatus("Gagal menghitung rute");
  }
}
