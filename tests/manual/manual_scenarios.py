"""
Manual Testing Script for Blind Debate Adjudicator
Run this to test the system interactively or with predefined scenarios
"""

import argparse
import os
import sys
import uuid
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parents[2]

# Base URL for API
BASE_URL = os.getenv("DEBATE_BASE_URL", "http://localhost:5000")


class DebateSystemTester:
    """Manual tester for the debate system via API"""

    def __init__(self, base_url=BASE_URL):
        self.base_url = base_url
        self.debate_id = None
        self.snapshot_id = None
        self.session = requests.Session()
        self.server_version = None
        self.auth_enabled = None
        self.access_token = None
        self.user_email = None

    def _headers(self, include_auth=True, include_debate=True):
        headers = {}
        if include_auth and self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        if include_debate and self.debate_id:
            headers["X-Debate-ID"] = self.debate_id
        return headers

    def _request(self, method, path, include_auth=True, include_debate=True, **kwargs):
        headers = self._headers(include_auth=include_auth, include_debate=include_debate)
        extra_headers = kwargs.pop("headers", None)
        if extra_headers:
            headers.update(extra_headers)
        return self.session.request(
            method,
            f"{self.base_url}{path}",
            headers=headers,
            timeout=10,
            **kwargs,
        )

    def _is_v3(self):
        return str(self.server_version).startswith("3")

    def _requires_auth(self):
        return self._is_v3() or self.auth_enabled is True

    def ensure_authenticated(self):
        """Create an isolated test user when the server requires auth."""
        if self.access_token or not self._requires_auth():
            return True

        unique_suffix = uuid.uuid4().hex[:12]
        self.user_email = f"codex-smoke-{unique_suffix}@example.com"
        password = "CodexSmokePass123!"
        payload = {
            "email": self.user_email,
            "password": password,
            "display_name": f"Codex Smoke {unique_suffix[:6]}",
        }

        response = self.session.post(
            f"{self.base_url}/api/auth/register",
            json=payload,
            timeout=10,
        )

        if response.status_code not in (200, 201):
            print(f"✗ Failed to create smoke-test user: {response.text}")
            return False

        data = response.json()
        self.access_token = data.get("access_token")
        if not self.access_token:
            print("✗ Registration succeeded but no access token was returned")
            return False

        print(f"✓ Authenticated smoke-test user: {self.user_email}")
        return True

    def check_server(self):
        """Check if server is running"""
        try:
            response = self.session.get(f"{self.base_url}/api/health", timeout=5)
            if response.status_code == 200:
                data = response.json()
                self.server_version = data.get("version", "unknown")
                self.auth_enabled = data.get("auth_enabled")
                auth_mode = "auth required" if self._requires_auth() else "guest posting"
                print(
                    f"✓ Server is running at {self.base_url} (version: {self.server_version}, {auth_mode})"
                )
                return True
        except requests.exceptions.ConnectionError:
            print(f"✗ Server not available at {self.base_url}")
            print("  Start the server with: python3 scripts/dev_workflow.py server")
            return False
        return False

    def create_debate(self, resolution, scope):
        """Create a new debate"""
        print("\n[Creating Debate]")
        print(f"  Resolution: {resolution}")

        if self._requires_auth() and not self.ensure_authenticated():
            return None

        endpoint = "/api/debates" if self._is_v3() else "/api/debate"
        response = self._request(
            "POST",
            endpoint,
            json={"resolution": resolution, "scope": scope},
        )

        if response.status_code in (200, 201):
            data = response.json()
            self.debate_id = data["debate_id"]
            print(f"✓ Created debate: {self.debate_id}")
            return data
        else:
            print(f"✗ Failed: {response.text}")
            return None

    def submit_post(self, side, facts, inference, counter_args="", topic_id=None):
        """Submit a post to the debate"""
        print(f"\n[Submitting Post - {side}]")
        print(f"  Facts: {facts[:60]}...")

        if not self.debate_id:
            print("✗ No debate created yet")
            return None

        response = self._request(
            "POST",
            "/api/debate/posts",
            json={
                "debate_id": self.debate_id,
                "side": side,
                "facts": facts,
                "inference": inference,
                "counter_arguments": counter_args,
                "topic_id": topic_id,
            },
        )

        if response.status_code == 200:
            data = response.json()
            outcome = data.get("modulation_outcome", "unknown")
            print(f"✓ Post {data['post_id']}: {outcome.upper()}")
            if data.get("block_reason"):
                print(f"  Block reason: {data['block_reason']}")
            return data
        else:
            print(f"✗ Failed: {response.text}")
            return None

    def generate_snapshot(self):
        """Generate a snapshot"""
        print("\n[Generating Snapshot]")

        if not self.debate_id:
            print("✗ No debate created yet")
            return None

        response = self._request(
            "POST",
            "/api/debate/snapshot",
            json={"debate_id": self.debate_id, "trigger_type": "manual"},
        )

        if response.status_code == 200:
            data = response.json()
            self.snapshot_id = data.get("snapshot_id")
            print(f"✓ Generated snapshot: {self.snapshot_id}")
            print(f"  Verdict: {data.get('verdict')}")
            print(f"  Confidence: {data.get('confidence')}")
            print(f"  Margin D: {data.get('margin_d')}")
            return data
        else:
            print(f"✗ Failed: {response.text}")
            return None

    def get_topics(self):
        """Get all topics"""
        print("\n[Getting Topics]")

        response = self._request("GET", "/api/debate/topics")

        if response.status_code == 200:
            data = response.json()
            topics = data.get("topics", [])
            print(f"✓ Found {len(topics)} topics:")
            for t in topics:
                print(f"  - {t['name']} (relevance: {t.get('relevance', 0):.2f})")
            return data
        else:
            print(f"✗ Failed: {response.text}")
            return None

    def get_verdict(self):
        """Get current verdict"""
        print("\n[Getting Verdict]")

        response = self._request("GET", "/api/debate/verdict")

        if response.status_code == 200:
            data = response.json()
            print("✓ Current verdict:")
            print(f"  Verdict: {data.get('verdict')}")
            print(f"  Confidence: {data.get('confidence')}")
            print(f"  FOR score: {data.get('overall_for')}")
            print(f"  AGAINST score: {data.get('overall_against')}")
            print(f"  Margin D: {data.get('margin_d')}")
            return data
        else:
            print(f"✗ Failed: {response.text}")
            return None

    def get_audits(self):
        """Get audit reports"""
        print("\n[Getting Audits]")

        response = self._request("GET", "/api/debate/audits")

        if response.status_code == 200:
            data = response.json()
            audits = data.get("audits", {})
            print("✓ Available audits:")
            for audit_type in audits.keys():
                print(f"  - {audit_type}")
            return data
        else:
            print(f"✗ Failed: {response.text}")
            return None

    def get_evidence_targets(self):
        """Get 'what evidence would change this' analysis"""
        print("\n[Getting Evidence Targets]")

        response = self._request("GET", "/api/debate/evidence-targets")

        if response.status_code == 200:
            data = response.json()
            print("✓ Evidence targets retrieved")
            return data
        else:
            print(f"✗ Failed: {response.text}")
            return None


def run_scenario_ai_regulation(base_url=BASE_URL):
    """Run a predefined test scenario about AI regulation"""
    print("=" * 70)
    print("SCENARIO: Should Advanced AI Development Be Paused?")
    print("=" * 70)

    tester = DebateSystemTester(base_url=base_url)

    if not tester.check_server():
        return False

    # Create debate
    debate = tester.create_debate(
        resolution="Should advanced AI development be paused for safety reasons?",
        scope="Discussion of AI governance, safety, and innovation trade-offs",
    )

    if not debate:
        return False

    # Submit FOR posts (pro-pause)
    post_results = []

    post_results.append(
        tester.submit_post(
            side="FOR",
            topic_id="t1",
            facts="AI systems have demonstrated capabilities that could be used to generate convincing misinformation at scale. Leading AI researchers have signed letters calling for pauses.",
            inference="Therefore, development should be paused until adequate safety measures are established.",
            counter_args="Arguments about innovation and competitiveness",
        )
    )

    post_results.append(
        tester.submit_post(
            side="FOR",
            topic_id="t1",
            facts="Current AI alignment techniques do not guarantee that advanced systems will remain under human control. Accidents in testing have already occurred.",
            inference="Pausing now prevents potentially catastrophic accidents later.",
            counter_args="Market-based safety approaches",
        )
    )

    # Submit AGAINST posts (anti-pause)
    post_results.append(
        tester.submit_post(
            side="AGAINST",
            topic_id="t3",
            facts="Pausing AI development in one country would simply allow other countries to take the lead. History shows that technological bans are rarely effective globally.",
            inference="A pause would harm domestic competitiveness without improving safety.",
            counter_args="Arguments about safety and misinformation",
        )
    )

    post_results.append(
        tester.submit_post(
            side="AGAINST",
            topic_id="t2",
            facts="AI development has already created significant economic value. Medical applications of AI are saving lives today.",
            inference="Pausing development would cause real harm to current beneficiaries.",
            counter_args="Long-term existential risk arguments",
        )
    )

    # Generate snapshot
    snapshot = tester.generate_snapshot()

    extra_results = []
    if snapshot:
        # Get additional info
        extra_results.append(tester.get_topics())
        extra_results.append(tester.get_verdict())
        extra_results.append(tester.get_audits())
        extra_results.append(tester.get_evidence_targets())

    print("\n" + "=" * 70)
    print("SCENARIO COMPLETE")
    print("=" * 70)

    return all(post_results) and bool(snapshot) and all(extra_results)


def run_scenario_renewable_energy(base_url=BASE_URL):
    """Run a predefined test scenario about renewable energy subsidies"""
    print("=" * 70)
    print("SCENARIO: Should Governments Subsidize Renewable Energy?")
    print("=" * 70)

    tester = DebateSystemTester(base_url=base_url)

    if not tester.check_server():
        return False

    # Create debate
    debate = tester.create_debate(
        resolution="Should governments provide subsidies for renewable energy?",
        scope="Economic, environmental, and policy considerations",
    )

    if not debate:
        return False

    # Submit FOR posts
    post_results = []

    post_results.append(
        tester.submit_post(
            side="FOR",
            topic_id="t2",
            facts="Renewable energy creates 3x more jobs per dollar invested than fossil fuels. Solar and wind costs have dropped 80% in the last decade.",
            inference="Subsidies for renewables are economically justified by job creation and declining costs.",
            counter_args="Market distortion arguments",
        )
    )

    post_results.append(
        tester.submit_post(
            side="FOR",
            topic_id="t1",
            facts="Climate change imposes external costs not reflected in fossil fuel prices. Carbon emissions cause measurable health impacts.",
            inference="Subsidies correct for market failures by internalizing environmental externalities.",
            counter_args="Economic efficiency concerns",
        )
    )

    # Submit AGAINST posts
    post_results.append(
        tester.submit_post(
            side="AGAINST",
            topic_id="t3",
            facts="Government subsidies distort price signals and lead to inefficient allocation of capital. Failed renewable companies have cost taxpayers billions.",
            inference="Market forces, not government subsidies, should determine energy investments.",
            counter_args="Environmental necessity arguments",
        )
    )

    post_results.append(
        tester.submit_post(
            side="AGAINST",
            topic_id="t4",
            facts="Subsidies create dependency. When subsidies are removed, industries often collapse. Nuclear energy provides baseload power without intermittency.",
            inference="Resources would be better spent on nuclear and grid infrastructure rather than intermittent renewables.",
            counter_args="Speed of deployment and safety",
        )
    )

    # Generate snapshot
    snapshot = tester.generate_snapshot()

    extra_results = []
    if snapshot:
        extra_results.append(tester.get_topics())
        extra_results.append(tester.get_verdict())
        extra_results.append(tester.get_audits())

    print("\n" + "=" * 70)
    print("SCENARIO COMPLETE")
    print("=" * 70)

    return all(post_results) and bool(snapshot) and all(extra_results)


def run_modulation_test(base_url=BASE_URL):
    """Test the modulation system with various content"""
    print("=" * 70)
    print("MODULATION TEST - Content Moderation")
    print("=" * 70)

    tester = DebateSystemTester(base_url=base_url)

    if not tester.check_server():
        return False

    # Create debate
    debate = tester.create_debate(
        resolution="Test debate for moderation", scope="Testing modulation rules"
    )

    if not debate:
        return False

    # Test various posts
    test_cases = [
        (
            "FOR",
            "Studies show economic growth correlates with education.",
            "Therefore, we should invest in education.",
            "Valid content - should pass",
        ),
        (
            "FOR",
            "You're all idiots who don't understand economics.",
            "Therefore, my view is correct.",
            "Harassment - should be blocked",
        ),
        (
            "FOR",
            "Check out my amazing products at discount prices!!! Click here!!!",
            "Buy now for great deals!",
            "Spam - should be blocked",
        ),
        (
            "AGAINST",
            "The data from the 2023 census shows population decline.",
            "Thus, immigration policy needs revision.",
            "Valid content - should pass",
        ),
        (
            "AGAINST",
            "My social security number is 123-45-6789.",
            "This proves my identity.",
            "PII - should be blocked",
        ),
    ]

    post_results = []

    for side, facts, inference, description in test_cases:
        print(f"\n[Test: {description}]")
        topic_id = "t1" if side == "FOR" else "t3"
        post_results.append(
            tester.submit_post(side=side, topic_id=topic_id, facts=facts, inference=inference)
        )

    # Generate snapshot to see allowed posts
    print("\n[Generating snapshot to see allowed posts...]")
    snapshot = tester.generate_snapshot()

    print("\n" + "=" * 70)
    print("MODULATION TEST COMPLETE")
    print("=" * 70)

    return all(post_results) and bool(snapshot)


def print_usage():
    """Print usage information"""
    print("""
Blind Debate Adjudicator - Manual Testing Script

Usage:
  python manual_scenarios.py [command] [--base-url URL]

Commands:
  server-check    Check if server is running
  scenario-ai     Run AI regulation debate scenario
  scenario-energy Run renewable energy debate scenario
  modulation      Test content moderation system
  custom          Interactive mode (create your own debate)

Examples:
  python manual_scenarios.py server-check
  python manual_scenarios.py scenario-ai
  python manual_scenarios.py server-check --base-url http://127.0.0.1:5055
  python manual_scenarios.py modulation

Before running tests:
  1. Start the server: python3 scripts/dev_workflow.py server
  2. Wait for "Server running" message
  3. Run this script in another terminal
""")


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("command", nargs="?")
    parser.add_argument("--base-url", default=BASE_URL)
    args = parser.parse_args()

    if not args.command:
        print_usage()
        return

    command = args.command

    if command == "server-check":
        tester = DebateSystemTester(base_url=args.base_url)
        success = tester.check_server()
        sys.exit(0 if success else 1)

    elif command == "scenario-ai":
        success = run_scenario_ai_regulation(base_url=args.base_url)
        sys.exit(0 if success else 1)

    elif command == "scenario-energy":
        success = run_scenario_renewable_energy(base_url=args.base_url)
        sys.exit(0 if success else 1)

    elif command == "modulation":
        success = run_modulation_test(base_url=args.base_url)
        sys.exit(0 if success else 1)

    elif command == "custom":
        print("Interactive mode not yet implemented.")
        print("Use the web interface at http://localhost:5000 for custom debates.")

    else:
        print(f"Unknown command: {command}")
        print_usage()
        sys.exit(1)


if __name__ == "__main__":
    main()
