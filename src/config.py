"""
Configuration management for Polymarket Research Bot
"""
import os
from dataclasses import dataclass
from typing import Optional
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    """Application configuration"""

    # Polymarket - uses free Gamma API (no auth required)
    polymarket_url: str = os.getenv("POLYMARKET_URL", "https://polymarket.com")
    
    # AI - Groq (FREE) - faster than NVIDIA NIM
    groq_api_key: str = os.getenv("GROQ_API_KEY", "")
    
    # Telegram Alerts
    telegram_bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    telegram_chat_id: str = os.getenv("TELEGRAM_CHAT_ID", "")
    
    # Logging
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    log_file: Optional[str] = os.getenv("LOG_FILE")

    # Research
    research_interval: int = int(os.getenv("RESEARCH_INTERVAL", "3600"))  # 1 hour default
    max_markets_per_run: int = int(os.getenv("MAX_MARKETS_PER_RUN", "10"))
    enable_alerts: bool = os.getenv("ENABLE_ALERTS", "true").lower() == "true"
    
    # Filter
    min_volume: float = float(os.getenv("MIN_VOLUME", "500000"))  # $100K min volume

    @classmethod
    def validate(cls) -> list[str]:
        """Validate configuration and return list of errors"""
        errors = []

        # Only require Telegram if alerts are enabled
        if cls.enable_alerts:
            if not cls.telegram_bot_token:
                errors.append("TELEGRAM_BOT_TOKEN required for alerts")
            if not cls.telegram_chat_id:
                errors.append("TELEGRAM_CHAT_ID required for alerts")

        return errors


def get_config() -> Config:
    """Get application config instance"""
    return Config()
