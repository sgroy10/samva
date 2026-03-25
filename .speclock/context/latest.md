# SpecLock Context Pack
> Generated: 2026-03-25T16:30:41.423Z
> Project: **samva**
> Repo: branch `main` @ `3305149`

## Goal
Samva — multi-tenant WhatsApp personal assistant SaaS

## SpecLock (Non-Negotiables)
> **These constraints MUST be followed. Do not violate any lock.**
- **[LOCK]** Self-plugin builder: generated code runs in exec() sandbox with ONLY httpx and json available. No filesystem, no os, no subprocess. _(user, 2026-03-25)_
- **[LOCK]** Admin phone 8928731453 — free access, no payment, no subscription check, plan=admin _(user, 2026-03-24)_
- **[LOCK]** Architecture: Node.js bridge + Python FastAPI in single Dockerfile — do not split into separate services _(user, 2026-03-24)_
- **[LOCK]** All Railway management via CLI — never ask user to use dashboard _(user, 2026-03-24)_
- **[LOCK]** GitHub repo: sgroy10/samva — git push auto-deploys to Railway _(user, 2026-03-24)_
- **[LOCK]** Railway project: terrific-grace, Service: romantic-generosity, URL: https://romantic-generosity-production.up.railway.app — NEVER change these _(user, 2026-03-24)_
- **[LOCK]** Never touch JewelClaw code — Samva is a completely separate repo at /Users/gadgetzone/samva _(user, 2026-03-24)_

## Key Decisions
- **[DEC]** Custom skills checked BEFORE general chat in routing. Keyword matching from trigger_keywords. _(user, 2026-03-25)_
- **[DEC]** User skills stored in DB (user_skills table), not as files. Survives deploys. _(user, 2026-03-25)_
- **[DEC]** Network matching is opt-in. Double confirmation before sharing any details. _(user, 2026-03-24)_
- **[DEC]** Confidence tagging only on chat intent. max_tokens:50 for speed. _(user, 2026-03-24)_
- **[DEC]** Soul Evolution APPENDS to system_prompt, never deletes. Runs Sunday 11pm IST. _(user, 2026-03-24)_
- **[DEC]** OpenRouter for Gemini 2.5 Flash — all LLM calls go through OpenRouter _(user, 2026-03-24)_
- **[DEC]** PostgreSQL on Railway, DATABASE_URL auto-injected _(user, 2026-03-24)_
- **[DEC]** Razorpay live keys active — rzp_live_6B2TJ6eDeIzIqX _(user, 2026-03-24)_
- **[DEC]** Dockerfile uses node:22-slim + python3 for dual runtime _(user, 2026-03-24)_
- **[DEC]** Samva is standalone repo at sgroy10/samva, NOT inside JewelClaw _(user, 2026-03-24)_

## Deploy Facts
- Provider: **Railway**
- Auto-deploy: No

## Recent Changes
- [2026-03-25T16:30:41] THE INVENTION: Sam's self-plugin builder — detect need, find API, write code, test, activate (api/app/services/skill_builder.py, api/app/services/agent.py, api/app/models.py)
- [2026-03-25T16:02:45] Bulletproof session management: auto-wipe on 401/405, auto-recover, reconnect button, status messages (bridge/src/sessionManager.js, bridge/src/index.js, web/public/index.html)
- [2026-03-24T18:22:45] Admin bypass, complete subscription management (payment confirm, expiry check, renewal, 3-day warning) (api/app/main.py, api/app/services/agent.py, api/app/config.py, bridge/src/index.js, web/public/index.html)
- [2026-03-24T15:52:36] Three Claude-reviewed fixes: language-aware confidence tags, network match confirmation+intro flow, verified Monday cron (api/app/services/confidence.py, api/app/services/network.py, api/app/services/agent.py, api/app/models.py)
- [2026-03-24T15:26:52] Three inventions: Soul Evolution, Confidence Transparency, Network Intelligence (api/app/services/soul_evolution.py, api/app/services/confidence.py, api/app/services/network.py, api/app/services/agent.py, api/app/services/onboarding.py, api/app/models.py, api/app/main.py, bridge/src/index.js, bridge/src/coreClient.js, bridge/src/sessionManager.js)
- [2026-03-24T01:50:12] Complete gold brief rewrite: gold_rate intent, 9am timing with dedup, price alerts >150/gm, JewelClaw-exact format with 14K+platinum+expert view (api/app/services/gold.py, api/app/services/agent.py, api/app/models.py)
- [2026-03-24T01:38:05] Wired IMAP email reading, Playwright web search, email connect command (api/app/services/email_draft.py, api/app/services/web_search.py, api/app/services/agent.py, Dockerfile, api/requirements.txt)
- [2026-03-24T01:24:59] Added quick guide after onboarding, help command, FAQ section on landing page (api/app/services/onboarding.py, api/app/services/agent.py, web/public/index.html)
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
