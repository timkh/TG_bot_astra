import os
import json
from datetime import datetime, timedelta
from flask import Flask, request

from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    LabeledPrice,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

import requests
from apscheduler.schedulers.background import BackgroundScheduler
from pytz import timezone


# ====================== CONFIG ======================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
DOMAIN = os.environ.get("DOMAIN")  # https://your-service.onrender.com


USERS_FILE = "users.json"


# ====================== FLASK ======================
app = Flask(__name__)


@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(force=True)
    update = await application.update_queue.put(data, application.bot)
    application.update_queue.put(update)
    return "ok", 200


@app.route("/health")
def health():
    return "ok", 200


# ====================== LOAD USERS ======================
def load_users():
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_users(data):
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


users = load_users()


# ====================== AI FORECAST ======================
AI_PROMPT = """
Ты — сверхточная нейросеть-астролог «АстраЛаб-3000».

Имя: {name}
Знак: {zodiac}
Дата рождения: {birth}
Сегодня: {today}

Соблюдай:
- 4–6 обращений по имени
- 3–5 упоминаний знака
- 200–320 слов
"""


def get_zodiac(birth: str):
    try:
        d, m, *_ = map(int, birth.split("."))
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
        return "Неизвестен"


def generate_forecast(name, birth):
    today = datetime.now().strftime("%d %B %Y")
    zodiac = get_zodiac(birth)

    prompt = AI_PROMPT.format(
        name=name, birth=birth, zodiac=zodiac, today=today
    )

    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
            json={
                "model": "llama-3.1-8b-instant",
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=20
        )
        return r.json()["choices"][0]["message"]["content"].strip()

    except Exception:
        return f"{name}, сегодня для {zodiac} благоприятная энергия..."


# ====================== COMMANDS ======================
async def start(update: Update, context):
    await update.message.reply_text(
        "Привет! Отправь две строки:\nИмя\nДД.ММ.ГГГГ"
    )


async def save_user(update: Update, context):
    if update.message.text.startswith("/"):
        return

    lines = update.message.text.split("\n")
    if len(lines) < 2:
        return await update.message.reply_text("Формат:\nИмя\nДД.ММ.ГГГГ")

    name = lines[0].strip().capitalize()
    birth = lines[1].strip()
    uid = str(update.message.from_user.id)

    users.setdefault(uid, {})
    users[uid]["name"] = name
    users[uid]["birth"] = birth
    users[uid]["trial_used"] = False
    save_users(users)

    # trial 1 day
    forecast = generate_forecast(name, birth)
    await update.message.reply_text(
        f"Твой пробный прогноз:\n\n{forecast}\n\nЧтобы продолжить — /subscribe"
    )


async def subscribe(update: Update, context):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("7 дней — 549⭐", callback_data="sub7")],
        [InlineKeyboardButton("30 дней — 1649⭐", callback_data="sub30")],
        [InlineKeyboardButton("365 дней — 5499⭐", callback_data="sub365")],
    ])
    await update.message.reply_text("Выбери подписку:", reply_markup=kb)


async def callback(update: Update, context):
    query = update.callback_query
    await query.answer()

    plan = query.data
    days = {"sub7": 7, "sub30": 30, "sub365": 365}[plan]
    price = {"sub7": 549, "sub30": 1649, "sub365": 5499}[plan]

    await query.message.reply_invoice(
        title=f"АстраЛаб — {days} дней",
        description="ИИ прогнозы каждый день",
        payload=f"plan_{days}",
        currency="XTR",
        prices=[LabeledPrice("Подписка", price)],
        provider_token="",  # Stars НЕ требует provider_token
    )


async def successful_payment(update: Update, context):
    payment = update.message.successful_payment
    uid = str(update.message.from_user.id)

    days = int(payment.invoice_payload.replace("plan_", ""))

    expires = datetime.now() + timedelta(days=days)

    users.setdefault(uid, {})
    users[uid]["paid"] = True
    users[uid]["expires"] = expires.isoformat()
    users[uid]["first_payment"] = datetime.now().isoformat()
    save_users(users)

    await update.message.reply_text(
        f"Оплата прошла!\nПодписка активна до {expires.strftime('%d.%m.%Y')}."
    )


# ====================== DAILY FORECAST JOB ======================
async def daily_job():
    now = datetime.now().date()

    for uid, u in users.items():
        if not u.get("paid"):
            continue

        if datetime.fromisoformat(u["expires"]).date() < now:
            continue

        name = u["name"]
        birth = u["birth"]
        try:
            await application.bot.send_message(
                chat_id=int(uid),
                text=generate_forecast(name, birth)
            )
        except Exception as e:
            print(f"Ошибка при отправке пользователю {uid}: {e}")


scheduler = BackgroundScheduler(timezone=timezone("Europe/Moscow"))
scheduler.add_job(daily_job, "cron", hour=8, minute=0)
scheduler.start()


# ====================== START BOT ======================
application = Application.builder().token(BOT_TOKEN).build()

application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("subscribe", subscribe))
application.add_handler(MessageHandler(filters.TEXT, save_user))
application.add_handler(CallbackQueryHandler(callback))
application.add_handler(
    MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment)
)


if __name__ == "__main__":
    # Устанавливаем webhook
    application.bot.set_webhook(f"{DOMAIN}/webhook")
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
