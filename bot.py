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


def format_trade_message(
    signal: TradingSignal,
    order: Optional[dict] = None,
) -> str:
    """Kısa AL/SAT bildirimi."""
    side = signal.signal.value
    if side == "DCA":
        side = "BUY"
    label = "AL" if side == "BUY" else "SAT"
    price = order.get("price", signal.current_price) if order else signal.current_price
    order_id = (order or {}).get("order_id", "-")
    reason = (signal.reason or "")[:180]

    return (
        f"{_mode_badge()} | {label} {signal.symbol}\n"
        f"Fiyat: ${price:,.2f}\n"
        f"Guc: {signal.strength:.0%}\n"
        f"Emir: {order_id}\n"
        f"{reason}"
    )


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
    """Veritabani islem kaydindan Telegram bildirimi."""
    side = trade.get("side", "")
    label = "AL" if side == "BUY" else "SAT"
    symbol = trade.get("symbol", "")
    price = float(trade.get("price") or 0)
    qty = float(trade.get("quantity") or 0)
    order_id = trade.get("order_id", "-")
    ts = (trade.get("executed_at") or trade.get("created_at") or "")[:16].replace("T", " ")

    text = (
        f"{_mode_badge()} | {label} {symbol}\n"
        f"Fiyat: ${price:,.2f}\n"
        f"Miktar: {qty:.6f}\n"
        f"Emir: {order_id}\n"
        f"Zaman: {ts}"
    )
    try:
        return asyncio.run(_send_text(text))
    except Exception as exc:
        logger.error("Telegram islem bildirimi hatasi: %s", exc)
        return False


def send_balance_notification() -> bool:
    """Saatlik (veya periyodik) bakiye ozeti Telegram."""
    from datetime import datetime

    import settings as cfg
    from paper_trading import get_portfolio_status

    cfg.reload_settings()
    try:
        s = get_portfolio_status()
    except Exception as exc:
        logger.error("Bakiye ozeti alinamadi: %s", exc)
        return False

    ts = datetime.now().strftime("%d.%m %H:%M")
    pnl_sign = "+" if s["pnl"] >= 0 else ""
    text = (
        f"{_mode_badge()} | Bakiye ({ts})\n"
        f"Toplam: ${s['equity']:,.2f}\n"
        f"Nakit USDT: ${s['usdt']:,.2f}\n"
        f"Baslangic: ${s['initial']:,.2f}\n"
        f"K/Z: {pnl_sign}${s['pnl']:,.2f} ({s['pnl_pct']:+.1f}%)"
    )
    if s.get("positions"):
        text += "\n\nPozisyonlar:\n" + "\n".join(s["positions"][:6])
    else:
        text += "\n\nAcik pozisyon yok."

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
    """Coklu coin tarama ozeti Telegram."""
    if not scans:
        return False

    def _short(sig_type: str) -> str:
        if sig_type in ("BUY", "DCA"):
            return "AL"
        if sig_type == "SELL":
            return "SAT"
        return "BEKLE"

    lines = []
    for s in scans[:8]:
        sig = s["signal"]
        base = s["symbol"].replace("USDT", "")
        lines.append(f"{base} {_short(sig.signal.value)} {sig.strength:.0%}")

    text = (
        f"{_mode_badge()} | Tarama ({len(scans)} coin)\n"
        + " · ".join(lines)
    )
    if picked_symbol:
        text += f"\nSecilen: {picked_symbol.replace('USDT', '')}"
        if gemini_reason:
            text += f"\nGemini: {gemini_reason[:100]}"
    text += f"\nAksiyon: {action}"

    # HOLD ise nedenini kısaca açıkla
    if action in ("HOLD", "SKIPPED_NO_PICK", "SKIPPED_LOW_STRENGTH"):
        best = max(scans, key=lambda s: s["signal"].strength, default=None)
        if best:
            sig = best["signal"]
            base = best["symbol"].replace("USDT", "")
            short = _short(sig.signal.value)
            if sig.signal.value == "HOLD" or sig.strength < 0.5:
                text += "\nNeden: Net AL/SAT sinyali yok (teknik kosullar saglanmadi)."
            else:
                text += (
                    f"\nEn guclu: {base} {short} {sig.strength:.0%} "
                    f"(esik altinda kalabilir)."
                )

    try:
        return asyncio.run(_send_text(text))
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
    """Her analiz dongusu icin kisa Telegram ozeti (HOLD dahil)."""
    label = signal_type
    if signal_type in ("BUY", "DCA"):
        label = "AL"
    elif signal_type == "SELL":
        label = "SAT"
    elif signal_type == "HOLD":
        label = "BEKLE"

    text = (
        f"{_mode_badge()} | Analiz\n"
        f"{symbol} ${price:,.2f}\n"
        f"Sinyal: {label} ({strength:.0%})\n"
        f"Haber: {sentiment_score:+.2f}\n"
        f"Aksiyon: {action}"
    )
    try:
        return asyncio.run(_send_text(text))
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
