"""
Samva Test Configuration.

Tests hit the LIVE API via /test-message endpoint.
Set SAM_TEST_URL and SAM_TEST_USER_ID as environment variables,
or they default to the production endpoint.
"""

import os
import pytest
import httpx

# Default to production — override with SAMVA_TEST_URL for staging
BASE_URL = os.environ.get("SAMVA_TEST_URL") or "https://romantic-generosity-production.up.railway.app"
USER_ID = os.environ.get("SAMVA_TEST_USER_ID") or "2348683f-abfb-4707-9149-80b8a8f05c03"


@pytest.fixture
def api_url():
    return BASE_URL


@pytest.fixture
def user_id():
    return USER_ID


@pytest.fixture
def send_message():
    """Send a message to Sam and return the reply text."""
    async def _send(text: str, timeout: float = 60.0) -> str:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{BASE_URL}/test-message",
                json={"userId": USER_ID, "text": text},
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("reply", "")
    return _send


@pytest.fixture
def send_message_raw():
    """Send a message and return the full JSON response."""
    async def _send(text: str, timeout: float = 60.0) -> dict:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{BASE_URL}/test-message",
                json={"userId": USER_ID, "text": text},
            )
            resp.raise_for_status()
            return resp.json()
    return _send


@pytest.fixture
def check_health():
    """Check the health endpoint and return version info."""
    async def _check() -> dict:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{BASE_URL}/health")
            resp.raise_for_status()
            return resp.json()
    return _check
