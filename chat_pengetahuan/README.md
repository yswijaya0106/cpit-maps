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
