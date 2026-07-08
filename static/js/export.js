/* RouteGIS — export selected route to GIS formats */

function bindExportButtons() {
  document.querySelectorAll(".btn-export").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const format = btn.dataset.format;
      const route = state.routes[state.selectedIndex];
      if (!route) {
        toast("Tidak ada rute terpilih", true);
        return;
      }
      btn.disabled = true;
      const originalText = btn.textContent;
      btn.textContent = "Mengekspor...";
      try {
        const payload = {
          format,
          routes: [
            {
              route_id: route.route_id,
              route_name: route.route_name,
              alternative: route.alternative,
              transport_mode: route.transport_mode,
              distance_km: route.distance_km,
              duration_min: route.duration_min,
              coordinates: route.coordinates,
              segments: route.segments,
            },
          ],
        };
        const res = await fetch("/api/export", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        if (!res.ok) throw new Error(await res.text());
        const blob = await res.blob();
        const disposition = res.headers.get("Content-Disposition") || "";
        const match = disposition.match(/filename=([^;]+)/);
        const filename = match ? match[1].trim() : `route.${format}`;
        downloadBlob(blob, filename);
        toast(`Berhasil mengekspor ${filename}`);
      } catch (err) {
        console.error(err);
        toast("Gagal mengekspor data", true);
      } finally {
        btn.disabled = false;
        btn.textContent = originalText;
      }
    });
  });
}
