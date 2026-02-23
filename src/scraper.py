"""

Polymarket Scraper using Gamma API (free, no key required)
"""
import asyncio
import json
import logging
from typing import Any, Dict, List
from pathlib import Path
import httpx

from config import get_config

logger = logging.getLogger(__name__)

# Gamma API Base URL (free, no key required)
GAMMA_API = "https://gamma-api.polymarket.com"


class PolymarketScraper:
    """Scrapes Polymarket data using free Gamma API"""

    def __init__(self, config):
        self.config = config
        self.base_url = GAMMA_API

    async def __aenter__(self):
        """Async context manager entry"""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        pass

    async def scrape_markets(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Scrape active markets from Polymarket using Gamma API with live prices"""
        markets = []

        try:
            logger.info("Fetching active markets from Polymarket Gamma API")
            
            # Use /markets endpoint for live prices
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{self.base_url}/markets",
                    params={
                        "active": "true",
                        "closed": "false",
                        "limit": limit
                    }
                )
                
                if response.status_code == 200:
                    data = response.json()
                    logger.info(f"Found {len(data)} active markets")
                    
                    for m in data:
                        volume = float(m.get("volumeNum", 0) or 0)
                        liquidity = float(m.get("liquidityNum", 0) or 0)
                        
                        # Use lastTradePrice or bestBid/bestAsk for live price
                        last_price = m.get("lastTradePrice")
                        best_bid = m.get("bestBid")
                        best_ask = m.get("bestAsk")
                        
                        # Use mid-price from bid/ask, or last trade
                        if best_bid and best_ask:
                            yes_price = (float(best_bid) + float(best_ask)) / 2
                        elif last_price:
                            yes_price = float(last_price)
                        else:
                            yes_price = 0.5
                        
                        market_data = {
                            "id": str(m.get("id", "")),
                            "question": m.get("question", ""),
                            "slug": m.get("slug", ""),
                            "url": f"https://polymarket.com/market/{m.get('slug', '')}",
                            "volume": volume,
                            "volume_24hr": float(m.get("volume24hr", 0) or 0),
                            "liquidity": liquidity,
                            "yes_price": yes_price,
                            "no_price": 1.0 - yes_price,
                            "probability": yes_price,
                            "best_bid": float(best_bid) if best_bid else 0,
                            "best_ask": float(best_ask) if best_ask else 0,
                            "end_date": m.get("endDate", ""),
                            "category": m.get("category", ""),
                        }
                        markets.append(market_data)
                    
                    logger.info(f"Extracted {len(markets)} markets with live prices")
                else:
                    logger.error(f"API returned status {response.status_code}: {response.text}")

            # Save raw data
            self._save_raw_data(markets)

        except Exception as e:
            logger.error(f"Error scraping markets: {e}", exc_info=True)

        return markets

    async def scrape_by_slug(self, slug: str) -> Dict[str, Any]:
        """Scrape a specific market by slug"""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{self.base_url}/markets",
                    params={"slug": slug}
                )
                
                if response.status_code == 200:
                    markets = response.json()
                    if markets:
                        return markets[0]
                        
        except Exception as e:
            logger.error(f"Error fetching market by slug {slug}: {e}")
            
        return {}

    async def scrape_by_tag(self, tag_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Scrape markets by tag (category)"""
        markets = []
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    f"{self.base_url}/events",
                    params={
                        "tag_id": tag_id,
                        "active": "true",
                        "closed": "false",
                        "limit": limit
                    }
                )
                
                if response.status_code == 200:
                    events = response.json()
                    for event in events:
                        for market in event.get("markets", []):
                            markets.append(market)
                            
        except Exception as e:
            logger.error(f"Error scraping by tag {tag_id}: {e}")
            
        return markets

    def _save_raw_data(self, markets: List[Dict[str, Any]]):
        """Save raw scraped data to file"""
        import time
        data_file = Path("data/raw") / f"markets_{int(time.time())}.json"
        data_file.parent.mkdir(parents=True, exist_ok=True)

        with open(data_file, 'w') as f:
            json.dump(markets, f, indent=2)

        logger.info(f"Saved raw data to {data_file}")


async def main():
    """Standalone scraper test"""
    async with PolymarketScraper(None) as scraper:
        markets = await scraper.scrape_markets(limit=20)
        print(f"\n📊 Scraped {len(markets)} markets from Polymarket!\n")
        
        # Show top 5 by volume
        sorted_markets = sorted(markets, key=lambda x: x.get("volume", 0), reverse=True)[:5]
        
        for i, m in enumerate(sorted_markets, 1):
            prob = m.get("probability", 0.5) * 100
            print(f"{i}. {m.get('question', 'N/A')[:60]}...")
            print(f"   💰 Vol: ${m.get('volume', 0):,.0f} | 📈 Yes: {prob:.1f}% | 🔗 {m.get('url', '')}")
            print()


if __name__ == "__main__":
    asyncio.run(main())
