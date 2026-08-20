# -*- coding: utf-8 -*-
"""Kelola akun login (tabel users) -- add/passwd/role/list/remove.
Lihat scripts/schema_users.sql, auth.py.

Usage (venv aktif):
    python scripts/manage_users.py add <username> <password> <admin|user>
    python scripts/manage_users.py passwd <username> <password baru>
    python scripts/manage_users.py role <username> <admin|user>
    python scripts/manage_users.py list
    python scripts/manage_users.py remove <username>
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from auth import hash_password  # noqa: E402
from db import db_cursor as pg_cursor  # noqa: E402

SCHEMA_PATH = Path(__file__).resolve().parent / "schema_users.sql"


def _ensure_schema():
    with pg_cursor() as cur:
        cur.execute(SCHEMA_PATH.read_text(encoding="utf-8"))


def cmd_add(username, password, role):
    if role not in ("admin", "user"):
        print("GAGAL: role harus 'admin' atau 'user'")
        sys.exit(1)
    _ensure_schema()
    with pg_cursor() as cur:
        cur.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (%s, %s, %s) "
            "ON CONFLICT (username) DO UPDATE SET password_hash=EXCLUDED.password_hash, role=EXCLUDED.role",
            (username, hash_password(password), role),
        )
    print(f"OK: user '{username}' (role={role}) dibuat/diperbarui.")


def cmd_passwd(username, password):
    _ensure_schema()
    with pg_cursor() as cur:
        cur.execute(
            "UPDATE users SET password_hash=%s WHERE username=%s",
            (hash_password(password), username),
        )
        if cur.rowcount == 0:
            print(f"GAGAL: user '{username}' tidak ditemukan.")
            sys.exit(1)
    print(f"OK: password '{username}' diperbarui.")


def cmd_role(username, role):
    if role not in ("admin", "user"):
        print("GAGAL: role harus 'admin' atau 'user'")
        sys.exit(1)
    _ensure_schema()
    with pg_cursor() as cur:
        cur.execute("UPDATE users SET role=%s WHERE username=%s", (role, username))
        if cur.rowcount == 0:
            print(f"GAGAL: user '{username}' tidak ditemukan.")
            sys.exit(1)
    print(f"OK: role '{username}' -> {role}.")


def cmd_list():
    _ensure_schema()
    with pg_cursor() as cur:
        cur.execute("SELECT username, role, created_at FROM users ORDER BY username")
        rows = cur.fetchall()
    if not rows:
        print("(belum ada user)")
        return
    for r in rows:
        print(f"  {r['username']:<20} role={r['role']:<6} dibuat={r['created_at']}")


def cmd_remove(username):
    _ensure_schema()
    with pg_cursor() as cur:
        cur.execute("DELETE FROM users WHERE username=%s", (username,))
        if cur.rowcount == 0:
            print(f"GAGAL: user '{username}' tidak ditemukan.")
            sys.exit(1)
    print(f"OK: user '{username}' dihapus.")


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(1)
    cmd, rest = args[0], args[1:]
    if cmd == "add" and len(rest) == 3:
        cmd_add(*rest)
    elif cmd == "passwd" and len(rest) == 2:
        cmd_passwd(*rest)
    elif cmd == "role" and len(rest) == 2:
        cmd_role(*rest)
    elif cmd == "list" and not rest:
        cmd_list()
    elif cmd == "remove" and len(rest) == 1:
        cmd_remove(*rest)
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
