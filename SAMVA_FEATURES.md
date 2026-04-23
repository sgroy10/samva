# SAMVA — Sam, Your Personal WhatsApp AI Agent

**Repository:** https://github.com/sgroy10/samva  
**Live URL:** https://romantic-generosity-production.up.railway.app  
**Platform:** WhatsApp (via Baileys)  
**Current Version:** 2026-04-22-v2  
**Codebase:** 187 commits | 47 Python service files | 18,500+ lines of code  
**Built by:** Sandeep Roy (sgroy10) with Claude Code  
**Development Period:** April 2026 (20 days)

---

## What is Samva?

Samva is a personal AI agent that lives inside your WhatsApp. Not a chatbot — an **agent** that knows you, remembers everything, manages your day, and speaks your language.

You message Sam the same way you message a friend. Sam reads your tone, knows your family, tracks your business, reminds you about things you forgot, and does the work — from generating PDFs to checking gold rates to booking follow-ups.

Sam is designed for India-first users: jewellers, small business owners, professionals, families. It speaks Hindi, English, Hinglish, Tamil, Gujarati, Marathi, and more. It knows Indian festivals, understands "lakh" and "crore", tracks Nifty and gold, and says "ji" when appropriate.

---

## What Sam Does Today (Verified, Working)

### Core Intelligence
| Feature | What It Does | How It Works |
|---------|-------------|--------------|
| **Conversational AI** | Natural chat in Hindi/English/Hinglish with personality, humor, and opinions | Gemini 2.5 Flash via OpenRouter with 400-line personality layer |
| **Memory (Hermes-style)** | Silently learns your preferences from conversations — wife's name, dietary choices, work patterns | Background LLM review every 5th message, saves to PostgreSQL with validation |
| **Empathy Engine** | Detects emotional context (hospital, stress, loneliness, celebrations) and responds as a friend first | 30+ emotional trigger words route to empathy-first prompts before any task handling |
| **Smart Routing** | Simple messages ("hi", "thanks") get instant responses; complex queries go through full processing | Message length + keyword analysis determines routing path |
| **Language Matching** | Responds in whatever language you write — pure Hindi, pure English, Tamil, Gujarati, Hinglish | Language detection + enforcement post-processor strips cross-language contamination |
| **Voice Notes** | Send a voice note, Sam listens, understands, and replies with a voice note in your language | Gemini ASR for transcription, Gemini TTS with Kore/Puck voices, emotion-aware tone |

### Business & Finance
| Feature | What It Does | How It Works |
|---------|-------------|--------------|
| **Gold/Silver/Platinum Rates** | Live rates in INR per gram with daily change arrows | Gold-API.com + Open Exchange Rates for USD/INR conversion |
| **Morning Brief** | Daily gold brief at your configured time (default 9 AM IST) with expert market view | Cron job checks user's brief_time, generates text + optional voice note |
| **EMI Calculator** | "50 lakh loan 8.5% 20 years" → instant EMI with total payment and interest breakdown | Handles lakh/crore in natural language, standard EMI formula |
| **Currency Conversion** | Any currency pair: "40000 thai baht to usd" → instant conversion | Open Exchange Rates API with 20+ currency name mappings (baht, yuan, riyal, etc.) |
| **Invoice/Quotation PDF** | "invoice bana do Rahul ke liye 22k chain 55000" → real PDF sent on WhatsApp | LLM extracts details → fpdf2 generates formatted document |
| **GST Calculator** | Product-wise GST rates for Indian businesses | Built-in rate database covering 50+ product categories |
| **FD Calculator** | Fixed deposit maturity calculation with compound interest | Standard compound interest formula |
| **Mutual Fund NAV** | Live NAV for Indian mutual funds | mftool library with public AMFI data |

### Productivity
| Feature | What It Does | How It Works |
|---------|-------------|--------------|
| **Reminders** | "yaad dila dena kal 9 baje meeting" → alarm set | Natural language time parsing, supports daily/weekly/monthly repeats |
| **Contact Management** | "save contact Ravi 9876543210 supplier" → saved permanently, searchable | Gemini extracts name/phone/tag, saves to Contacts table |
| **Email Check** | "check email" → smart summary of unread emails with urgency flags | IMAP fetch with Gemini summarization, tracks last-synced timestamp |
| **PDF Generation** | Any document: itinerary, business plan, goals, letter, meeting notes → real PDF | LLM generates content → fpdf2 renders → WhatsApp sends as document |
| **Meeting Notes** | Voice-describe a meeting → structured summary with action items and contacts saved | Transcription → Gemini structuring → auto-save contacts and reminders |

### Web & Search
| Feature | What It Does | How It Works |
|---------|-------------|--------------|
| **Web Search** | Any question about current events, prices, facts → real-time answer | Perplexity Sonar via OpenRouter (primary) + DuckDuckGo HTML (fallback) |
| **Weather** | "mumbai weather" → live temperature, humidity, conditions | OpenWeatherMap API |
| **Pincode/IFSC Lookup** | "pincode 400001" or "SBIN0001234" → instant details | India Post API + bank IFSC lookup |

### Astrology & Culture
| Feature | What It Does | How It Works |
|---------|-------------|--------------|
| **Rashifal** | Daily horoscope for any rashi in full Hindi | LLM-generated with date-aware prompting |
| **Kundli** | Birth chart analysis from date, time, place | LLM-based Vedic astrology with lagna/nakshatra calculation |
| **Panchang** | Today's tithi, nakshatra, rahu kaal | Date-aware calculation |
| **Festival Awareness** | Auto-wishes on 27 Indian festivals | Date-matched from built-in calendar |

### Proactive Behavior
| Feature | What It Does | How It Works |
|---------|-------------|--------------|
| **Morning Nudge (8-9 AM)** | Good morning + unreplied message count | Cron-triggered personality nudge |
| **Lunch Check (12:30-1:30 PM)** | "Lunch kar liya?" with option to analyze food photo | Time-window nudge |
| **Evening Wrap-up (6-7 PM)** | Day summary + reminder prompt | Time-window nudge |
| **Unreplied Message Alerts** | "Ravi ka reply pending hai — kal se" | InboxMessage table scan for unreplied contacts |
| **Fallback Check-in** | If nothing else triggers, Sam sends a varied topic every 4 hours | Rotating topic pool to avoid repetition |
| **Nightly Diary** | 10 PM daily summary of the day as a voice note | Cron job, LLM summarization, Gemini TTS |

### Safety
| Feature | What It Does | How It Works |
|---------|-------------|--------------|
| **SOS Detection** | Detects emergency keywords → provides emergency numbers immediately | Priority routing before ALL other processing |
| **Chest Pain / Medical** | Shows genuine concern + urges doctor visit + offers to call someone | Empathy-first routing with medical-specific prompts |
| **Night Safety Check (10-11 PM)** | "Ghar pahunch gaye? Sab theek?" | Late-night time-window nudge |

---

## Tech Stack

### Backend (Python)
| Component | Technology | Purpose |
|-----------|-----------|---------|
| **API Framework** | FastAPI | Async API server, handles all message processing |
| **LLM Provider** | OpenRouter (Gemini 2.5 Flash) | Primary LLM for all chat, classification, and generation |
| **Database** | PostgreSQL (Railway-hosted) | Users, conversations, memories, contacts, reminders, skills |
| **ORM** | SQLAlchemy 2.0 (async) | All database operations with asyncpg driver |
| **Voice ASR** | Gemini API (direct) | Audio transcription from WhatsApp voice notes |
| **Voice TTS** | Gemini TTS (Kore/Puck voices) | Voice note generation with emotion detection |
| **PDF Generation** | fpdf2 | Invoice, quotation, itinerary, custom document PDFs |
| **Web Search** | Perplexity Sonar via OpenRouter | Real-time web search with citations |
| **Web Search Fallback** | DuckDuckGo HTML | Captcha-free fallback search |
| **Email** | imaplib (IMAP) + smtplib (SMTP) | Email reading and sending with encryption |
| **Gold Rates** | Gold-API.com | Live precious metal prices |
| **Weather** | OpenWeatherMap API | Live weather data |
| **Currency** | Open Exchange Rates API | 170+ currency pairs |
| **Mutual Funds** | mftool | Indian MF NAV data |
| **Translation** | deep-translator | Multi-language translation |

### Bridge (Node.js)
| Component | Technology | Purpose |
|-----------|-----------|---------|
| **WhatsApp** | Baileys (WhatsApp Web API) | Multi-device WhatsApp connection without official API |
| **Session Management** | Custom session store | Persistent sessions with QR code pairing |
| **Cron Scheduler** | node-cron | 14 scheduled jobs for proactive features |
| **Audio Conversion** | ffmpeg | PCM → OGG Opus for WhatsApp voice notes |
| **HTTP Server** | Express.js | Bridge API for session and message management |

### Infrastructure
| Component | Technology | Purpose |
|-----------|-----------|---------|
| **Hosting** | Railway.app | Docker container, auto-SSL, persistent volumes |
| **Database** | Railway PostgreSQL | Managed PostgreSQL with automatic backups |
| **Domain** | samva.in | Landing page and QR code pairing |
| **Version Control** | GitHub (sgroy10/samva) | 187 commits, full history |
| **Deployment** | Railway CLI + manual verify | `railway up` → `railway redeploy` → health check |

---

## Architecture

```
User's WhatsApp
    ↓ (Baileys WebSocket)
[Bridge - Node.js]
    ├── Session Manager (connect, reconnect, QR pairing)
    ├── Message Handler (text, voice, image, document)
    ├── Cron Scheduler (14 jobs: alerts, briefs, diary, intelligence)
    └── Media Handler (voice→PCM→OGG, PDF delivery, image relay)
    ↓ (HTTP to localhost:8000)
[Core API - FastAPI]
    ├── Agent (message processor, intent detection, skill routing)
    ├── Orchestrator (7 layers of routing)
    │   ├── Layer 0: Document Generation (PDF detection)
    │   ├── Layer 0.4: Goal Tracking
    │   ├── Layer 0.5: Multi-step Workflows
    │   ├── Layer 1: Prebuilt Skills (30+ instant skills)
    │   ├── Layer 2: Intent Keywords (reminder, email, contact routing)
    │   ├── Layer 2.5: Custom Skills (disabled — was auto-building broken skills)
    │   └── Layer 4: Smart General Chat (empathy + planning + web search + LLM)
    ├── Memory System
    │   ├── Core Memory (user facts + recent 5 messages)
    │   ├── Working Memory (48-hour compressed summary)
    │   ├── Memory Beast (keyword search across all history)
    │   └── Background Review (Hermes-style silent learning every 5th message)
    ├── Personality Layer (418 lines of behavioral rules)
    ├── Services (gold, weather, email, contacts, reminders, etc.)
    └── LLM Layer (Gemini via OpenRouter, Perplexity for search)
    ↓
[PostgreSQL Database]
    ├── users, agent_souls, conversations
    ├── contacts, reminders, user_memory
    ├── inbox_messages, chat_insights
    ├── email_configs, stock_watchlist
    ├── detected_patterns, active_behaviors
    ├── pending_replies, pending_email_drafts
    ├── feedback_signals, api_cost_logs
    └── session_health, network_connections
```

---

## Database Schema (20 tables)

| Table | Purpose |
|-------|---------|
| users | User profiles, subscription status, payment info |
| agent_souls | Per-user AI personality, language, onboarding state |
| conversations | Full chat history (user + assistant messages) |
| user_memory | Key-value persistent memory (facts, preferences, learned behaviors) |
| contacts | Saved contacts with name, phone, company, tag |
| reminders | Scheduled reminders with repeat support |
| inbox_messages | All WhatsApp messages from contacts (Sam's inbox) |
| chat_insights | AI-generated insights from inbox analysis |
| email_configs | Connected email accounts (IMAP/SMTP, encrypted passwords) |
| stock_watchlist | Tracked stocks with price alerts |
| detected_patterns | Behavioral patterns Sam detects (gold check times, greeting habits) |
| active_behaviors | User-approved automated behaviors |
| pending_replies | Draft replies awaiting user confirmation |
| pending_email_drafts | Draft emails awaiting user confirmation |
| meeting_notes | Structured meeting transcripts with action items |
| chat_messages | Buffered chat messages for intelligence processing |
| feedback_signals | User reaction tracking (positive/negative) |
| api_cost_logs | Per-call LLM cost tracking (model, tokens, cost) |
| session_health | WhatsApp session status monitoring |
| soul_evolutions | Weekly AI personality evolution records |

---

## What We Learned (Honest Retrospective)

### What Went Right
- **Architecture is solid** — the layered orchestrator design handles 50+ use cases cleanly
- **Personality works** — Sam genuinely feels like a friend, not a robot
- **Memory system** — Hermes-style background learning captures preferences silently
- **India-first design** — Hindi grammar awareness, festival calendar, INR defaults, lakh/crore support
- **Voice pipeline** — end-to-end voice in → transcribe → process → TTS → voice out

### What Went Wrong
- **Testing discipline** — features were declared "done" after syntax checks, not end-to-end API tests
- **Deployment verification** — code was pushed but Railway didn't always deploy; no version check existed for 2+ weeks
- **Keyword collisions** — substring matching caused wrong skills to intercept queries ("mumbai today" matched "mumbai to" flights)
- **Auto skill builder** — automatically generated skills that produced broken/useless responses, intercepting real queries
- **Data pollution** — test messages sent to production account saved wrong facts to user memory
- **Silent failures** — 77 places where skills returned empty string on error instead of telling the user something went wrong

### Key Fixes Applied
1. Added `DEPLOY_VERSION` to health endpoint — every deploy is now version-verified
2. Disabled auto skill builder — was the #1 source of user-facing bugs
3. Replaced Playwright web search with Perplexity Sonar — Google blocks Playwright on cloud IPs
4. Fixed keyword matching — word boundaries for short keywords, multi-word phrases for intent routing
5. Added memory validation — keys must be snake_case, values capped, garbage values rejected
6. Fixed deployment procedure — `railway up` + `railway redeploy --yes` + version check

---

## The Vision: Where Sam Can Go

### Near-term (Stabilization)
- Automated test suite that runs 30+ queries before every deploy
- Staging environment for testing before production
- Re-enable context compression (currently disabled due to async DB issue)
- Re-enable FTS5 session search for cross-conversation recall

### Medium-term (Product)
- **Multi-user family plan** — Sapna, Shivani, parents all have their own Sam
- **Business mode** — Sam answers customer WhatsApp messages on behalf of the owner (with approval)
- **Payment integration** — Razorpay subscription for paid users
- **JewelClaw integration** — Sam becomes the chat interface for gold intelligence
- **Document analysis** — upload a PDF/contract, Sam reads and summarizes it

### Long-term (Platform)
- **Sam Network** — connect Sam users to each other (jeweller needs a supplier, Sam finds one)
- **Voice-first interface** — Sam as a voice assistant, not just text
- **Regional language models** — fine-tuned Samva LLM for Hindi/Gujarati/Tamil
- **Enterprise API** — businesses deploy Sam for their customers
- **Sam learns procedures** — when you teach Sam a multi-step workflow, it saves and repeats it

### The Dream
Sam becomes the one app every Indian family opens first. Not for search, not for shopping — for **living**. "Sam, mummy ka birthday kab hai?" "Sam, school fees bharna hai." "Sam, client ne kya bola kal?" "Sam, raat ko meri flight hai na?"

An AI that knows you better than your phone's search history. That cares enough to ask "sab theek?" when you've been quiet. That celebrates when your daughter comes first in class.

Not a product. A companion.

---

## File Structure

```
samva/
├── api/
│   ├── app/
│   │   ├── main.py              # FastAPI server, all endpoints
│   │   ├── config.py            # Environment variables
│   │   ├── database.py          # PostgreSQL async engine
│   │   ├── models.py            # 20 SQLAlchemy models
│   │   └── services/
│   │       ├── agent.py         # Main message processor
│   │       ├── orchestrator.py  # 7-layer routing engine
│   │       ├── personality.py   # 418-line personality + proactive nudges
│   │       ├── llm.py           # OpenRouter + Gemini TTS/ASR
│   │       ├── prebuilt_skills.py  # 30+ instant skills (3000+ lines)
│   │       ├── memory_manager.py   # Hierarchical memory builder
│   │       ├── memory_beast.py     # Full conversation search
│   │       ├── memory_review.py    # Hermes-style background learning
│   │       ├── web_search.py       # Perplexity + DuckDuckGo
│   │       ├── doc_generator.py    # PDF generation (all types)
│   │       ├── gold.py             # Gold/silver rates + briefs
│   │       ├── email_service.py    # IMAP/SMTP email management
│   │       ├── contacts.py         # Contact save/lookup
│   │       ├── reminders.py        # Reminder CRUD + cron checks
│   │       ├── skill_builder.py    # Auto skill builder (disabled)
│   │       ├── chat_intelligence.py # Inbox message analysis
│   │       ├── life_observer.py    # Spending/food/relationship detection
│   │       ├── pattern_watcher.py  # Behavioral pattern detection
│   │       ├── skill_learner.py    # Learning from interactions
│   │       ├── feedback.py         # User reaction tracking
│   │       ├── safety.py           # SOS and emergency handling
│   │       ├── onboarding.py       # 4-step new user flow
│   │       └── ... (20+ more services)
│   └── requirements.txt
├── bridge/
│   └── src/
│       ├── index.js             # Express server + 14 cron jobs
│       ├── sessionManager.js    # WhatsApp session lifecycle
│       ├── coreClient.js        # API communication
│       └── sessionStore.js      # Persistent session storage
├── web/                         # Landing page (samva.in)
├── Dockerfile                   # Multi-stage Docker build
├── start.sh                     # Container entrypoint
└── SAMVA_FEATURES.md            # This file
```

---

*Last updated: 23 April 2026*
*Version: 2026-04-22-v2*
*187 commits | 18,500+ lines | 20 days of building*
