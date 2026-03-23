from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    database_url: str = "sqlite+aiosqlite:///./data/db/samva.db"
    openrouter_api_key: str = ""
    samva_model: str = "google/gemini-2.5-flash"
    gemini_api_key: str = ""  # voice transcription
    encryption_key: str = ""  # IMAP passwords
    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    owner_phone: str = ""
    timezone: str = "Asia/Kolkata"
    debug: bool = False

    class Config:
        env_file = (".env", "../../.env")
        extra = "ignore"


settings = Settings()
