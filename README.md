# Telegram XP + Welcome Bot

Her mesaj için kelime sayısına göre XP, anti-spam, haftalık sıfırlama ve hoş geldin botu.

## Özellikler
- 1-2 kelime → 2 XP, 3-5 kelime → 5 XP, 6+ kelime → 10 XP
- 1sn altı spam → 1 XP
- 5sn'de 10 mesaj → 60sn mute
- `.sıra` / `.ben` komutları
- Her Cumartesi gecesi 00:00 (Pazar 00:00 TR) haftalık sıfırlama
- Render / Railway 7/24 uyumlu (keepalive)

## Kurulum
```bash
pip install -r requirements.txt
cp .env.example .env  # BOT_TOKEN ve WELCOME_BOT_TOKEN ekle
python bot.py          # XP Bot
python welcome_bot.py  # Hos Geldin Bot (ayrı token)
```

## Deploy
Bakınız `DEPLOY.md` ve `render.yaml`
- Render: Web Service olarak deploy et
- Railway/Fly.io: `Dockerfile` ile
- VPS: `docker compose up -d`
