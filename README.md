# Bobot

Simülasyon modunda çalışan otonom kripto analiz ajanı.

Haberleri RSS üzerinden çeker, Gemini (veya keyword fallback) ile sentiment üretir, SHORT_TERM teknik analiz (RSI/MACD) uygular, eşik geçince sanal AL/SAT verir ve Telegram’a bildirim yollar.

> **Uyarı:** Varsayılan mod simülasyondur (`PAPER_TRADING=True`). Gerçek para ile canlı işlem için ek doğrulama gerekir.

## Özellikler

- Watchlist tarama (BTC, ETH, SOL, AVAX, BNB, XRP)
- Haber + teknik sinyal birleşimi
- Simülasyon portföyü (SQLite)
- Stop-loss / take-profit otomatiği
- Telegram bildirimleri
- Streamlit kontrol paneli (start/stop, risk ayarları)

## Teknolojiler

| Katman | Teknoloji |
|--------|-----------|
| Dil | Python 3 |
| Borsa verisi | Binance public API (`python-binance` / REST) |
| Analiz | pandas, RSI/MACD |
| Haber | RSS (`feedparser`) |
| AI | Google Gemini REST API |
| Bildirim | Telegram Bot API |
| UI | Streamlit |
| Depolama | SQLite |
| Config | `.env` (`python-dotenv`) |

## Mimari (kısa)

```
main.py
  └─ execution.run_watchlist_cycle()
       ├─ news_engine + analyzer (+ gemini_client)
       ├─ strategies (SHORT_TERM)
       ├─ paper_trading + db_store   # simülasyon portföy
       ├─ binance_engine (fiyat/kline)
       └─ bot (Telegram)
```

Panel: `app.py` + `bot_runner.py` → arka planda `main.py --loop`.

## Kurulum

```bash
cd Bobot
python -m venv venv
venv\Scripts\activate          # Windows
pip install -r requirements.txt
copy .env.example .env
```

`.env` içinde doldurun:

- `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` (bildirim)
- `GEMINI_API_KEY` (opsiyonel; yoksa keyword fallback)

`PAPER_TRADING=True` kalsın (simülasyon açık).

## Kullanım

```bash
python main.py --loop 300      # her 5 dk (önerilen)
python main.py                 # tek tur
python main.py --dashboard     # kontrol paneli
python main.py --binance-test
python main.py --telegram-test
python main.py --gemini-test
```

veya `start.bat`.

## Proje yapısı

```
Bobot/
├── main.py              # CLI giriş
├── execution.py         # Tarama + emir + SL/TP
├── strategies.py        # SHORT_TERM strateji
├── indicators.py        # RSI / MACD / SMA
├── analyzer.py          # Sentiment orkestrasyonu
├── news_engine.py       # RSS haber
├── gemini_client.py     # Gemini API
├── paper_trading.py     # Simülasyon portföy
├── db_store.py          # SQLite
├── binance_engine.py    # Piyasa verisi / emir
├── bot.py               # Telegram
├── bot_runner.py        # Process start/stop
├── app.py               # Streamlit panel
├── settings.py          # .env ayarları
├── requirements.txt
├── .env.example
└── start.bat
```

## Staj / rapor notları

**Problem:** Kripto piyasasında haber ve teknik göstergeleri manuel takip etmek yavaş ve tutarsız.

**Çözüm:** Bobot periyodik döngüde haber + teknik analizi birleştirir, simülasyon ortamında karar verir, sonucu Telegram’a iletir.

**Kazanımlar:** API entegrasyonu, RSS/sentiment, teknik indikatörler, SQLite ile state yönetimi, Streamlit paneli, ortam değişkenleri ile güvenli config.

**Güvenlik:** `.env`, `keys/`, log ve veritabanı Git’e eklenmez. Canlı trading kapalı tutulmuştur.

## Lisans / kullanım

Eğitim ve simülasyon amaçlıdır. Yatırım tavsiyesi değildir.
