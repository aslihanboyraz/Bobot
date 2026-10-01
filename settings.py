"""
Merkezi yapılandırma — `.env` okur / yazar.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent

INVESTMENT_MODES = {
    "SHORT_TERM": {
        "label_tr": "Kisa/Orta Vade",
        "intervals": ["1h", "4h"],
        "stop_loss_pct": 5.0,
        "take_profit_pct": 15.0,
    },
}

NEWS_RSS_FEEDS = [
    "https://cointelegraph.com/rss",
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "https://decrypt.co/feed",
]

MAX_RETRIES = 3
RETRY_BACKOFF_SEC = 2.0
REQUEST_TIMEOUT = 30


def reload_settings() -> None:
    load_dotenv(BASE_DIR / ".env", override=True)
    _apply_settings()


def _env_bool(name: str, default: str = "False") -> bool:
    return os.getenv(name, default).lower() in ("true", "1", "yes")


def _apply_settings() -> None:
    global PAPER_TRADING, PAPER_INITIAL_BALANCE, USE_TESTNET
    global BINANCE_API_KEY, BINANCE_API_SECRET, BINANCE_PRIVATE_KEY, BINANCE_BASE_URL
    global TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
    global DEFAULT_SYMBOL, DEFAULT_QUOTE_QTY, DEFAULT_MODE, WATCHLIST
    global HTTP_PROXY, HTTPS_PROXY
    global GEMINI_API_KEY, GEMINI_MODEL, AUTO_TRADE_MIN_CONFIDENCE
    global STOP_LOSS_PCT, TAKE_PROFIT_PCT, LOOP_INTERVAL
    global TELEGRAM_NOTIFY_CYCLES, TELEGRAM_BALANCE_NOTIFY, TELEGRAM_BALANCE_INTERVAL
    global AUTO_TRADE_ENABLED, AUTO_RISK_MANAGEMENT

    PAPER_TRADING = _env_bool("PAPER_TRADING", "True")
    PAPER_INITIAL_BALANCE = float(os.getenv("PAPER_INITIAL_BALANCE", "10000"))

    USE_TESTNET = _env_bool("USE_TESTNET")
    if PAPER_TRADING:
        USE_TESTNET = False

    if USE_TESTNET:
        BINANCE_API_KEY = os.getenv("BINANCE_TESTNET_API_KEY", "")
        BINANCE_API_SECRET = os.getenv("BINANCE_TESTNET_API_SECRET", "")
        BINANCE_PRIVATE_KEY = os.getenv("BINANCE_TESTNET_PRIVATE_KEY", "")
        BINANCE_BASE_URL = "https://testnet.binance.vision/api"
    else:
        BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
        BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "")
        BINANCE_PRIVATE_KEY = os.getenv("BINANCE_PRIVATE_KEY", "")
        BINANCE_BASE_URL = "https://api.binance.com/api"

    if not PAPER_TRADING and not BINANCE_PRIVATE_KEY and os.getenv("BINANCE_PRIVATE_KEY_PATH"):
        pk_path = BASE_DIR / os.getenv("BINANCE_PRIVATE_KEY_PATH", "")
        if pk_path.exists():
            BINANCE_PRIVATE_KEY = str(pk_path)

    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

    DEFAULT_SYMBOL = os.getenv("DEFAULT_SYMBOL", "BTCUSDT")
    DEFAULT_QUOTE_QTY = float(os.getenv("DEFAULT_QUOTE_QTY", "50"))
    DEFAULT_MODE = "SHORT_TERM"

    watchlist_raw = os.getenv("WATCHLIST", "").strip()
    if watchlist_raw:
        WATCHLIST = [s.strip().upper() for s in watchlist_raw.split(",") if s.strip()]
    else:
        WATCHLIST = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "AVAXUSDT", "BNBUSDT", "XRPUSDT"]

    HTTP_PROXY = os.getenv("HTTP_PROXY", "").strip()
    HTTPS_PROXY = os.getenv("HTTPS_PROXY", "").strip()

    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
    GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-latest")
    AUTO_TRADE_MIN_CONFIDENCE = float(os.getenv("AUTO_TRADE_MIN_CONFIDENCE", "65"))
    STOP_LOSS_PCT = float(os.getenv("STOP_LOSS_PCT", "5"))
    TAKE_PROFIT_PCT = float(os.getenv("TAKE_PROFIT_PCT", "15"))
    LOOP_INTERVAL = int(os.getenv("LOOP_INTERVAL", "300"))
    TELEGRAM_NOTIFY_CYCLES = _env_bool("TELEGRAM_NOTIFY_CYCLES", "True")
    TELEGRAM_BALANCE_NOTIFY = _env_bool("TELEGRAM_BALANCE_NOTIFY", "True")
    TELEGRAM_BALANCE_INTERVAL = int(os.getenv("TELEGRAM_BALANCE_INTERVAL", "3600"))

    AUTO_TRADE_ENABLED = _env_bool("AUTO_TRADE_ENABLED", "True")
    AUTO_RISK_MANAGEMENT = _env_bool("AUTO_RISK_MANAGEMENT", "True")

    INVESTMENT_MODES["SHORT_TERM"]["stop_loss_pct"] = STOP_LOSS_PCT
    INVESTMENT_MODES["SHORT_TERM"]["take_profit_pct"] = TAKE_PROFIT_PCT


_apply_settings()


def save_env_updates(updates: dict[str, str]) -> None:
    """`.env` dosyasındaki anahtarları günceller (yoksa ekler)."""
    env_path = BASE_DIR / ".env"
    lines: list[str] = []
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()

    done: set[str] = set()
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in line:
            key = line.split("=", 1)[0].strip()
            if key in updates:
                out.append(f"{key}={updates[key]}")
                done.add(key)
                continue
        out.append(line)

    for key, val in updates.items():
        if key not in done:
            out.append(f"{key}={val}")

    env_path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
    reload_settings()


def get_watchlist() -> list[str]:
    reload_settings()
    return list(WATCHLIST)


def get_risk_settings() -> dict:
    reload_settings()
    return {
        "symbol": DEFAULT_SYMBOL,
        "watchlist": get_watchlist(),
        "quote_qty": DEFAULT_QUOTE_QTY,
        "min_confidence": AUTO_TRADE_MIN_CONFIDENCE,
        "stop_loss_pct": STOP_LOSS_PCT,
        "take_profit_pct": TAKE_PROFIT_PCT,
        "loop_interval": LOOP_INTERVAL,
        "auto_trade_enabled": AUTO_TRADE_ENABLED,
        "auto_risk_management": AUTO_RISK_MANAGEMENT,
    }


def save_risk_settings(
    *,
    symbol: str,
    watchlist: list[str],
    quote_qty: float,
    min_confidence: float,
    stop_loss_pct: float,
    take_profit_pct: float,
    loop_interval: int,
    auto_trade_enabled: bool = True,
    auto_risk_management: bool = True,
) -> None:
    wl = [s.upper() for s in watchlist if s]
    if symbol.upper() not in wl:
        wl.insert(0, symbol.upper())
    save_env_updates({
        "DEFAULT_SYMBOL": symbol.upper(),
        "WATCHLIST": ",".join(wl),
        "DEFAULT_QUOTE_QTY": str(quote_qty),
        "AUTO_TRADE_MIN_CONFIDENCE": str(int(min_confidence)),
        "STOP_LOSS_PCT": str(stop_loss_pct),
        "TAKE_PROFIT_PCT": str(take_profit_pct),
        "LOOP_INTERVAL": str(int(loop_interval)),
        "AUTO_TRADE_ENABLED": "True" if auto_trade_enabled else "False",
        "AUTO_RISK_MANAGEMENT": "True" if auto_risk_management else "False",
    })


def save_telegram_settings(token: str, chat_id: str) -> None:
    save_env_updates({
        "TELEGRAM_BOT_TOKEN": token.strip(),
        "TELEGRAM_CHAT_ID": str(chat_id).strip(),
    })


def save_gemini_settings(api_key: str, model: str = "") -> None:
    updates = {"GEMINI_API_KEY": api_key.strip()}
    if model.strip():
        updates["GEMINI_MODEL"] = model.strip()
    save_env_updates(updates)


def telegram_configured() -> bool:
    reload_settings()
    return bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)
