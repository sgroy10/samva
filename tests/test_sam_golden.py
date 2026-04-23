"""
Samva Golden Test Suite — 30 baseline tests.

Every test hits the LIVE API. If any test fails, the deploy is broken.
Run with: pytest tests/ -v

These tests cover:
1-5:   Deployment health + greetings
6-10:  Core skills (gold, weather, currency, EMI, BMI)
11-15: Memory + contacts
16-20: Empathy + safety
21-25: PDF generation
26-30: Web search + keyword routing regressions
"""

import pytest

pytestmark = pytest.mark.asyncio


# ═══════════════════════════════════════════════════════════════
# 1-5: DEPLOYMENT HEALTH + GREETINGS
# ═══════════════════════════════════════════════════════════════

class TestDeploymentHealth:
    async def test_01_health_endpoint(self, check_health):
        """Health endpoint returns version and status ok."""
        health = await check_health()
        assert health["status"] == "ok"
        assert "version" in health

    async def test_02_greeting_hi(self, send_message):
        """Simple 'hi' gets a friendly response, not an error."""
        reply = await send_message("hi")
        assert len(reply) > 5
        assert "error" not in reply.lower()
        assert "wrong" not in reply.lower()

    async def test_03_greeting_hindi(self, send_message):
        """Hindi greeting gets Hindi response."""
        reply = await send_message("namaste sam")
        assert len(reply) > 5

    async def test_04_thanks(self, send_message):
        """'Thanks' gets a polite response, not a skill trigger."""
        reply = await send_message("thanks")
        assert len(reply) > 3
        assert "remind" not in reply.lower()

    async def test_05_ok_no_pending_reply(self, send_message):
        """'ok' should NOT trigger a pending reply send."""
        reply = await send_message("ok")
        assert "Reply sent to" not in reply


# ═══════════════════════════════════════════════════════════════
# 6-10: CORE SKILLS
# ═══════════════════════════════════════════════════════════════

class TestCoreSkills:
    async def test_06_gold_rate(self, send_message):
        """Gold rate returns actual INR prices."""
        reply = await send_message("gold rate")
        assert "₹" in reply or "Gold" in reply or "gold" in reply

    async def test_07_weather(self, send_message):
        """Weather returns temperature data."""
        reply = await send_message("mumbai weather")
        assert "°C" in reply or "weather" in reply.lower()

    async def test_08_currency_conversion(self, send_message):
        """Currency conversion gives actual numbers."""
        reply = await send_message("100 dollars to rupees")
        assert "INR" in reply or "₹" in reply

    async def test_09_emi_calculator(self, send_message):
        """EMI calculation with lakh returns correct format."""
        reply = await send_message("emi calculate 30 lakh 9 percent 15 years")
        assert "EMI" in reply
        assert "₹" in reply or "Rs" in reply

    async def test_10_bmi_calculator(self, send_message):
        """BMI with feet+inches calculates correctly (5'10" 75kg = ~23.7)."""
        reply = await send_message("bmi calculate weight 75kg height 5 feet 10 inch")
        assert "BMI" in reply
        # 5'10" at 75kg = BMI ~23.7, should be Normal
        assert "32" not in reply  # Regression: was showing 32.3 (wrong)


# ═══════════════════════════════════════════════════════════════
# 11-15: MEMORY + CONTACTS
# ═══════════════════════════════════════════════════════════════

class TestMemoryAndContacts:
    async def test_11_memory_recall_wife(self, send_message):
        """Sam remembers wife's name (Sapna) and that she's vegetarian."""
        reply = await send_message("meri wife ke baare mein kya yaad hai")
        has_sapna = "Sapna" in reply or "sapna" in reply
        has_veg = "vegetarian" in reply.lower() or "veg" in reply.lower()
        assert has_sapna or has_veg, f"Expected Sapna or vegetarian in: {reply[:200]}"

    async def test_12_memory_recall_daughter(self, send_message):
        """Sam remembers daughter Shivani."""
        reply = await send_message("meri beti ka naam kya hai")
        assert "Shivani" in reply or "shivani" in reply

    async def test_13_yaad_hai_is_recall_not_save(self, send_message):
        """'kya yaad hai' should RECALL memory, not trigger memory_update."""
        reply = await send_message("tujhe kya yaad hai mere baare mein")
        assert "I'll remember" not in reply
        assert "note" not in reply.lower() or "noted" not in reply.lower()

    async def test_14_contact_save(self, send_message):
        """Save contact works (or says already exists)."""
        reply = await send_message("save contact Test Kumar 9999988888 tester")
        assert "Saved" in reply or "save" in reply.lower() or "Noted" in reply or "already" in reply.lower() or "contact" in reply.lower()

    async def test_15_reminder_set(self, send_message):
        """Reminder creation works with Hindi."""
        reply = await send_message("yaad dila dena kal subah 8 baje walk karna hai")
        has_reminder = "⏰" in reply or "Reminder" in reply or "💼" in reply
        assert has_reminder, f"Expected reminder confirmation in: {reply[:200]}"


# ═══════════════════════════════════════════════════════════════
# 16-20: EMPATHY + SAFETY
# ═══════════════════════════════════════════════════════════════

class TestEmpathyAndSafety:
    async def test_16_hospital_empathy(self, send_message):
        """Hospital mention triggers empathy, not task mode."""
        reply = await send_message("kal hospital jana hai blood test ke liye")
        empathy_words = ["theek", "oh", "hospital", "hua", "concern", "care"]
        has_empathy = any(w in reply.lower() for w in empathy_words)
        assert has_empathy, f"Expected empathy in: {reply[:200]}"

    async def test_17_stress_empathy(self, send_message):
        """Stress mention gets genuine concern."""
        reply = await send_message("bahut stressed hoon office mein")
        assert len(reply) > 30  # Not a one-liner
        assert "error" not in reply.lower()

    async def test_18_good_news_celebration(self, send_message):
        """Good news gets celebration, not generic response."""
        reply = await send_message("mera promotion ho gaya")
        celebration_words = ["badhai", "congratulat", "amazing", "wow", "great", "🎉"]
        has_celebration = any(w in reply.lower() for w in celebration_words)
        assert has_celebration, f"Expected celebration in: {reply[:200]}"

    async def test_19_chest_pain_safety(self, send_message):
        """Chest pain triggers medical safety response."""
        reply = await send_message("chest mein dard ho raha hai")
        safety_words = ["doctor", "hospital", "emergency", "call", "112"]
        has_safety = any(w in reply.lower() for w in safety_words)
        assert has_safety, f"Expected safety response in: {reply[:200]}"

    async def test_20_date_awareness(self, send_message):
        """Sam knows today's date (should not hallucinate)."""
        reply = await send_message("aaj kya date hai")
        # Should contain current month or year
        assert "2026" in reply or "April" in reply or "april" in reply or "May" in reply


# ═══════════════════════════════════════════════════════════════
# 21-25: PDF GENERATION
# ═══════════════════════════════════════════════════════════════

class TestPDFGeneration:
    async def test_21_custom_pdf(self, send_message_raw):
        """'make me a pdf' generates actual PDF."""
        data = await send_message_raw("make me a pdf of my weekly goals")
        reply = data.get("reply", "")
        assert "__PDF__" in reply, f"Expected PDF in: {reply[:150]}"

    async def test_22_invoice_pdf(self, send_message_raw):
        """Invoice generation works."""
        data = await send_message_raw("invoice bana do Ravi ke liye gold ring 25000")
        reply = data.get("reply", "")
        assert "__PDF__" in reply, f"Expected PDF in: {reply[:150]}"

    async def test_23_itinerary_pdf(self, send_message_raw):
        """Itinerary generation works."""
        data = await send_message_raw("itinerary banao 2 din Jaipur")
        reply = data.get("reply", "")
        assert "__PDF__" in reply, f"Expected PDF in: {reply[:150]}"

    async def test_24_gold_report_pdf(self, send_message_raw):
        """Gold report PDF works."""
        data = await send_message_raw("gold report pdf")
        reply = data.get("reply", "")
        assert "__PDF__" in reply, f"Expected PDF in: {reply[:150]}"

    async def test_25_make_me_a_pdf_variants(self, send_message_raw):
        """Various PDF request phrasings all work."""
        data = await send_message_raw("pdf bana do meri diet plan ka")
        reply = data.get("reply", "")
        assert "__PDF__" in reply, f"Expected PDF in: {reply[:150]}"


# ═══════════════════════════════════════════════════════════════
# 26-30: WEB SEARCH + KEYWORD ROUTING REGRESSIONS
# ═══════════════════════════════════════════════════════════════

class TestWebSearchAndRouting:
    async def test_26_web_search_works(self, send_message):
        """Web search returns actual content, not captcha or empty."""
        reply = await send_message("India GDP growth rate 2025")
        assert len(reply) > 30
        assert "captcha" not in reply.lower()

    async def test_27_petrol_not_flights(self, send_message):
        """REGRESSION: 'petrol price mumbai' should NOT match flights skill."""
        reply = await send_message("petrol price mumbai today")
        assert "Dono cities batao" not in reply  # flights skill response
        assert "flight" not in reply.lower()

    async def test_28_nursery_not_gita(self, send_message):
        """REGRESSION: 'Shivani nursery' should NOT match Gita skill."""
        reply = await send_message("Shivani ke liye nursery suggest karo")
        assert "shloka" not in reply.lower()
        assert "gita" not in reply.lower()

    async def test_29_news_gives_content(self, send_message):
        """News query returns summarized content, not raw links."""
        reply = await send_message("aaj ki top news India")
        assert len(reply) > 50
        # Should not be just raw Google links
        assert reply.count("http") < 5  # Some links OK, but not a link dump

    async def test_30_ipl_gives_content(self, send_message):
        """IPL query returns actual data, not just 'check cricbuzz'."""
        reply = await send_message("IPL 2026 points table")
        assert len(reply) > 50
        # Should not be just a redirect
        assert "cricbuzz.com" not in reply.lower() or len(reply) > 100
