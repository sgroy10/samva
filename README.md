# Samva

Multi-tenant WhatsApp personal assistant SaaS. Two processes — Node.js WhatsApp bridge (Baileys + Express) and Python core API (FastAPI + Gemini 2.5 Flash).

## Quick Start

```bash
cp .env.example .env
# Fill in API keys

# Start both services
bash start.sh
```

## Architecture

- **Bridge** (port 3000): Express + Baileys. Serves landing page, manages WhatsApp sessions, proxies /api/* to Python.
- **API** (port 8000): FastAPI. AI logic, database, skills. Gemini 2.5 Flash via OpenRouter.

## Environment Variables

| Variable | Description |
|---|---|
| DATABASE_URL | PostgreSQL connection string (or SQLite for local dev) |
| OPENROUTER_API_KEY | OpenRouter API key for Gemini |
| GEMINI_API_KEY | Direct Gemini API key (voice transcription) |
| RAZORPAY_KEY_ID | Razorpay key ID |
| RAZORPAY_KEY_SECRET | Razorpay key secret |
| ENCRYPTION_KEY | Fernet key for encrypting email passwords |

## Deploy to Railway

Push to GitHub and connect via Railway. The Procfile and railway.json handle the rest.
