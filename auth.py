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
import hashlib
import hmac
import os

PBKDF2_ITERATIONS = 260_000


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
