import sqlite3
import threading
import time
from datetime import datetime

import config

db_lock = threading.Lock()

_CACHE_TTL = 30
_role_cache = {}
_ar_cache = {}


def _cache_get(cache, key, ttl=_CACHE_TTL):
    v = cache.get(key)
    if v is not None and time.time() - v[1] < ttl:
        return v[0]
    return None


def _cache_set(cache, key, value):
    cache[key] = (value, time.time())


def _cache_del(cache, key):
    cache.pop(key, None)


def get_connection():
    conn = sqlite3.connect(config.DB_NAME, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def init_db():
    with db_lock:
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute(
                """CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER UNIQUE NOT NULL,
                    username TEXT,
                    first_name TEXT,
                    role TEXT NOT NULL DEFAULT 'user',
                    registration_date TEXT NOT NULL
                )"""
            )
            cur.execute(
                """CREATE TABLE IF NOT EXISTS warnings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    moderator_id INTEGER NOT NULL,
                    reason TEXT,
                    date TEXT NOT NULL
                )"""
            )
            cur.execute(
                """CREATE TABLE IF NOT EXISTS logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    admin_id INTEGER NOT NULL,
                    action TEXT NOT NULL,
                    target_id INTEGER,
                    reason TEXT,
                    date TEXT NOT NULL
                )"""
            )
            cur.execute(
                """CREATE TABLE IF NOT EXISTS chats (
                    chat_id INTEGER PRIMARY KEY,
                    title TEXT,
                    added_date TEXT NOT NULL
                )"""
            )
            cur.execute(
                """CREATE TABLE IF NOT EXISTS antireklama_settings (
                    chat_id INTEGER PRIMARY KEY,
                    enabled INTEGER NOT NULL DEFAULT 0,
                    block_links INTEGER NOT NULL DEFAULT 1,
                    block_forwards INTEGER NOT NULL DEFAULT 1,
                    action TEXT NOT NULL DEFAULT 'delete',
                    warn_on_violation INTEGER NOT NULL DEFAULT 0
                )"""
            )
            conn.commit()
        finally:
            conn.close()
    ensure_owner()


def get_user(user_id):
    with db_lock:
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            return cur.fetchone()
        finally:
            conn.close()


def add_user(user_id, username, first_name, role="user"):
    with db_lock:
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute(
                """INSERT OR IGNORE INTO users
                   (user_id, username, first_name, role, registration_date)
                   VALUES (?, ?, ?, ?, ?)""",
                (user_id, username, first_name, role, now_str()),
            )
            cur.execute(
                "UPDATE users SET username = ?, first_name = ? WHERE user_id = ?",
                (username, first_name, user_id),
            )
            conn.commit()
        finally:
            conn.close()


def set_role(user_id, role):
    with db_lock:
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute("UPDATE users SET role = ? WHERE user_id = ?", (role, user_id))
            conn.commit()
            invalidate_role(user_id)
            return cur.rowcount > 0
        finally:
            conn.close()


def get_role(user_id):
    cached = _cache_get(_role_cache, user_id)
    if cached is not None:
        return cached
    user = get_user(user_id)
    role = user["role"] if user else "user"
    _cache_set(_role_cache, user_id, role)
    return role


def invalidate_role(user_id):
    _cache_del(_role_cache, user_id)


def ensure_owner():
    owner_id = config.OWNER_ID
    if not owner_id:
        return
    if get_user(owner_id) is None:
        add_user(owner_id, None, "Owner", role="owner")
    else:
        set_role(owner_id, "owner")


def find_user_by_username(username):
    with db_lock:
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT * FROM users WHERE username = ? COLLATE NOCASE", (username,)
            )
            return cur.fetchone()
        finally:
            conn.close()


def get_all_user_ids():
    with db_lock:
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT user_id FROM users")
            return [row["user_id"] for row in cur.fetchall()]
        finally:
            conn.close()


def add_warning(user_id, moderator_id, reason):
    with db_lock:
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO warnings (user_id, moderator_id, reason, date) "
                "VALUES (?, ?, ?, ?)",
                (user_id, moderator_id, reason, now_str()),
            )
            conn.commit()
        finally:
            conn.close()


def count_warnings(user_id):
    with db_lock:
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT COUNT(*) AS c FROM warnings WHERE user_id = ?", (user_id,)
            )
            return cur.fetchone()["c"]
        finally:
            conn.close()


def get_warnings(user_id):
    with db_lock:
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT * FROM warnings WHERE user_id = ? ORDER BY id DESC", (user_id,)
            )
            return cur.fetchall()
        finally:
            conn.close()


def remove_last_warning(user_id):
    with db_lock:
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT id FROM warnings WHERE user_id = ? ORDER BY id DESC LIMIT 1",
                (user_id,),
            )
            row = cur.fetchone()
            if row is None:
                return False
            cur.execute("DELETE FROM warnings WHERE id = ?", (row["id"],))
            conn.commit()
            return True
        finally:
            conn.close()


def clear_warnings(user_id):
    with db_lock:
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute("DELETE FROM warnings WHERE user_id = ?", (user_id,))
            conn.commit()
        finally:
            conn.close()


def add_log(admin_id, action, target_id=None, reason=None):
    with db_lock:
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO logs (admin_id, action, target_id, reason, date) "
                "VALUES (?, ?, ?, ?, ?)",
                (admin_id, action, target_id, reason, now_str()),
            )
            conn.commit()
        finally:
            conn.close()


def get_staff():
    with db_lock:
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT * FROM users WHERE role IN ('moderator','admin','owner')"
            )
            return cur.fetchall()
        finally:
            conn.close()


def get_stats():
    with db_lock:
        conn = get_connection()
        try:
            cur = conn.cursor()
            stats = {}
            cur.execute("SELECT COUNT(*) AS c FROM users")
            stats["users"] = cur.fetchone()["c"]
            for r in ("user", "moderator", "admin", "owner"):
                cur.execute("SELECT COUNT(*) AS c FROM users WHERE role = ?", (r,))
                stats[r] = cur.fetchone()["c"]
            cur.execute("SELECT COUNT(*) AS c FROM warnings")
            stats["warnings"] = cur.fetchone()["c"]
            cur.execute("SELECT COUNT(*) AS c FROM logs")
            stats["logs"] = cur.fetchone()["c"]
            return stats
        finally:
            conn.close()


def add_chat(chat_id, title=None):
    with db_lock:
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute(
                "INSERT OR IGNORE INTO chats (chat_id, title, added_date) VALUES (?, ?, ?)",
                (chat_id, title, now_str()),
            )
            conn.commit()
        finally:
            conn.close()


def remove_chat(chat_id):
    with db_lock:
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute("DELETE FROM chats WHERE chat_id = ?", (chat_id,))
            conn.commit()
        finally:
            conn.close()


def get_all_chats():
    with db_lock:
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT chat_id FROM chats")
            return [row["chat_id"] for row in cur.fetchall()]
        finally:
            conn.close()


_AR_DEFAULTS = {"chat_id": 0, "enabled": 0, "block_links": 1, "block_forwards": 1, "action": "delete", "warn_on_violation": 0}


def get_antireklama_settings(chat_id):
    cached = _cache_get(_ar_cache, chat_id, ttl=15)
    if cached is not None:
        return cached
    with db_lock:
        conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM antireklama_settings WHERE chat_id = ?", (chat_id,))
            row = cur.fetchone()
            settings = dict(row) if row else {**_AR_DEFAULTS, "chat_id": chat_id}
            _cache_set(_ar_cache, chat_id, settings)
            return settings
        finally:
            conn.close()


def upsert_antireklama(chat_id, **kwargs):
    with db_lock:
        conn = get_connection()
        try:
            cur = conn.cursor()
            row = get_antireklama_settings(chat_id)
            row.update(kwargs)
            cur.execute(
                """INSERT INTO antireklama_settings (chat_id, enabled, block_links, block_forwards, action, warn_on_violation)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(chat_id) DO UPDATE SET
                   enabled = excluded.enabled, block_links = excluded.block_links,
                   block_forwards = excluded.block_forwards, action = excluded.action,
                   warn_on_violation = excluded.warn_on_violation""",
                (row["chat_id"], row["enabled"], row["block_links"], row["block_forwards"], row["action"], row["warn_on_violation"]),
            )
            conn.commit()
        finally:
            conn.close()
    _cache_del(_ar_cache, chat_id)
