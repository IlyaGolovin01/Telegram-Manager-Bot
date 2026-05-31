import threading
import time

from telebot import types
from telebot.apihelper import ApiTelegramException

import config
from bot_instance import bot
from database import (
    add_chat, add_log, add_user, add_warning, clear_warnings, count_warnings,
    get_all_chats, get_all_user_ids, get_anti_advertising_settings, get_role,
    get_staff, get_stats, get_user, get_warnings, remove_chat, remove_last_warning,
    set_role, upsert_anti_advertising,
)
from utils import (
    ROLES, ROLE_TITLES, _TARGET_NOT_FOUND, antispam, build_help, can_act,
    esc, extract_target, format_duration, get_args, is_ad_message,
    mention, parse_duration, register_message_user, require, role_level,
)


def sync_chat_roles(chat_id):
    try:
        admins = bot.get_chat_administrators(chat_id)
        for a in admins:
            u = a.user
            if a.status == "creator":
                set_role(u.id, "owner")
                add_user(u.id, u.username, u.first_name, role="owner")
            elif a.status == "administrator":
                cur_role = get_role(u.id)
                if cur_role not in ("owner", "admin"):
                    set_role(u.id, "admin")
                add_user(u.id, u.username, u.first_name, role=get_role(u.id))
            else:
                add_user(u.id, u.username, u.first_name, role="user")
        print(f"[sync] Синхронизирован чат {chat_id}: {len(admins)} участников")
    except Exception as e:
        print(f"[sync_chat_roles] {e}")


def sync_all_chats():
    for chat_id in get_all_chats():
        sync_chat_roles(chat_id)


@bot.message_handler(commands=["start"])
def cmd_start(message):
    try:
        register_message_user(message)
        if not antispam(message.from_user.id):
            return
        role = get_role(message.from_user.id)
        bot.reply_to(
            message,
            f"👋 <b>Привет, {esc(message.from_user.first_name)}!</b>\n\n"
            "Я бот для управления чатом. Используй /help.\n\n"
            f"Твоя роль: <b>{ROLE_TITLES.get(role)}</b>",
        )
    except Exception as e:
        print(f"[/start] {e}")


@bot.message_handler(commands=["help"])
def cmd_help(message):
    try:
        register_message_user(message)
        if not antispam(message.from_user.id):
            return
        bot.reply_to(message, build_help(get_role(message.from_user.id)))
    except Exception as e:
        print(f"[/help] {e}")


@bot.message_handler(commands=["profile"])
def cmd_profile(message):
    try:
        register_message_user(message)
        if not antispam(message.from_user.id):
            return
        target_id, _, _ = extract_target(message)
        if target_id is None:
            target_id = message.from_user.id
        row = get_user(target_id)
        if row is None:
            bot.reply_to(message, "⚠️ Пользователь не найден в базе.")
            return
        warns = count_warnings(target_id)
        bot.reply_to(
            message,
            "📇 <b>Профиль пользователя</b>\n\n"
            f"🆔 ID: <code>{row['user_id']}</code>\n"
            f"👤 Имя: {esc(row['first_name'])}\n"
            f"🔗 Username: @{esc(row['username']) if row['username'] else '—'}\n"
            f"🎖 Роль: <b>{ROLE_TITLES.get(row['role'])}</b>\n"
            f"⚠️ Предупреждений: <b>{warns}/{config.WARN_LIMIT}</b>\n"
            f"📅 Регистрация: {esc(row['registration_date'])}",
        )
    except Exception as e:
        print(f"[/profile] {e}")


@bot.message_handler(commands=["mute"])
def cmd_mute(message):
    try:
        register_message_user(message)
        if not antispam(message.from_user.id) or not require(message, "moderator"):
            return
        actor = message.from_user.id
        target_id, disp, rest = extract_target(message)
        if target_id is None:
            if disp == _TARGET_NOT_FOUND:
                bot.reply_to(message, "⚠️ Пользователь не найден.\n💡 Убедитесь, что он писал боту, или ответьте на его сообщение.")
            else:
                bot.reply_to(message, "⚠️ <code>/mute @user 10m причина</code>\n💡 Или ответьте на сообщение пользователя.")
            return
        if not can_act(actor, target_id):
            bot.reply_to(message, "⛔️ Вы не можете заглушить этого пользователя.")
            return
        seconds = parse_duration(rest[0]) if rest else None
        if seconds is not None:
            reason = " ".join(rest[1:]) if len(rest) > 1 else "не указана"
        else:
            seconds = None
            reason = " ".join(rest) if rest else "не указана"
        until_date = int(time.time()) + seconds if seconds else None
        bot.restrict_chat_member(
            message.chat.id, target_id, until_date=until_date,
            permissions=types.ChatPermissions(can_send_messages=False),
        )
        add_log(actor, "mute", target_id, reason)
        bot.reply_to(
            message,
            f"🔇 {disp} заглушён на <b>{format_duration(seconds)}</b>.\n"
            f"📝 Причина: {esc(reason)}",
        )
    except ApiTelegramException as e:
        bot.reply_to(message, f"❌ Ошибка Telegram: {esc(e.description)}")
    except Exception as e:
        print(f"[/mute] {e}")
        bot.reply_to(message, "❌ Не удалось выполнить команду.")


@bot.message_handler(commands=["unmute"])
def cmd_unmute(message):
    try:
        register_message_user(message)
        if not antispam(message.from_user.id) or not require(message, "moderator"):
            return
        target_id, disp, _ = extract_target(message)
        if target_id is None:
            if disp == _TARGET_NOT_FOUND:
                bot.reply_to(message, "⚠️ Пользователь не найден.\n💡 Убедитесь, что он писал боту, или ответьте на его сообщение.")
            else:
                bot.reply_to(message, "⚠️ <code>/unmute @user</code>\n💡 Или ответьте на сообщение пользователя.")
            return
        bot.restrict_chat_member(
            message.chat.id, target_id,
            permissions=types.ChatPermissions(
                can_send_messages=True, can_send_media_messages=True,
                can_send_other_messages=True, can_add_web_page_previews=True,
                can_send_polls=True, can_invite_users=True,
            ),
        )
        add_log(message.from_user.id, "unmute", target_id)
        bot.reply_to(message, f"🔊 {disp} размучен.")
    except ApiTelegramException as e:
        bot.reply_to(message, f"❌ Ошибка Telegram: {esc(e.description)}")
    except Exception as e:
        print(f"[/unmute] {e}")
        bot.reply_to(message, "❌ Не удалось выполнить команду.")


@bot.message_handler(commands=["warn"])
def cmd_warn(message):
    try:
        register_message_user(message)
        if not antispam(message.from_user.id) or not require(message, "moderator"):
            return
        actor = message.from_user.id
        target_id, disp, rest = extract_target(message)
        if target_id is None:
            if disp == _TARGET_NOT_FOUND:
                bot.reply_to(message, "⚠️ Пользователь не найден.\n💡 Убедитесь, что он писал боту, или ответьте на его сообщение.")
            else:
                bot.reply_to(message, "⚠️ <code>/warn @user причина</code>\n💡 Или ответьте на сообщение пользователя.")
            return
        if not can_act(actor, target_id):
            bot.reply_to(message, "⛔️ Вы не можете предупредить этого пользователя.")
            return
        reason = " ".join(rest) if rest else "не указана"
        add_warning(target_id, actor, reason)
        total = count_warnings(target_id)
        add_log(actor, "warn", target_id, reason)
        if total >= config.WARN_LIMIT:
            try:
                bot.ban_chat_member(message.chat.id, target_id)
            except ApiTelegramException as e:
                print(f"[/warn auto-ban] {e}")
            add_log(actor, "auto-ban", target_id, reason)
            clear_warnings(target_id)
            bot.reply_to(
                message,
                f"⚠️ {disp} получил <b>{total}/{config.WARN_LIMIT}</b> предупреждений и 🔨 <b>автоматически забанен</b>.",
            )
        else:
            bot.reply_to(
                message,
                f"⚠️ {disp} получил предупреждение (<b>{total}/{config.WARN_LIMIT}</b>).\n"
                f"📝 Причина: {esc(reason)}",
            )
    except Exception as e:
        print(f"[/warn] {e}")
        bot.reply_to(message, "❌ Не удалось выполнить команду.")


@bot.message_handler(commands=["unwarn"])
def cmd_unwarn(message):
    try:
        register_message_user(message)
        if not antispam(message.from_user.id) or not require(message, "moderator"):
            return
        target_id, disp, _ = extract_target(message)
        if target_id is None:
            if disp == _TARGET_NOT_FOUND:
                bot.reply_to(message, "⚠️ Пользователь не найден.\n💡 Убедитесь, что он писал боту, или ответьте на его сообщение.")
            else:
                bot.reply_to(message, "⚠️ <code>/unwarn @user</code>\n💡 Или ответьте на сообщение пользователя.")
            return
        if remove_last_warning(target_id):
            add_log(message.from_user.id, "unwarn", target_id)
            bot.reply_to(
                message,
                f"✅ С {disp} снято предупреждение. Осталось: <b>{count_warnings(target_id)}</b>.",
            )
        else:
            bot.reply_to(message, f"ℹ️ У {disp} нет предупреждений.")
    except Exception as e:
        print(f"[/unwarn] {e}")
        bot.reply_to(message, "❌ Не удалось выполнить команду.")


@bot.message_handler(commands=["warnings"])
def cmd_warnings(message):
    try:
        register_message_user(message)
        if not antispam(message.from_user.id) or not require(message, "moderator"):
            return
        target_id, disp, _ = extract_target(message)
        if target_id is None:
            if disp == _TARGET_NOT_FOUND:
                bot.reply_to(message, "⚠️ Пользователь не найден.\n💡 Убедитесь, что он писал боту, или ответьте на его сообщение.")
            else:
                bot.reply_to(message, "⚠️ <code>/warnings @user</code>\n💡 Или ответьте на сообщение пользователя.")
            return
        warns = get_warnings(target_id)
        if not warns:
            bot.reply_to(message, f"ℹ️ У {disp} нет предупреждений.")
            return
        lines = [f"⚠️ <b>Предупреждения {disp}</b> ({len(warns)}/{config.WARN_LIMIT}):\n"]
        for i, w in enumerate(warns, 1):
            lines.append(f"{i}. {esc(w['reason'])} — <i>{esc(w['date'])}</i>")
        bot.reply_to(message, "\n".join(lines))
    except Exception as e:
        print(f"[/warnings] {e}")
        bot.reply_to(message, "❌ Не удалось выполнить команду.")


@bot.message_handler(commands=["ban"])
def cmd_ban(message):
    try:
        register_message_user(message)
        if not antispam(message.from_user.id) or not require(message, "admin"):
            return
        actor = message.from_user.id
        target_id, disp, rest = extract_target(message)
        if target_id is None:
            if disp == _TARGET_NOT_FOUND:
                bot.reply_to(message, "⚠️ Пользователь не найден.\n💡 Убедитесь, что он писал боту, или ответьте на его сообщение.")
            else:
                bot.reply_to(message, "⚠️ <code>/ban @user 1d причина</code>\n💡 Или ответьте на сообщение пользователя.")
            return
        if not can_act(actor, target_id):
            bot.reply_to(message, "⛔️ Вы не можете забанить этого пользователя.")
            return
        seconds = parse_duration(rest[0]) if rest else None
        if seconds is not None:
            reason = " ".join(rest[1:]) if len(rest) > 1 else "не указана"
        else:
            seconds = None
            reason = " ".join(rest) if rest else "не указана"
        until_date = int(time.time()) + seconds if seconds else None
        bot.ban_chat_member(message.chat.id, target_id, until_date=until_date)
        add_log(actor, "ban", target_id, reason)
        duration_str = f" на <b>{format_duration(seconds)}</b>" if seconds else ""
        bot.reply_to(message, f"🔨 {disp} забанен{duration_str}.\n📝 Причина: {esc(reason)}")
    except ApiTelegramException as e:
        bot.reply_to(message, f"❌ Ошибка Telegram: {esc(e.description)}")
    except Exception as e:
        print(f"[/ban] {e}")
        bot.reply_to(message, "❌ Не удалось выполнить команду.")


@bot.message_handler(commands=["unban"])
def cmd_unban(message):
    try:
        register_message_user(message)
        if not antispam(message.from_user.id) or not require(message, "admin"):
            return
        target_id, disp, _ = extract_target(message)
        if target_id is None:
            if disp == _TARGET_NOT_FOUND:
                bot.reply_to(message, "⚠️ Пользователь не найден.\n💡 Убедитесь, что он писал боту, или ответьте на его сообщение.")
            else:
                bot.reply_to(message, "⚠️ <code>/unban @user</code>\n💡 Или ответьте на сообщение пользователя.")
            return
        bot.unban_chat_member(message.chat.id, target_id, only_if_banned=True)
        add_log(message.from_user.id, "unban", target_id)
        bot.reply_to(message, f"✅ {disp} разбанен.")
    except ApiTelegramException as e:
        bot.reply_to(message, f"❌ Ошибка Telegram: {esc(e.description)}")
    except Exception as e:
        print(f"[/unban] {e}")
        bot.reply_to(message, "❌ Не удалось выполнить команду.")


@bot.message_handler(commands=["kick"])
def cmd_kick(message):
    try:
        register_message_user(message)
        if not antispam(message.from_user.id) or not require(message, "admin"):
            return
        actor = message.from_user.id
        target_id, disp, rest = extract_target(message)
        if target_id is None:
            if disp == _TARGET_NOT_FOUND:
                bot.reply_to(message, "⚠️ Пользователь не найден.\n💡 Убедитесь, что он писал боту, или ответьте на его сообщение.")
            else:
                bot.reply_to(message, "⚠️ <code>/kick @user причина</code>\n💡 Или ответьте на сообщение пользователя.")
            return
        if not can_act(actor, target_id):
            bot.reply_to(message, "⛔️ Вы не можете кикнуть этого пользователя.")
            return
        reason = " ".join(rest) if rest else "не указана"
        bot.ban_chat_member(message.chat.id, target_id)
        bot.unban_chat_member(message.chat.id, target_id, only_if_banned=True)
        add_log(actor, "kick", target_id, reason)
        bot.reply_to(message, f"👢 {disp} кикнут.\n📝 Причина: {esc(reason)}")
    except ApiTelegramException as e:
        bot.reply_to(message, f"❌ Ошибка Telegram: {esc(e.description)}")
    except Exception as e:
        print(f"[/kick] {e}")
        bot.reply_to(message, "❌ Не удалось выполнить команду.")


@bot.message_handler(commands=["clear"])
def cmd_clear(message):
    try:
        register_message_user(message)
        if not antispam(message.from_user.id) or not require(message, "admin"):
            return
        args = get_args(message)
        if not args or not args[0].isdigit():
            bot.reply_to(message, "⚠️ <code>/clear 10</code>")
            return
        count = min(int(args[0]), 100)
        deleted = 0
        last_id = message.message_id
        for mid in range(last_id, last_id - count - 1, -1):
            try:
                bot.delete_message(message.chat.id, mid)
                deleted += 1
            except Exception:
                pass
        add_log(message.from_user.id, f"clear ({deleted})")
        bot.send_message(message.chat.id, f"🧹 Удалено сообщений: <b>{deleted}</b>.")
    except Exception as e:
        print(f"[/clear] {e}")
        bot.reply_to(message, "❌ Не удалось выполнить команду.")


@bot.message_handler(commands=["admins"])
def cmd_admins(message):
    try:
        register_message_user(message)
        if not antispam(message.from_user.id) or not require(message, "admin"):
            return
        staff = get_staff()
        if not staff:
            bot.reply_to(message, "ℹ️ Администрация не найдена.")
            return
        order = {"owner": 0, "admin": 1, "moderator": 2}
        staff = sorted(staff, key=lambda r: order.get(r["role"], 9))
        lines = ["👮 <b>Администрация чата:</b>\n"]
        for r in staff:
            lines.append(
                f"{ROLE_TITLES.get(r['role'])} — "
                f"{mention(r['user_id'], r['username'], r['first_name'])}"
            )
        bot.reply_to(message, "\n".join(lines))
    except Exception as e:
        print(f"[/admins] {e}")
        bot.reply_to(message, "❌ Не удалось выполнить команду.")


@bot.message_handler(commands=["antiadvertising"])
def cmd_anti_advertising(message):
    try:
        register_message_user(message)
        if not antispam(message.from_user.id) or not require(message, "admin"):
            return
        args = get_args(message)
        chat_id = message.chat.id
        settings = get_anti_advertising_settings(chat_id)

        if not args:
            status = "✅ включена" if settings["enabled"] else "❌ выключена"
            links = "✅" if settings["block_links"] else "❌"
            fwd = "✅" if settings["block_forwards"] else "❌"
            actions = {"delete": "удаление", "warn": "предупреждение", "ban": "бан"}
            bot.reply_to(
                message,
                f"🛡 <b>Антиреклама</b> — {status}\n\n"
                f"🔗 Блокировать ссылки: {links}\n"
                f"📨 Блокировать репосты: {fwd}\n"
                f"⚙️ Действие: {actions.get(settings['action'], settings['action'])}\n\n"
                f"<code>/antiadvertising on</code> — включить\n"
                f"<code>/antiadvertising off</code> — выключить\n"
                f"<code>/antiadvertising links on/off</code> — блокировка ссылок\n"
                f"<code>/antiadvertising forwards on/off</code> — блокировка репостов\n"
                f"<code>/antiadvertising action delete|warn|ban</code> — действие",
            )
            return

        cmd = args[0].lower()
        if cmd == "on":
            upsert_anti_advertising(chat_id, enabled=1)
            bot.reply_to(message, "🛡 Антиреклама <b>включена</b>.")
        elif cmd == "off":
            upsert_anti_advertising(chat_id, enabled=0)
            bot.reply_to(message, "🛡 Антиреклама <b>выключена</b>.")
        elif cmd == "links" and len(args) > 1:
            val = 1 if args[1].lower() in ("on", "1", "yes", "да") else 0
            upsert_anti_advertising(chat_id, block_links=val)
            bot.reply_to(message, f"🔗 Блокировка ссылок: <b>{'включена' if val else 'выключена'}</b>.")
        elif cmd == "forwards" and len(args) > 1:
            val = 1 if args[1].lower() in ("on", "1", "yes", "да") else 0
            upsert_anti_advertising(chat_id, block_forwards=val)
            bot.reply_to(message, f"📨 Блокировка репостов: <b>{'включена' if val else 'выключена'}</b>.")
        elif cmd == "action" and len(args) > 1:
            act = args[1].lower()
            if act not in ("delete", "warn", "ban"):
                bot.reply_to(message, "⚠️ Доступные действия: delete, warn, ban.")
                return
            upsert_anti_advertising(chat_id, action=act)
            names = {"delete": "удаление", "warn": "предупреждение", "ban": "бан"}
            bot.reply_to(message, f"⚙️ Действие: <b>{names[act]}</b>.")
        else:
            bot.reply_to(message, "⚠️ Неверная команда. Используйте <code>/antiadvertising</code> без аргументов для справки.")
    except Exception as e:
        print(f"[/antiadvertising] {e}")
        bot.reply_to(message, "❌ Не удалось выполнить команду.")


@bot.message_handler(commands=["addadmin"])
def cmd_addadmin(message):
    try:
        register_message_user(message)
        if not antispam(message.from_user.id) or not require(message, "owner"):
            return
        target_id, disp, _ = extract_target(message)
        if target_id is None:
            if disp == _TARGET_NOT_FOUND:
                bot.reply_to(message, "⚠️ Пользователь не найден.\n💡 Убедитесь, что он писал боту, или ответьте на его сообщение.")
            else:
                bot.reply_to(message, "⚠️ <code>/addadmin @user</code>\n💡 Или ответьте на сообщение пользователя.")
            return
        if get_user(target_id) is None:
            add_user(target_id, None, None, role="admin")
        else:
            set_role(target_id, "admin")
        add_log(message.from_user.id, "addadmin", target_id)
        bot.reply_to(message, f"⚙️ {disp} назначен <b>администратором</b>.")
    except Exception as e:
        print(f"[/addadmin] {e}")
        bot.reply_to(message, "❌ Не удалось выполнить команду.")


@bot.message_handler(commands=["removeadmin"])
def cmd_removeadmin(message):
    try:
        register_message_user(message)
        if not antispam(message.from_user.id) or not require(message, "owner"):
            return
        target_id, disp, _ = extract_target(message)
        if target_id is None:
            if disp == _TARGET_NOT_FOUND:
                bot.reply_to(message, "⚠️ Пользователь не найден.\n💡 Убедитесь, что он писал боту, или ответьте на его сообщение.")
            else:
                bot.reply_to(message, "⚠️ <code>/removeadmin @user</code>\n💡 Или ответьте на сообщение пользователя.")
            return
        if target_id == config.OWNER_ID:
            bot.reply_to(message, "⛔️ Нельзя снять владельца.")
            return
        set_role(target_id, "user")
        add_log(message.from_user.id, "removeadmin", target_id)
        bot.reply_to(message, f"✅ {disp} теперь обычный <b>пользователь</b>.")
    except Exception as e:
        print(f"[/removeadmin] {e}")
        bot.reply_to(message, "❌ Не удалось выполнить команду.")


@bot.message_handler(commands=["setrole"])
def cmd_setrole(message):
    try:
        register_message_user(message)
        if not antispam(message.from_user.id) or not require(message, "owner"):
            return
        target_id, disp, rest = extract_target(message)
        if target_id is None:
            if disp == _TARGET_NOT_FOUND:
                bot.reply_to(message, "⚠️ Пользователь не найден.\n💡 Убедитесь, что он писал боту, или ответьте на его сообщение.")
            else:
                bot.reply_to(message, "⚠️ <code>/setrole @user роль</code>\n💡 Или ответьте на сообщение пользователя.")
            return
        if not rest:
            bot.reply_to(message, "⚠️ <code>/setrole @user роль</code>\nРоли: user, moderator, admin, owner")
            return
        role = rest[0].lower()
        if role not in ROLES:
            bot.reply_to(message, "⚠️ Неверная роль. Доступно: user, moderator, admin, owner.")
            return
        if target_id == config.OWNER_ID and role != "owner":
            bot.reply_to(message, "⛔️ Нельзя понизить роль владельца.")
            return
        if get_user(target_id) is None:
            add_user(target_id, None, None, role=role)
        else:
            set_role(target_id, role)
        add_log(message.from_user.id, f"setrole -> {role}", target_id)
        bot.reply_to(message, f"✅ Роль {disp} изменена на <b>{ROLE_TITLES.get(role)}</b>.")
    except Exception as e:
        print(f"[/setrole] {e}")
        bot.reply_to(message, "❌ Не удалось выполнить команду.")


@bot.message_handler(commands=["broadcast"])
def cmd_broadcast(message):
    try:
        register_message_user(message)
        if not antispam(message.from_user.id) or not require(message, "owner"):
            return
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2:
            bot.reply_to(message, "⚠️ <code>/broadcast текст</code>")
            return
        body = parts[1]
        sent, failed = 0, 0
        for uid in get_all_user_ids():
            try:
                bot.send_message(uid, f"📢 <b>Объявление:</b>\n\n{esc(body)}")
                sent += 1
            except Exception:
                failed += 1
        add_log(message.from_user.id, "broadcast", None, body)
        bot.reply_to(
            message,
            f"📨 Рассылка завершена.\n✅ Доставлено: <b>{sent}</b>\n❌ Ошибок: <b>{failed}</b>",
        )
    except Exception as e:
        print(f"[/broadcast] {e}")
        bot.reply_to(message, "❌ Не удалось выполнить команду.")


@bot.message_handler(commands=["stats"])
def cmd_stats(message):
    try:
        register_message_user(message)
        if not antispam(message.from_user.id) or not require(message, "owner"):
            return
        s = get_stats()
        bot.reply_to(
            message,
            "📊 <b>Статистика бота</b>\n\n"
            f"👥 Всего пользователей: <b>{s['users']}</b>\n"
            f"👑 Владельцев: <b>{s['owner']}</b>\n"
            f"⚙️ Администраторов: <b>{s['admin']}</b>\n"
            f"🛡 Модераторов: <b>{s['moderator']}</b>\n"
            f"👤 Обычных: <b>{s['user']}</b>\n"
            f"⚠️ Предупреждений: <b>{s['warnings']}</b>\n"
            f"📜 Записей в логах: <b>{s['logs']}</b>",
        )
    except Exception as e:
        print(f"[/stats] {e}")
        bot.reply_to(message, "❌ Не удалось выполнить команду.")


@bot.my_chat_member_handler()
def handle_my_chat_member(update):
    try:
        chat = update.chat
        new = update.new_chat_member.status
        if new in ("member", "administrator"):
            add_chat(chat.id, chat.title)
            sync_chat_roles(chat.id)
            print(f"[my_chat_member] Бот добавлен в чат {chat.id}")
        elif new in ("left", "kicked"):
            remove_chat(chat.id)
            print(f"[my_chat_member] Бот удалён из чата {chat.id}")
    except Exception as e:
        print(f"[my_chat_member] {e}")


@bot.chat_member_handler()
def handle_chat_member(update):
    try:
        u = update.new_chat_member.user
        old_status = update.old_chat_member.status
        new_status = update.new_chat_member.status
        if old_status == new_status:
            return
        if new_status == "creator":
            set_role(u.id, "owner")
            add_user(u.id, u.username, u.first_name, role="owner")
            print(f"[chat_member] {u.id} назначен владельцем")
        elif new_status == "administrator":
            cur_role = get_role(u.id)
            if cur_role not in ("owner", "admin"):
                set_role(u.id, "admin")
                add_user(u.id, u.username, u.first_name, role="admin")
            print(f"[chat_member] {u.id} назначен администратором")
        elif old_status in ("creator", "administrator") and new_status in ("member", "restricted"):
            cur_role = get_role(u.id)
            if cur_role not in ("owner", "admin"):
                pass
            print(f"[chat_member] {u.id} лишён админских прав")
    except Exception as e:
        print(f"[chat_member] {e}")


@bot.message_handler(
    func=lambda m: (
        m.chat.id
        and not (m.text and m.text.startswith("/"))
        and role_level(get_role(m.from_user.id)) < ROLES["admin"]
        and is_ad_message(m, get_anti_advertising_settings(m.chat.id))
    ),
    content_types=["text", "photo", "video", "document", "animation"],
)
def handle_anti_advertising(message):
    try:
        chat_id = message.chat.id
        uid = message.from_user.id
        settings = get_anti_advertising_settings(chat_id)
        action = settings.get("action", "delete")

        try:
            bot.delete_message(chat_id, message.message_id)
        except Exception:
            pass

        name = mention(uid, message.from_user.username, message.from_user.first_name)
        if action in ("warn", "ban"):
            add_warning(uid, uid, "Реклама")
            total = count_warnings(uid)
            if total >= config.WARN_LIMIT or action == "ban":
                try:
                    bot.ban_chat_member(chat_id, uid)
                    clear_warnings(uid)
                    add_log(uid, "auto-ban", uid, "Реклама")
                    bot.send_message(chat_id, f"🔨 {name} забанен за рекламу.")
                except Exception:
                    pass
            else:
                add_log(uid, "auto-warn", uid, "Реклама")
                bot.send_message(chat_id, f"⚠️ {name} — предупреждение за рекламу (<b>{total}/{config.WARN_LIMIT}</b>).")

    except Exception as e:
        print(f"[anti_advertising_handler] {e}")


@bot.message_handler(func=lambda m: True, content_types=["text"])
def catch_all(message):
    register_message_user(message)
    try:
        add_chat(message.chat.id, message.chat.title)
    except Exception:
        pass
