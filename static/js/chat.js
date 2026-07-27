/* The Next - SiJalan — asisten chat (Gemini), digroundkan ke data rute/analisis yang sedang aktif */

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

/* Markdown ringan buat balasan asisten (bold/italic/kode inline, daftar
   bernomor/poin, paragraf) -- BUKAN parser markdown lengkap, cukup utk gaya
   jawaban model (mis. "**Nilai:** 60", daftar skor bernomor spt di panel
   skor IJD). escapeHtml() dijalankan LEBIH DULU, olah markup di ATAS hasil
   yang sudah di-escape -- jadi HTML mentah apa pun di dalam teks (baik dari
   user maupun jawaban model) tidak pernah dieksekusi sbg tag; tag <strong>/
   <ul>/dst. yang ditambahkan di sini sepenuhnya kita yang buat, aman. */
function renderMarkdownLite(text) {
  const inline = (s) => s
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, "$1<em>$2</em>")
    .replace(/`([^`]+?)`/g, "<code>$1</code>");

  const lines = escapeHtml(text).split("\n");
  const html = [];
  // Model sering nulis "1. **X**:" lalu poin "- ..." di baris berikutnya
  // (dipisah baris kosong) sbg RINCIAN nomor itu, bukan daftar baru --
  // dilacak dua tingkat (topList/subList) supaya poin itu jadi <ul> BERSARANG
  // di dalam <li> nomornya, bukan menutup <ol> dan membuat tiap nomor
  // restart dari "1." lagi (bug yang ditemukan 27 Jul 2026 dari laporan user:
  // panel skor IJD 5 komponen semua tampil "1.").
  let topList = null;    // "ol" | "ul" | null
  let topLiOpen = false; // <li> level atas sedang terbuka, blm ditutup
  let subList = null;    // "ul" bersarang di dlm <li> level atas yg terbuka

  const closeSub = () => { if (subList) { html.push(`</${subList}>`); subList = null; } };
  const closeTopLi = () => { closeSub(); if (topLiOpen) { html.push("</li>"); topLiOpen = false; } };
  const closeTop = () => { closeTopLi(); if (topList) { html.push(`</${topList}>`); topList = null; } };

  for (const raw of lines) {
    const line = raw.trim();
    if (!line) continue; // baris kosong TIDAK menutup daftar -- lihat catatan di atas
    const ol = line.match(/^\d+[.)]\s+(.*)/);
    const ul = line.match(/^[-*]\s+(.*)/);

    if (ol) {
      closeTopLi();
      if (topList !== "ol") { closeTop(); html.push("<ol>"); topList = "ol"; }
      html.push(`<li>${inline(ol[1])}`);
      topLiOpen = true;
    } else if (ul && topList === "ol" && topLiOpen) {
      // poin di bawah nomor yang masih terbuka -> sub-daftar bersarang
      if (!subList) { html.push("<ul>"); subList = "ul"; }
      html.push(`<li>${inline(ul[1])}</li>`);
    } else if (ul) {
      closeTopLi();
      if (topList !== "ul") { closeTop(); html.push("<ul>"); topList = "ul"; }
      html.push(`<li>${inline(ul[1])}</li>`);
    } else {
      closeTop();
      html.push(`<p>${inline(line)}</p>`);
    }
  }
  closeTop();
  return html.join("");
}

function renderChatMessages() {
  const listEl = document.getElementById("chatMessages");
  if (!listEl) return;
  listEl.innerHTML = state.chat.messages
    .map((m) => `<div class="chat-msg chat-msg-${m.role}">${m.role === "assistant" ? renderMarkdownLite(m.text) : escapeHtml(m.text)}</div>`)
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
    (data.actions || []).forEach(runChatAction);
  } catch (err) {
    console.error(err);
    state.chat.messages.push({ role: "assistant", text: "Maaf, terjadi kesalahan saat menghubungi asisten. Coba lagi." });
  } finally {
    state.chat.busy = false;
    renderChatMessages();
  }
}

/* Tool yang dipanggil model tapi dieksekusi di FRONTEND, bukan di server
   (lihat CLIENT_ACTION_TOOLS di chat_providers.py -- daftar nama tool di
   sana HARUS sinkron dgn key di sini). Backend hanya meneruskan nama+argumen
   tool call apa adanya lewat data.actions, tanpa tahu/peduli apa yang
   sungguh terjadi di UI -- kalau nama actionnya tidak dikenal di sini,
   diam-diam diabaikan drpd melempar error yang bikin panggilan chat gagal. */
const CHAT_CLIENT_ACTIONS = {
  tampilkan_usulan_di_peta: (args) => {
    if (!args || args.id == null) return;
    if (typeof loadUsulanDetail !== "function") return;
    loadUsulanDetail(args.id);
    document.getElementById("usulanBrowseDetail")?.scrollIntoView({ behavior: "smooth", block: "center" });
  },
};

function runChatAction(action) {
  const fn = CHAT_CLIENT_ACTIONS[action?.nama];
  if (fn) fn(action.argumen || {});
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
