"""
Teknik indikatör hesaplamaları — saf pandas (Python 3.14 uyumlu).
Opsiyonel olarak kurulu `ta` kütüphanesini de kullanır.
"""

from __future__ import annotations

import pandas as pd

# Opsiyonel: `pip install ta` (Python 3.14 uyumlu)
_ta_lib = None
try:
    from ta.momentum import RSIIndicator
    from ta.trend import MACD as TaMACD

    _ta_lib = True
except ImportError:
    pass


def calc_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    if _ta_lib:
        return RSIIndicator(close=series, window=period).rsi()
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, 1e-10)
    return 100 - (100 / (1 + rs))


def calc_macd(
    series: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    if _ta_lib:
        macd_obj = TaMACD(close=series, window_fast=fast, window_slow=slow, window_sign=signal)
        return macd_obj.macd(), macd_obj.macd_signal(), macd_obj.macd_diff()
    ema_fast = series.ewm(span=fast).mean()
    ema_slow = series.ewm(span=slow).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal).mean()
    return macd_line, signal_line, macd_line - signal_line


def calc_sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(period).mean()


def add_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """DataFrame'e SMA, RSI ve MACD sütunları ekler."""
    out = df.copy()
    out["sma_20"] = calc_sma(out["close"], 20)
    out["sma_50"] = calc_sma(out["close"], 50)
    out["sma_200"] = calc_sma(out["close"], 200)
    out["rsi"] = calc_rsi(out["close"], 14)
    macd_line, signal_line, histogram = calc_macd(out["close"])
    out["macd"] = macd_line
    out["macd_signal"] = signal_line
    out["macd_hist"] = histogram
    return out
