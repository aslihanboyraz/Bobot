"""
Haber & Sentiment Analiz Modülü — ücretsiz RSS + Gemini AI duyarlılık analizi.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Optional

from db_store import insert_news_sentiment
from gemini_client import analyze_news_sentiment
from news_engine import fetch_all_news

logger = logging.getLogger(__name__)


def _clean_text(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:512]


def _score_to_100(score: float) -> int:
    return max(0, min(100, int(round((score + 1) / 2 * 100))))


def _overall_mood(avg_score: float) -> str:
    if avg_score >= 0.15:
        return "BULLISH"
    if avg_score <= -0.15:
        return "BEARISH"
    return "NEUTRAL"


def _keyword_sentiment(text: str) -> dict:
    """Gemini yoksa gelişmiş anahtar kelime fallback."""
    text = _clean_text(text).lower()

    positive = (
        "surge", "rally", "bullish", "gain", "rise", "approval", "adoption",
        "record", "high", "etf", "upgrade", "partnership", "breakout", "soar",
        "jump", "recovery", "inflow", "milestone", "launch", "yüksel", "artış",
    )
    negative = (
        "crash", "drop", "bearish", "ban", "hack", "fraud", "sec", "lawsuit",
        "fall", "low", "dump", "plunge", "selloff", "warning", "collapse",
        "outflow", "düşüş", "dusus", "investigation", "fine",
    )

    pos = sum(1 for w in positive if w in text)
    neg = sum(1 for w in negative if w in text)

    if pos > neg and pos > 0:
        return {"score": min(0.75, 0.2 + pos * 0.12), "label": "positive"}
    if neg > pos and neg > 0:
        return {"score": max(-0.75, -0.2 - neg * 0.12), "label": "negative"}
    return {"score": 0.0, "label": "neutral"}


def _analyze_with_keyword_fallback(news: list[dict]) -> tuple[list[dict], float, str]:
    articles = []
    scores = []
    for article in news:
        text = article.get("title", "") + " " + article.get("summary", "")
        result = _keyword_sentiment(text)
        article["sentiment_score"] = result["score"]
        article["sentiment_label"] = result["label"]
        article["score_100"] = _score_to_100(result["score"])
        articles.append(article)
        scores.append(result["score"])

    avg_score = sum(scores) / len(scores) if scores else 0.0
    overall = _overall_mood(avg_score)
    return articles, avg_score, overall


def run_sentiment_analysis(symbol: str = "BTCUSDT", save_to_db: bool = True) -> dict:
    """
    RSS haberleri çeker, Gemini ile duyarlılık analizi yapar (key yoksa keyword fallback).
    Returns: average_score, score_100, overall_label, articles, model
    """
    symbol = symbol.upper()
    news = fetch_all_news(symbol, max_items=10)
    model = "Keyword Fallback"

    gemini_result = analyze_news_sentiment(symbol, news)

    if gemini_result:
        articles = gemini_result["articles"]
        avg_score = gemini_result["average_score"]
        overall = gemini_result["overall_label"]
        model = gemini_result.get("model", "Gemini")
        summary_tr = gemini_result.get("summary_tr", "")

        for art in articles:
            art["symbol"] = symbol
            art["score_100"] = _score_to_100(art.get("sentiment_score", 0.0))
    else:
        articles, avg_score, overall = _analyze_with_keyword_fallback(news)
        summary_tr = ""
        for art in articles:
            art["symbol"] = symbol

    if save_to_db:
        for article in articles:
            try:
                insert_news_sentiment(
                    source=article.get("source", "unknown"),
                    title=article["title"],
                    url=article.get("url", ""),
                    sentiment_score=article.get("sentiment_score", 0.0),
                    label=article.get("sentiment_label", "neutral"),
                )
            except Exception as exc:
                logger.warning("DB kayıt hatası: %s", exc)

    logger.info(
        "Sentiment [%s] — %d haber, skor: %+.3f (%s) · %s",
        symbol, len(articles), avg_score, overall, model,
    )

    return {
        "symbol": symbol,
        "average_score": round(avg_score, 4),
        "score_100": _score_to_100(avg_score),
        "overall_label": overall,
        "articles": articles,
        "count": len(articles),
        "model": model,
        "summary_tr": summary_tr,
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
    }
