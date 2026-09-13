# 7/24 Deploy Rehberi

PC kapalıyken de çalışması için botu bir sunucuya atman lazım. 3 seçeneğin var:

---

### SEÇENEK 1: En Kolay + Ücretsiz -> Railway.app (Önerilen)

1. Bu klasörü GitHub'a at:
   ```powershell
   git add .
   git commit -m "xp bot"
   git push
   ```
2. https://railway.app -> Login with Github -> New Project -> Deploy from Github Repo -> klasor1'i seç
3. Variables sekmesine gir -> `BOT_TOKEN` = BotFather tokenini ekle
4. Settings -> Deploy -> Start Command: `python bot.py`
5. Volumes -> Add Volume -> Mount Path: `/app` -> `xp.db` için (yoksa her deployda XP sıfırlanır) - alternatif: Settings'de `NIXPACKS` kullanıyorsan sadece çalışır, veri Railway'de kalır.
6. Deploy -> Loglarda `Bot aktif!` görürsen tamam.

Ücret: Ayda ~5$ free kredi veriyor, bu bot için fazlasıyla yeter (aylık <1$).

### SEÇENEK 2: Tamamen Bedava + Kalıcı -> Oracle Free VPS (En sağlam)

Oracle Cloud bedava 4 OCPU 24GB RAM VPS veriyor, ömür boyu free.

1. https://cloud.oracle.com -> Free account aç
2. Instance oluştur -> Ubuntu 22.04
3. SSH ile bağlan:
   ```bash
   ssh ubuntu@IP_ADRESIN
   sudo apt update && sudo apt install python3-pip git -y
   git clone <repo-url>
   cd klasor1
   pip3 install -r requirements.txt
   nano .env  # BOT_TOKEN=... yapistir
   ```
4. 7/24 çalışması için systemd:
   ```bash
   sudo nano /etc/systemd/system/xpbot.service
   ```
   İçine yapıştır:
   ```
   [Unit]
   Description=Telegram XP Bot
   After=network.target

   [Service]
   User=ubuntu
   WorkingDirectory=/home/ubuntu/klasor1
   ExecStart=/usr/bin/python3 /home/ubuntu/klasor1/bot.py
   Restart=always
   RestartSec=5

   [Install]
   WantedBy=multi-user.target
   ```
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable xpbot
   sudo systemctl start xpbot
   sudo systemctl status xpbot  # aktif mi kontrol
   ```

PC'yi kapat, bot çalışmaya devam eder.

### SEÇENEK 3: Docker ile herhangi bir VPS (Hetzner 3.5€/ay, Contabo 5€/ay)

Sunucuda:
```bash
git clone <repo>
cd klasor1
nano .env
docker compose up -d
docker logs -f xpbot
```

---

### ÖNEMLİ: Render.com kullanma!

Render free web service 15 dakikada uyuyor, bot durur. Kullanacaksan Background Worker alman lazım (7$).

### XP Verisi Silinmesin

`xp.db` dosyası sunucuda kalır. Railway/Fly.io'da Volume eklemezsen her yeniden başlatmada sıfırlanır. VPS/Oracle'da sorun yok, dosya kalıcı.

İstersen SQLite yerine Postgres'e de geçirebilirim, o zaman hiç kaybolmaz.
