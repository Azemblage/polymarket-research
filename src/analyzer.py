"""
Market Analysis and Insights Generator
"""
import json
import logging
from pathlib import Path
from typing import Any, Dict, List

from config import get_config

logger = logging.getLogger(__name__)


class Analyzer:
    """Analyzes market data and research results"""

    def __init__(self, config):
        self.config = config
        self.processed_dir = Path("data/processed")

    def analyze_market(self, market: Dict[str, Any], research_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze a market with its research data

        Args:
            market: Market data from scraper
            research_data: Research results from researcher

        Returns:
            Analysis with recommendations and metrics
        """
        analysis = {
            "market_id": market.get("id"),
            "title": market.get("title"),
            "timestamp": research_data.get("research_timestamp"),
        }

        # Price analysis
        price_analysis = self._analyze_prices(market)
        analysis["price_analysis"] = price_analysis

        # Sentiment analysis
        sentiment_score = self._calculate_sentiment_score(research_data)
        analysis["sentiment_score"] = sentiment_score
        analysis["sentiment"] = research_data.get("insights", {}).get("overall_sentiment", "unknown")

        # Confidence
        analysis["confidence"] = research_data.get("confidence", 0.0)

        # Liquidity analysis
        liquidity_metrics = self._analyze_liquidity(market)
        analysis["liquidity_metrics"] = liquidity_metrics

        # Volume analysis
        volume_metrics = self._analyze_volume(market)
        analysis["volume_metrics"] = volume_metrics

        # Generate recommendation
        recommendation = self._generate_recommendation(analysis)
        analysis["recommendation"] = recommendation

        # Risk assessment
        analysis["risk_factors"] = self._assess_risks(market, research_data)

        # Save analysis
        self._save_analysis(analysis)

        return analysis

    def _analyze_prices(self, market: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze market prices"""
        yes_price = market.get("yes_price", 0.5)
        no_price = market.get("no_price", 0.5)
        spread = abs(yes_price - no_price)

        return {
            "yes_price": yes_price,
            "no_price": no_price,
            "spread": spread,
            "implied_probability": yes_price,
            "mid_price": (yes_price + (1 - no_price)) / 2 if no_price > 0 else 0.5,
        }

    def _calculate_sentiment_score(self, research_data: Dict[str, Any]) -> float:
        """Calculate normalized sentiment score (-1 to 1)"""
        sentiment = research_data.get("insights", {}).get("overall_sentiment", "neutral")
        confidence = research_data.get("confidence", 0.5)

        if sentiment == "bullish":
            base_score = 1.0
        elif sentiment == "bearish":
            base_score = -1.0
        else:
            base_score = 0.0

        # Weight by confidence
        return base_score * confidence

    def _analyze_liquidity(self, market: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze market liquidity"""
        liquidity = market.get("liquidity", 0)
        volume = market.get("volume", 0)

        # Determine liquidity tier
        if liquidity > 1000000:
            tier = "high"
        elif liquidity > 100000:
            tier = "medium"
        else:
            tier = "low"

        return {
            "liquidity": liquidity,
            "volume": volume,
            "tier": tier,
            "liquid_cushion": liquidity / max(volume, 1),
        }

    def _analyze_volume(self, market: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze trading volume"""
        volume = market.get("volume", 0)

        # Determine volume tier
        if volume > 500000:
            tier = "high"
        elif volume > 100000:
            tier = "medium"
        else:
            tier = "low"

        return {
            "volume": volume,
            "tier": tier,
            "volume_rank": None,  # Would need market set for ranking
        }

    def _generate_recommendation(self, analysis: Dict[str, Any]) -> Dict[str, Any]:
        """Generate trading recommendation"""
        sentiment = analysis.get("sentiment")
        confidence = analysis.get("confidence", 0)
        liquidity_tier = analysis.get("liquidity_metrics", {}).get("tier", "low")

        # Simple recommendation logic
        if confidence < 0.6:
            action = "HOLD"
            reason = "Low confidence in prediction"
        elif liquidity_tier == "low":
            action = "CAUTION"
            reason = "Low liquidity may cause slippage"
        elif sentiment == "bullish":
            action = "BUY YES"
            reason = f"Bullish sentiment with {confidence:.1%} confidence"
        elif sentiment == "bearish":
            action = "BUY NO"
            reason = f"Bearish sentiment with {confidence:.1%} confidence"
        else:
            action = "HOLD"
            reason = "Neutral sentiment"

        return {
            "action": action,
            "reason": reason,
            "confidence": confidence,
            "max_position_size": self._calculate_position_size(analysis),
        }

    def _calculate_position_size(self, analysis: Dict[str, Any]) -> float:
        """Calculate recommended position size (as % of liquidity)"""
        liquidity = analysis.get("liquidity_metrics", {}).get("liquidity", 0)
        confidence = analysis.get("confidence", 0)

        if liquidity == 0 or confidence < 0.7:
            return 0.0

        # Conservative position sizing: max 5% of liquidity
        base_size = min(0.05, confidence * 0.1)

        # Adjust for liquidity depth
        if liquidity > 1000000:
            multiplier = 1.0
        elif liquidity > 100000:
            multiplier = 0.7
        else:
            multiplier = 0.3

        return base_size * multiplier

    def _assess_risks(self, market: Dict[str, Any], research_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Identify and assess risk factors"""
        risks = []

        # Low liquidity risk
        if market.get("liquidity", 0) < 100000:
            risks.append({
                "type": "liquidity",
                "severity": "high" if market.get("liquidity", 0) < 50000 else "medium",
                "description": "Low market liquidity may cause execution issues",
            })

        # Low confidence risk
        if research_data.get("confidence", 0) < 0.6:
            risks.append({
                "type": "prediction",
                "severity": "high",
                "description": "Low confidence in AI analysis",
            })

        # High spread risk
        if market.get("yes_price", 0.5) - market.get("no_price", 0.5) > 0.3:
            risks.append({
                "type": "pricing",
                "severity": "medium",
                "description": "Wide bid-ask spread indicates inefficient pricing",
            })

        return risks

    def _save_analysis(self, analysis: Dict[str, Any]):
        """Save analysis to disk"""
        market_id = analysis.get("market_id", "unknown")
        timestamp = analysis.get("timestamp", 0)
        analysis_file = self.processed_dir / f"analysis_{market_id}_{int(timestamp)}.json"

        analysis_file.parent.mkdir(parents=True, exist_ok=True)
        with open(analysis_file, 'w') as f:
            json.dump(analysis, f, indent=2)

        logger.debug(f"Saved analysis to {analysis_file}")