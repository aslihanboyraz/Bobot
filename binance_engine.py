"""
Binance Spot Execution Engine — python-binance ile Testnet / Canlı API desteği.
Paper Trading modunda piyasa verisi API anahtarı olmadan çekilir.
"""

from __future__ import annotations

import logging
import os
import time
from decimal import Decimal, ROUND_DOWN
from typing import Any, Optional, Union

import requests
from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceRequestException

import settings
from settings import MAX_RETRIES, REQUEST_TIMEOUT, RETRY_BACKOFF_SEC

logger = logging.getLogger(__name__)

MarketClient = Union[Client, "PublicMarketClient"]

# Binance public API yedek sunucuları (SSL/proxy sorunlarında sırayla dener)
PUBLIC_API_BASES = (
    "https://api.binance.com/api/v3",
    "https://api1.binance.com/api/v3",
    "https://api2.binance.com/api/v3",
    "https://api3.binance.com/api/v3",
)

_PROXY_ENV_KEYS = (
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
    "http_proxy", "https_proxy", "all_proxy",
)


def _market_session() -> requests.Session:
    """HTTP oturumu — .env'de proxy varsa VPN üzerinden, yoksa doğrudan bağlantı."""
    settings.reload_settings()
    session = requests.Session()
    proxy = settings.HTTPS_PROXY or settings.HTTP_PROXY
    if proxy:
        session.proxies = {"http": proxy, "https": proxy}
        session.trust_env = False
        logger.info("Market client — VPN/proxy aktif: %s", proxy)
    else:
        session.trust_env = False
        session.proxies = {"http": None, "https": None}
    return session


class PublicMarketClient:
    """Canlı Binance public endpoint — API key gerektirmez (Paper Trading verisi)."""

    def __init__(self) -> None:
        self._session = _market_session()
        self._bases = list(PUBLIC_API_BASES)
        logger.info("Public market client — %s", self._bases[0])

    def _get(self, path: str, params: Optional[dict] = None) -> Any:
        path = path.lstrip("/")
        last_exc: Optional[Exception] = None

        # Ortam değişkenlerindeki proxy ayarlarını geçici olarak temizle
        saved_env = {k: os.environ.pop(k) for k in _PROXY_ENV_KEYS if k in os.environ}
        proxy = settings.HTTPS_PROXY or settings.HTTP_PROXY
        req_proxies = {"http": proxy, "https": proxy} if proxy else {"http": None, "https": None}
        try:
            for base in self._bases:
                url = f"{base}/{path}"
                try:
                    resp = self._session.get(
                        url,
                        params=params or {},
                        timeout=REQUEST_TIMEOUT,
                        proxies=req_proxies,
                    )
                    resp.raise_for_status()
                    return resp.json()
                except (requests.RequestException, OSError) as exc:
                    last_exc = exc
                    logger.warning("Binance endpoint başarısız (%s): %s", base, exc)
        finally:
            os.environ.update(saved_env)

        raise last_exc  # type: ignore[misc]

    def ping(self) -> dict:
        return self._get("ping")

    def get_symbol_ticker(self, symbol: str) -> dict:
        return self._get("ticker/price", {"symbol": symbol})

    def get_ticker(self, symbol: str) -> dict:
        return self._get("ticker/24hr", {"symbol": symbol})

    def get_klines(self, symbol: str, interval: str, limit: int = 100) -> list:
        return self._get(
            "klines",
            {"symbol": symbol, "interval": interval, "limit": limit},
        )


class BinanceEngine:
    """Binance Spot API sarmalayıcı — Testnet ve Canlı mod desteği."""

    def __init__(self) -> None:
        settings.reload_settings()
        self._client: Optional[Client] = None
        self._public_client: Optional[PublicMarketClient] = None
        self._symbol_info_cache: dict[str, dict] = {}

    @property
    def use_testnet(self) -> bool:
        settings.reload_settings()
        return settings.USE_TESTNET

    @property
    def paper_trading(self) -> bool:
        settings.reload_settings()
        return settings.PAPER_TRADING

    def _public_client_instance(self) -> PublicMarketClient:
        """Fiyat/mum verisi — her modda API key gerektirmez."""
        if self._public_client is None:
            self._public_client = PublicMarketClient()
        return self._public_client

    @property
    def client(self) -> MarketClient:
        if self.paper_trading:
            return self._public_client_instance()
        if self._client is None:
            self._client = self._create_authenticated_client()
        return self._client

    def _create_authenticated_client(self) -> Client:
        if settings.PAPER_TRADING:
            raise RuntimeError("Paper modda authenticated client gerekmez.")

        api_key = settings.BINANCE_API_KEY
        api_secret = settings.BINANCE_API_SECRET
        private_key = settings.BINANCE_PRIVATE_KEY
        use_testnet = self.use_testnet
        base_url = settings.BINANCE_BASE_URL
        label = "TESTNET" if use_testnet else "CANLI"

        has_secret = bool(api_secret)
        has_private_key = bool(private_key)

        if not api_key or (not has_secret and not has_private_key):
            mode = "Testnet" if use_testnet else "Canlı"
            raise ValueError(
                f"Binance {mode} API anahtarları eksik. "
                f".env dosyasını kontrol edin."
            )

        if has_private_key and api_key:
            client = Client(api_key, private_key=private_key, testnet=use_testnet, ping=False)
        elif api_key and has_secret:
            client = Client(api_key, api_secret, testnet=use_testnet, ping=False)
        else:
            client = Client(testnet=use_testnet, ping=False)

        if use_testnet:
            client.API_URL = base_url

        logger.info("Binance client başlatıldı — Mod: %s | URL: %s", label, client.API_URL)
        return client

    def _retry(self, func, *args, **kwargs) -> Any:
        """Rate limit ve ağ hatalarında exponential backoff ile yeniden dene."""
        last_exc: Optional[Exception] = None
        for attempt in range(MAX_RETRIES):
            try:
                return func(*args, **kwargs)
            except BinanceAPIException as e:
                last_exc = e
                if e.code in (-1003, -1015):  # Rate limit
                    wait = RETRY_BACKOFF_SEC * (2 ** attempt)
                    logger.warning("Rate limit — %s sn bekleniyor (deneme %d/%d)", wait, attempt + 1, MAX_RETRIES)
                    time.sleep(wait)
                elif e.code == -2010:  # Insufficient balance
                    raise
                else:
                    raise
            except (BinanceRequestException, ConnectionError, TimeoutError, requests.RequestException) as e:
                last_exc = e
                wait = RETRY_BACKOFF_SEC * (2 ** attempt)
                logger.warning("Bağlantı hatası — %s sn bekleniyor: %s", wait, e)
                time.sleep(wait)
        raise last_exc  # type: ignore[misc]

    # ── Hesap ───────────────────────────────────────────────────────────

    def get_account_balance(self, asset: str = "USDT") -> dict:
        """Belirli bir varlığın bakiyesini döndürür."""
        account = self._retry(self.client.get_account)
        for bal in account.get("balances", []):
            if bal["asset"] == asset:
                return {
                    "asset": asset,
                    "free": float(bal["free"]),
                    "locked": float(bal["locked"]),
                    "total": float(bal["free"]) + float(bal["locked"]),
                }
        return {"asset": asset, "free": 0.0, "locked": 0.0, "total": 0.0}

    def get_all_balances(self, min_value: float = 0.001) -> list[dict]:
        """Sıfırdan büyük tüm bakiyeleri listeler."""
        account = self._retry(self.client.get_account)
        result = []
        for bal in account.get("balances", []):
            free = float(bal["free"])
            locked = float(bal["locked"])
            total = free + locked
            if total >= min_value:
                result.append({
                    "asset": bal["asset"],
                    "free": free,
                    "locked": locked,
                    "total": total,
                })
        return result

    # ── Piyasa verisi ─────────────────────────────────────────────────────

    def get_klines(
        self,
        symbol: str,
        interval: str,
        limit: int = 100,
    ) -> list[list]:
        """Mum (kline) verilerini çeker."""
        return self._retry(
            self._public_client_instance().get_klines,
            symbol=symbol,
            interval=interval,
            limit=limit,
        )

    def get_ticker_price(self, symbol: str) -> float:
        """Anlık fiyat."""
        ticker = self._retry(self._public_client_instance().get_symbol_ticker, symbol=symbol)
        return float(ticker["price"])

    def get_24h_stats(self, symbol: str) -> dict:
        """24 saatlik istatistikler."""
        stats = self._retry(self._public_client_instance().get_ticker, symbol=symbol)
        return {
            "symbol": symbol,
            "price_change_pct": float(stats["priceChangePercent"]),
            "high": float(stats["highPrice"]),
            "low": float(stats["lowPrice"]),
            "volume": float(stats["volume"]),
            "quote_volume": float(stats["quoteVolume"]),
        }

    # ── Sembol bilgisi ────────────────────────────────────────────────────

    def _get_symbol_info(self, symbol: str) -> dict:
        if symbol not in self._symbol_info_cache:
            info = self._retry(self.client.get_symbol_info, symbol=symbol)
            self._symbol_info_cache[symbol] = info or {}
        return self._symbol_info_cache[symbol]

    def _format_quantity(self, symbol: str, quantity: float) -> str:
        info = self._get_symbol_info(symbol)
        for f in info.get("filters", []):
            if f["filterType"] == "LOT_SIZE":
                step = Decimal(f["stepSize"])
                qty = Decimal(str(quantity)).quantize(step, rounding=ROUND_DOWN)
                return str(qty)
        return f"{quantity:.8f}"

    def _format_price(self, symbol: str, price: float) -> str:
        info = self._get_symbol_info(symbol)
        for f in info.get("filters", []):
            if f["filterType"] == "PRICE_FILTER":
                tick = Decimal(f["tickSize"])
                p = Decimal(str(price)).quantize(tick, rounding=ROUND_DOWN)
                return str(p)
        return f"{price:.2f}"

    # ── Emirler ───────────────────────────────────────────────────────────

    def place_market_buy(self, symbol: str, quote_qty: float) -> dict:
        """USDT cinsinden piyasa alım emri."""
        logger.info("MARKET BUY %s — %.2f USDT [%s]", symbol, quote_qty, "TESTNET" if self.use_testnet else "CANLI")
        order = self._retry(
            self.client.order_market_buy,
            symbol=symbol,
            quoteOrderQty=quote_qty,
        )
        return self._normalize_order(order)

    def place_market_sell(self, symbol: str, quantity: float) -> dict:
        """Piyasa satış emri."""
        qty_str = self._format_quantity(symbol, quantity)
        logger.info("MARKET SELL %s — %s [%s]", symbol, qty_str, "TESTNET" if self.use_testnet else "CANLI")
        order = self._retry(
            self.client.order_market_sell,
            symbol=symbol,
            quantity=qty_str,
        )
        return self._normalize_order(order)

    def place_limit_buy(self, symbol: str, quantity: float, price: float) -> dict:
        """Limit alım emri."""
        qty_str = self._format_quantity(symbol, quantity)
        price_str = self._format_price(symbol, price)
        logger.info("LIMIT BUY %s — %s @ %s", symbol, qty_str, price_str)
        order = self._retry(
            self.client.order_limit_buy,
            symbol=symbol,
            quantity=qty_str,
            price=price_str,
        )
        return self._normalize_order(order)

    def place_limit_sell(self, symbol: str, quantity: float, price: float) -> dict:
        """Limit satış emri."""
        qty_str = self._format_quantity(symbol, quantity)
        price_str = self._format_price(symbol, price)
        logger.info("LIMIT SELL %s — %s @ %s", symbol, qty_str, price_str)
        order = self._retry(
            self.client.order_limit_sell,
            symbol=symbol,
            quantity=qty_str,
            price=price_str,
        )
        return self._normalize_order(order)

    def cancel_order(self, symbol: str, order_id: int) -> dict:
        return self._retry(self.client.cancel_order, symbol=symbol, orderId=order_id)

    def get_open_orders(self, symbol: Optional[str] = None) -> list[dict]:
        kwargs = {"symbol": symbol} if symbol else {}
        return self._retry(self.client.get_open_orders, **kwargs)

    @staticmethod
    def _normalize_order(order: dict) -> dict:
        """Emir yanıtını standart formata dönüştürür."""
        fills = order.get("fills", [])
        total_qty = sum(float(f.get("qty", 0)) for f in fills)
        total_quote = sum(float(f.get("qty", 0)) * float(f.get("price", 0)) for f in fills)
        avg_price = total_quote / total_qty if total_qty > 0 else float(order.get("price", 0))

        return {
            "order_id": str(order.get("orderId", "")),
            "symbol": order.get("symbol", ""),
            "side": order.get("side", ""),
            "type": order.get("type", ""),
            "status": order.get("status", ""),
            "quantity": total_qty or float(order.get("origQty", 0)),
            "quote_qty": total_quote or float(order.get("cummulativeQuoteQty", 0)),
            "price": avg_price,
            "raw": order,
        }

    def ping(self) -> bool:
        """API bağlantısını test eder."""
        try:
            self._retry(self._public_client_instance().ping)
            return True
        except Exception as e:
            logger.error("Binance ping başarısız: %s", e)
            return False


def get_engine() -> BinanceEngine:
    """Her çağrıda güncel settings ile yeni engine (Streamlit cache sorununu önler)."""
    settings.reload_settings()
    return BinanceEngine()


def check_market_connection(symbol: str = "BTCUSDT") -> dict:
    """Binance piyasa bağlantısını test eder (paper modda public API)."""
    import time

    settings.reload_settings()
    symbol = symbol.upper()
    t0 = time.time()
    if settings.PAPER_TRADING:
        mode_label = "Simülasyon · public API"
    elif settings.USE_TESTNET:
        mode_label = "Testnet"
    else:
        mode_label = "Canlı API"

    try:
        engine = get_engine()
        ok = engine.ping()
        price = engine.get_ticker_price(symbol) if ok else None
        ms = int((time.time() - t0) * 1000)
        if ok:
            return {
                "ok": True,
                "mode": mode_label,
                "symbol": symbol,
                "price": price,
                "latency_ms": ms,
                "message": f"Baglanti OK · {symbol} ${price:,.2f} · {ms}ms",
            }
        return {
            "ok": False,
            "mode": mode_label,
            "symbol": symbol,
            "price": None,
            "latency_ms": ms,
            "message": "Binance yanit vermedi.",
        }
    except Exception as exc:
        return {
            "ok": False,
            "mode": mode_label,
            "symbol": symbol,
            "price": None,
            "latency_ms": int((time.time() - t0) * 1000),
            "message": str(exc),
        }
