"""
Telegram bildirimleri — yalnızca AL/SAT sonrası kısa mesaj (onay butonu yok).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

import settings
from settings import PAPER_TRADING, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, USE_TESTNET
from strategies import TradingSignal

logger = logging.getLogger(__name__)


def _mode_badge() -> str:
    if PAPER_TRADING:
        return "SIM"
    if USE_TESTNET:
        return "TESTNET"
    return "CANLI"


def _coin(symbol: str) -> str:
    return (symbol or "").replace("USDT", "")


def _balance_line() -> str:
    try:
        from paper_trading import get_portfolio_status

        s = get_portfolio_status()
        return f"Bakiye ${s['equity']:,.0f} · nakit ${s['usdt']:,.0f} · K/Z ${s['pnl']:+,.0f}"
    except Exception:
        return ""


def format_trade_message(
    signal: TradingSignal,
    order: Optional[dict] = None,
) -> str:
    """Kisa AL/SAT bildirimi."""
    side = signal.signal.value
    if side == "DCA":
        side = "BUY"
    label = "AL" if side == "BUY" else "SAT"
    price = order.get("price", signal.current_price) if order else signal.current_price
    quote = (order or {}).get("quote_qty")
    bal = _balance_line()
    lines = [
        f"{_mode_badge()} | {label} {_coin(signal.symbol)}",
        f"${price:,.2f}" + (f" · ${float(quote):,.0f}" if quote else ""),
    ]
    if bal:
        lines.append(bal)
    return "\n".join(lines)


async def _send_text(text: str) -> bool:
    settings.reload_settings()
    token = settings.TELEGRAM_BOT_TOKEN
    chat_id = settings.TELEGRAM_CHAT_ID
    if not token or not chat_id:
        logger.warning("Telegram yapilandirmasi eksik — bildirim gonderilmedi.")
        return False

    try:
        from telegram.ext import Application

        app = Application.builder().token(token).build()
        async with app:
            await app.bot.send_message(chat_id=chat_id, text=text)
        return True
    except Exception as exc:
        logger.error("Telegram bildirim hatasi: %s", exc)
        return False


def send_trade_notification(
    signal: TradingSignal,
    order: Optional[dict] = None,
) -> bool:
    """AL/SAT emri sonrasi Telegram bildirimi (senkron)."""
    if signal.signal.value == "HOLD":
        return False
    text = format_trade_message(signal, order)
    try:
        return asyncio.run(_send_text(text))
    except Exception as exc:
        logger.error("Telegram bildirim hatasi: %s", exc)
        return False


def send_trade_record_notification(trade: dict) -> bool:
    """Islem kaydindan kisa Telegram bildirimi."""
    side = trade.get("side", "")
    label = "AL" if side == "BUY" else "SAT"
    symbol = trade.get("symbol", "")
    price = float(trade.get("price") or 0)
    quote = trade.get("quote_qty")
    bal = _balance_line()
    lines = [
        f"{_mode_badge()} | {label} {_coin(symbol)}",
        f"${price:,.2f}" + (f" · ${float(quote):,.0f}" if quote else ""),
    ]
    if bal:
        lines.append(bal)
    try:
        return asyncio.run(_send_text("\n".join(lines)))
    except Exception as exc:
        logger.error("Telegram islem bildirimi hatasi: %s", exc)
        return False


def send_balance_notification() -> bool:
    """Periyodik bakiye ozeti."""
    from datetime import datetime

    import settings as cfg
    from paper_trading import get_portfolio_status

    cfg.reload_settings()
    try:
        s = get_portfolio_status()
    except Exception as exc:
        logger.error("Bakiye ozeti alinamadi: %s", exc)
        return False

    ts = datetime.now().strftime("%H:%M")
    text = (
        f"{_mode_badge()} | Bakiye {ts}\n"
        f"${s['equity']:,.0f} · nakit ${s['usdt']:,.0f} · K/Z ${s['pnl']:+,.0f}"
    )
    if s.get("positions"):
        text += "\n" + " · ".join(s["positions"][:4])

    try:
        return asyncio.run(_send_text(text))
    except Exception as exc:
        logger.error("Telegram bakiye bildirimi hatasi: %s", exc)
        return False


def send_watchlist_summary(
    scans: list[dict],
    picked_symbol: Optional[str],
    action: str,
    gemini_reason: str = "",
) -> bool:
    """Kisa tarama ozeti."""
    if not scans:
        return False

    action_tr = {
        "HOLD": "BEKLE",
        "BUY": "AL",
        "SELL": "SAT",
        "DCA": "AL",
        "AUTO_OFF": "KAPALI",
        "SKIPPED_NO_PICK": "BEKLE",
        "SKIPPED_LOW_STRENGTH": "BEKLE",
    }.get(action, action)
    if action.startswith("SL_TP:"):
        action_tr = action.replace("SL_TP:", "")
    if action.startswith("ERROR"):
        action_tr = "HATA"

    coin = _coin(picked_symbol) if picked_symbol else "-"
    bal = _balance_line()
    lines = [f"{_mode_badge()} | Tarama · {action_tr}"]
    if picked_symbol and action_tr not in ("BEKLE", "KAPALI"):
        lines.append(f"Secilen: {coin}")
    if bal:
        lines.append(bal)

    try:
        return asyncio.run(_send_text("\n".join(lines)))
    except Exception as exc:
        logger.error("Telegram tarama ozeti hatasi: %s", exc)
        return False


def send_cycle_notification(
    symbol: str,
    price: float,
    signal_type: str,
    strength: float,
    action: str,
    sentiment_score: float = 0.0,
) -> bool:
    """Tek dongu ozeti — kisa."""
    label = {"BUY": "AL", "DCA": "AL", "SELL": "SAT", "HOLD": "BEKLE"}.get(signal_type, signal_type)
    bal = _balance_line()
    lines = [
        f"{_mode_badge()} | {_coin(symbol)} {label}",
        f"${price:,.2f} · {strength:.0%}",
    ]
    if bal:
        lines.append(bal)
    try:
        return asyncio.run(_send_text("\n".join(lines)))
    except Exception as exc:
        logger.error("Telegram dongu bildirimi hatasi: %s", exc)
        return False


def send_status_message(text: str) -> bool:
    """Basit durum mesaji (senkron)."""
    try:
        return asyncio.run(_send_text(text))
    except Exception as exc:
        logger.error("Telegram mesaj hatasi: %s", exc)
        return False


def discover_chat_id(token: Optional[str] = None) -> tuple[Optional[str], str]:
    """
    Bota /start yazildiktan sonra son chat ID'yi bulur.
    Returns: (chat_id, mesaj)
    """
    import requests

    settings.reload_settings()
    token = (token or settings.TELEGRAM_BOT_TOKEN or "").strip()
    if not token:
        return None, "Bot token bos."

    try:
        resp = requests.get(
            f"https://api.telegram.org/bot{token}/getUpdates",
            timeout=settings.REQUEST_TIMEOUT,
        )
        data = resp.json()
    except Exception as exc:
        return None, f"Telegram API hatasi: {exc}"

    if not data.get("ok"):
        return None, f"API hatasi: {data.get('description', 'bilinmiyor')}"

    updates = data.get("result") or []
    if not updates:
        return None, "Henuz mesaj yok. Telegram'da botunuza /start yazin, sonra tekrar deneyin."

    for upd in reversed(updates):
        msg = upd.get("message") or upd.get("channel_post")
        if msg and msg.get("chat", {}).get("id") is not None:
            cid = str(msg["chat"]["id"])
            name = msg["chat"].get("first_name") or msg["chat"].get("title") or "chat"
            return cid, f"Bulundu: {cid} ({name})"

    return None, "Chat ID bulunamadi."


def test_connection(token: Optional[str] = None, chat_id: Optional[str] = None) -> tuple[bool, str]:
    """Test mesaji gonderir."""
    settings.reload_settings()
    token = (token or settings.TELEGRAM_BOT_TOKEN or "").strip()
    chat_id = (chat_id or settings.TELEGRAM_CHAT_ID or "").strip()
    if not token or not chat_id:
        return False, "Token ve Chat ID gerekli."

    ok = asyncio.run(_send_text_with(token, chat_id, "Bobot baglantisi OK. AL/SAT bildirimleri buraya gelecek."))
    if ok:
        return True, "Test mesaji gonderildi."
    return False, "Mesaj gonderilemedi. Token veya Chat ID'yi kontrol edin."


async def _send_text_with(token: str, chat_id: str, text: str) -> bool:
    try:
        from telegram.ext import Application

        app = Application.builder().token(token).build()
        async with app:
            await app.bot.send_message(chat_id=chat_id, text=text)
        return True
    except Exception as exc:
        logger.error("Telegram hatasi: %s", exc)
        return False
