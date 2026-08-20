"""Autentikasi berbasis tabel users (username/password_hash/role) --
menggantikan APP_USERNAME/APP_PASSWORD tunggal di .env (nilainya cuma
dipakai SEKALI sbg seed akun admin pertama, lihat _seed_initial_admin_user()
di app.py -- setelah itu kredensial login dikelola lewat tabel users, bukan
.env lagi).

Password di-hash pakai hashlib.pbkdf2_hmac (stdlib, sengaja tanpa dependency
baru spt bcrypt/passlib -- 260k iterasi SHA-256 cukup utk skala aplikasi
internal ini). Format tersimpan mandiri (self-describing, algoritma+iterasi+
salt ikut disimpan): "pbkdf2_sha256$<iterasi>$<salt hex>$<hash hex>".
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import time

PBKDF2_ITERATIONS = 260_000

# Kunci penanda-tangan token sesi (cookie login form, lihat POST
# /api/auth/login di app.py) -- HARUS diset di .env (SESSION_SECRET) supaya
# sesi tetap valid lintas restart server. Kalau tidak diset, jatuh ke acak
# per-proses (dev lokal saja) -- SEMUA sesi yang ada langsung tidak valid
# tiap kali server restart, aman (cuma minta login ulang) tapi bukan
# pengalaman yang bagus utk staging/produksi.
SESSION_SECRET = os.getenv("SESSION_SECRET") or secrets.token_hex(32)
SESSION_TTL_SECONDS = 60 * 60 * 12  # 12 jam


def create_session_token(username: str, role: str) -> str:
    payload = {"u": username, "r": role, "exp": int(time.time()) + SESSION_TTL_SECONDS}
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    sig = hmac.new(SESSION_SECRET.encode("utf-8"), raw, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(raw).decode() + "." + base64.urlsafe_b64encode(sig).decode()


def verify_session_token(token: str):
    """None kalau tidak valid/kedaluwarsa, else {"username", "role"}."""
    try:
        raw_b64, sig_b64 = token.split(".")
        raw = base64.urlsafe_b64decode(raw_b64 + "==")
        sig = base64.urlsafe_b64decode(sig_b64 + "==")
        expected = hmac.new(SESSION_SECRET.encode("utf-8"), raw, hashlib.sha256).digest()
        if not hmac.compare_digest(sig, expected):
            return None
        payload = json.loads(raw)
        if payload.get("exp", 0) < time.time():
            return None
        return {"username": payload["u"], "role": payload["r"]}
    except Exception:
        return None


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algo, iterations, salt_hex, hash_hex = stored_hash.split("$")
        if algo != "pbkdf2_sha256":
            return False
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
        iterations = int(iterations)
    except (ValueError, AttributeError):
        return False
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(dk, expected)
