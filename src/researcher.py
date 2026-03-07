"""
AI-powered Market Researcher with Telegram Alerts
"""
import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional, List
from pathlib import Path

from config import get_config

_SRC_DIR = Path(__file__).parent

logger = logging.getLogger(__name__)


def _fmt_vol(v: float) -> str:
    """Format volume as compact string: $1.2M, $420K, $92K."""
    if v >= 1_000_000:
        return f"${v/1_000_000:.1f}M"
    elif v >= 1_000:
        return f"${v/1_000:.0f}K"
    return f"${v:.0f}"


def _truncate(text: str, limit: int = 72) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0] + "..."


def _build_market_card(m: Dict[str, Any]) -> str:
    """Build a single HTML market card with direction, edge, confidence, and AI reasoning."""
    import html as html_lib
    prob = m.get("probability", 0.5)
    insights = m.get("insights", {})
    groq = insights.get("groq_analysis", {})

    ai_estimate = groq.get("estimated_true_probability", prob)
    edge = groq.get("edge", ai_estimate - prob)
    confidence = groq.get("confidence", 0.0)
    direction = groq.get("direction", "HOLD")
    reasoning = groq.get("reasoning", "")

    if direction == "BUY_YES":
        signal = "🟢 <b>BUY YES</b>"
    elif direction == "BUY_NO":
        signal = "🔴 <b>BUY NO</b>"
    else:
        signal = "⚪ HOLD"

    conf_str = f"<b>{confidence:.0%}</b>" if confidence >= 0.75 else f"{confidence:.0%}"
    vol_24h = _fmt_vol(m.get("volume_24hr", m.get("volume", 0)))
    end_date = (m.get("end_date", "") or "")[:10] or "?"
    question = html_lib.escape(_truncate(m.get("question", "Unknown"), 72))
    url = m.get("url", "")
    reasoning_snippet = html_lib.escape(reasoning[:160] + ("..." if len(reasoning) > 160 else ""))

    lines = [
        f"{signal} — Market: {prob:.0%} → AI: {ai_estimate:.0%}",
        f"<b><a href='{url}'>{question}</a></b>",
        f"Edge: <b>{edge:+.0%}</b> | Confidence: {conf_str} | Vol 24h: {vol_24h} | Ends: {end_date}",
    ]
    if reasoning_snippet:
        lines.append(f"💡 <i>{reasoning_snippet}</i>")
    return "\n".join(lines)


async def send_telegram_alert(config, markets_with_research: List[Dict[str, Any]]) -> None:
    """Send Telegram alert with market research — high-confidence plays only."""
    if not config.telegram_bot_token or not config.telegram_chat_id:
        logger.warning("Telegram not configured - skipping alert")
        return

    try:
        import httpx

        # Filter to high-confidence, high-edge plays only
        def _is_actionable(m: Dict[str, Any]) -> bool:
            groq = m.get("insights", {}).get("groq_analysis", {})
            edge = abs(groq.get("edge", 0))
            confidence = groq.get("confidence", 0)
            direction = groq.get("direction", "HOLD")
            return edge > 0.05 and confidence > 0.60 and direction != "HOLD"

        actionable = [m for m in markets_with_research if _is_actionable(m)]
        filtered_count = len(markets_with_research) - len(actionable)

        # Sort by edge strength descending
        actionable.sort(key=lambda m: abs(m.get("insights", {}).get("groq_analysis", {}).get("edge", 0)), reverse=True)

        divider = "<code>─────────────────────────────</code>"
        lines = [
            "📊 <b>Polymarket Research Report</b>",
            f"<i>Scanned {len(markets_with_research)} markets — {len(actionable)} high-confidence plays found</i>",
            divider,
            "",
        ]

        if actionable:
            for m in actionable[:8]:
                lines.append(_build_market_card(m))
                lines.append("")
        else:
            lines.append("<i>No high-confidence plays this scan. All markets below edge/confidence threshold.</i>")
            lines.append("")

        lines.append(divider)
        lines.append(f"<i>{filtered_count} markets below edge/confidence threshold — not shown</i>")

        msg = "\n".join(lines)

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"https://api.telegram.org/bot{config.telegram_bot_token}/sendMessage",
                json={
                    "chat_id": config.telegram_chat_id,
                    "text": msg,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                }
            )
            if response.status_code == 200:
                logger.info("Telegram alert sent successfully.")
            else:
                logger.error(f"Telegram API error {response.status_code}: {response.text[:200]}")

    except Exception as e:
        logger.error(f"Failed to send Telegram alert: {e}")


class Researcher:
    """Conducts AI-powered research on Polymarket markets"""

    CACHE_TTL_HOURS = 4  # Reject cache entries older than this

    def __init__(self, config):
        self.config = config
        self.cache_dir = _SRC_DIR.parent / "data" / "cache"

    async def research_market(self, market: Dict[str, Any], use_cache: bool = True) -> Dict[str, Any]:
        """
        Perform comprehensive research on a market

        Args:
            market: Market data from scraper
            use_cache: Whether to use cached results (default True)

        Returns:
            Research results with insights and analysis
        """
        market_id = market.get("id", "unknown")
        cache_file = self.cache_dir / f"research_{market_id}.json"

        # Check cache first (unless disabled), respecting TTL
        if use_cache and cache_file.exists():
            age_hours = (time.time() - cache_file.stat().st_mtime) / 3600
            if age_hours < self.CACHE_TTL_HOURS:
                logger.info(f"Loading cached research for market {market_id} ({age_hours:.1f}h old)")
                with open(cache_file, 'r') as f:
                    return json.load(f)
            else:
                logger.info(f"Cache expired for market {market_id} ({age_hours:.1f}h old), refreshing")

        logger.info(f"Researching market: {market.get('question', market.get('title', 'Unknown'))}")

        try:
            # Gather research data
            research_data = {
                "market_id": market_id,
                "title": market.get("title"),
                "url": market.get("url"),
                "research_timestamp": time.time(),
            }

            # Get historical sentiment for delta
            historical = self._get_historical_research(market_id)
            if historical:
                old_prob = historical.get("probability", market.get("probability", 0.5))
                new_prob = market.get("probability", 0.5)
                research_data["sentiment_delta"] = new_prob - old_prob
            else:
                research_data["sentiment_delta"] = 0.0

            # Call AI providers
            insights = await self._gather_insights(market)
            insights["sentiment_delta"] = research_data["sentiment_delta"]
            research_data["insights"] = insights

            # Calculate confidence scores
            research_data["confidence"] = self._calculate_confidence(insights)

            # Generate summary
            research_data["summary"] = self._generate_summary(insights)

            # Add probability for next delta check
            research_data["probability"] = market.get("probability")

            # Cache results
            await self._cache_research(cache_file, research_data)

            return research_data

        except Exception as e:
            logger.error(f"Error researching market {market_id}: {e}", exc_info=True)
            return {
                "market_id": market_id,
                "error": str(e),
                "confidence": 0.0,
            }

    async def _gather_insights(self, market: Dict[str, Any]) -> Dict[str, Any]:
        """Gather insights from AI providers"""
        insights = {
            "sentiment": None,
            "key_factors": [],
            "risks": [],
            "opportunities": [],
        }

        # Use Groq (FREE, fast Llama) - or basic if API fails
        groq_insights = await self._get_groq_insights(market)
        if groq_insights:
            insights["groq_analysis"] = groq_insights
            insights["sentiment"] = groq_insights.get("sentiment")
            insights["key_factors"] = groq_insights.get("key_factors", [])
            insights["risks"] = groq_insights.get("risks", [])
            insights["opportunities"] = groq_insights.get("opportunities", [])
        else:
            # Fallback to basic probability-based analysis
            prob = market.get("probability", 0.5)
            sentiment = "bullish" if prob > 0.6 else "bearish" if prob < 0.4 else "neutral"
            insights["sentiment"] = sentiment
            insights["key_factors"] = [f"Probability: {prob:.1%}", f"Volume: ${market.get('volume', 0):,.0f}"]
            insights["risks"] = ["Basic analysis only - AI unavailable"]
            insights["opportunities"] = ["Add valid API key for AI analysis"]

        # Combine insights
        insights.update(self._combine_insights(insights))

        return insights

    async def _get_groq_insights(self, market: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Get insights from Groq (FREE, fast Llama model)"""
        import os
        import httpx
        
        api_key = os.getenv("GROQ_API_KEY", "")
        if not api_key:
            logger.warning("GROQ_API_KEY not set - using basic analysis")
            prob = market.get("probability", 0.5)
            sentiment = "bullish" if prob > 0.6 else "bearish" if prob < 0.4 else "neutral"
            return {
                "sentiment": sentiment,
                "confidence": 0.6,
                "reasoning": f"Based on market probability of {prob:.1%}",
                "key_factors": [f"Current yes price: {prob:.1%}", f"Volume: ${market.get('volume', 0):,.0f}"],
                "risks": ["No AI analysis - set GROQ_API_KEY"],
                "opportunities": ["Set GROQ_API_KEY for deeper analysis"]
            }
        
        try:
            question = market.get("question", "Unknown market")
            prob = market.get("probability", 0.5)
            volume = market.get("volume", 0)
            volume_24h = market.get("volume_24hr", 0)
            end_date = market.get("end_date", "unknown")[:10] if market.get("end_date") else "unknown"
            category = market.get("category", "general")
            spread = abs(market.get("best_ask", prob) - market.get("best_bid", prob))
            url = market.get("url", "")

            prompt = f"""You are an expert prediction market analyst. Analyze this Polymarket binary market and estimate whether it is MISPRICED — i.e. whether the crowd probability diverges from the true probability.

Market: {question}
Category: {category}
Current YES Price: {prob:.1%}
Resolution Date: {end_date}
Total Volume: ${volume:,.0f}
24h Volume: ${volume_24h:,.0f}
Bid-Ask Spread: {spread:.3f}
URL: {url}

Provide your analysis as JSON with these fields:
1. "estimated_true_probability": your independent estimate of YES probability (0.0-1.0), based on your knowledge — NOT anchored to the market price
2. "edge": estimated_true_probability minus market price (positive = market underpricing YES, negative = market overpricing YES)
3. "direction": "BUY_YES", "BUY_NO", or "HOLD"
4. "confidence": your confidence in this assessment (0.0-1.0)
5. "resolution_risk": "LOW", "MEDIUM", or "HIGH" — how ambiguous is the resolution criteria?
6. "key_factors": list of 3 most important factors for resolution
7. "risks": list of 2 main risks to your thesis
8. "reasoning": 1-2 sentence explanation of the edge

Respond in JSON format only. Be honest if you have low confidence or insufficient information."""

            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": "llama-3.3-70b-versatile",
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": 500,
                        "temperature": 0.5
                    }
                )
                
                if response.status_code == 200:
                    result = response.json()
                    content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
                    
                    # Try to parse JSON from response
                    try:
                        import re
                        json_match = re.search(r'\{.*\}', content, re.DOTALL)
                        if json_match:
                            analysis = json.loads(json_match.group())
                            estimated_prob = float(analysis.get("estimated_true_probability", prob))
                            edge = estimated_prob - prob
                            sentiment = "bullish" if edge > 0.03 else "bearish" if edge < -0.03 else "neutral"
                            return {
                                "sentiment": sentiment,
                                "estimated_true_probability": estimated_prob,
                                "edge": round(edge, 3),
                                "direction": analysis.get("direction", "HOLD"),
                                "confidence": float(analysis.get("confidence", 0.5)),
                                "resolution_risk": analysis.get("resolution_risk", "MEDIUM"),
                                "reasoning": analysis.get("reasoning", "")[:300],
                                "key_factors": analysis.get("key_factors", [])[:3],
                                "risks": analysis.get("risks", [])[:3],
                            }
                    except Exception as parse_err:
                        logger.warning(f"Failed to parse Groq JSON response: {parse_err}")
                    
                    # Fallback if JSON parsing fails
                    return {
                        "sentiment": "bullish" if prob > 0.6 else "bearish" if prob < 0.4 else "neutral",
                        "confidence": 0.7,
                        "reasoning": f"AI analysis received ({len(content)} chars)",
                        "key_factors": [f"Probability: {prob:.1%}", f"Volume: ${volume:,.0f}"],
                        "risks": ["Parse error"],
                        "opportunities": ["Review raw response"]
                    }
                else:
                    logger.error(f"Groq API error: {response.status_code}")
                    
        except Exception as e:
            logger.error(f"Error calling Groq API: {e}")
        
        return None

    def _combine_insights(self, insights: Dict[str, Any]) -> Dict[str, Any]:
        """Combine insights from AI providers"""
        sentiments = []
        for key in ("groq_analysis", "openai_analysis", "anthropic_analysis"):
            if key in insights:
                sentiments.append(insights[key].get("sentiment"))

        if sentiments:
            bullish_count = sum(1 for s in sentiments if s == "bullish")
            bearish_count = sum(1 for s in sentiments if s == "bearish")
            if bullish_count > bearish_count:
                overall_sentiment = "bullish"
            elif bearish_count > bullish_count:
                overall_sentiment = "bearish"
            else:
                overall_sentiment = "neutral"
        else:
            overall_sentiment = "unknown"

        return {
            "overall_sentiment": overall_sentiment,
            "provider_count": len([k for k in insights.keys() if k.endswith("_analysis")]),
        }

    def _calculate_confidence(self, insights: Dict[str, Any]) -> float:
        """Calculate overall confidence score"""
        confidences = []
        for key in ("groq_analysis", "openai_analysis", "anthropic_analysis"):
            if key in insights:
                confidences.append(float(insights[key].get("confidence", 0)))

        return sum(confidences) / len(confidences) if confidences else 0.0

    def _generate_summary(self, insights: Dict[str, Any]) -> str:
        """Generate human-readable summary"""
        overall_sentiment = insights.get("overall_sentiment", "unknown")
        confidence = insights.get("confidence", 0)

        return (
            f"Sentiment: {overall_sentiment} (confidence: {confidence:.1%}). "
            f"Analysis based on {insights.get('provider_count', 0)} AI provider(s)."
        )

    async def _cache_research(self, cache_file: Path, research_data: Dict[str, Any]):
        """Cache research results to disk"""
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        with open(cache_file, 'w') as f:
            json.dump(research_data, f, indent=2)
        logger.debug(f"Cached research to {cache_file}")

    def _get_historical_research(self, market_id: str) -> Optional[Dict[str, Any]]:
        """Load cached research for delta calculation. Returns None if missing or expired."""
        cache_file = self.cache_dir / f"research_{market_id}.json"
        if cache_file.exists():
            try:
                age_hours = (time.time() - cache_file.stat().st_mtime) / 3600
                if age_hours < self.CACHE_TTL_HOURS:
                    with open(cache_file, 'r') as f:
                        return json.load(f)
            except Exception as e:
                logger.warning(f"Error loading historical cache for {market_id}: {e}")
        return None