import sqlite3
import time
import logging
import os
import re
import threading
import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from collections import defaultdict, deque
from http.server import HTTPServer, BaseHTTPRequestHandler

from telegram import Update, ChatPermissions
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, ContextTypes, filters
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN bulunamadı! .env dosyası oluştur ve içine BOT_TOKEN=... yaz")

DB_PATH = "xp.db"

# --- Haftalık Reset Ayarları ---
WEEKLY_RESET_ENABLED = True
WEEKLY_RESET_TZ = "Europe/Istanbul"
# 6 = Pazar 00:00 = Cumartesi gecesi 00:00  (cumartesi gecesi sıfırlansın isteniyor)
# Eğer Cuma gecesi 00:00 istiyorsan 5 yap
WEEKLY_RESET_WEEKDAY = 6  # 0=Pzt ... 6=Pazar
WEEKLY_RESET_HOUR = 0
WEEKLY_RESET_MINUTE = 0
last_weekly_reset_date = None

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Spam / Flood Takibi (memory'de tutulur) ---
user_message_times = defaultdict(lambda: deque())
muted_users = {}
last_message_time = {}

FLOOD_WINDOW = 5
FLOOD_LIMIT = 10
FLOOD_MUTE_SECONDS = 60
SPAM_INTERVAL = 1.0

# --- DB İşlemleri ---
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            xp INTEGER DEFAULT 0,
            level INTEGER DEFAULT 0,
            message_count INTEGER DEFAULT 0,
            last_xp_time REAL DEFAULT 0
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS active_chats (
            chat_id INTEGER PRIMARY KEY,
            title TEXT,
            last_seen REAL
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS weekly_winners (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            week TEXT,
            user_id INTEGER,
            username TEXT,
            first_name TEXT,
            xp INTEGER
        )
    """)
    conn.commit()
    conn.close()

def save_chat(chat):
    if not chat:
        return
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        title = getattr(chat, 'title', None) or getattr(chat, 'first_name', None) or str(chat.id)
        c.execute("INSERT OR REPLACE INTO active_chats (chat_id, title, last_seen) VALUES (?, ?, ?)",
                  (chat.id, title, time.time()))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"save_chat hata: {e}")

def get_all_chats():
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT chat_id FROM active_chats")
        rows = c.fetchall()
        conn.close()
        return [r[0] for r in rows]
    except:
        return []

def get_level(xp: int) -> int:
    level = 0
    while True:
        need = 5 * (level ** 2) + 50 * level + 100
        if xp >= need:
            xp -= need
            level += 1
        else:
            break
    return level

def xp_for_next_level(level: int) -> int:
    return 5 * (level ** 2) + 50 * level + 100

def get_user(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row

def add_xp(user_id, username, first_name, xp_gain):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT xp, level, message_count FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    now = time.time()
    
    if row is None:
        xp = xp_gain
        level = get_level(xp)
        c.execute("INSERT INTO users (user_id, username, first_name, xp, level, message_count, last_xp_time) VALUES (?, ?, ?, ?, ?, ?, ?)",
                  (user_id, username, first_name, xp, level, 1, now))
        conn.commit()
        conn.close()
        return xp, level, level > 0, 0
    else:
        old_xp, old_level, msg_count = row
        new_xp = old_xp + xp_gain
        new_level = get_level(new_xp)
        c.execute("UPDATE users SET xp = ?, level = ?, message_count = ?, username = ?, first_name = ?, last_xp_time = ? WHERE user_id = ?",
                  (new_xp, new_level, msg_count + 1, username, first_name, now, user_id))
        conn.commit()
        conn.close()
        leveled_up = new_level > old_level
        return new_xp, new_level, leveled_up, old_level

def calculate_xp_by_words(text: str) -> tuple[int, int]:
    if not text or not text.strip():
        return 2, 0
    words = text.strip().split()
    wc = len(words)
    if wc < 3:
        return 2, wc
    elif 3 <= wc <= 5:
        return 5, wc
    else:
        return 10, wc

def is_muted(user_id: int) -> tuple[bool, int]:
    if user_id in muted_users:
        remaining = muted_users[user_id] - time.time()
        if remaining > 0:
            return True, int(remaining)
        else:
            del muted_users[user_id]
            if user_id in user_message_times:
                user_message_times[user_id].clear()
            return False, 0
    return False, 0

def get_tz():
    try:
        return ZoneInfo(WEEKLY_RESET_TZ)
    except:
        # Windows'ta tzdata yoksa fallback UTC+3 (Türkiye)
        from datetime import timezone
        return timezone(timedelta(hours=3))

def get_next_reset_time() -> str:
    try:
        tz = get_tz()
        now = datetime.now(tz)
        days_ahead = (WEEKLY_RESET_WEEKDAY - now.weekday()) % 7
        next_reset = now.replace(hour=WEEKLY_RESET_HOUR, minute=WEEKLY_RESET_MINUTE, second=0, microsecond=0) + timedelta(days=days_ahead)
        if next_reset <= now:
            next_reset += timedelta(days=7)
        try:
            return next_reset.strftime("%d.%m.%Y %H:%M (%A) - %Z")
        except:
            return next_reset.strftime("%d.%m.%Y %H:%M")
    except Exception as e:
        return f"Hesaplanamadi: {e}"

async def perform_weekly_reset(app):
    """Haftalık XP sıfırlama - Top 10'u kaydet, duyuru yap, sonra sıfırla"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT username, first_name, xp, level, message_count, user_id FROM users ORDER BY xp DESC LIMIT 10")
    top = c.fetchall()
    
    if not top or all(r[2] == 0 for r in top):
        logger.info("Weekly reset: XP yok, sıfırlama atlandı")
        conn.close()
        return

    tz = get_tz()
    now = datetime.now(tz)
    week_str = now.strftime("%Y-W%W")

    # Kazananları kaydet
    for username, first_name, xp, level, msg_count, user_id in top:
        try:
            c.execute("INSERT INTO weekly_winners (week, user_id, username, first_name, xp) VALUES (?, ?, ?, ?, ?)",
                      (week_str, user_id, username, first_name, xp))
        except:
            pass

    # Duyuru metni
    text = f"♻️ **Haftalık XP Sıfırlandı!**\n"
    text += f"📅 {now.strftime('%d.%m.%Y %H:%M')} - Yeni hafta başladı!\n\n"
    text += "🏆 **Geçen Haftanın Top 10'u:**\n"
    for i, (username, first_name, xp, level, msg_count, user_id) in enumerate(top, 1):
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
        name = f"@{username}" if username else first_name
        text += f"{medal} {name} — {xp} XP (Lv.{level})\n"
    text += "\n✨ Herkes 0 XP'den yeniden başlıyor! Bol şans!"

    # Sıfırla: sadece xp ve level, mesaj sayısı kalabilir (istersen onu da sıfırla)
    c.execute("UPDATE users SET xp = 0, level = 0")
    conn.commit()
    conn.close()

    logger.warning(f"HAFTALIK SIFIRLAMA YAPILDI {week_str} - Top: {top[0] if top else 'yok'}")

    # Tüm gruplara duyuru gönder
    chats = get_all_chats()
    for chat_id in chats:
        try:
            await app.bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")
            await asyncio.sleep(0.5)
        except Exception as e:
            logger.warning(f"Weekly duyuru {chat_id} gonderilemedi: {e}")

async def weekly_reset_loop(app):
    global last_weekly_reset_date
    tz = get_tz()
    logger.info(f"Haftalik reset aktif: her Cumartesi gecesi 00:00 (Pazar 00:00) {WEEKLY_RESET_TZ}")
    while True:
        try:
            now = datetime.now(tz)
            if (WEEKLY_RESET_ENABLED and 
                now.weekday() == WEEKLY_RESET_WEEKDAY and 
                now.hour == WEEKLY_RESET_HOUR and 
                now.minute == WEEKLY_RESET_MINUTE):
                today_str = now.strftime("%Y-%m-%d")
                if last_weekly_reset_date != today_str:
                    await perform_weekly_reset(app)
                    last_weekly_reset_date = today_str
            await asyncio.sleep(30)
        except Exception as e:
            logger.error(f"Weekly loop hata: {e}")
            await asyncio.sleep(60)

async def post_init(app):
    # Bot açıldığında haftalık loop'u başlat
    asyncio.create_task(weekly_reset_loop(app))

def start_keepalive():
    port = os.getenv("PORT")
    if not port:
        return
    try:
        port = int(port)
    except:
        return
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-type", "text/plain; charset=utf-8")
            self.end_headers()
            try:
                next_reset = get_next_reset_time()
            except:
                next_reset = "bilinmiyor"
            msg = f"✅ XP Bot aktif - 7/24 calisiyor\nNext reset: {next_reset}"
            self.wfile.write(msg.encode())
        def log_message(self, format, *args):
            return
    def run():
        try:
            server = HTTPServer(("0.0.0.0", port), Handler)
            logger.info(f"Keepalive HTTP server port {port} dinleniyor (Render icin)")
            server.serve_forever()
        except Exception as e:
            logger.error(f"Keepalive baslatilamadi: {e}")
    t = threading.Thread(target=run, daemon=True)
    t.start()

# --- Komut Handlerları ---
async def rank_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message or update.channel_post
    user = update.effective_user
    if not user:
        return
    # Chat'i kaydet (haftalık duyuru için)
    if update.effective_chat:
        save_chat(update.effective_chat)
    row = get_user(user.id)
    if not row:
        text = "Henüz hiç XP'n yok knk, bir mesaj at da başlayalım! 😎"
        if msg:
            await msg.reply_text(text)
        else:
            await update.effective_chat.send_message(text)
        return
    
    _, username, first_name, xp, level, msg_count, _ = row
    need = xp_for_next_level(level)
    total_for_current = sum(xp_for_next_level(i) for i in range(level))
    current_level_xp = xp - total_for_current
    if current_level_xp < 0:
        current_level_xp = 0
    
    next_reset = get_next_reset_time()
    reply = (
        f"📊 **Senin İstatistiklerin**\n\n"
        f"👤 {first_name} (@{username or 'yok'})\n"
        f"⭐ XP: {xp}\n"
        f"🏆 Seviye: {level}\n"
        f"💬 Mesaj: {msg_count}\n"
        f"📈 Sonraki seviye: {current_level_xp}/{need} XP\n"
        f"♻️ Haftalık sıfırlama: {next_reset}"
    )
    target = msg if msg else update.effective_message
    if target:
        await target.reply_text(reply, parse_mode="Markdown")
    else:
        await update.effective_chat.send_message(reply, parse_mode="Markdown")

async def leaderboard_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message or update.channel_post
    if update.effective_chat:
        save_chat(update.effective_chat)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT username, first_name, xp, level, message_count FROM users ORDER BY xp DESC LIMIT 10")
    rows = c.fetchall()
    conn.close()

    if not rows or all(r[2]==0 for r in rows):
        text = "Liderlik tablosu boş, ilk mesajı sen at! 🚀\n♻️ Her Cumartesi gece 00:00'da sıfırlanır."
        if msg:
            await msg.reply_text(text)
        else:
            await update.effective_chat.send_message(text)
        return

    next_reset = get_next_reset_time()
    text = "🏆 **XP Liderlik Tablosu - Top 10**\n"
    text += f"♻️ Sıfırlama: {next_reset}\n\n"
    for i, (username, first_name, xp, level, msg_count) in enumerate(rows, 1):
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
        name = f"@{username}" if username else first_name
        text += f"{medal} {name} — Lv.{level} | {xp} XP ({msg_count} mesaj)\n"

    target = msg if msg else update.effective_message
    if target:
        await target.reply_text(text, parse_mode="Markdown")
    else:
        await update.effective_chat.send_message(text, parse_mode="Markdown")

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat:
        save_chat(update.effective_chat)
    next_reset = get_next_reset_time()
    await update.message.reply_text(
        "Selam knk! 👋 Ben XP Botu.\n\n"
        "**XP Sistemi:**\n"
        "• 1-2 kelime → 2 XP\n"
        "• 3-5 kelime → 5 XP\n"
        "• 6+ kelime → 10 XP\n\n"
        "**Anti-Spam:**\n"
        "• 1 saniyeden hızlı atarsan sadece 1 XP\n"
        "• 5 saniyede 10 mesaj atarsan 1 dakika susturulursun + XP yok\n\n"
        "**Haftalık Sıfırlama:**\n"
        f"• Her Cumartesi gecesi 00:00'da tüm XP'ler sıfırlanır\n"
        f"• Sonraki: {next_reset}\n\n"
        "**Komutlar:**\n"
        "• `.sıra` / `sıra` / `/leaderboard` → Top 10\n"
        "• `.ben` / `ben` / `/rank` → Kendi XP'n\n"
        "• `/stats` → Sunucu istatistikleri\n"
    )

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat:
        save_chat(update.effective_chat)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*), SUM(xp), SUM(message_count) FROM users")
    count, total_xp, total_msg = c.fetchone()
    c.execute("SELECT COUNT(*) FROM active_chats")
    chat_count = c.fetchone()[0]
    conn.close()
    next_reset = get_next_reset_time()
    await update.message.reply_text(
        f"📈 **Sunucu İstatistikleri**\n\n"
        f"👥 Toplam kullanıcı: {count or 0}\n"
        f"⭐ Toplam XP dağıtıldı: {total_xp or 0}\n"
        f"💬 Toplam mesaj: {total_msg or 0}\n"
        f"📢 Aktif grup: {chat_count or 0}\n"
        f"♻️ Sonraki sıfırlama: {next_reset}",
        parse_mode="Markdown"
    )

async def next_reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat:
        save_chat(update.effective_chat)
    txt = get_next_reset_time()
    await update.message.reply_text(f"♻️ Sonraki haftalık sıfırlama:\n**{txt}**\nHer Cumartesi gecesi 00:00 (Pazar 00:00) Türkiye saati", parse_mode="Markdown")

async def manual_reset_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Sadece adminler yapabilsin
    user = update.effective_user
    chat = update.effective_chat
    if not chat or chat.type == "private":
        await update.message.reply_text("Bu komut sadece grupta ve adminler için.")
        return
    try:
        member = await context.bot.get_chat_member(chat.id, user.id)
        if member.status not in ["administrator", "creator"]:
            await update.message.reply_text("⛔ Sadece yöneticiler sıfırlayabilir!")
            return
    except:
        pass
    await update.message.reply_text("♻️ Manuel haftalık sıfırlama yapılıyor...")
    await perform_weekly_reset(context.application)

# Noktalı komutlar için wrapperlar
async def dot_sira_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await leaderboard_command(update, context)

async def dot_ben_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await rank_command(update, context)

# --- Ana Mesaj Handler (XP Verme) ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message or update.channel_post
    if not msg or not msg.from_user:
        return
    if msg.from_user.is_bot:
        return
    # Chat'i kaydet
    if update.effective_chat:
        save_chat(update.effective_chat)
    text_raw = msg.text or msg.caption or ""
    text_lower = text_raw.strip().lower()
    if text_lower in [".sıra", "sıra", ".sira", "sira", ".top", "top", ".ben", "ben", ".rank", "rank", ".xp", "xp"]:
        return

    user = msg.from_user
    user_id = user.id
    username = user.username or ""
    first_name = user.first_name or "Bilinmeyen"
    now = time.time()

    muted, remaining = is_muted(user_id)
    if muted:
        logger.info(f"Muted user {first_name} [{user_id}] mesaj attı ama {remaining}s kaldı, XP yok")
        return

    dq = user_message_times[user_id]
    while dq and now - dq[0] > FLOOD_WINDOW:
        dq.popleft()
    dq.append(now)

    if len(dq) >= FLOOD_LIMIT:
        muted_users[user_id] = now + FLOOD_MUTE_SECONDS
        user_message_times[user_id].clear()
        logger.warning(f"FLOOD {first_name} [{user_id}] 5sn'de {FLOOD_LIMIT} mesaj -> 60sn mute")
        try:
            chat = update.effective_chat
            if chat and chat.type in ["group", "supergroup"]:
                await context.bot.restrict_chat_member(
                    chat_id=chat.id,
                    user_id=user_id,
                    permissions=ChatPermissions(can_send_messages=False),
                    until_date=int(now + FLOOD_MUTE_SECONDS)
                )
                await msg.reply_text(
                    f"⛔ {first_name} 5 saniyede {FLOOD_LIMIT} mesaj attığın için 1 dakika susturuldun!\n"
                    f"Flood yapma knk, XP de vermiyorum."
                )
            else:
                await msg.reply_text(
                    f"⚠️ {first_name} çok hızlı yazıyorsun! 1 dakika boyunca XP alamayacaksın."
                )
        except Exception as e:
            logger.warning(f"Mute atılamadı (bot admin değil mi?): {e}")
            try:
                await msg.reply_text(f"⚠️ {first_name} flood yaptın! 1 dakika XP yok.")
            except:
                pass
        return

    is_spam = user_id in last_message_time and (now - last_message_time[user_id]) < SPAM_INTERVAL
    last_message_time[user_id] = now

    if is_spam:
        xp_gain = 1
        wc = len(text_raw.strip().split()) if text_raw else 0
        reason = f"SPAM 1sn altı ({wc} kelime ama 1 XP)"
    else:
        xp_gain, wc = calculate_xp_by_words(text_raw)
        reason = f"{wc} kelime"

    new_xp, new_level, leveled_up, old_level = add_xp(user_id, username, first_name, xp_gain)

    logger.info(f"+{xp_gain} XP ({reason}) -> {first_name} (@{username}) [{user_id}] | Toplam: {new_xp} | Lv: {new_level}")

    if leveled_up:
        try:
            await msg.reply_text(
                f"🎉 Tebrikler {first_name}! Seviye atladın!\n"
                f"⬆️ {old_level} → {new_level}\n"
                f"⭐ Toplam XP: {new_xp}"
            )
        except Exception as e:
            logger.error(f"Level mesajı gönderilemedi: {e}")

async def handle_channel_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await handle_message(update, context)

def main():
    init_db()
    start_keepalive()
    print("Bot başlatılıyor...")
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", start_command))
    app.add_handler(CommandHandler("rank", rank_command))
    app.add_handler(CommandHandler("ben", rank_command))
    app.add_handler(CommandHandler("seviye", rank_command))
    app.add_handler(CommandHandler("xp", rank_command))
    app.add_handler(CommandHandler("leaderboard", leaderboard_command))
    app.add_handler(CommandHandler("top", leaderboard_command))
    app.add_handler(CommandHandler("sıra", leaderboard_command))
    app.add_handler(CommandHandler("sira", leaderboard_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("sifirlama", next_reset_command))
    app.add_handler(CommandHandler("hafta", next_reset_command))
    app.add_handler(CommandHandler("reset_haftalik", manual_reset_command))

    app.add_handler(MessageHandler(filters.Regex(r'(?i)^\s*\.?s[ıi]ra\s*$'), dot_sira_handler))
    app.add_handler(MessageHandler(filters.Regex(r'(?i)^\s*\.?top\s*$'), dot_sira_handler))
    app.add_handler(MessageHandler(filters.Regex(r'(?i)^\s*\.?leaderboard\s*$'), dot_sira_handler))
    app.add_handler(MessageHandler(filters.Regex(r'(?i)^\s*\.?ben\s*$'), dot_ben_handler))
    app.add_handler(MessageHandler(filters.Regex(r'(?i)^\s*\.?rank\s*$'), dot_ben_handler))
    app.add_handler(MessageHandler(filters.Regex(r'(?i)^\s*\.?xp\s*$'), dot_ben_handler))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.UpdateType.CHANNEL_POST, handle_channel_post))

    print("✅ Bot aktif! Mesajlar dinleniyor...")
    print(f"XP: <3=2, 3-5=5, 6+=10 | Spam <1sn=1 XP | Flood 5sn'de 10=60sn mute")
    print(f"♻️ Haftalık sıfırlama: Her Cumartesi gecesi 00:00 (Pazar 00:00) {WEEKLY_RESET_TZ} - Sonraki: {get_next_reset_time()}")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
