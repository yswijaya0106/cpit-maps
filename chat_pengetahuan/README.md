# Catatan pengetahuan asisten chat

Tahap 4a docs/kajian_agentic_workflow_fitur_ai.md. Tiap file `*.md` (selain
README) adalah satu catatan topik yang disisipkan ke system prompt chat HANYA
bila pertanyaan pengguna memuat salah satu `kata_kunci`-nya (maks 3 catatan,
lihat `_pilih_catatan` di chat_providers.py). Isinya: tabel/kolom/layer yang
benar utk topik itu, supaya model tidak menebak.

Format:

    ---
    judul: Pelabuhan
    kata_kunci: [pelabuhan, dermaga*, kapal]
    ---
    - isi catatan (Markdown ringkas)

Kata kunci dicocokkan sbg kata utuh, tidak peka huruf besar/kecil; akhiran `*`
= awalan kata (mis. `penumpang*`). Frasa boleh (`jalan nasional`). Setiap
fakta di sini harus dicek ke data sebelum ditambahkan -- catatan yang salah
langsung menurunkan skor paket uji (scripts/uji_chat.py).

## Tahap 4b: loop belajar

- Catatan dimuat ulang otomatis saat file di folder ini berubah (tanpa restart).
- Kata kunci tak pernah lengkap: catatan yang tidak cocok tetap disebut
  `judul [nama]` di prompt, dan model bisa membacanya sendiri lewat tool
  `baca_catatan_pengetahuan`.
- `chat_log` mencatat catatan yang dipakai, revisi otomatis, query yang error,
  dan 👍/👎 pengguna (tombol di bawah tiap jawaban).
- `scripts/belajar_catatan_chat.py` mengumpulkan kasus gagal (chat_log + laporan
  uji_chat), lalu agen DeepSeek memeriksa database dan menulis draf ke
  `_usulan/<tgl>-<nama>.md` (`status: usulan`, tidak dibaca chat) beserta
  `.bukti.md` (bukti SQL yang dijalankan ulang skrip). Review, lalu
  `--terima <draf>` untuk mengaktifkannya, dan jalankan uji_chat.py lagi.
- `status:` selain `aktif` (default) membuat catatan dilewati.
