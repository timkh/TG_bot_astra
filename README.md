AstraLab 3000 — python-telegram-bot version

Run:
1) set env BOT_TOKEN
2) pip install -r requirements.txt
3) python main.py

Notes:
- Payments use Telegram Stars. provider_token must be empty for digital goods (Stars).
- Prices configured in env (PRICE_7/30/365) as integer number of Stars.
- For production on Render: you can keep polling (works), or I can provide webhook version (recommended).
