"""Cache hasil hitungan berat yang DIBAGI antar worker uvicorn + disajikan basi
sambil diperbarui di background (stale-while-revalidate).

Kenapa: staging menjalankan 2 worker (proses terpisah). Cache in-process lama
(dict per modul) berarti tiap worker menghitung sendiri-sendiri -- saat startup
keduanya warm-up bersamaan (~9 hitungan berat di 2 core, load ~9 selama ~6 menit),
dan tiap TTL 10 menit habis, user pertama di worker itu menunggu hitung ulang
(Road Safety pernah 436 dtk di staging). Di sini:

- hasil disimpan juga ke disk (.cache/shared/<nama>/<hash>.pkl, pickle) -> worker
  lain cukup memuat file, tidak menghitung ulang;
- file kunci (O_EXCL) mencegah dua worker menghitung kunci yang sama bersamaan;
  worker yang kalah menunggu file hasil muncul;
- lewat TTL, nilai lama TETAP dikembalikan dan hitung ulang jalan di thread
  background (satu kali, lintas worker) -> user tidak pernah menunggu kecuali
  benar-benar belum ada nilai sama sekali;
- clear() menulis penanda generasi di disk -> SEMUA worker membuang nilai yang
  lebih tua dari penanda itu (invalidasi setelah impor berlaku lintas proses).

Nilai harus bisa di-pickle (dict/list/tuple/DataFrame). Konsekuensi TTL: data
yang tersaji bisa setua TTL + lama hitung ulang (bukan persis TTL).
"""
import hashlib
import os
import pickle
import threading
import time
from pathlib import Path

CACHE_ROOT = Path(__file__).resolve().parent / ".cache" / "shared"
_KUNCI_BASI_DETIK = 15 * 60  # kunci lebih tua dari ini dianggap sisa proses yang mati


def _ambil_kunci(path: Path) -> bool:
    """True bila kunci berhasil dibuat (proses ini pemiliknya)."""
    for _ in range(2):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            return True
        except FileExistsError:
            try:
                if time.time() - path.stat().st_mtime > _KUNCI_BASI_DETIK:
                    path.unlink(missing_ok=True)
                    continue
            except FileNotFoundError:
                continue
            return False
    return False


class SharedCache:
    def __init__(self, nama: str, ttl_detik: float, tunggu_maks_detik: float = 600):
        self.nama = nama
        self.ttl = ttl_detik
        self.tunggu_maks = tunggu_maks_detik
        self.dir = CACHE_ROOT / nama
        self._mem = {}  # hash -> (ts, nilai)
        self._sedang_refresh = set()
        self._lock = threading.Lock()

    # -- utilitas -----------------------------------------------------------
    def _hash(self, key) -> str:
        return hashlib.sha1(repr(key).encode("utf-8")).hexdigest()[:20]

    def _gen_ts(self) -> float:
        try:
            return (self.dir / ".gen").stat().st_mtime
        except FileNotFoundError:
            return 0.0

    def _baca_disk(self, h: str, gen: float):
        """(ts, nilai) dari disk bila ada & tidak lebih tua dari generasi, else None."""
        p = self.dir / f"{h}.pkl"
        try:
            ts = p.stat().st_mtime
            if ts < gen:
                return None
            with open(p, "rb") as f:
                return ts, pickle.load(f)
        except (FileNotFoundError, EOFError, pickle.UnpicklingError):
            return None

    def _tulis(self, h: str, nilai):
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.dir / f"{h}.{os.getpid()}.tmp"
        with open(tmp, "wb") as f:
            pickle.dump(nilai, f, protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(tmp, self.dir / f"{h}.pkl")
        ts = (self.dir / f"{h}.pkl").stat().st_mtime
        with self._lock:
            self._mem[h] = (ts, nilai)

    def _hitung_dgn_kunci(self, h: str, compute, pakai_disk_gen=None):
        """Hitung + simpan, memegang kunci lintas worker. None bila kunci dipegang
        proses lain (pemanggil yang memutuskan menunggu atau tidak). pakai_disk_gen:
        bila diberi, setelah kunci didapat cek dulu apakah proses lain baru saja
        menulis hasil (>= generasi itu) -- pakai itu, jangan hitung ulang."""
        self.dir.mkdir(parents=True, exist_ok=True)
        kunci = self.dir / f"{h}.lock"
        if not _ambil_kunci(kunci):
            return None
        try:
            if pakai_disk_gen is not None:
                disk = self._baca_disk(h, pakai_disk_gen)
                if disk:
                    with self._lock:
                        self._mem[h] = disk
                    return (disk[1],)
            nilai = compute()
            self._tulis(h, nilai)
            return (nilai,)
        finally:
            kunci.unlink(missing_ok=True)

    def _refresh_bg(self, h: str, compute):
        with self._lock:
            if h in self._sedang_refresh:
                return
            self._sedang_refresh.add(h)

        def _jalan():
            try:
                self._hitung_dgn_kunci(h, compute)
            except Exception as e:  # noqa: BLE001 -- nilai lama tetap tersaji
                print(f"[shared_cache:{self.nama}] refresh background gagal: {e}")
            finally:
                with self._lock:
                    self._sedang_refresh.discard(h)

        threading.Thread(target=_jalan, daemon=True, name=f"cache-{self.nama}").start()

    # -- API ----------------------------------------------------------------
    def get(self, key, compute):
        h = self._hash(key)
        gen = self._gen_ts()
        with self._lock:
            mem = self._mem.get(h)
        if mem and mem[0] < gen:
            mem = None
        disk = self._baca_disk(h, gen) if not mem or mem[0] < self._disk_mtime(h) else None
        if disk and (not mem or disk[0] > mem[0]):
            with self._lock:
                self._mem[h] = disk
            mem = disk
        if mem:
            if time.time() - mem[0] >= self.ttl:
                self._refresh_bg(h, compute)
            return mem[1]

        # belum ada nilai sama sekali -> harus menunggu (sekali per kunci lintas worker):
        # cek disk DULU (worker lain mungkin baru selesai), baru coba ambil kunci.
        mulai = time.time()
        while True:
            disk = self._baca_disk(h, gen)
            if disk:
                with self._lock:
                    self._mem[h] = disk
                return disk[1]
            hasil = self._hitung_dgn_kunci(h, compute, pakai_disk_gen=gen)
            if hasil is not None:
                return hasil[0]
            if time.time() - mulai > self.tunggu_maks:
                nilai = compute()  # pemegang kunci terlalu lama -- hitung sendiri
                self._tulis(h, nilai)
                return nilai
            time.sleep(1.0)

    def _disk_mtime(self, h: str) -> float:
        try:
            return (self.dir / f"{h}.pkl").stat().st_mtime
        except FileNotFoundError:
            return 0.0

    def clear(self):
        """Invalidasi semua kunci di SEMUA worker (penanda generasi di disk)."""
        self.dir.mkdir(parents=True, exist_ok=True)
        penanda = self.dir / ".gen"
        penanda.write_text(str(time.time()))
        with self._lock:
            self._mem.clear()


def kunci_startup(nama: str = "warm") -> bool:
    """True utk SATU worker saja (yang pertama) -- dipakai warm-up startup supaya
    hitungan berat tidak dijalankan semua worker bersamaan. Kunci dilepas oleh
    lepas_kunci_startup(); bila proses mati, kunci basi setelah 15 menit."""
    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    return _ambil_kunci(CACHE_ROOT / f".{nama}.lock")


def lepas_kunci_startup(nama: str = "warm"):
    (CACHE_ROOT / f".{nama}.lock").unlink(missing_ok=True)
