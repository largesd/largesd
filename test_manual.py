"""
Manual Testing Script for Blind Debate Adjudicator
Run this to test the system interactively or with predefined scenarios
"""
import argparse
import sys
import os
import json
import requests
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))

# Base URL for API
BASE_URL = os.getenv("DEBATE_BASE_URL", "http://localhost:5000")


class DebateSystemTester:
    """Manual tester for the debate system via API"""
    
    def __init__(self, base_url=BASE_URL):
        self.base_url = base_url
        self.debate_id = None
        self.snapshot_id = None
    
    def check_server(self):
        """Check if server is running"""
        try:
            response = requests.get(f"{self.base_url}/api/health", timeout=5)
            if response.status_code == 200:
                print(f"✓ Server is running at {self.base_url}")
                return True
        except requests.exceptions.ConnectionError:
            print(f"✗ Server not available at {self.base_url}")
            print("  Start the server with: ./start.sh --v2")
            return False
        return False
    
    def create_debate(self, motion, moderation_criteria, debate_frame):
        """Create a new debate"""
        print(f"\n[Creating Debate]")
        print(f"  Motion: {motion}")
        
        response = requests.post(
            f"{self.base_url}/api/debate",
            json={
                "motion": motion,
                "moderation_criteria": moderation_criteria,
                "debate_frame": debate_frame,
            }
        )
        
        if response.status_code == 200:
            data = response.json()
            self.debate_id = data['debate_id']
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
        
        response = requests.post(
            f"{self.base_url}/api/debate/posts",
            json={
                "debate_id": self.debate_id,
                "side": side,
                "facts": facts,
                "inference": inference,
                "counter_arguments": counter_args,
                "topic_id": topic_id
            }
        )
        
        if response.status_code == 200:
            data = response.json()
            outcome = data.get('modulation_outcome', 'unknown')
            print(f"✓ Post {data['post_id']}: {outcome.upper()}")
            if data.get('block_reason'):
                print(f"  Block reason: {data['block_reason']}")
            return data
        else:
            print(f"✗ Failed: {response.text}")
            return None
    
    def generate_snapshot(self):
        """Generate a snapshot"""
        print(f"\n[Generating Snapshot]")
        
        if not self.debate_id:
            print("✗ No debate created yet")
            return None
        
        response = requests.post(
            f"{self.base_url}/api/debate/snapshot",
            json={"debate_id": self.debate_id, "trigger_type": "manual"}
        )
        
        if response.status_code == 200:
            data = response.json()
            self.snapshot_id = data.get('snapshot_id')
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
        print(f"\n[Getting Topics]")
        
        response = requests.get(f"{self.base_url}/api/debate/topics")
        
        if response.status_code == 200:
            data = response.json()
            topics = data.get('topics', [])
            print(f"✓ Found {len(topics)} topics:")
            for t in topics:
                print(f"  - {t['name']} (relevance: {t.get('relevance', 0):.2f})")
            return data
        else:
            print(f"✗ Failed: {response.text}")
            return None
    
    def get_verdict(self):
        """Get current verdict"""
        print(f"\n[Getting Verdict]")
        
        response = requests.get(f"{self.base_url}/api/debate/verdict")
        
        if response.status_code == 200:
            data = response.json()
            print(f"✓ Current verdict:")
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
        print(f"\n[Getting Audits]")
        
        response = requests.get(f"{self.base_url}/api/debate/audits")
        
        if response.status_code == 200:
            data = response.json()
            audits = data.get('audits', {})
            print(f"✓ Available audits:")
            for audit_type in audits.keys():
                print(f"  - {audit_type}")
            return data
        else:
            print(f"✗ Failed: {response.text}")
            return None
    
    def get_evidence_targets(self):
        """Get 'what evidence would change this' analysis"""
        print(f"\n[Getting Evidence Targets]")
        
        response = requests.get(f"{self.base_url}/api/debate/evidence-targets")
        
        if response.status_code == 200:
            data = response.json()
            print(f"✓ Evidence targets retrieved")
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
        motion="Should advanced AI development be paused for safety reasons?",
        moderation_criteria=(
            "Allow good-faith arguments that engage the pause motion directly. "
            "Block harassment, spam, PII, and off-topic content. Prefer evidence "
            "about safety, governance, competitiveness, and current impacts."
        ),
        debate_frame=(
            "Judge which side most fairly interprets the pause motion, best captures "
            "the core clash between safety and continued deployment, and most usefully "
            "informs a neutral policymaker."
        ),
    )
    
    if not debate:
        return False
    
    # Submit FOR posts (pro-pause)
    post_results = []

    post_results.append(tester.submit_post(
        side="FOR",
        facts="AI systems have demonstrated capabilities that could be used to generate convincing misinformation at scale. Leading AI researchers have signed letters calling for pauses.",
        inference="Therefore, development should be paused until adequate safety measures are established.",
        counter_args="Arguments about innovation and competitiveness"
    ))
    
    post_results.append(tester.submit_post(
        side="FOR",
        facts="Current AI alignment techniques do not guarantee that advanced systems will remain under human control. Accidents in testing have already occurred.",
        inference="Pausing now prevents potentially catastrophic accidents later.",
        counter_args="Market-based safety approaches"
    ))
    
    # Submit AGAINST posts (anti-pause)
    post_results.append(tester.submit_post(
        side="AGAINST",
        facts="Pausing AI development in one country would simply allow other countries to take the lead. History shows that technological bans are rarely effective globally.",
        inference="A pause would harm domestic competitiveness without improving safety.",
        counter_args="Arguments about safety and misinformation"
    ))
    
    post_results.append(tester.submit_post(
        side="AGAINST",
        facts="AI development has already created significant economic value. Medical applications of AI are saving lives today.",
        inference="Pausing development would cause real harm to current beneficiaries.",
        counter_args="Long-term existential risk arguments"
    ))
    
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
        motion="Should governments provide subsidies for renewable energy?",
        moderation_criteria=(
            "Allow evidence-backed arguments about costs, benefits, fairness, and "
            "implementation. Block harassment, spam, PII, and off-topic content."
        ),
        debate_frame=(
            "Judge which side best informs a neutral policymaker balancing economic "
            "efficiency, environmental impact, grid reliability, and long-term public value."
        ),
    )
    
    if not debate:
        return False
    
    # Submit FOR posts
    post_results = []

    post_results.append(tester.submit_post(
        side="FOR",
        facts="Renewable energy creates 3x more jobs per dollar invested than fossil fuels. Solar and wind costs have dropped 80% in the last decade.",
        inference="Subsidies for renewables are economically justified by job creation and declining costs.",
        counter_args="Market distortion arguments"
    ))
    
    post_results.append(tester.submit_post(
        side="FOR",
        facts="Climate change imposes external costs not reflected in fossil fuel prices. Carbon emissions cause measurable health impacts.",
        inference="Subsidies correct for market failures by internalizing environmental externalities.",
        counter_args="Economic efficiency concerns"
    ))
    
    # Submit AGAINST posts
    post_results.append(tester.submit_post(
        side="AGAINST",
        facts="Government subsidies distort price signals and lead to inefficient allocation of capital. Failed renewable companies have cost taxpayers billions.",
        inference="Market forces, not government subsidies, should determine energy investments.",
        counter_args="Environmental necessity arguments"
    ))
    
    post_results.append(tester.submit_post(
        side="AGAINST",
        facts="Subsidies create dependency. When subsidies are removed, industries often collapse. Nuclear energy provides baseload power without intermittency.",
        inference="Resources would be better spent on nuclear and grid infrastructure rather than intermittent renewables.",
        counter_args="Speed of deployment and safety"
    ))
    
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
        motion="Test debate for moderation",
        moderation_criteria=(
            "Allow only good-faith arguments that engage the motion directly. Block "
            "harassment, spam, PII, and off-topic content."
        ),
        debate_frame="Judge the moderation outcomes by whether the criteria are applied fairly and consistently.",
    )
    
    if not debate:
        return False
    
    # Test various posts
    test_cases = [
        ("FOR", "Studies show economic growth correlates with education.", 
         "Therefore, we should invest in education.", "Valid content - should pass"),
        
        ("FOR", "You're all idiots who don't understand economics.", 
         "Therefore, my view is correct.", "Harassment - should be blocked"),
        
        ("FOR", "Check out my amazing products at discount prices!!! Click here!!!", 
         "Buy now for great deals!", "Spam - should be blocked"),
        
        ("AGAINST", "The data from the 2023 census shows population decline.", 
         "Thus, immigration policy needs revision.", "Valid content - should pass"),
        
        ("AGAINST", "My social security number is 123-45-6789.", 
         "This proves my identity.", "PII - should be blocked"),
    ]
    
    post_results = []

    for side, facts, inference, description in test_cases:
        print(f"\n[Test: {description}]")
        post_results.append(tester.submit_post(side=side, facts=facts, inference=inference))
    
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
  python test_manual.py [command] [--base-url URL]

Commands:
  server-check    Check if server is running
  scenario-ai     Run AI regulation debate scenario
  scenario-energy Run renewable energy debate scenario
  modulation      Test content moderation system
  custom          Interactive mode (create your own debate)

Examples:
  python test_manual.py server-check
  python test_manual.py scenario-ai
  python test_manual.py server-check --base-url http://127.0.0.1:5055
  python test_manual.py modulation

Before running tests:
  1. Start the server: ./start.sh --v2
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
