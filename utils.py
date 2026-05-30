import html
import re
import threading
import time

import config
from bot_instance import bot
from database import (
    add_user, find_user_by_username, get_role, get_user,
)

ROLES = {"user": 1, "moderator": 2, "admin": 3, "owner": 4}
VALID_ROLES = set(ROLES.keys())
ROLE_TITLES = {
    "user": "👤 Пользователь",
    "moderator": "🛡 Модератор",
    "admin": "⚙️ Администратор",
    "owner": "👑 Владелец",
}

_last_command = {}
_antispam_lock = threading.Lock()


def esc(text):
    return html.escape(str(text)) if text is not None else ""


def role_level(role):
    return ROLES.get(role, 1)


def has_permission(user_id, min_role):
    return role_level(get_role(user_id)) >= ROLES[min_role]


def mention(user_id, username, first_name):
    name = first_name or username or str(user_id)
    return f'<a href="tg://user?id={user_id}">{esc(name)}</a>'


def can_act(actor_id, target_id):
    if actor_id == target_id:
        return False
    if target_id == config.OWNER_ID:
        return False
    return role_level(get_role(actor_id)) > role_level(get_role(target_id))


def register_message_user(message):
    try:
        u = message.from_user
        if u is None:
            return
        role = "owner" if u.id == config.OWNER_ID else "user"
        add_user(u.id, u.username, u.first_name, role=role)
    except Exception as e:
        print(f"[register_message_user] {e}")


def antispam(user_id):
    if user_id == config.OWNER_ID:
        return True
    with _antispam_lock:
        now = time.time()
        if now - _last_command.get(user_id, 0) < config.ANTISPAM_SECONDS:
            return False
        _last_command[user_id] = now
        return True


def require(message, min_role):
    if not has_permission(message.from_user.id, min_role):
        bot.reply_to(message, "⛔️ <b>Недостаточно прав</b> для этой команды.")
        return False
    return True


def get_args(message):
    parts = message.text.split()
    return parts[1:] if len(parts) > 1 else []


_TARGET_NOT_FOUND = "___USER_NOT_FOUND___"


def resolve_target(message, arg=None):
    if message.reply_to_message and message.reply_to_message.from_user:
        tu = message.reply_to_message.from_user
        add_user(tu.id, tu.username, tu.first_name, role=get_role(tu.id))
        return tu.id, mention(tu.id, tu.username, tu.first_name)
    if not arg:
        return None, None
    arg = arg.strip()
    if arg.lstrip("-").isdigit():
        uid = int(arg)
        row = get_user(uid)
        if row:
            return uid, mention(uid, row["username"], row["first_name"])
        return uid, f"<code>{uid}</code>"
    row = find_user_by_username(arg.lstrip("@"))
    if row:
        return row["user_id"], mention(
            row["user_id"], row["username"], row["first_name"]
        )
    return None, _TARGET_NOT_FOUND


def extract_target(message):
    args = get_args(message)
    if message.reply_to_message and message.reply_to_message.from_user:
        tid, disp = resolve_target(message)
        return tid, disp, args
    if args:
        tid, disp = resolve_target(message, args[0])
        return tid, disp, args[1:]
    return None, None, []


def parse_duration(text):
    if not text:
        return None
    text = text.strip().lower()
    units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    try:
        if text[-1] in units:
            return int(text[:-1]) * units[text[-1]]
        return int(text) * 60
    except (ValueError, IndexError):
        return None


def format_duration(seconds):
    if not seconds:
        return "навсегда"
    parts = []
    for name, count in (("д", 86400), ("ч", 3600), ("м", 60), ("с", 1)):
        if seconds >= count:
            parts.append(f"{seconds // count}{name}")
            seconds %= count
    return " ".join(parts) if parts else "0с"


def build_help(role):
    lines = ["📖 <b>Список доступных команд</b>\n", "<b>Для всех:</b>",
             "/start — запуск бота",
             "/help — список команд",
             "/profile — профиль"]
    if role_level(role) >= ROLES["moderator"]:
        lines += ["\n<b>Модератор и выше:</b>",
                  "/mute @user время причина",
                  "/unmute @user",
                  "/warn @user причина",
                  "/unwarn @user",
                  "/warnings @user"]
    if role_level(role) >= ROLES["admin"]:
        lines += ["\n<b>Администратор и выше:</b>",
                  "/ban @user причина",
                  "/unban @user",
                  "/kick @user причина",
                  "/clear количество",
                  "/admins",
                  "/antireklama — настройка антирекламы"]
    if role_level(role) >= ROLES["owner"]:
        lines += ["\n<b>Только владелец:</b>",
                  "/addadmin @user",
                  "/removeadmin @user",
                  "/setrole @user роль",
                  "/broadcast текст",
                  "/stats"]
    return "\n".join(lines)


_URL_RE = re.compile(r"https?://[^\s<>]+|t\.me/[^\s<>]+|www\.[^\s<>]+")


def is_ad_message(message, settings):
    if not settings.get("enabled"):
        return False
    text = message.text or message.caption or ""
    if settings.get("block_links") and _URL_RE.search(text):
        return True
    if settings.get("block_forwards") and (message.forward_from or message.forward_from_chat or message.forward_sender_name):
        return True
    return False
