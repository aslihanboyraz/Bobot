# Bobot — Staj Defteri Özeti

## Proje adı
Bobot — Otonom Kripto Paper Trading Ajanı

## Amaç
Kripto piyasasında haber akışı ve teknik göstergeleri otomatik tarayıp paper (sanal) ortamda AL/SAT kararı üreten, sonucu Telegram ile bildiren bir Python uygulaması geliştirmek.

## Yapılanlar
1. Binance public API üzerinden fiyat ve mum verisi çekimi
2. RSS haber toplama (CoinTelegraph, CoinDesk, Decrypt)
3. Gemini AI / keyword ile sentiment analizi
4. SHORT_TERM strateji (RSI + MACD + 4h trend)
5. Watchlist tarama ve eşik bazlı paper emir
6. Stop-loss / take-profit otomasyonu
7. SQLite ile portföy ve işlem geçmişi
8. Telegram bildirimleri
9. Streamlit kontrol paneli (start/stop, risk ayarları)
10. Kod sadeleştirme: gereksiz sohbet/sepet/AI katmanları kaldırılarak çekirdek döngü netleştirildi

## Kullanılan teknolojiler
Python, pandas, Binance API, Gemini API, Telegram Bot API, Streamlit, SQLite, python-dotenv

## Çalıştırma
`python main.py --loop 300` (paper trading varsayılan)

## Sonuç
Sistem paper modda uçtan uca çalışır: tarama → sinyal → sanal emir → Telegram. Canlı trading bilinçli olarak varsayılan dışı bırakılmıştır.

## Not
Gerçek para ile işlem yapılmamıştır. Proje eğitim / staj amaçlıdır.
