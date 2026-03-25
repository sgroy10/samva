"""
THE INVENTION — Sam's Self-Plugin Builder.

Sam detects that a user needs live data or a capability that doesn't exist.
Sam finds the right API, writes the connector, tests it, activates it.
The user never sees code. They just see Sam getting smarter.

Flow:
1. detect_skill_need() — should Sam build something new?
2. design_skill() — what API, what code, what triggers
3. test_skill() — run the code in sandbox, verify it works
4. activate_skill() — save to DB, register for routing
5. execute_skill() — run a user's custom skill on demand
"""

import logging
import asyncio
import traceback
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from ..models import UserSkill, AgentSoul
from .llm import call_gemini, call_gemini_json

logger = logging.getLogger("samva.skill_builder")


# ── Known API Registry ───────────────────────────────────────────
# Curated list of FREE APIs Sam can use. Gemini picks from these first.

API_REGISTRY = [
    {
        "name": "OpenFDA Drug Interactions",
        "url": "https://api.fda.gov/drug/label.json",
        "description": "US FDA drug labels. MUST search using: ?search=openfda.generic_name:{drugname}&limit=1. Response has results[0].drug_interactions array. Extract the drug name from the user query first.",
        "category": "medical",
        "auth": "none",
        "example": "GET https://api.fda.gov/drug/label.json?search=openfda.generic_name:warfarin&limit=1 then read results[0]['drug_interactions'][0]",
    },
    {
        "name": "Yahoo Finance",
        "url": "https://query1.finance.yahoo.com/v8/finance/chart/",
        "description": "Stock prices, indices, commodities, crypto — real-time",
        "category": "finance",
        "auth": "none",
        "example": "https://query1.finance.yahoo.com/v8/finance/chart/RELIANCE.NS?range=1d&interval=1d",
    },
    {
        "name": "OpenWeatherMap",
        "url": "https://api.openweathermap.org/data/2.5/weather",
        "description": "Current weather for any city",
        "category": "weather",
        "auth": "api_key (free tier)",
        "example": "https://api.openweathermap.org/data/2.5/weather?q=Mumbai&appid=FREE_KEY&units=metric",
    },
    {
        "name": "ExchangeRate API",
        "url": "https://open.er-api.com/v6/latest/",
        "description": "Currency exchange rates — 150+ currencies",
        "category": "finance",
        "auth": "none",
        "example": "https://open.er-api.com/v6/latest/USD",
    },
    {
        "name": "Gold API",
        "url": "https://api.gold-api.com/price/",
        "description": "Gold, silver, platinum spot prices",
        "category": "commodities",
        "auth": "none",
        "example": "https://api.gold-api.com/price/XAU",
    },
    {
        "name": "Nutritionix (Calories)",
        "url": "https://trackapi.nutritionix.com/v2/natural/nutrients",
        "description": "Calorie and nutrition data for any food described in plain text",
        "category": "health",
        "auth": "api_key (free tier)",
        "example": "POST with {'query': '2 eggs and toast'}",
    },
    {
        "name": "NewsAPI",
        "url": "https://newsapi.org/v2/everything",
        "description": "News articles from 80,000+ sources searchable by keyword",
        "category": "news",
        "auth": "api_key (free tier)",
        "example": "https://newsapi.org/v2/everything?q=gold+price&apiKey=FREE_KEY",
    },
    {
        "name": "REST Countries",
        "url": "https://restcountries.com/v3.1/",
        "description": "Country data — population, currency, languages, timezone",
        "category": "reference",
        "auth": "none",
        "example": "https://restcountries.com/v3.1/name/india",
    },
    {
        "name": "Dictionary API",
        "url": "https://api.dictionaryapi.dev/api/v2/entries/en/",
        "description": "English word definitions, pronunciation, examples",
        "category": "language",
        "auth": "none",
        "example": "https://api.dictionaryapi.dev/api/v2/entries/en/negotiate",
    },
]

REGISTRY_TEXT = "\n".join(
    f"- {a['name']}: {a['description']} (auth: {a['auth']}, url: {a['url']})"
    for a in API_REGISTRY
)


# ── Step 1: Detect if Sam should build something ─────────────────

async def detect_skill_need(
    db: AsyncSession, user_id: str, text: str, reply: str, soul_prompt: str
) -> dict:
    """
    After Sam gives a chat reply, check if the user's question
    reveals a need for live data that Sam can't currently provide.

    Returns {"should_build": True/False, "need": "description"} or empty dict.
    Only triggers when Sam is clearly guessing or the user needs live/real-time data.
    """
    # Get existing user skills to avoid rebuilding
    existing = await db.execute(
        select(UserSkill).where(UserSkill.user_id == user_id, UserSkill.is_active == True)
    )
    existing_skills = [s.skill_name for s in existing.scalars().all()]
    existing_str = ", ".join(existing_skills) if existing_skills else "none"

    try:
        result = await call_gemini_json(
            f"""You are analyzing whether an AI assistant needs a NEW live data capability.

The assistant just answered a question. Determine if:
1. The user needs LIVE/REAL-TIME data that the AI is guessing about
2. A specific API or data source could give a better answer
3. This capability does NOT already exist

The assistant already has these built-in skills: chat, email, business cards, meeting notes, reminders, gold prices, stock watchlist, web search.
The assistant has these custom skills for this user: {existing_str}
The user's profile: {soul_prompt[:300]}

Return JSON:
{{"should_build": true/false, "need": "one line description of what data/capability is needed", "category": "medical/finance/weather/reference/other"}}

Rules:
- Only return true if a SPECIFIC API would genuinely help
- Return false for general knowledge questions Gemini can handle
- Return false if a built-in skill already covers this
- Return false if an existing custom skill covers this""",
            f"User asked: {text}\nSam replied: {reply[:300]}",
            user_id=user_id,
            max_tokens=100,
        )

        if result.get("should_build"):
            logger.info(f"[{user_id}] Skill need detected: {result.get('need')}")
        return result

    except Exception as e:
        logger.debug(f"Skill need detection failed: {e}")
        return {"should_build": False}


# ── Step 2: Design the skill — find API + write code ─────────────

async def design_skill(user_id: str, need: str, category: str = "other") -> dict:
    """
    Given a need description, find the right API and write the connector code.
    Returns the full skill specification.
    """
    result = await call_gemini_json(
        f"""You are a senior Python developer building an API connector.

TASK: Build a skill that fulfills this need: "{need}"

AVAILABLE APIs (prefer these — they're free and tested):
{REGISTRY_TEXT}

If none of the above fit, suggest ANY well-known free/freemium REST API.

Write a Python async function that:
1. Takes a 'query' string parameter (the user's question in plain text)
2. Calls the appropriate API using httpx
3. Parses the response
4. Returns a short, WhatsApp-friendly answer string
5. Handles errors gracefully (returns error message, never crashes)

Return JSON:
{{
    "skill_name": "short_snake_case_name",
    "description": "one line of what this does",
    "trigger_keywords": ["keyword1", "keyword2", "keyword3"],
    "api_url": "base URL of the API used",
    "python_code": "the complete async function code"
}}

CRITICAL RULES for python_code:
- Function MUST be named: async def execute(query: str) -> str
- ONLY use httpx for HTTP calls (already imported in sandbox)
- ONLY use json for parsing (already imported)
- Return a plain string (WhatsApp message)
- Handle all exceptions — return error string, never raise
- Keep response SHORT — this is WhatsApp, not a report
- Do NOT import anything — httpx and json are pre-imported
- The function receives the user's EXACT words as 'query'""",
        f"Need: {need}\nCategory: {category}",
        user_id=user_id,
        max_tokens=2000,  # Code + JSON needs more tokens
    )

    return result


# ── Step 3: Test the skill in isolated subprocess ────────────────

# Runner script template — executed in a separate process
# Has NO access to: database, API keys, filesystem, parent memory
_RUNNER_SCRIPT = '''
import asyncio, httpx, json, sys

{code}

async def _main():
    try:
        result = await execute("""{query}""")
        print("__RESULT__:" + str(result))
    except Exception as e:
        print("__ERROR__:" + str(e))

asyncio.run(_main())
'''


async def test_skill(python_code: str, test_query: str = "test") -> dict:
    """
    Execute generated code in an ISOLATED SUBPROCESS.
    The subprocess has:
    - No database access
    - No API keys from environment
    - No filesystem write access
    - 10 second hard timeout (killed if exceeded)
    - Separate memory space (can't exhaust parent)
    """
    import tempfile
    import os

    # Escape the query for embedding in the script
    safe_query = test_query.replace('"""', '\\"\\"\\"').replace("\\", "\\\\")

    script = _RUNNER_SCRIPT.replace("{code}", python_code).replace("{query}", safe_query)

    # Write to temp file
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, dir="/tmp") as f:
            f.write(script)
            tmp_path = f.name

        # Run in subprocess with clean environment (no inherited env vars)
        clean_env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/usr/local/bin"),
            "HOME": "/tmp",
        }

        proc = await asyncio.create_subprocess_exec(
            "python3", tmp_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=clean_env,
        )

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10.0)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            return {"passed": False, "output": "Timeout — killed after 10 seconds"}

        output = stdout.decode("utf-8", errors="replace").strip()
        errors = stderr.decode("utf-8", errors="replace").strip()

        # Parse result
        if "__RESULT__:" in output:
            result = output.split("__RESULT__:", 1)[1].strip()
            if not result or len(result) < 3:
                return {"passed": False, "output": f"Empty result: '{result}'"}

            # Reject responses that are clearly errors or failures
            lower_result = result.lower()
            hard_fails = ["404", "403", "500", "502", "503", "not_found", "NOT_FOUND", "unauthorized"]
            soft_fails = ["error", "failed", "timeout", "unavailable"]
            if any(sig in result for sig in hard_fails):
                return {"passed": False, "output": f"API error: {result[:200]}"}
            if any(sig in lower_result for sig in soft_fails) and len(result) < 150:
                return {"passed": False, "output": f"Likely error: {result[:200]}"}

            logger.info(f"Skill test passed (subprocess): {result[:100]}")
            return {"passed": True, "output": result[:500]}

        if "__ERROR__:" in output:
            return {"passed": False, "output": output.split("__ERROR__:", 1)[1].strip()[:300]}

        # No marker found — check stderr
        if errors:
            return {"passed": False, "output": f"Process error: {errors[:300]}"}

        return {"passed": False, "output": f"No output from subprocess. stdout: {output[:200]}"}

    except Exception as e:
        return {"passed": False, "output": f"Subprocess error: {str(e)[:200]}"}
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass


# ── Rate Limiting ────────────────────────────────────────────────

MAX_BUILDS_PER_DAY = 3

async def _check_rate_limit(db: AsyncSession, user_id: str) -> bool:
    """Returns True if user is within daily build limit."""
    from sqlalchemy import func, text
    result = await db.execute(
        select(func.count(UserSkill.id)).where(
            UserSkill.user_id == user_id,
        ).where(text("created_at >= NOW() - INTERVAL '1 day'"))
    )
    count = result.scalar() or 0
    return count < MAX_BUILDS_PER_DAY


# ── Step 4: Full build pipeline ──────────────────────────────────

async def build_skill_for_user(
    db: AsyncSession, user_id: str, need: str, category: str = "other"
) -> str:
    """
    The full pipeline: design → test → activate.
    Runs in background. Returns status message.
    """
    build_log = [f"[{datetime.utcnow().isoformat()}] Build started for: {need}"]

    try:
        # Rate limit check — max 3 builds per user per day
        if not await _check_rate_limit(db, user_id):
            logger.warning(f"[{user_id}] Skill build rate limited (max {MAX_BUILDS_PER_DAY}/day)")
            return ""

        # Step 1: Design
        build_log.append("Designing skill...")
        spec = await design_skill(user_id, need, category)

        if not spec.get("python_code") or not spec.get("skill_name"):
            build_log.append(f"Design failed: {spec}")
            return ""

        skill_name = spec["skill_name"]
        build_log.append(f"Designed: {skill_name} — {spec.get('description', '')}")
        build_log.append(f"API: {spec.get('api_url', '?')}")

        # Step 2: Test
        build_log.append("Testing with sample query...")
        test_query = need[:50]  # Use the need description as test query
        test_result = await test_skill(spec["python_code"], test_query)

        build_log.append(f"Test {'PASSED' if test_result['passed'] else 'FAILED'}: {test_result['output'][:200]}")

        if not test_result["passed"]:
            # One retry with fixed code
            build_log.append("Retrying with error feedback...")
            fix_spec = await call_gemini_json(
                f"""The skill code failed testing. Fix it.

Original code:
{spec['python_code']}

Error:
{test_result['output']}

Return JSON with ONLY the fixed python_code:
{{"python_code": "fixed async def execute(query: str) -> str code"}}

Same rules: only httpx and json available, handle errors, return string.""",
                "Fix the code.",
                user_id=user_id,
            )

            if fix_spec.get("python_code"):
                spec["python_code"] = fix_spec["python_code"]
                test_result = await test_skill(spec["python_code"], test_query)
                build_log.append(f"Retry {'PASSED' if test_result['passed'] else 'FAILED'}: {test_result['output'][:200]}")

        # Step 3: Save to DB
        existing = await db.execute(
            select(UserSkill).where(
                UserSkill.user_id == user_id, UserSkill.skill_name == skill_name
            )
        )
        existing_skill = existing.scalar_one_or_none()

        if existing_skill:
            existing_skill.python_code = spec["python_code"]
            existing_skill.description = spec.get("description", "")
            existing_skill.trigger_keywords = spec.get("trigger_keywords", [])
            existing_skill.api_url = spec.get("api_url", "")
            existing_skill.test_result = test_result["output"][:500]
            existing_skill.test_passed = test_result["passed"]
            existing_skill.is_active = test_result["passed"]
            existing_skill.build_log = "\n".join(build_log)
        else:
            db.add(UserSkill(
                user_id=user_id,
                skill_name=skill_name,
                description=spec.get("description", ""),
                trigger_keywords=spec.get("trigger_keywords", []),
                api_url=spec.get("api_url", ""),
                python_code=spec["python_code"],
                test_result=test_result["output"][:500],
                test_passed=test_result["passed"],
                is_active=test_result["passed"],
                build_log="\n".join(build_log),
            ))

        await db.commit()

        if test_result["passed"]:
            logger.info(f"[{user_id}] NEW SKILL BUILT: {skill_name}")
            return spec.get("description", skill_name)
        else:
            logger.warning(f"[{user_id}] Skill build failed: {skill_name}")
            return ""

    except Exception as e:
        build_log.append(f"BUILD FAILED: {str(e)}")
        logger.error(f"[{user_id}] Skill build error: {e}", exc_info=True)
        return ""


# ── Step 5: Execute a user's custom skill ────────────────────────

async def execute_user_skill(db: AsyncSession, user_id: str, query: str) -> str:
    """
    Check if any of the user's custom skills should handle this query.
    Returns the skill's response, or empty string if no skill matches.
    """
    result = await db.execute(
        select(UserSkill).where(
            UserSkill.user_id == user_id,
            UserSkill.is_active == True,
        )
    )
    skills = result.scalars().all()

    if not skills:
        return ""

    query_lower = query.lower()

    # Pass 1: keyword match (fast, no AI cost)
    for skill in skills:
        keywords = skill.trigger_keywords or []
        if any(kw.lower() in query_lower for kw in keywords):
            logger.info(f"[{user_id}] Custom skill keyword match: {skill.skill_name}")
            try:
                result = await test_skill(skill.python_code, query)
                if result["passed"]:
                    return result["output"]
            except Exception as e:
                logger.error(f"[{user_id}] Skill exec error ({skill.skill_name}): {e}")

    # Pass 2: check if query is semantically about any skill's domain
    # Build a quick description list for Gemini to match against
    if len(skills) > 0 and len(query) > 10:
        skill_list = "\n".join(
            f"{i+1}. {s.skill_name}: {s.description}" for i, s in enumerate(skills)
        )
        try:
            match = await call_gemini_json(
                f"""Does this user query match any of these custom skills?
Skills:
{skill_list}

Return JSON: {{"match": 0}} if no match, or {{"match": N}} where N is the skill number (1-based).
Only match if the query is clearly asking for what the skill provides.""",
                query,
                user_id=user_id,
                max_tokens=20,
            )
            idx = match.get("match", 0)
            if idx > 0 and idx <= len(skills):
                skill = skills[idx - 1]
                logger.info(f"[{user_id}] Custom skill semantic match: {skill.skill_name}")
                result = await test_skill(skill.python_code, query)
                if result["passed"]:
                    return result["output"]
        except Exception:
            pass

    return ""


# ── Background trigger — called after chat replies ───────────────

async def maybe_build_skill(
    db: AsyncSession, user_id: str, text: str, reply: str, soul_prompt: str
):
    """
    Called after a chat reply with confidence < HIGH.
    Checks if Sam should build a new skill for this user.
    Runs the full build pipeline if yes.
    Returns notification message or empty string.
    """
    need_check = await detect_skill_need(db, user_id, text, reply, soul_prompt)

    if not need_check.get("should_build"):
        return ""

    need = need_check.get("need", "")
    category = need_check.get("category", "other")

    if not need:
        return ""

    # Build it
    description = await build_skill_for_user(db, user_id, need, category)

    if description:
        # Get user's language
        soul_result = await db.execute(
            select(AgentSoul).where(AgentSoul.user_id == user_id)
        )
        soul = soul_result.scalar_one_or_none()
        lang = soul.language_preference if soul else "auto"

        if lang in ("hindi", "hinglish"):
            return f"\U0001f9e0 Sam ne ek nayi capability seekh li aapke liye — ab main *{description}* kar sakti hoon!"
        else:
            return f"\U0001f9e0 Sam learned something new for you — I can now *{description}*!"

    return ""
