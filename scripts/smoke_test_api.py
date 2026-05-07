#!/usr/bin/env python3
"""
End-to-end API smoke test for the Blind Debate Adjudicator.

Automates the full flow:
  1. Register / login
  2. Create debate
  3. Post arguments
  4. Trigger async snapshot
  5. Poll until complete
  6. Display results + LLM usage

Usage:
  # Mock mode (free, fast)
  python scripts/smoke_test_api.py

  # OpenRouter mode (costs real money)
  OPENROUTER_API_KEY=sk-or-v1-xxx OPENROUTER_MODEL=openai/gpt-4o-mini \
    LLM_PROVIDER=openrouter NUM_JUDGES=3 python scripts/smoke_test_api.py

  # Custom server URL
  API_BASE=http://localhost:5000 python scripts/smoke_test_api.py
"""

from __future__ import annotations

import os
import sys
import time

import requests


class Colors:
    OK = "\033[92m"
    WARN = "\033[93m"
    FAIL = "\033[91m"
    INFO = "\033[94m"
    BOLD = "\033[1m"
    END = "\033[0m"


def _c(color: str, text: str) -> str:
    return f"{color}{text}{Colors.END}"


class SmokeTestClient:
    def __init__(self, base_url: str):
        self.base = base_url.rstrip("/")
        self.token: str | None = None
        self.user_id: str | None = None
        self.debate_id: str | None = None
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})

    def _get_csrf_token(self) -> str:
        """Fetch an HTML page to set the CSRF cookie, then return the token."""
        self.session.get(f"{self.base}/login.html")
        for cookie in self.session.cookies:
            if cookie.name == "csrf_token":
                return cookie.value
        return ""

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _post(self, endpoint: str, payload: dict | None = None, auth: bool = True) -> dict:
        headers = {}
        if auth and self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if self.debate_id:
            headers["X-Debate-ID"] = self.debate_id
        if not headers.get("Authorization"):
            headers["X-CSRF-Token"] = self._get_csrf_token()
        resp = self.session.post(
            f"{self.base}{endpoint}",
            headers=headers,
            json=payload or {},
            timeout=30,
        )
        try:
            data = resp.json()
        except Exception:
            data = {"error": resp.text}
        if not resp.ok:
            raise RuntimeError(f"HTTP {resp.status_code}: {data.get('error', resp.text)}")
        return data

    def _get(self, endpoint: str, auth: bool = True) -> dict:
        headers = {}
        if auth and self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if self.debate_id:
            headers["X-Debate-ID"] = self.debate_id
        resp = self.session.get(
            f"{self.base}{endpoint}",
            headers=headers,
            timeout=30,
        )
        try:
            data = resp.json()
        except Exception:
            data = {"error": resp.text}
        if not resp.ok:
            raise RuntimeError(f"HTTP {resp.status_code}: {data.get('error', resp.text)}")
        return data

    # ------------------------------------------------------------------
    # Steps
    # ------------------------------------------------------------------
    def health_check(self) -> None:
        print(_c(Colors.INFO, "→ Step 0: Health check"))
        data = self._get("/api/health", auth=False)
        print(f"  Status: {data.get('status', 'unknown')}")
        print()

    def register(self, email: str, password: str, display_name: str) -> None:
        print(_c(Colors.INFO, "→ Step 1: Register user"))
        try:
            data = self._post(
                "/api/auth/register",
                {"email": email, "password": password, "display_name": display_name},
                auth=False,
            )
            self.user_id = data.get("user_id")
            print(f"  {_c(Colors.OK, 'Registered')} → {self.user_id}")
        except RuntimeError as e:
            if "already exists" in str(e).lower() or "email" in str(e).lower():
                print(f"  {_c(Colors.WARN, 'User already exists')} — will log in instead")
            else:
                raise
        print()

    def login(self, email: str, password: str) -> None:
        print(_c(Colors.INFO, "→ Step 2: Log in"))
        data = self._post(
            "/api/auth/login",
            {"email": email, "password": password},
            auth=False,
        )
        self.token = data.get("access_token")
        self.user_id = data.get("user", {}).get("user_id")
        print(f"  {_c(Colors.OK, 'Logged in')} → token: {self.token[:20]}...")
        print()

    def create_debate(self, resolution: str, scope: str, motion: str) -> None:
        print(_c(Colors.INFO, "→ Step 3: Create debate"))
        data = self._post(
            "/api/debates",
            {"resolution": resolution, "scope": scope, "motion": motion},
        )
        self.debate_id = data.get("debate_id")
        print(f"  {_c(Colors.OK, 'Created')} → {self.debate_id}")
        print(f"  Resolution: {resolution}")
        print()

    def activate_debate(self) -> None:
        print(_c(Colors.INFO, "→ Step 4: Activate debate"))
        data = self._post(f"/api/debate/{self.debate_id}/activate", {})
        print(f"  {_c(Colors.OK, 'Activated')} → {data.get('debate_id')}")
        print()

    def post_argument(self, side: str, topic_id: str, facts: str, inference: str) -> None:
        print(_c(Colors.INFO, f"→ Step 5: Post argument ({side})"))
        data = self._post(
            "/api/debate/posts",
            {"side": side, "topic_id": topic_id, "facts": facts, "inference": inference},
        )
        post_id = data.get("post_id", data.get("submission_id", "?"))
        print(f"  {_c(Colors.OK, 'Posted')} → {post_id}")
        print()

    def trigger_snapshot(self) -> str:
        print(_c(Colors.INFO, "→ Step 6: Trigger snapshot"))
        data = self._post("/api/debate/snapshot", {"trigger_type": "manual"})
        job_id = data.get("job_id")
        print(f"  {_c(Colors.OK, 'Queued')} → job_id: {job_id}")
        print()
        return job_id

    def poll_job(self, job_id: str, interval: float = 2.0, timeout: float = 120.0) -> dict:
        print(_c(Colors.INFO, f"→ Step 7: Poll job {job_id}"))
        start = time.time()
        while time.time() - start < timeout:
            data = self._get(f"/api/debate/snapshot-jobs/{job_id}")
            status = data.get("status")
            progress = data.get("progress")
            if isinstance(progress, int | float):
                pct = f" ({int(progress * 100)}%)"
            else:
                pct = ""
            print(f"  Status: {status}{pct}", end="\r", flush=True)
            if status == "completed":
                print()
                print(f"  {_c(Colors.OK, 'Completed')} in {time.time() - start:.1f}s")
                print()
                return data
            if status == "failed":
                print()
                print(f"  {_c(Colors.FAIL, 'FAILED')}: {data.get('error')}")
                print()
                return data
            time.sleep(interval)
        print()
        raise TimeoutError(f"Job did not complete within {timeout}s")

    def show_snapshot(self) -> None:
        print(_c(Colors.INFO, "→ Step 8: Fetch snapshot"))
        data = self._get("/api/debate/snapshot")
        if not data.get("has_snapshot"):
            print(f"  {_c(Colors.WARN, 'No snapshot available')}")
            print()
            return
        snap = data
        print(f"  {_c(Colors.OK, 'Snapshot found')}")
        print(f"  ID:         {snap.get('snapshot_id')}")
        print(f"  Verdict:    {_c(Colors.BOLD, snap.get('verdict', 'NO VERDICT'))}")
        print(f"  Confidence: {snap.get('confidence', 0):.2f}")
        print(f"  Trigger:    {snap.get('trigger_type')}")
        print(f"  Timestamp:  {snap.get('timestamp')}")

        meta = snap.get("provider_metadata")
        if meta:
            print()
            print(_c(Colors.INFO, "  LLM Usage:"))
            print(f"    Provider:      {meta.get('provider', 'mock')}")
            print(f"    Model:         {meta.get('actual_model', 'n/a')}")
            print(f"    Judges:        {meta.get('num_judges', 'n/a')}")
            print(f"    LLM Calls:     {meta.get('llm_call_count', 'n/a')}")
            print(f"    Total Tokens:  {meta.get('total_tokens', 'n/a')}")
            print(f"    Prompt:        {meta.get('prompt_tokens', 'n/a')}")
            print(f"    Completion:    {meta.get('completion_tokens', 'n/a')}")

            cost = meta.get("cost_estimate")
            if cost:
                print(f"    Cost Estimate: ${cost:.4f}")
        print()

    def show_metrics(self) -> None:
        print(_c(Colors.INFO, "→ Step 9: Server metrics"))
        try:
            data = self._get("/metrics", auth=False)
            print(f"  Metrics endpoint returned {len(str(data))} chars")
        except Exception as e:
            print(f"  {_c(Colors.WARN, 'Skipped')}: {e}")
        print()


def main() -> int:
    base = os.getenv("API_BASE", "http://127.0.0.1:5000")
    email = os.getenv("SMOKE_EMAIL", "smoke@test.local")
    password = os.getenv("SMOKE_PASSWORD", "SmokePass123!")
    display_name = os.getenv("SMOKE_NAME", "Smoke Tester")

    print(_c(Colors.BOLD, "=" * 60))
    print(_c(Colors.BOLD, "Blind Debate Adjudicator — API Smoke Test"))
    print(_c(Colors.BOLD, "=" * 60))
    print(f"Server:    {base}")
    local_provider = os.getenv("LLM_PROVIDER")
    local_model = os.getenv("OPENROUTER_MODEL")
    if local_provider or local_model:
        print(
            f"Local env hint: provider={local_provider or '(unset)'} model={local_model or '(unset)'}"
        )
        print("Actual server runtime is reported from snapshot metadata after generation.")
    print()

    client = SmokeTestClient(base)
    start_all = time.time()

    try:
        client.health_check()
        client.register(email, password, display_name)
        client.login(email, password)
        client.create_debate(
            resolution="Should artificial intelligence be strictly regulated by governments?",
            scope="technology_policy",
            motion="This house believes AI should be strictly regulated.",
        )
        client.activate_debate()
        client.post_argument(
            side="FOR",
            topic_id="ai_regulation",
            facts="Unregulated AI has caused at least 3 major market disruptions in 2024. The EU AI Act already mandates risk-based classification.",
            inference="Therefore, strict government regulation is necessary to prevent economic and social harm.",
        )
        client.post_argument(
            side="AGAINST",
            topic_id="ai_regulation",
            facts="Excessive regulation in the EU has reduced AI startup formation by 18% compared to the US. China regulates heavily but still leads in AI patents.",
            inference="Thus, strict regulation stifles innovation without guaranteeing safety.",
        )
        job_id = client.trigger_snapshot()
        job = client.poll_job(job_id)
        if job.get("status") != "completed":
            print(_c(Colors.FAIL, "Snapshot job failed. Aborting."))
            return 1
        client.show_snapshot()
        client.show_metrics()
    except Exception as e:
        print()
        print(_c(Colors.FAIL, f"SMOKE TEST FAILED: {e}"))
        import traceback

        traceback.print_exc()
        return 1

    elapsed = time.time() - start_all
    print(_c(Colors.BOLD, "=" * 60))
    print(_c(Colors.OK, f"SMOKE TEST PASSED in {elapsed:.1f}s"))
    print(_c(Colors.BOLD, "=" * 60))
    return 0


if __name__ == "__main__":
    sys.exit(main())
