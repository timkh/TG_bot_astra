#!/usr/bin/env python3
# coding: utf-8
"""
AstraLab 3000 — rewritten for python-telegram-bot (async).
Features:
- Request contact on /start
- 1-day trial after entering name+birth
- Subscriptions: 7 / 30 / 365 days via Telegram Stars (currency="XTR", provider_token="")
- Daily forecast at 08:00 Europe/Helsinki (APScheduler)
- Users stored in JSON (users.json)
- Optional Groq integration (GROQ_API_KEY)
"""

import os
import json
import threading
import time
from datetime import datetime, timedelta
from pytz import timezone
import locale
import logging
from typing import Dict

import requests
from apscheduler.schedulers.background import BackgroundScheduler

from telegram import (
    Update,
    LabeledPrice,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    PreCheckoutQueryHandler,
    filters,
)

# ----------------- Config -----------------
try:
    locale.setlocale(locale.LC_TIME, "ru_RU.UTF-8")
except Exception:
    pass

BOT_TOKEN = os.environ.get("BOT_TOKEN")  # required
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
USERS_FILE = os.environ.get("USERS_FILE", "users.json")

TIMEZONE = os.environ.get("TIMEZONE", "Europe/Helsinki")
DAILY_HOUR = int(os.environ.get("DAILY_HOUR", "8"))
DAILY_MINUTE = int(os.environ.get("DAILY_MINUTE", "0"))

# Prices in Stars (integers)
PRICE_7 = int(os.environ.get("PRICE_7", "549"))
PRICE_30 = int(os.environ.get("PRICE_30", "1649"))
PRICE_365 = int(os.environ.get("PRICE_365", "5499"))

# ----------------- Logging -----------------
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# ----------------- Users storage -----------------
_lock = threading.Lock()


def load_users() -> Dict:
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.exception("Failed to load users.json: %s", e)
            return {}
    return {}


def save_users(data: Dict):
    with _lock:
        with open(USERS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


users = load_users()

# ----------------- Utilities -----------------


def iso_now():
    return datetime.now(timezone(TIMEZONE)).isoformat()


def parse_date_ddmmyyyy(s: str):
    try:
        parts = s.strip().split(".")
        if len(parts) >= 3:
            d, m, y = int(parts[0]), int(parts[1]), int(parts[2])
            return datetime(year=y, month=m, day=d).date()
    except Exception:
        return None
    return None


def get_zodiac_sign(birth_date: str) -> str:
    try:
        d, m = map(int, birth_date.strip().split(".")[:2])
        if (m == 3 and d >= 21) or (m == 4 and d <= 19):
            return "Овен"
        if (m == 4 and d >= 20) or (m == 5 and d <= 20):
            return "Телец"
        if (m == 5 and d >= 21) or (m == 6 and d <= 20):
            return "Близнецы"
        if (m == 6 and d >= 21) or (m == 7 and d <= 22):
            return "Рак"
        if (m == 7 and d >= 23) or (m == 8 and d <= 22):
            return "Лев"
        if (m == 8 and d >= 23) or (m == 9 and d <= 22):
            return "Дева"
        if (m == 9 and d >= 23) or (m == 10 and d <= 22):
            return "Весы"
        if (m == 10 and d >= 23) or (m == 11 and d <= 21):
            return "Скорпион"
        if (m == 11 and d >= 22) or (m == 12 and d <= 21):
            return "Стрелец"
        if (m == 12 and d >= 22) or (m == 1 and d <= 19):
            return "Козерог"
        if (m == 1 and d >= 20) or (m == 2 and d <= 18):
            return "Водолей"
        if (m == 2 and d >= 19) or (m == 3 and d <= 20):
            return "Рыбы"
    except Exception:
        pass
    return "неизвестен"


# ----------------- AI Prompt -----------------
AI_PROMPT = """
Ты — сверхточная нейросеть-астролог «АстраЛаб», работающая на квантовой нумерологии и транзитах 2025–2026 годов.

Имя: {name}
Знак зодиака: {zodiac}
Дата рождения: {birth}
Сегодня: {today}

Строго соблюдай:
- Прогноз только на 1 день
- 4–6 обращений по имени
- 3–5 упоминаний знака
- Одна деталь из прошлого
- Прогноз с датами на 1–3 дня
- Ритуал под {zodiac}
- Фраза: «Вселенная уже запустила этот сценарий»
- 200–320 слов, без списков
"""


def generate_forecast(name: str, birth: str) -> str:
    today = datetime.now(timezone(TIMEZONE)).strftime("%d %B %Y")
    zodiac = get_zodiac_sign(birth)
    prompt = AI_PROMPT.format(name=name, zodiac=zodiac, birth=birth, today=today)

    if GROQ_API_KEY:
        try:
            r = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                json={
                    "model": "llama-3.1-8b-instant",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.87,
                    "max_tokens": 700,
                },
                timeout=18,
            )
            if r.status_code == 200:
                return r.json()["choices"][0]["message"]["content"].strip()
        except Exception:
            logger.exception("Groq error")
    # fallback
    return f"{name}, как настоящий {zodiac}, ты входишь в мощный поток энергии. Вселенная уже запустила этот сценарий — держи фокус и помни уроки прошлого."


# ----------------- Keyboards -----------------
def contact_kb():
    kb = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    kb.add(KeyboardButton("Поделиться номером телефона", request_contact=True))
    return kb


def sub_kb():
    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("7 дней — 549 ★", callback_data="sub7")],
            [InlineKeyboardButton("30 дней — 1649 ★", callback_data="sub30")],
            [InlineKeyboardButton("Год — 5499 ★", callback_data="sub365")],
        ]
    )
    return kb


# ----------------- Handlers -----------------


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = str(user.id)
    users.setdefault(uid, {})
    u = users[uid]
    u.setdefault("user_id", uid)
    u.setdefault("paid", False)
    if "username" not in u and user.username:
        u["username"] = user.username
    save_users(users)

    await update.message.reply_text(
        "Привет! Я — ИИ-астролог.\n\nСначала поделись номером телефона (он сохранится в базе), затем отправь в двух строках:\nИмя\nДД.MM.ГГГГ",
        reply_markup=contact_kb(),
    )


async def contact_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    contact = update.message.contact
    if not contact or contact.user_id is None:
        await update.message.reply_text("Пожалуйста, нажмите кнопку 'Поделиться номером телефона'.")
        return
    uid = str(update.effective_user.id)
    users.setdefault(uid, {})
    users[uid]["phone"] = contact.phone_number
    users[uid]["contact_saved_at"] = iso_now()
    save_users(users)
    await update.message.reply_text("Номер сохранён. Теперь отправь две строки:\nИмя\nДД.MM.ГГГГ")


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ""
    if text.startswith("/"):
        return
    uid = str(update.effective_user.id)
    lines = [x.strip() for x in text.split("\n") if x.strip()]
    if len(lines) < 2:
        await update.message.reply_text(
            "Пиши имя и дату рождения в двух строках.\nПример:\nАня\n12.03.1990"
        )
        return
    name = lines[0].strip().capitalize()
    birth = lines[1].strip()
    if not parse_date_ddmmyyyy(birth):
        await update.message.reply_text("Неправильный формат даты. Используй ДД.MM.ГГГГ (например 12.03.1990).")
        return

    users.setdefault(uid, {})
    u = users[uid]
    u.update({"name": name, "birth": birth})
    if "trial_start" not in u:
        u["trial_start"] = iso_now()
    save_users(users)

    await update.message.reply_text(generate_forecast(name, birth) + "\n\nЧтобы получать прогнозы каждый день → /subscribe")


async def forecast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    u = users.get(uid)
    if not u or "name" not in u or "birth" not in u:
        await update.message.reply_text("Сначала отправь имя и дату рождения в двух строках (или нажми /start).")
        return
    now_date = datetime.now(timezone(TIMEZONE)).date()
    allowed = False
    if "trial_start" in u:
        try:
            trial_date = datetime.fromisoformat(u["trial_start"]).date()
            if (now_date - trial_date).days <= 0:
                allowed = True
        except Exception:
            pass
    if u.get("paid") and "expires" in u:
        try:
            if datetime.fromisoformat(u["expires"]).date() >= now_date:
                allowed = True
        except Exception:
            pass
    if not allowed:
        await update.message.reply_text("Подписка нужна для ежедневных прогнозов →", reply_markup=sub_kb())
        return
    await update.message.reply_text(generate_forecast(u["name"], u["birth"]))


async def subscribe_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Выбери подписку:", reply_markup=sub_kb())


# ----------------- Payments -----------------


async def invoice_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    choice = q.data
    if choice == "sub7":
        days, price = 7, PRICE_7
    elif choice == "sub30":
        days, price = 30, PRICE_30
    else:
        days, price = 365, PRICE_365

    prices = [LabeledPrice(f"{days} дней", price)]

    try:
        # provider_token must be empty for Telegram Stars (digital goods)
        await context.bot.send_invoice(
            chat_id=q.message.chat_id,
            title=f"АстраЛаб — {days} дней",
            description="Ежедневные ИИ-прогнозы",
            payload=f"sub_{days}d",
            provider_token="",  # EMPTY for Stars (digital)
            currency="XTR",
            prices=prices,
            start_parameter=f"astralab_{days}",
        )
    except Exception as e:
        logger.exception("Failed to send invoice")
        await q.message.reply_text("Не удалось создать инвойс. Проверь конфигурацию провайдера.")


async def precheckout_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.pre_checkout_query
    try:
        await query.answer(ok=True)
    except Exception:
        logger.exception("precheckout answer failed")


async def successful_payment_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    uid = str(msg.from_user.id)
    payload = msg.successful_payment.invoice_payload
    try:
        days = int(payload.split("_")[1].replace("d", ""))
    except Exception:
        days = 30
    now = datetime.now(timezone(TIMEZONE))
    expires = now + timedelta(days=days)
    users.setdefault(uid, {})
    u = users[uid]
    u["paid"] = True
    # extend if exists
    if "expires" in u:
        try:
            cur = datetime.fromisoformat(u["expires"])
            if cur > now:
                expires = cur + timedelta(days=days)
        except Exception:
            pass
    u["expires"] = expires.isoformat()
    u["first_payment_date"] = u.get("first_payment_date", now.isoformat())
    save_users(users)
    await msg.reply_text(f"Оплата прошла! Подписка активна до {expires.strftime('%d.%m.%Y')}. Спасибо 🌟")


# ----------------- Daily job -----------------
scheduler = BackgroundScheduler(timezone=timezone(TIMEZONE))


def daily_job(application: Application):
    now = datetime.now(timezone(TIMEZONE)).date()
    for uid, u in list(users.items()):
        if not u.get("name") or not u.get("birth"):
            continue
        allowed = False
        if "trial_start" in u:
            try:
                ts = datetime.fromisoformat(u["trial_start"]).date()
                if (now - ts).days <= 0:
                    allowed = True
            except Exception:
                pass
        if u.get("paid") and u.get("expires"):
            try:
                if datetime.fromisoformat(u["expires"]).date() >= now:
                    allowed = True
            except Exception:
                pass
        if not allowed:
            try:
                application.bot.send_message(
                    chat_id=int(uid),
                    text=f"Привет, {u.get('name','друг')}! Ваша подписка истекла — хотите продлить?",
                    reply_markup=sub_kb(),
                )
            except Exception:
                logger.exception("Failed to send renewal message")
            continue
        try:
            application.bot.send_message(
                chat_id=int(uid),
                text=f"Доброе утро, {u.get('name','')}!\n\n" + generate_forecast(u["name"], u["birth"]),
            )
        except Exception:
            logger.exception("Failed to send daily forecast")


# ----------------- Startup -----------------


def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN is not set")
        return

    app = Application.builder().token(BOT_TOKEN).build()

    # Handlers
    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(MessageHandler(filters.CONTACT, contact_handler))
    app.add_handler(CommandHandler("forecast", forecast_cmd))
    app.add_handler(CommandHandler("subscribe", subscribe_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    app.add_handler(CallbackQueryHandler(invoice_callback, pattern="^sub"))
    app.add_handler(PreCheckoutQueryHandler(precheckout_handler))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_handler))

    # Start APScheduler AFTER app built
    scheduler.add_job(lambda: daily_job(app), "cron", hour=DAILY_HOUR, minute=DAILY_MINUTE)
    scheduler.start()
    logger.info("Scheduler started: daily at %02d:%02d %s", DAILY_HOUR, DAILY_MINUTE, TIMEZONE)

    # Run bot (polling). For Render you may prefer webhook mode; tell me if you want webhook.
    app.run_polling(allowed_updates=None)


if __name__ == "__main__":
    main()
