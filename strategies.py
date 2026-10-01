"""
SHORT_TERM swing stratejisi — RSI + MACD + haber sentiment.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import pandas as pd

from settings import INVESTMENT_MODES
from indicators import calc_macd, calc_rsi, calc_sma

logger = logging.getLogger(__name__)


class SignalType(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"
    DCA = "DCA"


@dataclass
class TradingSignal:
    symbol: str
    mode: str
    signal: SignalType
    strength: float  # 0.0 – 1.0
    current_price: float
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    indicators: dict = field(default_factory=dict)
    reason: str = ""


def klines_to_dataframe(klines: list[list]) -> pd.DataFrame:
    df = pd.DataFrame(klines, columns=[
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_volume", "trades", "taker_buy_base",
        "taker_buy_quote", "ignore",
    ])
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
    return df


class ShortTermStrategy:
    """Swing Trading — 1h/4h, RSI(14), MACD, haber sentiment."""

    mode = "SHORT_TERM"

    def analyze(
        self,
        symbol: str,
        klines_by_interval: dict[str, list],
        sentiment_score: Optional[float] = None,
    ) -> TradingSignal:
        cfg = INVESTMENT_MODES["SHORT_TERM"]
        df_1h = klines_to_dataframe(klines_by_interval.get("1h", []))
        df_4h = klines_to_dataframe(klines_by_interval.get("4h", []))

        if df_1h.empty:
            return TradingSignal(symbol, self.mode, SignalType.HOLD, 0.0, 0.0, reason="Veri yok")

        price = float(df_1h["close"].iloc[-1])
        rsi = calc_rsi(df_1h["close"], 14)
        rsi_val = float(rsi.iloc[-1]) if not rsi.empty and pd.notna(rsi.iloc[-1]) else 50.0

        macd_line, signal_line, histogram = calc_macd(df_1h["close"])
        macd_cross_up = bool(
            len(macd_line) >= 2
            and macd_line.iloc[-2] <= signal_line.iloc[-2]
            and macd_line.iloc[-1] > signal_line.iloc[-1]
        )
        macd_cross_down = bool(
            len(macd_line) >= 2
            and macd_line.iloc[-2] >= signal_line.iloc[-2]
            and macd_line.iloc[-1] < signal_line.iloc[-1]
        )

        trend_4h = "neutral"
        if not df_4h.empty and len(df_4h) >= 20:
            sma20 = calc_sma(df_4h["close"], 20)
            if pd.notna(sma20.iloc[-1]):
                trend_4h = "up" if price > sma20.iloc[-1] else "down"

        indicators = {
            "rsi_14": round(rsi_val, 2),
            "macd_cross_up": macd_cross_up,
            "macd_cross_down": macd_cross_down,
            "macd_histogram": round(float(histogram.iloc[-1]), 4) if len(histogram) > 0 else 0,
            "trend_4h": trend_4h,
            "sentiment": sentiment_score,
        }

        strength = 0.0
        signal = SignalType.HOLD
        reasons: list[str] = []

        if macd_cross_up and rsi_val < 60 and trend_4h != "down":
            signal = SignalType.BUY
            strength = 0.75
            reasons.append("MACD yukari kesisim, RSI uygun, 4h trend destekliyor")

        if rsi_val < 35 and trend_4h == "up":
            signal = SignalType.BUY
            strength = max(strength, 0.65)
            reasons.append(f"RSI asiri satim ({rsi_val:.1f}) + 4h yukselis trendi")

        if macd_cross_down and rsi_val > 60:
            signal = SignalType.SELL
            strength = 0.7
            reasons.append("MACD asagi kesisim, RSI yuksek")

        hist_val = float(histogram.iloc[-1]) if len(histogram) > 0 and pd.notna(histogram.iloc[-1]) else 0.0
        if signal == SignalType.HOLD and hist_val > 0 and 35 <= rsi_val <= 48 and trend_4h != "down":
            signal = SignalType.BUY
            strength = 0.58
            reasons.append(f"RSI alim bolgesi ({rsi_val:.0f}), MACD momentum pozitif")

        if signal == SignalType.HOLD and hist_val < 0 and rsi_val >= 62 and trend_4h != "up":
            signal = SignalType.SELL
            strength = 0.58
            reasons.append(f"RSI satis bolgesi ({rsi_val:.0f}), MACD momentum negatif")

        if sentiment_score is not None:
            if sentiment_score > 0.15 and signal in (SignalType.BUY, SignalType.HOLD):
                if signal == SignalType.HOLD and rsi_val < 52 and trend_4h != "down":
                    signal = SignalType.BUY
                    strength = max(strength, 0.55)
                    reasons.append(f"Pozitif haber + RSI uygun ({sentiment_score:+.2f})")
                elif signal == SignalType.BUY:
                    strength = min(1.0, strength + sentiment_score * 0.25)
                    reasons.append(f"Pozitif haber sentiment ({sentiment_score:+.2f})")
            elif sentiment_score < -0.15 and signal in (SignalType.BUY, SignalType.HOLD):
                if signal == SignalType.HOLD and rsi_val > 55:
                    signal = SignalType.SELL
                    strength = max(strength, 0.55)
                    reasons.append(f"Negatif haber + RSI yuksek ({sentiment_score:+.2f})")
                elif signal == SignalType.BUY:
                    strength *= 0.65
                    reasons.append(f"Negatif sentiment ({sentiment_score:+.2f}) — dikkat")

        sl = price * (1 - cfg["stop_loss_pct"] / 100)
        tp = price * (1 + cfg["take_profit_pct"] / 100)

        return TradingSignal(
            symbol=symbol,
            mode=self.mode,
            signal=signal,
            strength=round(strength, 3),
            current_price=price,
            stop_loss=round(sl, 2),
            take_profit=round(tp, 2),
            indicators=indicators,
            reason=" | ".join(reasons) if reasons else "Belirgin sinyal yok — BEKLE",
        )


_STRATEGY = ShortTermStrategy()


def analyze_market(
    symbol: str,
    mode: str,
    klines_by_interval: dict[str, list],
    sentiment_score: Optional[float] = None,
) -> TradingSignal:
    """SHORT_TERM piyasa analizi (mode parametresi uyumluluk icin tutulur)."""
    return _STRATEGY.analyze(symbol, klines_by_interval, sentiment_score)
