"""
Simülasyon motoru — canlı fiyatlarla sanal emir (gerçek para yok).
"""

from __future__ import annotations

import logging
import uuid
from typing import Optional

from settings import PAPER_INITIAL_BALANCE
from db_store import get_paper_portfolio, insert_trade, update_paper_portfolio

logger = logging.getLogger(__name__)


class PaperTradingEngine:
    """10.000$ sanal bakiye ile işlem simülasyonu."""

    def __init__(self) -> None:
        self.portfolio = get_paper_portfolio()

    def _holdings(self) -> dict[str, dict]:
        return self.portfolio.get("holdings", {})

    def market_buy(self, symbol: str, quote_qty: float, price: float, mode: str) -> dict:
        usdt = self.portfolio["usdt_balance"]
        if quote_qty > usdt:
            raise ValueError(f"Yetersiz sanal USDT: ${usdt:,.2f} (gerekli: ${quote_qty:,.2f})")

        base = symbol.replace("USDT", "")
        quantity = quote_qty / price

        holdings = self._holdings()
        pos = holdings.get(base, {"quantity": 0.0, "avg_cost": 0.0})
        old_qty = pos["quantity"]
        old_avg = pos["avg_cost"]
        new_qty = old_qty + quantity
        new_avg = ((old_qty * old_avg) + quote_qty) / new_qty if new_qty > 0 else price

        holdings[base] = {"quantity": new_qty, "avg_cost": new_avg}
        new_usdt = usdt - quote_qty

        update_paper_portfolio(new_usdt, holdings)
        self.portfolio = get_paper_portfolio()

        order_id = f"SIM-{uuid.uuid4().hex[:8].upper()}"
        result = {
            "order_id": order_id,
            "symbol": symbol,
            "side": "BUY",
            "type": "MARKET",
            "status": "FILLED",
            "quantity": quantity,
            "quote_qty": quote_qty,
            "price": price,
        }

        insert_trade(
            symbol=symbol,
            side="BUY",
            order_type="MARKET",
            quantity=quantity,
            quote_qty=quote_qty,
            price=price,
            order_id=order_id,
            status="FILLED",
            pnl=None,
            mode=mode,
            is_testnet=False,
            is_paper=True,
        )
        logger.info("SIM BUY %s — %.4f @ $%.2f ($%.2f)", symbol, quantity, price, quote_qty)
        return result

    def market_sell(
        self,
        symbol: str,
        quantity: Optional[float],
        price: float,
        mode: str,
    ) -> dict:
        base = symbol.replace("USDT", "")
        holdings = self._holdings()
        pos = holdings.get(base, {"quantity": 0.0, "avg_cost": 0.0})
        available = pos["quantity"]

        if quantity is None:
            quantity = available
        if quantity <= 0:
            raise ValueError(f"Satılacak sanal {base} yok.")
        if quantity > available:
            raise ValueError(f"Yetersiz {base}: {available:.8f} (istenen: {quantity:.8f})")

        quote_qty = quantity * price
        avg_cost = pos["avg_cost"]
        pnl = (price - avg_cost) * quantity

        new_qty = available - quantity
        if new_qty <= 1e-10:
            holdings.pop(base, None)
        else:
            holdings[base] = {"quantity": new_qty, "avg_cost": avg_cost}

        new_usdt = self.portfolio["usdt_balance"] + quote_qty
        update_paper_portfolio(new_usdt, holdings)
        self.portfolio = get_paper_portfolio()

        order_id = f"SIM-{uuid.uuid4().hex[:8].upper()}"
        result = {
            "order_id": order_id,
            "symbol": symbol,
            "side": "SELL",
            "type": "MARKET",
            "status": "FILLED",
            "quantity": quantity,
            "quote_qty": quote_qty,
            "price": price,
            "pnl": pnl,
        }

        insert_trade(
            symbol=symbol,
            side="SELL",
            order_type="MARKET",
            quantity=quantity,
            quote_qty=quote_qty,
            price=price,
            order_id=order_id,
            status="FILLED",
            pnl=pnl,
            mode=mode,
            is_testnet=False,
            is_paper=True,
        )
        logger.info("SIM SELL %s — %.4f @ $%.2f | PnL: $%+.2f", symbol, quantity, price, pnl)
        return result

    def get_balance(self, asset: str) -> dict:
        if asset == "USDT":
            free = self.portfolio["usdt_balance"]
            return {"asset": "USDT", "free": free, "locked": 0.0, "total": free}

        pos = self._holdings().get(asset, {"quantity": 0.0, "avg_cost": 0.0})
        qty = pos["quantity"]
        return {"asset": asset, "free": qty, "locked": 0.0, "total": qty}

    def portfolio_value(self, prices: dict[str, float]) -> dict:
        """Toplam portföy değeri ve PnL."""
        usdt = self.portfolio["usdt_balance"]
        crypto_value = 0.0
        for asset, pos in self._holdings().items():
            sym = f"{asset}USDT"
            p = prices.get(sym, prices.get(asset, 0.0))
            crypto_value += pos["quantity"] * p

        total = usdt + crypto_value
        initial = self.portfolio["initial_balance"]
        return {
            "usdt": usdt,
            "crypto_value": crypto_value,
            "total": total,
            "initial": initial,
            "pnl": total - initial,
            "pnl_pct": ((total - initial) / initial * 100) if initial > 0 else 0.0,
            "holdings": self._holdings(),
        }


_paper_engine: Optional[PaperTradingEngine] = None


def get_paper_engine() -> PaperTradingEngine:
    global _paper_engine
    if _paper_engine is None:
        _paper_engine = PaperTradingEngine()
    else:
        _paper_engine.portfolio = get_paper_portfolio()
    return _paper_engine


def get_portfolio_status() -> dict:
    """Simülasyon portföy özeti — canlı fiyatlarla equity."""
    import settings
    from binance_engine import get_engine

    settings.reload_settings()
    engine = get_paper_engine()
    holdings = engine._holdings()
    prices: dict[str, float] = {}
    be = get_engine()

    for asset in holdings:
        sym = f"{asset}USDT"
        try:
            prices[sym] = float(be.get_ticker_price(sym))
        except Exception:
            prices[sym] = float(holdings[asset].get("avg_cost", 0) or 0)

    val = engine.portfolio_value(prices)
    positions: list[str] = []
    for asset, pos in holdings.items():
        sym = f"{asset}USDT"
        p = prices.get(sym, 0.0)
        qty = float(pos.get("quantity", 0) or 0)
        if qty > 0:
            positions.append(f"{asset}: {qty:.6f} (${qty * p:,.2f})")

    return {
        "mode": "SIM" if settings.PAPER_TRADING else "LIVE",
        "usdt": val["usdt"],
        "equity": val["total"],
        "initial": val["initial"],
        "pnl": val["pnl"],
        "pnl_pct": val["pnl_pct"],
        "positions": positions,
    }
