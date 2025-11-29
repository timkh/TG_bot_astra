#!/usr/bin/env python3
# coding: utf-8

import os
import json
import threading
import time
from datetime import datetime, timedelta
from pytz import timezone
import locale

import telebot
from telebot.types import LabeledPrice, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from flask import Flask
from apscheduler.schedulers.background import BackgroundScheduler
import atexit
import requests

# -------------------- Конфигурация --------------------
try:
    locale.setlocale(locale.LC_TIME, "ru_RU.UTF-8")
except Exception:
    pass

BOT_TOKEN = os.environ["BOT_TOKEN"]            # обязателен
PROVIDER_TOKEN = os.environ.get("PROVIDER_TOKEN", "")  # обязателен для оплаты (Telegram payment / Stars)
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")      # опционно для генерации через Groq

USERS_FILE = "users.json"
TIMEZONE = "Europe/Moscow"  # рассылка в 8:00 по Москве
DAILY_HOUR = 8
DAILY_MINUTE = 0

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")
app = Flask(__name__)

# -------------------- Пользователи (файл) --------------------
_lock = threading.Lock()

def load_users():
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_users(data):
    with _lock:
        with open(USERS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

users = load_users()

# -------------------- Утилиты --------------------
def iso_now():
    return datetime.now(timezone(TIMEZONE)).isoformat()

def parse_date_ddmmyyyy(s):
    """Попытка распарсить ДД.ММ.ГГГГ или ДД.MM.YYYY (возвращает datetime.date или None)"""
    try:
        parts = s.strip().split('.')
        if len(parts) >= 3:
            d, m, y = int(parts[0]), int(parts[1]), int(parts[2])
            return datetime(year=y, month=m, day=d).date()
    except Exception:
        pass
    return None

def get_zodiac_sign(birth_date: str) -> str:
    try:
        d, m = map(int, birth_date.strip().split('.')[:2])
        if (m == 3 and d >= 21) or (m == 4 and d <= 19): return "Овен"
        if (m == 4 and d >= 20) or (m == 5 and d <= 20): return "Телец"
        if (m == 5 and d >= 21) or (m == 6 and d <= 20): return "Близнецы"
        if (m == 6 and d >= 21) or (m == 7 and d <= 22): return "Рак"
        if (m == 7 and d >= 23) or (m == 8 and d <= 22): return "Лев"
        if (m == 8 and d >= 23) or (m == 9 and d <= 22): return "Дева"
        if (m == 9 and d >= 23) or (m == 10 and d <= 22): return "Весы"
        if (m == 10 and d >= 23) or (m == 11 and d <= 21): return "Скорпион"
        if (m == 11 and d >= 22) or (m == 12 and d <= 21): return "Стрелец"
        if (m == 12 and d >= 22) or (m == 1 and d <= 19): return "Козерог"
        if (m == 1 and d >= 20) or (m == 2 and d <= 18): return "Водолей"
        if (m == 2 and d >= 19) or (m == 3 and d <= 20): return "Рыбы"
    except:
        pass
    return "неизвестен"

# -------------------- Промпт / генерация прогноза --------------------
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

def generate_forecast(name, birth):
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
                    "max_tokens": 700
                },
                timeout=18
            )
            if r.status_code == 200:
                return r.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:
            print(f"Groq error: {e}")

    # fallback текст
    return f"{name}, как настоящий {zodiac}, ты входишь в мощный поток энергии. Вселенная уже запустила этот сценарий — держи фокус и помни уроки прошлого."

# -------------------- Вспомогательные клавиатуры --------------------
def make_contact_request_kb():
    kb = ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    kb.add(KeyboardButton("Поделиться номером телефона", request_contact=True))
    return kb

def make_subscribe_kb():
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(
        InlineKeyboardButton("7 дней — 549", callback_data="sub7"),
        InlineKeyboardButton("30 дней — 1649", callback_data="sub30"),
        InlineKeyboardButton("Год — 5499", callback_data="sub365")
    )
    return kb

# -------------------- Flask health --------------------
@app.route('/health')
def health():
    return "АстраЛаб 3000 — OK", 200

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

# -------------------- Хендлеры --------------------
@bot.message_handler(commands=['start'])
def start_handler(m):
    uid = str(m.from_user.id)
    users.setdefault(uid, {})
    # Сохраним базовую запись если нет
    u = users[uid]
    u.setdefault("user_id", uid)
    u.setdefault("paid", False)
    # trial_start не назначаем пока пользователь не введёт имя/дату
    # Сохраним если есть username
    if "username" not in u and m.from_user.username:
        u["username"] = m.from_user.username
    save_users(users)

    bot.send_message(
        m.chat.id,
        "Привет! Я — ИИ-астролог.\n\nСначала поделись номером телефона (он сохранится в базе), затем отправь в двух строках:\nИмя\nДД.MM.ГГГГ",
        reply_markup=make_contact_request_kb()
    )

@bot.message_handler(content_types=['contact'])
def contact_handler(m):
    # Пользователь поделился контактом
    if not m.contact or not m.contact.user_id:
        bot.reply_to(m, "Спасибо, но нужна именно ваша контактная кнопка.")
        return

    uid = str(m.from_user.id)
    users.setdefault(uid, {})
    users[uid]["phone"] = m.contact.phone_number
    users[uid]["contact_saved_at"] = iso_now()
    save_users(users)

    bot.reply_to(m, "Номер сохранён. Теперь отправь две строки:\nИмя\nДД.MM.ГГГГ")

@bot.message_handler(commands=['forecast'])
def cmd_forecast(m):
    uid = str(m.from_user.id)
    u = users.get(uid)
    if not u or "name" not in u or "birth" not in u:
        return bot.reply_to(m, "Сначала отправь имя и дату рождения в двух строках (или нажми /start).")
    # Проверяем доступ: либо в триале (1 день), либо оплачено и не истекло
    now_date = datetime.now(timezone(TIMEZONE)).date()
    allowed = False

    # trial check (1 day)
    if "trial_start" in u:
        try:
            trial_date = datetime.fromisoformat(u["trial_start"]).date()
            if (now_date - trial_date).days <= 0:  # same day => trial valid (1 day)
                allowed = True
        except Exception:
            pass

    # paid check
    if u.get("paid") and "expires" in u:
        try:
            if datetime.fromisoformat(u["expires"]).date() >= now_date:
                allowed = True
        except Exception:
            pass

    if not allowed:
        kb = make_subscribe_kb()
        return bot.reply_to(m, "Подписка нужна для ежедневных прогнозов →", reply_markup=kb)

    bot.reply_to(m, generate_forecast(u["name"], u["birth"]))

@bot.message_handler(commands=['subscribe'])
def subscribe_cmd(m):
    kb = make_subscribe_kb()
    bot.reply_to(m, "Выбери подписку:", reply_markup=kb)

@bot.message_handler(content_types=['text'])
def text_input(m):
    if m.text.startswith('/'):
        return

    uid = str(m.from_user.id)
    lines = [x.strip() for x in m.text.split('\n') if x.strip()]
    if len(lines) < 2:
        return bot.reply_to(m, "Пиши имя и дату рождения в двух строках.\nПример:\nАня\n12.03.1990")

    name = lines[0].strip().capitalize()
    birth = lines[1].strip()
    # validate date
    if not parse_date_ddmmyyyy(birth):
        return bot.reply_to(m, "Неправильный формат даты. Используй ДД.MM.ГГГГ (например 12.03.1990).")

    users.setdefault(uid, {})
    u = users[uid]
    u.update({
        "name": name,
        "birth": birth
    })
    # если триал ещё не назначен — назначаем триал (1 день, включая день ввода)
    if "trial_start" not in u:
        u["trial_start"] = iso_now()
    save_users(users)

    # Отправляем прогноз (первый бесплатный день)
    bot.reply_to(m, generate_forecast(name, birth) + "\n\nЧтобы получать прогнозы каждый день → /subscribe")

# -------------------- Инвойсы / оплаты --------------------
@bot.callback_query_handler(func=lambda c: c.data in ["sub7","sub30","sub365"])
def invoice_handler(c):
    if c.data == "sub7":
        days, price = 7, 549
    elif c.data == "sub30":
        days, price = 30, 1649
    else:
        days, price = 365, 5499

    # Важно: формат amount в LabeledPrice зависит от провайдера (минимальные единицы).
    # Для Telegram Payments для обычных валют это копейки/центы (amount в integer).
    # Для Stars (XTR) — уточни у провайдера, какова минимальная единица. Здесь мы передаём целое число.
    prices = [LabeledPrice(f"{days} дней", price)]

    try:
        bot.send_invoice(
  chat_id=USER_ID,
  title="Test Stars",
  description="Test цифровой товар",
  payload="test_payload",
  provider_token="",
  currency="XTR",
  prices=[LabeledPrice("Test", 1)],
  start_parameter="test_stars"
)


        bot.answer_callback_query(c.id)
    except Exception as e:
        bot.answer_callback_query(c.id, "Не удалось создать инвойс. Проверь конфигурацию провайдера.", show_alert=True)
        print("Invoice error:", e)

@bot.pre_checkout_query_handler(func=lambda q: True)
def pre_checkout(q):
    try:
        bot.answer_pre_checkout_query(q.id, ok=True)
    except Exception as e:
        print("pre_checkout error:", e)

@bot.message_handler(content_types=['successful_payment'])
def successful_payment(m):
    uid = str(m.from_user.id)
    payload = m.successful_payment.invoice_payload
    # Ожидаем payload формата sub_{days}d
    try:
        days = int(payload.split('_')[1].replace('d', ''))
    except Exception:
        days = 30

    now = datetime.now(timezone(TIMEZONE))
    expires = now + timedelta(days=days)

    users.setdefault(uid, {})
    u = users[uid]
    u["paid"] = True
    # Если уже есть expires в будущем — продлеваем от текущей expires
    if "expires" in u:
        try:
            current_expires = datetime.fromisoformat(u["expires"])
            if current_expires > now:
                # продление от текущей даты окончания
                expires = current_expires + timedelta(days=days)
        except Exception:
            pass

    u["expires"] = expires.isoformat()
    u["first_payment_date"] = u.get("first_payment_date", now.isoformat())
    # Уберём trial_start после оплаты (или оставим - не критично) — но trial действует только 1 день
    save_users(users)

    bot.reply_to(m, f"Оплата прошла! Подписка активна до {expires.strftime('%d.%m.%Y')}. Спасибо 🌟")

# -------------------- Ежедневная рассылка --------------------
scheduler = BackgroundScheduler(timezone=timezone(TIMEZONE))
scheduler.start()

def daily_job():
    now = datetime.now(timezone(TIMEZONE)).date()
    for uid, u in list(users.items()):
        # нужно имя и дата рождения
        if not u.get("name") or not u.get("birth"):
            continue

        allowed = False

        # trial: 1 день (day of trial_start)
        if "trial_start" in u:
            try:
                ts = datetime.fromisoformat(u["trial_start"]).date()
                if (now - ts).days <= 0:
                    allowed = True
            except Exception:
                pass

        # paid subscription
        if u.get("paid") and u.get("expires"):
            try:
                if datetime.fromisoformat(u["expires"]).date() >= now:
                    allowed = True
            except Exception:
                pass

        if not allowed:
            # если подписка истекла — предложим продление один раз в утренней рассылке
            try:
                bot.send_message(int(uid), f"Привет, {u.get('name','друг')}! Ваша подписка истекла — хотите продлить?", reply_markup=make_subscribe_kb())
            except Exception:
                pass
            continue

        # Отправляем прогноз
        try:
            bot.send_message(
                int(uid),
                f"Доброе утро, {u.get('name','') }!\n\n" + generate_forecast(u['name'], u['birth'])
            )
        except Exception:
            pass

# Запланировать cron на 8:00 по TIMEZONE
scheduler.add_job(daily_job, "cron", hour=DAILY_HOUR, minute=DAILY_MINUTE)
atexit.register(lambda: scheduler.shutdown())

# -------------------- Запуск --------------------
if __name__ == "__main__":
    # Запуск Flask health endpoint в отдельном потоке (нужно для Render)
    threading.Thread(target=run_flask, daemon=True).start()
    time.sleep(1)
    print("АстраЛаб 3000 запущен (polling).")
    bot.infinity_polling(none_stop=True)
