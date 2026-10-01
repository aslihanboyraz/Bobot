"""
Islem orkestrasyonu — watchlist tarama → emir → Telegram.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Optional

from analyzer import run_sentiment_analysis
from binance_engine import get_engine
import settings
from settings import DEFAULT_QUOTE_QTY, DEFAULT_SYMBOL, INVESTMENT_MODES
from db_store import get_active_mode, insert_trading_signal, insert_trade, set_active_mode
from paper_trading import get_paper_engine
from strategies import SignalType, TradingSignal, analyze_market

logger = logging.getLogger(__name__)

ACTIVE_MODE = "SHORT_TERM"
MIN_STRENGTH = 0.5


def _trade_min_strength() -> float:
    settings.reload_settings()
    return max(MIN_STRENGTH, settings.AUTO_TRADE_MIN_CONFIDENCE / 100.0)


def _usdt_balance() -> float:
    if settings.PAPER_TRADING:
        return float(get_paper_engine().portfolio.get("usdt_balance", 0) or 0)
    engine = get_engine()
    return float(engine.get_account_balance("USDT").get("free", 0) or 0)


def compute_auto_quote_qty(symbol: str) -> float:
    """Sabit quote tutari — nakit bakiyeyi asmaz."""
    settings.reload_settings()
    available = max(0.0, _usdt_balance())
    return round(min(settings.DEFAULT_QUOTE_QTY, available), 2)


def run_sl_tp_monitor(notify: bool = True) -> list[dict]:
    """Acik pozisyonlarda stop-loss / take-profit kontrolu."""
    settings.reload_settings()
    if not settings.AUTO_RISK_MANAGEMENT:
        return []

    actions: list[dict] = []
    if settings.PAPER_TRADING:
        holdings = get_paper_engine()._holdings()
    else:
        holdings = {}
        engine = get_engine()
        for asset in ("BTC", "ETH", "SOL", "AVAX", "BNB", "XRP"):
            qty = float(engine.get_account_balance(asset).get("free", 0) or 0)
            if qty > 0:
                holdings[asset] = {"quantity": qty, "avg_cost": 0.0}

    be = get_engine()
    for asset, pos in list(holdings.items()):
        qty = float(pos.get("quantity", 0) or 0)
        if qty <= 0:
            continue
        symbol = f"{asset}USDT"
        try:
            price = float(be.get_ticker_price(symbol))
        except Exception as exc:
            logger.warning("SL/TP fiyat hatasi [%s]: %s", symbol, exc)
            continue

        avg_cost = float(pos.get("avg_cost", 0) or 0)
        if avg_cost <= 0:
            avg_cost = price

        sl_pct = settings.STOP_LOSS_PCT
        tp_pct = settings.TAKE_PROFIT_PCT
        sl_price = avg_cost * (1.0 - sl_pct / 100.0)
        tp_price = avg_cost * (1.0 + tp_pct / 100.0)

        trigger: Optional[str] = None
        if price <= sl_price:
            trigger = "STOP_LOSS"
        elif price >= tp_price:
            trigger = "TAKE_PROFIT"
        if not trigger:
            continue

        try:
            executor = get_executor(symbol)
            order = executor.manual_sell()
            actions.append({
                "symbol": symbol,
                "trigger": trigger,
                "price": price,
                "sl_price": sl_price,
                "tp_price": tp_price,
                "order": order,
            })
            logger.info(
                "Otomatik satis [%s] %s — fiyat $%.2f (SL $%.2f / TP $%.2f)",
                symbol, trigger, price, sl_price, tp_price,
            )
            if notify and order:
                from bot import send_trade_record_notification

                send_trade_record_notification({
                    "side": "SELL",
                    "symbol": symbol,
                    "price": order.get("price", price),
                    "quantity": order.get("quantity"),
                    "order_id": order.get("order_id"),
                    "executed_at": datetime.now(timezone.utc).isoformat(),
                    "reason": trigger,
                })
        except Exception as exc:
            logger.error("SL/TP satis hatasi [%s]: %s", symbol, exc)

    return actions


class ExecutionEngine:
    def __init__(self, symbol: str = DEFAULT_SYMBOL) -> None:
        self.symbol = symbol
        self.engine = get_engine()
        self.paper = settings.PAPER_TRADING

    def fetch_klines_for_mode(self, mode: str = ACTIVE_MODE) -> dict[str, list]:
        intervals = INVESTMENT_MODES.get(mode, INVESTMENT_MODES["SHORT_TERM"]).get("intervals", ["1h"])
        klines = {}
        for interval in intervals:
            try:
                klines[interval] = self.engine.get_klines(self.symbol, interval, limit=200)
            except Exception as e:
                logger.error("Kline hatasi (%s %s): %s", self.symbol, interval, e)
                klines[interval] = []
        return klines

    def _current_price(self) -> float:
        return self.engine.get_ticker_price(self.symbol)

    def execute_signal(
        self,
        signal: TradingSignal,
        quote_qty: float = DEFAULT_QUOTE_QTY,
        force: bool = False,
    ) -> Optional[dict]:
        if signal.signal == SignalType.HOLD:
            logger.info("HOLD sinyali — emir gonderilmedi.")
            return None

        if not force and signal.strength < _trade_min_strength():
            logger.info("Sinyal gucu yetersiz (%.2f) — emir gonderilmedi.", signal.strength)
            return None

        mode = get_active_mode()
        price = self._current_price()

        if self.paper:
            paper = get_paper_engine()
            if signal.signal in (SignalType.BUY, SignalType.DCA):
                return paper.market_buy(self.symbol, quote_qty, price, mode)
            if signal.signal == SignalType.SELL:
                base = self.symbol.replace("USDT", "")
                qty = paper.get_balance(base)["free"]
                if qty <= 0:
                    logger.warning("Satilacak sanal %s yok.", base)
                    return None
                return paper.market_sell(self.symbol, qty, price, mode)
            return None

        order_result = None
        try:
            if signal.signal in (SignalType.BUY, SignalType.DCA):
                order_result = self.engine.place_market_buy(self.symbol, quote_qty)
            elif signal.signal == SignalType.SELL:
                base_asset = self.symbol.replace("USDT", "")
                balance = self.engine.get_account_balance(base_asset)
                if balance["free"] > 0:
                    order_result = self.engine.place_market_sell(self.symbol, balance["free"])
                else:
                    return None

            if order_result:
                insert_trade(
                    symbol=order_result["symbol"],
                    side=order_result["side"],
                    order_type=order_result["type"],
                    quantity=order_result["quantity"],
                    quote_qty=order_result["quote_qty"],
                    price=order_result["price"],
                    order_id=order_result["order_id"],
                    status=order_result["status"],
                    pnl=None,
                    mode=mode,
                    is_testnet=settings.USE_TESTNET,
                    is_paper=False,
                )
        except Exception as e:
            logger.error("Emir yurutme hatasi: %s", e)
            raise
        return order_result

    def manual_sell(self, quantity: Optional[float] = None) -> dict:
        mode = get_active_mode()
        price = self._current_price()

        if self.paper:
            return get_paper_engine().market_sell(self.symbol, quantity, price, mode)

        if quantity is None:
            base_asset = self.symbol.replace("USDT", "")
            balance = self.engine.get_account_balance(base_asset)
            quantity = balance["free"]
        if quantity <= 0:
            raise ValueError(f"Satilacak miktar yok: {quantity}")

        order = self.engine.place_market_sell(self.symbol, quantity)
        insert_trade(
            symbol=order["symbol"], side=order["side"], order_type=order["type"],
            quantity=order["quantity"], quote_qty=order["quote_qty"], price=order["price"],
            order_id=order["order_id"], status=order["status"], pnl=None,
            mode=mode, is_testnet=settings.USE_TESTNET, is_paper=False,
        )
        return order


def get_executor(symbol: str = DEFAULT_SYMBOL) -> ExecutionEngine:
    settings.reload_settings()
    return ExecutionEngine(symbol)


def scan_symbol(symbol: str, mode: str = ACTIVE_MODE) -> dict:
    """Tek coin tarama — emir yok."""
    symbol = symbol.upper()
    executor = get_executor(symbol)
    sentiment = run_sentiment_analysis(symbol=symbol, save_to_db=True)
    sentiment_score = float(sentiment.get("average_score", 0.0) or 0.0)
    klines = executor.fetch_klines_for_mode(mode)
    signal = analyze_market(symbol, mode, klines, sentiment_score)

    insert_trading_signal(
        symbol=signal.symbol,
        mode=signal.mode,
        signal_type=signal.signal.value,
        strength=signal.strength,
        indicators=signal.indicators,
        sentiment_score=sentiment_score,
        reason=signal.reason,
    )
    logger.info(
        "Tarama [%s] sinyal=%s guc=%.0f%% sentiment=%+.3f model=%s",
        symbol,
        signal.signal.value,
        signal.strength * 100,
        sentiment_score,
        sentiment.get("model", "?"),
    )
    return {
        "symbol": symbol,
        "signal": signal,
        "sentiment": sentiment,
        "sentiment_score": sentiment_score,
    }


def run_watchlist_cycle(
    quote_qty: Optional[float] = None,
    notify: bool = True,
    auto_execute: Optional[bool] = None,
) -> dict:
    """Watchlist tarar; Gemini en iyi firsati secer; emir verir."""
    settings.reload_settings()
    if auto_execute is None:
        auto_execute = settings.AUTO_TRADE_ENABLED

    watchlist = settings.get_watchlist()
    mode = ACTIVE_MODE
    min_strength = _trade_min_strength()

    try:
        set_active_mode(mode)
    except Exception:
        pass

    sl_tp_actions = run_sl_tp_monitor(notify=notify)

    scans: list[dict] = []
    for sym in watchlist:
        try:
            scans.append(scan_symbol(sym, mode=mode))
        except Exception as exc:
            logger.error("Tarama hatasi [%s]: %s", sym, exc)

    candidates: list[dict] = []
    for s in scans:
        sig = s["signal"]
        tradable = sig.signal in (SignalType.BUY, SignalType.SELL, SignalType.DCA)
        if tradable and sig.strength >= min_strength:
            candidates.append({
                "symbol": s["symbol"],
                "signal": sig.signal.value,
                "strength": sig.strength,
                "min_strength": min_strength,
                "price": sig.current_price,
                "sentiment_score": s["sentiment_score"],
                "sentiment_label": s["sentiment"].get("overall_label", "NEUTRAL"),
                "reason": sig.reason,
                "gemini_summary": s["sentiment"].get("summary_tr", ""),
            })

    picked_symbol: Optional[str] = None
    gemini_reason = ""
    if candidates:
        from gemini_client import pick_best_opportunity

        pick = pick_best_opportunity(candidates)
        if pick:
            picked_symbol = pick["symbol"]
            gemini_reason = pick.get("reason_tr", "")

    action_taken = "HOLD"
    order_result = None
    notified = False

    if picked_symbol and auto_execute:
        picked_scan = next((s for s in scans if s["symbol"] == picked_symbol), None)
        if picked_scan:
            try:
                executor = get_executor(picked_symbol)
                qty = quote_qty
                if qty is None:
                    sig_type = picked_scan["signal"].signal
                    if sig_type in (SignalType.BUY, SignalType.DCA):
                        qty = compute_auto_quote_qty(picked_symbol)
                    else:
                        qty = settings.DEFAULT_QUOTE_QTY
                order_result = executor.execute_signal(
                    picked_scan["signal"], quote_qty=qty, force=False,
                )
                if order_result:
                    action_taken = picked_scan["signal"].signal.value
                    if notify:
                        from bot import send_trade_notification, send_trade_record_notification

                        notified = send_trade_notification(
                            picked_scan["signal"], order_result,
                        )
                        if not notified:
                            send_trade_record_notification({
                                "side": order_result.get("side", action_taken),
                                "symbol": picked_symbol,
                                "price": order_result.get("price"),
                                "quantity": order_result.get("quantity"),
                                "order_id": order_result.get("order_id"),
                                "executed_at": datetime.now(timezone.utc).isoformat(),
                            })
            except Exception as exc:
                logger.error("Emir hatasi [%s]: %s", picked_symbol, exc)
                action_taken = f"ERROR: {exc}"
    elif candidates and not auto_execute:
        action_taken = "AUTO_OFF"
    elif candidates:
        action_taken = "SKIPPED_NO_PICK"

    if sl_tp_actions and action_taken == "HOLD":
        action_taken = f"SL_TP:{sl_tp_actions[0]['trigger']}"

    if notify and settings.TELEGRAM_NOTIFY_CYCLES and not notified:
        from bot import send_watchlist_summary

        notified = send_watchlist_summary(
            scans, picked_symbol, action_taken, gemini_reason,
        )

    logger.info(
        "Watchlist tarama (%d coin) · aday=%d · secilen=%s · aksiyon=%s · sl_tp=%d",
        len(scans), len(candidates), picked_symbol or "-", action_taken, len(sl_tp_actions),
    )

    return {
        "watchlist": watchlist,
        "scans": scans,
        "candidates": candidates,
        "picked_symbol": picked_symbol,
        "gemini_reason": gemini_reason,
        "action_taken": action_taken,
        "order_result": order_result,
        "sl_tp_actions": sl_tp_actions,
        "auto_execute": auto_execute,
        "notified": notified,
        "timestamp": time.time(),
    }
