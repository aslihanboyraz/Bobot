"""
Google Gemini — haber sentiment + firsat secimi.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Optional

import requests

import settings
from settings import GEMINI_API_KEY, GEMINI_MODEL, REQUEST_TIMEOUT

logger = logging.getLogger(__name__)

GEMINI_MODEL_FALLBACKS = (
    "gemini-flash-latest",
    "gemini-2.5-flash-lite",
    "gemini-3-flash-preview",
    "gemini-pro-latest",
    "gemini-2.5-flash",
)


def is_valid_api_key_format(key: str) -> bool:
    key = (key or "").strip()
    if len(key) < 20:
        return False
    return key.startswith("AIza") or key.startswith("AQ.")


def _gemini_post(model: str, key: str, payload: dict) -> requests.Response:
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent"
    )
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": key,
    }
    return requests.post(url, json=payload, headers=headers, timeout=REQUEST_TIMEOUT)


def _models_to_try() -> list[str]:
    settings.reload_settings()
    primary = (settings.GEMINI_MODEL or GEMINI_MODEL or "").strip()
    models: list[str] = []
    if primary:
        models.append(primary)
    for m in GEMINI_MODEL_FALLBACKS:
        if m not in models:
            models.append(m)
    return models


def test_gemini_connection() -> tuple[bool, str]:
    settings.reload_settings()
    key = settings.GEMINI_API_KEY.strip()
    if not key:
        return False, "GEMINI_API_KEY bos. aistudio.google.com adresinden key alin."
    if not is_valid_api_key_format(key):
        return False, "Key formati taninmadi. AIza... veya AQ.... ile baslamali."

    payload = {
        "contents": [{"parts": [{"text": "Yalnizca su kelimeyi yaz: OK"}]}],
        "generationConfig": {"temperature": 0, "maxOutputTokens": 16},
    }
    for model in _models_to_try():
        try:
            resp = _gemini_post(model, key, payload)
            if resp.status_code == 404:
                continue
            resp.raise_for_status()
            data = resp.json()
            text = (
                data.get("candidates", [{}])[0]
                .get("content", {})
                .get("parts", [{}])[0]
                .get("text", "")
                .strip()
            )
            key_type = "Auth (AQ.)" if key.startswith("AQ.") else "Standard (AIza)"
            return True, f"Gemini OK · {key_type} · model={model} · yanit={text[:20] or 'OK'}"
        except requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                continue
            detail = ""
            try:
                detail = exc.response.json().get("error", {}).get("message", "")
            except Exception:
                detail = str(exc)
            return False, f"Gemini hatasi ({model}): {detail or exc}"
        except Exception as exc:
            return False, f"Gemini baglanti hatasi: {exc}"

    return False, "Hicbir Gemini modeli calismadi. Key veya model adini kontrol edin."


def _call_gemini(prompt: str, max_tokens: int = 800) -> Optional[str]:
    settings.reload_settings()
    key = settings.GEMINI_API_KEY.strip()
    if not key or not is_valid_api_key_format(key):
        if key:
            logger.warning("Gemini key formati taninmadi")
        return None

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": max_tokens},
    }

    last_exc: Optional[Exception] = None
    for model in _models_to_try():
        try:
            resp = _gemini_post(model, key, payload)
            if resp.status_code == 404:
                continue
            resp.raise_for_status()
            data = resp.json()
            text = (
                data.get("candidates", [{}])[0]
                .get("content", {})
                .get("parts", [{}])[0]
                .get("text", "")
                .strip()
            )
            if text:
                return text
        except Exception as exc:
            last_exc = exc
            logger.warning("Gemini API hatasi (%s): %s", model, exc)

    if last_exc:
        logger.warning("Gemini tum modeller basarisiz: %s", last_exc)
    return None


def _extract_json(text: str) -> Optional[dict]:
    if not text:
        return None
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
    return None


def _label_to_score(label: str) -> tuple[float, str]:
    label = label.upper()
    if label in ("BULLISH", "POSITIVE", "BUY"):
        return 0.65, "positive"
    if label in ("BEARISH", "NEGATIVE", "SELL"):
        return -0.65, "negative"
    return 0.0, "neutral"


def analyze_news_sentiment(symbol: str, articles: list[dict]) -> Optional[dict]:
    if not settings.GEMINI_API_KEY or not articles:
        return None

    news_block = "\n".join(
        f"{i}. Baslik: {a.get('title', '')}\n   Ozet: {a.get('summary', '')[:200]}"
        for i, a in enumerate(articles, 1)
    )

    prompt = f"""Sen bir kripto piyasa analistisin. Asagidaki {symbol} haberlerini analiz et.

HABERLER:
{news_block}

Yalnizca gecerli JSON dondur:
{{
  "overall": "BULLISH veya BEARISH veya NEUTRAL",
  "overall_score": -1.0 ile 1.0 arasi sayi,
  "summary_tr": "Turkce tek cumle piyasa ozeti (max 150 karakter)",
  "articles": [
    {{"index": 1, "sentiment": "BULLISH/BEARISH/NEUTRAL", "score": 0.0}}
  ]
}}"""

    raw = _call_gemini(prompt, max_tokens=900)
    parsed = _extract_json(raw)
    if not parsed:
        logger.warning("Gemini JSON parse edilemedi")
        return None

    overall = str(parsed.get("overall", "NEUTRAL")).upper()
    if overall not in ("BULLISH", "BEARISH", "NEUTRAL"):
        overall = "NEUTRAL"

    try:
        avg_score = float(parsed.get("overall_score", 0.0))
        avg_score = max(-1.0, min(1.0, avg_score))
    except (TypeError, ValueError):
        avg_score, _ = _label_to_score(overall)

    article_sentiments = parsed.get("articles", [])
    enriched = []
    for i, art in enumerate(articles):
        sent_entry = next(
            (a for a in article_sentiments if a.get("index") == i + 1),
            None,
        )
        if sent_entry:
            sent_label = str(sent_entry.get("sentiment", "NEUTRAL")).upper()
            try:
                score = float(sent_entry.get("score", 0.0))
            except (TypeError, ValueError):
                score, _ = _label_to_score(sent_label)
        else:
            sent_label = overall
            score = avg_score

        label_map = {"BULLISH": "positive", "BEARISH": "negative", "NEUTRAL": "neutral"}
        enriched.append({
            **art,
            "sentiment_score": round(max(-1.0, min(1.0, score)), 4),
            "sentiment_label": label_map.get(sent_label, "neutral"),
            "gemini_sentiment": sent_label,
        })

    used_model = _models_to_try()[0]
    return {
        "overall_label": overall,
        "average_score": round(avg_score, 4),
        "summary_tr": parsed.get("summary_tr", ""),
        "articles": enriched,
        "model": f"Gemini ({used_model})",
    }


def pick_best_opportunity(candidates: list[dict]) -> Optional[dict]:
    """Adaylardan en iyi AL/SAT firsatini secer."""
    if not candidates:
        return None
    if len(candidates) == 1:
        return {"symbol": candidates[0]["symbol"], "reason_tr": "Tek uygun aday"}

    settings.reload_settings()
    key = settings.GEMINI_API_KEY
    if not key or not is_valid_api_key_format(key):
        best = max(candidates, key=lambda c: c.get("strength", 0))
        return {
            "symbol": best["symbol"],
            "reason_tr": "Gemini yok — en yuksek teknik guc secildi",
        }

    lines = []
    for c in candidates:
        lines.append(
            f"- {c['symbol']}: sinyal={c.get('signal')} guc={c.get('strength', 0):.0%} "
            f"haber={c.get('sentiment_label', 'N/A')} ({c.get('sentiment_score', 0):+.2f}) "
            f"fiyat=${c.get('price', 0):,.2f} · {c.get('reason', '')[:80]}"
        )

    prompt = f"""Sen kripto portfoy yoneticisisin. Asagidaki adaylardan TEK bir parite sec.
Yalnizca gecerli JSON dondur:
{{
  "symbol": "PARITE (ornek ETHUSDT)",
  "reason_tr": "Turkce kisa secim gerekcesi (max 120 karakter)"
}}

ADAYLAR:
{chr(10).join(lines)}

Risk/getiri dengesine gore en iyi firsati sec. Sadece listedeki sembollerden birini yaz."""

    raw = _call_gemini(prompt, max_tokens=300)
    parsed = _extract_json(raw)
    if parsed and parsed.get("symbol"):
        sym = str(parsed["symbol"]).upper()
        if any(c["symbol"] == sym for c in candidates):
            return {
                "symbol": sym,
                "reason_tr": str(parsed.get("reason_tr", "Gemini secimi"))[:120],
            }

    best = max(candidates, key=lambda c: c.get("strength", 0))
    return {
        "symbol": best["symbol"],
        "reason_tr": "Gemini parse hatasi — en yuksek guc secildi",
    }
