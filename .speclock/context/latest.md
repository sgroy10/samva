# SpecLock Context Pack
> Generated: 2026-03-24T01:19:29.637Z
> Project: **samva**
> Repo: branch `main` @ `606fc2f`

## Goal
Samva — multi-tenant WhatsApp personal assistant SaaS

## SpecLock (Non-Negotiables)
> **These constraints MUST be followed. Do not violate any lock.**
- **[LOCK]** Architecture: Node.js bridge + Python FastAPI in single Dockerfile — do not split into separate services _(user, 2026-03-24)_
- **[LOCK]** All Railway management via CLI — never ask user to use dashboard _(user, 2026-03-24)_
- **[LOCK]** GitHub repo: sgroy10/samva — git push auto-deploys to Railway _(user, 2026-03-24)_
- **[LOCK]** Railway project: terrific-grace, Service: romantic-generosity, URL: https://romantic-generosity-production.up.railway.app — NEVER change these _(user, 2026-03-24)_
- **[LOCK]** Never touch JewelClaw code — Samva is a completely separate repo at /Users/gadgetzone/samva _(user, 2026-03-24)_

## Key Decisions
- **[DEC]** OpenRouter for Gemini 2.5 Flash — all LLM calls go through OpenRouter _(user, 2026-03-24)_
- **[DEC]** PostgreSQL on Railway, DATABASE_URL auto-injected _(user, 2026-03-24)_
- **[DEC]** Razorpay live keys active — rzp_live_6B2TJ6eDeIzIqX _(user, 2026-03-24)_
- **[DEC]** Dockerfile uses node:22-slim + python3 for dual runtime _(user, 2026-03-24)_
- **[DEC]** Samva is standalone repo at sgroy10/samva, NOT inside JewelClaw _(user, 2026-03-24)_

## Deploy Facts
- Provider: **Railway**
- Auto-deploy: No

## Recent Changes
- [2026-03-24T01:19:29] Fix Baileys 405 disconnect — use Browsers.ubuntu + fetchLatestBaileysVersion, fix reconnect counter (bridge/src/sessionManager.js)
- [2026-03-24T01:10:40] Samva v1 deployed to Railway — 28 files, 4274 lines, all endpoints live (Dockerfile, start.sh, bridge/src/index.js, api/app/main.py, web/public/index.html)

## Pinned Notes
- **[NOTE]** Railway env vars: OPENROUTER_API_KEY, GEMINI_API_KEY, RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET, DATABASE_URL, SAMVA_MODE=true

## Agent Instructions
1. Follow ALL SpecLock items strictly — they are non-negotiable.
2. Do not contradict recorded decisions without explicit user approval.
3. If you detect drift from constraints, stop and flag it.
4. Call `speclock_detect_drift` proactively to check for constraint violations.
5. Call `speclock_get_context` to refresh this context at any time.
6. Call `speclock_session_summary` before ending your session.

---
*Powered by [SpecLock](https://github.com/sgroy10/speclock) — Developed by Sandeep Roy*
