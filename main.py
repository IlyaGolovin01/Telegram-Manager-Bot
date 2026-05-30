import threading
import time

from bot_instance import bot
from database import init_db
import handlers

if __name__ == "__main__":
    init_db()
    threading.Thread(
        target=handlers.sync_all_chats, daemon=True, name="sync-chats"
    ).start()
    print("Бот запущен...")
    while True:
        try:
            bot.infinity_polling(
                skip_pending=True, timeout=30,
                allowed_updates=["message", "my_chat_member", "chat_member"],
            )
        except Exception as e:
            print(f"[polling] {e}")
            time.sleep(5)
