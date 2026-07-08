/* RouteGIS — asisten chat (Gemini), digroundkan ke data rute/analisis yang sedang aktif */

function buildChatContext() {
  const route = state.routes[state.selectedIndex];
  if (!route) return null;

  const context = {
    rute: {
      nama: route.route_name,
      mode_transportasi: route.transport_mode,
      jarak_km: route.distance_km,
      durasi_menit: route.duration_min,
    },
  };
  if (state.lastAdminRegions) context.wilayah_administratif_dilalui = state.lastAdminRegions;
  if (state.lastRoadClass) context.klasifikasi_jalan_osm = state.lastRoadClass;
  if (state.lastUsulanNearby) context.usulan_inpres_di_sekitar_rute = state.lastUsulanNearby;
  return context;
}

function renderChatMessages() {
  const listEl = document.getElementById("chatMessages");
  if (!listEl) return;
  listEl.innerHTML = state.chat.messages
    .map((m) => `<div class="chat-msg chat-msg-${m.role}">${escapeHtml(m.text)}</div>`)
    .join("");
  if (state.chat.busy) {
    listEl.innerHTML += `<div class="chat-msg chat-msg-assistant chat-msg-loading">Mengetik...</div>`;
  }
  listEl.scrollTop = listEl.scrollHeight;
}

async function sendChatMessage(text) {
  if (!text.trim() || state.chat.busy) return;

  state.chat.messages.push({ role: "user", text: text.trim() });
  state.chat.busy = true;
  renderChatMessages();

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        messages: state.chat.messages,
        context: buildChatContext(),
      }),
    });
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    state.chat.messages.push({ role: "assistant", text: data.reply });
  } catch (err) {
    console.error(err);
    state.chat.messages.push({ role: "assistant", text: "Maaf, terjadi kesalahan saat menghubungi asisten. Coba lagi." });
  } finally {
    state.chat.busy = false;
    renderChatMessages();
  }
}

const CHAT_GREETING = "Halo! Cari rute lalu tanya saya tentang jarak, wilayah yang dilalui, klasifikasi jalan, atau usulan Inpres di sekitarnya.";

function resetChat() {
  state.chat.messages = [{ role: "assistant", text: CHAT_GREETING }];
  state.chat.busy = false;
  renderChatMessages();
}

function bindChatPanel() {
  const toggleBtn = document.getElementById("btnChatToggle");
  const panel = document.getElementById("chatPanel");
  const closeBtn = document.getElementById("chatClose");
  const form = document.getElementById("chatForm");
  const input = document.getElementById("chatInput");
  const summaryBtn = document.getElementById("btnChatSummary");

  toggleBtn.addEventListener("click", () => {
    panel.hidden = !panel.hidden;
    if (!panel.hidden) input.focus();
  });
  closeBtn.addEventListener("click", () => (panel.hidden = true));

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const text = input.value;
    input.value = "";
    sendChatMessage(text);
  });

  summaryBtn.addEventListener("click", () => {
    if (!state.routes[state.selectedIndex]) {
      toast("Cari rute dulu sebelum minta ringkasan", true);
      return;
    }
    sendChatMessage("Tolong buatkan ringkasan singkat mengenai rute ini berdasarkan data yang tersedia.");
  });

  renderChatMessages();
}
