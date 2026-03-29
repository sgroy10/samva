from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    database_url: str = "sqlite+aiosqlite:///./data/db/samva.db"
    openrouter_api_key: str = ""
    samva_model: str = "google/gemini-2.5-flash"
    gemini_api_key: str = ""  # voice transcription
    encryption_key: str = ""  # IMAP passwords
    gemlens_api_key: str = ""  # GemLens jewelry image analysis
    jewelcraft_api_key: str = ""  # JewelCraft AI (render, enhance, ads, VTO)
    jewelcraft_base_url: str = "https://ihggfkujfvfdiadpqnnn.supabase.co/functions/v1"
    bridge_url: str = "http://localhost:3000"
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_phone_number: str = ""
    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    owner_phone: str = ""
    admin_phone: str = ""  # Admin gets free access, no payment required
    timezone: str = "Asia/Kolkata"
    debug: bool = False

    class Config:
        env_file = (".env", "../../.env")
        extra = "ignore"


settings = Settings()
