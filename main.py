"""
Bobot — otonom kripto ajanı.

    python main.py              # Tek döngü: analiz → emir → Telegram
    python main.py --loop 300   # Her 300 sn (önerilen)
    python main.py --dashboard  # Küçük durum ekranı
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import settings
from settings import DEFAULT_SYMBOL, PAPER_TRADING, USE_TESTNET
from db_store import init_db
from execution import run_watchlist_cycle

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("bobot")


def _mode_label() -> str:
    if PAPER_TRADING:
        return "SIM"
    if USE_TESTNET:
        return "TESTNET"
    return "CANLI"


def run_once(symbol: str = DEFAULT_SYMBOL) -> dict:
    """Tek otonom dongu — tum watchlist taranir."""
    init_db()
    settings.reload_settings()

    from binance_engine import get_engine

    engine = get_engine()
    if not engine.ping():
        logger.error("Binance API'ye baglanilamadi — cikiyor.")
        sys.exit(1)

    wl = settings.get_watchlist()
    logger.info("Bobot [%s] tarama: %s", _mode_label(), ", ".join(wl))

    result = run_watchlist_cycle(notify=True)
    logger.info(
        "Sonuc: %d coin · secilen=%s · aksiyon=%s · telegram=%s",
        len(result.get("scans", [])),
        result.get("picked_symbol") or "-",
        result["action_taken"],
        result["notified"],
    )
    return result


def run_loop(interval: int, symbol: str = DEFAULT_SYMBOL) -> None:
    """Belirli aralıklarla otonom döngü."""
    logger.info("Dongu modu — her %d sn (Ctrl+C ile durdur).", interval)
    settings.reload_settings()
    wl = settings.get_watchlist()
    try:
        from bot import send_status_message

        if settings.telegram_configured():
            send_status_message(
                f"Bobot basladi [{_mode_label()}]\n"
                f"Tarama: {', '.join(w.replace('USDT','') for w in wl)}\n"
                f"Dongu {interval} sn · Gemini destekli"
            )
    except Exception:
        pass

    last_balance_at = 0.0

    while True:
        try:
            run_once(symbol)
        except KeyboardInterrupt:
            logger.info("Durduruldu.")
            break
        except Exception as exc:
            logger.error("Dongu hatasi: %s", exc)

        settings.reload_settings()
        if settings.telegram_configured() and settings.TELEGRAM_BALANCE_NOTIFY:
            now = time.time()
            interval_bal = max(300, settings.TELEGRAM_BALANCE_INTERVAL)
            if last_balance_at == 0 or (now - last_balance_at) >= interval_bal:
                try:
                    from bot import send_balance_notification

                    if send_balance_notification():
                        last_balance_at = now
                        logger.info("Telegram bakiye ozeti gonderildi.")
                except Exception as exc:
                    logger.warning("Bakiye bildirimi hatasi: %s", exc)

        logger.info("Sonraki analiz %d sn sonra...", interval)
        time.sleep(interval)


def run_dashboard() -> None:
    """Küçük Streamlit durum ekranı."""
    import subprocess

    app_path = Path(__file__).resolve().parent / "app.py"
    logger.info("Durum ekrani baslatiliyor...")
    subprocess.run([sys.executable, "-m", "streamlit", "run", str(app_path)], check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Bobot — otonom AL/SAT ajanı")
    parser.add_argument("--symbol", default=DEFAULT_SYMBOL, help="Trading sembolu")
    parser.add_argument(
        "--loop",
        type=int,
        default=0,
        metavar="SEC",
        help="Dongu araligi (sn). Ornek: --loop 300",
    )
    parser.add_argument("--dashboard", action="store_true", help="Kucuk durum ekrani")
    parser.add_argument("--telegram-test", action="store_true", help="Telegram test mesaji gonder")
    parser.add_argument("--gemini-test", action="store_true", help="Gemini API testi")
    parser.add_argument("--binance-test", action="store_true", help="Binance baglanti testi")
    args = parser.parse_args()

    if args.binance_test:
        from binance_engine import check_market_connection

        result = check_market_connection(args.symbol)
        print(result["message"])
        sys.exit(0 if result["ok"] else 1)
    if args.telegram_test:
        from bot import test_connection

        ok, msg = test_connection()
        print(msg)
        sys.exit(0 if ok else 1)
    if args.gemini_test:
        from gemini_client import test_gemini_connection

        ok, msg = test_gemini_connection()
        print(msg)
        sys.exit(0 if ok else 1)
    if args.dashboard:
        run_dashboard()
    elif args.loop > 0:
        run_loop(args.loop, args.symbol)
    else:
        run_once(args.symbol)


if __name__ == "__main__":
    main()
