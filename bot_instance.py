import telebot
import config

bot = telebot.TeleBot(config.BOT_TOKEN, parse_mode="HTML")
