import os
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, ContextTypes, filters
from dotenv import load_dotenv

load_dotenv()

# Ayrı token kullan - .env'de WELCOME_BOT_TOKEN ekle
# Yoksa BOT_TOKEN'ı kullanır (tek botla da çalışır)
BOT_TOKEN = os.getenv("WELCOME_BOT_TOKEN") or os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("WELCOME_BOT_TOKEN bulunamadı! .env'e WELCOME_BOT_TOKEN=... ekle (BotFather'dan yeni bot oluştur)")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ======= BURAYI KENDİ GRUBUNA GÖRE DÜZENLE =======
WELCOME_TITLE = "Ake Grubu"  # grubunun adı

WELCOME_TEXT = """Hoş geldin {mention} 🎉

👋 **{group}**'na hoş geldin!

📜 **Kurallar:**
1. Küfür / spam / flood yasak
2. Reklam ve +18 yasak
3. Saygılı ol, eğlen!

💬 **XP Sistemi:**
• Mesaj atarak XP kazanırsın
• `.ben` → kendi XP'n
• `.sıra` → Top 10
• Her Cumartesi 00:00 sıfırlanır

🔗 Faydalı:
• Kurallar için /kurallar
• Yardım için /help
"""

RULES_TEXT = """📜 **Grup Kuralları:**

1. Spam / flood yapma (5sn'de 10 mesaj = 1dk mute)
2. Küfür, hakaret, +18 yasak
3. Reklam / link spam yasak
4. Yöneticilere saygılı ol
5. Eğlenmene bak knk 😎

İyi sohbetler!"""

HELP_TEXT = """🤖 **Hoş Geldin Botu**

• Yeni gelenlere otomatik hoş geldin yazar
• `/kurallar` → kuralları gösterir
• `/bilgi` → grup hakkında bilgi
• `/help` → bu mesaj

Botu yönetici yapmayı unutma!
"""

# Grup bilgisi
ABOUT_TEXT = f"""ℹ️ **{WELCOME_TITLE} Hakkında:**

Aktif sohbet grubu, XP sistemi ile seviye atlarsın.
Her mesajın XP kazandırır, haftalık lider olmaya çalış!

Sorun olursa yöneticilere yaz.
"""

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
            self.wfile.write("✅ Welcome Bot aktif".encode())
        def log_message(self, format, *args):
            return
    def run():
        try:
            server = HTTPServer(("0.0.0.0", port), Handler)
            logger.info(f"Keepalive port {port}")
            server.serve_forever()
        except Exception as e:
            logger.error(f"Keepalive hata: {e}")
    threading.Thread(target=run, daemon=True).start()

# --- Komutlar ---
async def kurallar_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(RULES_TEXT, parse_mode="Markdown")

async def bilgi_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(ABOUT_TEXT, parse_mode="Markdown")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_TEXT, parse_mode="Markdown")

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"Selam! 👋 Ben Hoş Geldin Botuyum.\n\n"
        f"Yeni gelenlere otomatik mesaj atarım.\n"
        f"Beni gruba ekle ve yönetici yap, gerisini hallederim.\n\n"
        f"Komutlar:\n"
        f"/kurallar - kurallar\n"
        f"/bilgi - grup hakkında\n"
        f"/help - yardım"
    )

# --- Yeni Üye Karşılama ---
async def welcome_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.new_chat_members:
        return

    chat = update.effective_chat
    group_name = chat.title if chat and chat.title else WELCOME_TITLE

    for member in msg.new_chat_members:
        # Botun kendisi eklenirse hoş geldin atma
        if member.is_bot:
            continue

        mention = f"@{member.username}" if member.username else member.first_name
        # Mention için inline mention (tıklanabilir)
        try:
            # Kullanıcı username yoksa mention için tg://user?id=
            if member.username:
                mention_md = f"@{member.username}"
            else:
                mention_md = f"[{member.first_name}](tg://user?id={member.id})"
        except:
            mention_md = member.first_name

        text = WELCOME_TEXT.format(mention=mention_md, group=group_name, user=member.first_name)

        # Butonlar
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📜 Kurallar", callback_data="rules")],
            [InlineKeyboardButton("🏆 Sıralama (.sıra)", callback_data="sira")],
        ])

        try:
            await msg.reply_text(text, parse_mode="Markdown", reply_markup=keyboard)
            logger.info(f"Hosgeldin atildi: {member.first_name} ({member.id}) -> {group_name}")
        except Exception as e:
            logger.error(f"Hosgeldin gonderilemedi: {e}")
            try:
                await context.bot.send_message(chat_id=chat.id, text=text, parse_mode="Markdown")
            except:
                pass

    # Telegram'ın "Ali gruba katıldı" servis mesajını silmek istersen (bot admin olmalı)
    # İstersen kapatmak için alt satırı yorum yap
    try:
        await msg.delete()
    except:
        pass

async def goodbye_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.left_chat_member:
        return
    member = msg.left_chat_member
    if member.is_bot:
        return
    try:
        await msg.reply_text(f"Güle güle {member.first_name} 👋")
        await msg.delete()
    except:
        pass

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    await query.answer()
    if query.data == "rules":
        await query.message.reply_text(RULES_TEXT, parse_mode="Markdown")
    elif query.data == "sira":
        await query.message.reply_text("Sıralamayı görmek için gruba `.sıra` yaz knk! 🏆")

def main():
    start_keepalive()
    print("Welcome bot başlatılıyor...")
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("kurallar", kurallar_command))
    app.add_handler(CommandHandler("bilgi", bilgi_command))
    app.add_handler(CommandHandler("rules", kurallar_command))

    # Yeni üye ve ayrılan üye
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_new_member))
    app.add_handler(MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER, goodbye_member))

    # Butonlar
    from telegram.ext import CallbackQueryHandler
    app.add_handler(CallbackQueryHandler(button_callback))

    print("✅ Welcome Bot aktif! Yeni üyeler bekleniyor...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
