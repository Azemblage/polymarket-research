"""
AI-powered Market Researcher with Telegram Alerts
"""
import asyncio
import json
import logging
from typing import Any, Dict, Optional, List
from pathlib import Path

from config import get_config

logger = logging.getLogger(__name__)


async def send_telegram_alert(config, markets_with_research: List[Dict[str, Any]]) -> None:
    """Send Telegram alert with market research"""
    if not config.telegram_bot_token or not config.telegram_chat_id:
        logger.warning("Telegram not configured - skipping alert")
        return
    
    try:
        import httpx
        
        # Categorize markets
        green_markets = [m for m in markets_with_research if m.get("probability", 0) > 0.80]
        yellow_markets = [m for m in markets_with_research if 0.60 < m.get("probability", 0) <= 0.80]
        
        # Build message
        lines = [
            "🎯 Polymarket Research Report",
            "=" * 35,
            f"Scanned {len(markets_with_research)} markets | Found {len(green_markets)} SURE BETS",
            ""
        ]
        
        # GREEN - SURE BETS
        if green_markets:
            lines.append("🟢 SURE BETS (>80% - BUY YES):")
            for m in sorted(green_markets, key=lambda x: x.get("probability", 0), reverse=True)[:10]:
                prob = m.get("probability", 0) * 100
                lines.append(f"✅ {prob:.0f}% | ${m.get('volume', 0):,.0f}")
                lines.append(f"   {m.get('question', '')}")
                lines.append(f"   🔗 {m.get('url', '')}")
            lines.append("")
        else:
            lines.append("No sure bets found this scan.")
        
        
        msg = "\n".join(lines)
        
        # Send via Telegram
        async with httpx.AsyncClient(timeout=30.0) as client:
            await client.post(
                f"https://api.telegram.org/bot{config.telegram_bot_token}/sendMessage",
                json={
                    "chat_id": config.telegram_chat_id,
                    "text": msg,
                    "parse_mode": "Markdown"
                }
            )
            logger.info("Telegram alert sent!")
            
    except Exception as e:
        logger.error(f"Failed to send Telegram alert: {e}")


class Researcher:
    """Conducts AI-powered research on Polymarket markets"""

    def __init__(self, config):
        self.config = config
        self.cache_dir = Path("data/cache")

    async def research_market(self, market: Dict[str, Any]) -> Dict[str, Any]:
        """
        Perform comprehensive research on a market

        Args:
            market: Market data from scraper

        Returns:
            Research results with insights and analysis
        """
        market_id = market.get("id", "unknown")
        cache_file = self.cache_dir / f"research_{market_id}.json"

        # Check cache first
        if cache_file.exists():
            logger.info(f"Loading cached research for market {market_id}")
            with open(cache_file, 'r') as f:
                return json.load(f)

        logger.info(f"Researching market: {market.get('question', market.get('title', 'Unknown'))}")

        try:
            # Gather research data
            research_data = {
                "market_id": market_id,
                "title": market.get("title"),
                "url": market.get("url"),
                "research_timestamp": asyncio.get_event_loop().time(),
            }

            # Call AI providers
            insights = await self._gather_insights(market)
            research_data["insights"] = insights

            # Calculate confidence scores
            research_data["confidence"] = self._calculate_confidence(insights)

            # Generate summary
            research_data["summary"] = self._generate_summary(insights)

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
            url = market.get("url", "")
            
            prompt = f"""You are a crypto prediction market analyst. Analyze this Polymarket market:

Market: {question}
Current Yes Probability: {prob:.1%}
Volume: ${volume:,.0f}
URL: {url}

Provide a brief analysis with:
1. sentiment: "bullish", "bearish", or "neutral" 
2. confidence: 0.0-1.0
3. key_factors: list of 3 important factors
4. risks: list of 2-3 risks
5. opportunities: list of 2-3 opportunities
6. reasoning: brief explanation

Respond in JSON format only."""

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
                            return {
                                "sentiment": analysis.get("sentiment", "neutral"),
                                "confidence": float(analysis.get("confidence", 0.5)),
                                "reasoning": analysis.get("reasoning", "")[:200],
                                "key_factors": analysis.get("key_factors", [])[:3],
                                "risks": analysis.get("risks", [])[:3],
                                "opportunities": analysis.get("opportunities", [])[:3]
                            }
                    except:
                        pass
                    
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
        """Combine insights from multiple AI providers"""
        sentiments = []

        if "openai_analysis" in insights:
            sentiments.append(insights["openai_analysis"].get("sentiment"))

        if "anthropic_analysis" in insights:
            sentiments.append(insights["anthropic_analysis"].get("sentiment"))

        # Determine overall sentiment (simple majority)
        if sentiments:
            bullish_count = sum(1 for s in sentiments if s == "bullish")
            bearish_count = sum(1 for s in sentiments if s == "bearish")
            neutral_count = sum(1 for s in sentiments if s == "neutral")

            if bullish_count > bearish_count and bullish_count > neutral_count:
                overall_sentiment = "bullish"
            elif bearish_count > bullish_count and bearish_count > neutral_count:
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

        if "openai_analysis" in insights:
            confidences.append(insights["openai_analysis"].get("confidence", 0))

        if "anthropic_analysis" in insights:
            confidences.append(insights["anthropic_analysis"].get("confidence", 0))

        if confidences:
            return sum(confidences) / len(confidences)
        return 0.0

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