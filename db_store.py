"""
SQLite depolama — paper portföy, işlemler, sinyaller, haber sentiment.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Generator, Optional

from settings import BASE_DIR

logger = logging.getLogger(__name__)

DB_PATH = BASE_DIR / "crypto_agent.db"


def _json_dumps_safe(data: Any) -> str:
    def _convert(obj: Any) -> Any:
        if isinstance(obj, dict):
            return {k: _convert(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [_convert(v) for v in obj]
        if hasattr(obj, "item") and callable(getattr(obj, "item")):
            return obj.item()
        return obj

    return json.dumps(_convert(data))


@contextmanager
def get_connection() -> Generator[sqlite3.Connection, None, None]:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_db() -> None:
    with get_connection() as conn:
        cur = conn.cursor()

        cur.execute("""
            CREATE TABLE IF NOT EXISTS news_sentiments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT,
                title TEXT NOT NULL,
                url TEXT,
                sentiment_score REAL,
                label TEXT,
                analyzed_at TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS trading_signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                mode TEXT NOT NULL,
                signal_type TEXT NOT NULL,
                strength REAL,
                indicators TEXT,
                sentiment_score REAL,
                reason TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS active_investment_mode (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                mode TEXT NOT NULL DEFAULT 'SHORT_TERM',
                updated_at TEXT NOT NULL
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS trade_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                side TEXT NOT NULL,
                order_type TEXT NOT NULL,
                quantity REAL,
                quote_qty REAL,
                price REAL,
                order_id TEXT,
                status TEXT,
                pnl REAL,
                mode TEXT,
                is_testnet INTEGER DEFAULT 1,
                is_paper INTEGER DEFAULT 0,
                executed_at TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS paper_portfolio (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                usdt_balance REAL NOT NULL,
                holdings TEXT NOT NULL DEFAULT '{}',
                initial_balance REAL NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

        from settings import PAPER_INITIAL_BALANCE

        cur.execute(
            """INSERT OR IGNORE INTO paper_portfolio
               (id, usdt_balance, holdings, initial_balance, updated_at)
               VALUES (1, ?, '{}', ?, ?)""",
            (PAPER_INITIAL_BALANCE, PAPER_INITIAL_BALANCE, _now_iso()),
        )
        try:
            cur.execute("ALTER TABLE trade_history ADD COLUMN is_paper INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass

        cur.execute(
            "INSERT OR IGNORE INTO active_investment_mode (id, mode, updated_at) VALUES (1, 'SHORT_TERM', ?)",
            (_now_iso(),),
        )

    logger.info("Veritabani baslatildi: %s", DB_PATH)


def insert_news_sentiment(
    source: str,
    title: str,
    url: str,
    sentiment_score: float,
    label: str,
) -> None:
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO news_sentiments (source, title, url, sentiment_score, label, analyzed_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (source, title, url, sentiment_score, label, _now_iso()),
        )


def insert_trading_signal(
    symbol: str,
    mode: str,
    signal_type: str,
    strength: float,
    indicators: dict,
    sentiment_score: Optional[float],
    reason: str,
) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            """INSERT INTO trading_signals
               (symbol, mode, signal_type, strength, indicators, sentiment_score, reason)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (symbol, mode, signal_type, strength, _json_dumps_safe(indicators), sentiment_score, reason),
        )
        return cur.lastrowid or 0


def get_active_mode() -> str:
    with get_connection() as conn:
        row = conn.execute("SELECT mode FROM active_investment_mode WHERE id = 1").fetchone()
    return row["mode"] if row else "SHORT_TERM"


def set_active_mode(mode: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE active_investment_mode SET mode = ?, updated_at = ? WHERE id = 1",
            (mode, _now_iso()),
        )


def insert_trade(
    symbol: str,
    side: str,
    order_type: str,
    quantity: Optional[float],
    quote_qty: Optional[float],
    price: Optional[float],
    order_id: str,
    status: str,
    pnl: Optional[float],
    mode: str,
    is_testnet: bool,
    is_paper: bool = False,
) -> None:
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO trade_history
               (symbol, side, order_type, quantity, quote_qty, price, order_id,
                status, pnl, mode, is_testnet, is_paper, executed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                symbol, side, order_type, quantity, quote_qty, price,
                order_id, status, pnl, mode, int(is_testnet), int(is_paper), _now_iso(),
            ),
        )


def get_trade_history(limit: int = 50, paper_only: Optional[bool] = None) -> list[dict]:
    with get_connection() as conn:
        if paper_only is True:
            rows = conn.execute(
                "SELECT * FROM trade_history WHERE is_paper = 1 ORDER BY executed_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        elif paper_only is False:
            rows = conn.execute(
                "SELECT * FROM trade_history WHERE is_paper = 0 ORDER BY executed_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM trade_history ORDER BY executed_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
    return [dict(r) for r in rows]


def get_paper_portfolio() -> dict:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM paper_portfolio WHERE id = 1").fetchone()
    if not row:
        from settings import PAPER_INITIAL_BALANCE

        return {
            "usdt_balance": PAPER_INITIAL_BALANCE,
            "holdings": {},
            "initial_balance": PAPER_INITIAL_BALANCE,
        }
    holdings = {}
    if row["holdings"]:
        try:
            holdings = json.loads(row["holdings"])
        except (json.JSONDecodeError, TypeError):
            holdings = {}
    return {
        "usdt_balance": float(row["usdt_balance"]),
        "holdings": holdings,
        "initial_balance": float(row["initial_balance"]),
    }


def update_paper_portfolio(usdt_balance: float, holdings: dict) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE paper_portfolio SET usdt_balance = ?, holdings = ?, updated_at = ? WHERE id = 1",
            (usdt_balance, json.dumps(holdings), _now_iso()),
        )
