"""
Bobot kontrol paneli — bakiye, bot start/stop, risk, Telegram, Gemini.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import settings
from settings import (
    get_risk_settings,
    save_gemini_settings,
    save_risk_settings,
    save_telegram_settings,
)
from db_store import get_paper_portfolio, get_trade_history, init_db, reset_paper_portfolio
from bot_runner import is_bot_running, read_bot_log, start_bot, stop_bot
from bot import discover_chat_id, test_connection
from binance_engine import check_market_connection
from paper_trading import get_portfolio_status
import paper_trading as paper_mod

import streamlit as st
import pandas as pd

st.set_page_config(page_title="Bobot", page_icon="🤖", layout="wide")
init_db()
settings.reload_settings()

DEFAULT_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "AVAXUSDT", "BNBUSDT", "XRPUSDT"]


def _mode() -> str:
    if settings.PAPER_TRADING:
        return "Simülasyon"
    if settings.USE_TESTNET:
        return "TESTNET"
    return "CANLI"


st.title("Bobot")
st.caption(f"Mod: **{_mode()}** · SHORT_TERM · watchlist ajan")

# ── Ozet ────────────────────────────────────────────────────────────────
try:
    status = get_portfolio_status()
except Exception:
    p = get_paper_portfolio()
    status = {
        "equity": p["usdt_balance"],
        "usdt": p["usdt_balance"],
        "initial": p["initial_balance"],
        "pnl": 0.0,
        "pnl_pct": 0.0,
        "positions": [],
    }

c1, c2, c3, c4 = st.columns(4)
c1.metric("Toplam", f"${status['equity']:,.2f}")
c2.metric("Nakit USDT", f"${status['usdt']:,.2f}")
c3.metric("K/Z", f"${status['pnl']:+,.2f}", f"{status['pnl_pct']:+.1f}%")
c4.metric("Bot", "Calisiyor" if is_bot_running() else "Durdu")

if status.get("positions"):
    st.write("Pozisyonlar:", " · ".join(status["positions"][:6]))

# ── Bakiye sifirla ──────────────────────────────────────────────────────
st.subheader("Bakiye")
rb1, rb2, rb3 = st.columns([2, 2, 2])
with rb1:
    reset_amount = st.number_input(
        "Yeni baslangic bakiyesi (USDT)",
        min_value=100.0,
        value=float(settings.PAPER_INITIAL_BALANCE or 10000),
        step=100.0,
    )
with rb2:
    st.write("")
    st.write("")
    if st.button("Bakiyeyi sifirla", type="secondary"):
        reset_paper_portfolio(float(reset_amount))
        paper_mod._paper_engine = None
        st.success(f"Bakiye sifirlandi: ${reset_amount:,.2f} USDT (pozisyonlar temizlendi)")
        st.rerun()
with rb3:
    st.caption("Pozisyonlari siler, nakiti sectigin tutara ceker.")

# ── Bot kontrol ─────────────────────────────────────────────────────────
st.subheader("Bot")
risk = get_risk_settings()
col_a, col_b, col_c = st.columns(3)
with col_a:
    if st.button("Baslat", type="primary", disabled=is_bot_running()):
        ok, msg = start_bot(int(risk["loop_interval"]))
        st.success(msg) if ok else st.error(msg)
        st.rerun()
with col_b:
    if st.button("Durdur", disabled=not is_bot_running()):
        ok, msg = stop_bot()
        st.success(msg) if ok else st.error(msg)
        st.rerun()
with col_c:
    if st.button("Yenile"):
        st.rerun()

log = read_bot_log(25)
if log:
    with st.expander("Son log", expanded=False):
        st.code(log, language="text")

# ── Risk / watchlist ────────────────────────────────────────────────────
st.subheader("Risk & Watchlist")
with st.form("risk_form"):
    wl_default = risk.get("watchlist") or DEFAULT_SYMBOLS
    watchlist = st.multiselect("Watchlist", options=DEFAULT_SYMBOLS, default=[s for s in wl_default if s in DEFAULT_SYMBOLS] or DEFAULT_SYMBOLS)
    _sym_opts = DEFAULT_SYMBOLS
    _sym_idx = _sym_opts.index(risk["symbol"]) if risk.get("symbol") in _sym_opts else 0
    symbol = st.selectbox("Varsayilan sembol", options=_sym_opts, index=_sym_idx)
    quote_qty = st.number_input("Alim tutari (USDT)", min_value=5.0, value=float(risk["quote_qty"]), step=5.0)
    min_conf = st.slider("Min guven %", 50, 90, int(risk["min_confidence"]))
    sl = st.number_input("Stop Loss %", min_value=0.5, value=float(risk["stop_loss_pct"]), step=0.5)
    tp = st.number_input("Take Profit %", min_value=0.5, value=float(risk["take_profit_pct"]), step=0.5)
    loop_iv = st.number_input("Dongu (sn)", min_value=60, value=int(risk["loop_interval"]), step=60)
    auto_trade = st.toggle("Otomatik emir", value=bool(risk["auto_trade_enabled"]))
    auto_risk = st.toggle("SL/TP aktif", value=bool(risk["auto_risk_management"]))
    if st.form_submit_button("Kaydet"):
        if not watchlist:
            st.error("En az bir coin secin.")
        else:
            save_risk_settings(
                symbol=symbol,
                watchlist=watchlist,
                quote_qty=float(quote_qty),
                min_confidence=float(min_conf),
                stop_loss_pct=float(sl),
                take_profit_pct=float(tp),
                loop_interval=int(loop_iv),
                auto_trade_enabled=auto_trade,
                auto_risk_management=auto_risk,
            )
            st.success("Ayarlar kaydedildi.")

# ── Islem gecmisi ───────────────────────────────────────────────────────
st.subheader("Son islemler")
trades = get_trade_history(limit=20)
if trades:
    df = pd.DataFrame(trades)[["executed_at", "side", "symbol", "price", "quantity", "status"]]
    st.dataframe(df, use_container_width=True, hide_index=True)
else:
    st.info("Henuz islem yok.")

# ── Baglantilar ─────────────────────────────────────────────────────────
st.subheader("Baglantilar")
t1, t2, t3 = st.tabs(["Telegram", "Gemini", "Binance"])

with t1:
    token = st.text_input("Bot token", value=settings.TELEGRAM_BOT_TOKEN, type="password")
    chat_id = st.text_input("Chat ID", value=settings.TELEGRAM_CHAT_ID)
    c1, c2 = st.columns(2)
    if c1.button("Telegram kaydet"):
        save_telegram_settings(token, chat_id)
        st.success("Kaydedildi.")
    if c2.button("Chat ID bul"):
        cid, msg = discover_chat_id(token)
        st.info(msg)
        if cid:
            save_telegram_settings(token, cid)
    if st.button("Telegram test"):
        ok, msg = test_connection(token, chat_id)
        st.success(msg) if ok else st.error(msg)

with t2:
    gkey = st.text_input("Gemini API key", value=settings.GEMINI_API_KEY, type="password")
    gmodel = st.text_input("Model", value=settings.GEMINI_MODEL)
    if st.button("Gemini kaydet"):
        save_gemini_settings(gkey, gmodel)
        st.success("Kaydedildi.")
    if st.button("Gemini test"):
        from gemini_client import test_gemini_connection

        ok, msg = test_gemini_connection()
        st.success(msg) if ok else st.error(msg)

with t3:
    if st.button("Binance baglanti testi"):
        result = check_market_connection(settings.DEFAULT_SYMBOL)
        st.success(result["message"]) if result["ok"] else st.error(result["message"])
