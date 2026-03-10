"""
Flask API for Blind Debate Adjudicator
"""
import os
import sys
from datetime import datetime
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from debate_engine import DebateEngine
from models import Side

app = Flask(__name__)
CORS(app)

# Initialize debate engine
debate_engine = DebateEngine(fact_check_mode="ONLINE_ALLOWLIST")

# Store for current debate
current_debate = None


@app.route('/api/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat()
    })


@app.route('/api/debate', methods=['POST'])
def create_debate():
    """Create a new debate"""
    global current_debate
    
    data = request.json or {}
    resolution = data.get('resolution', 'Resolved: AI should be banned.')
    scope = data.get('scope', 'Whether AI development should be banned and the implications.')
    
    current_debate = debate_engine.create_debate(resolution, scope)
    
    return jsonify({
        "debate_id": current_debate.debate_id,
        "resolution": current_debate.resolution,
        "scope": current_debate.scope,
        "created_at": current_debate.created_at.isoformat()
    })


@app.route('/api/debate', methods=['GET'])
def get_debate():
    """Get current debate info"""
    global current_debate
    
    if not current_debate:
        # Create default debate
        current_debate = debate_engine.create_debate(
            "Resolved: AI should be banned.",
            "Whether AI development should be banned and the implications."
        )
    
    return jsonify({
        "debate_id": current_debate.debate_id,
        "resolution": current_debate.resolution,
        "scope": current_debate.scope,
        "created_at": current_debate.created_at.isoformat(),
        "pending_posts": len(current_debate.pending_posts)
    })


@app.route('/api/debate/posts', methods=['POST'])
def submit_post():
    """Submit a new post"""
    global current_debate
    
    if not current_debate:
        return jsonify({"error": "No active debate"}), 400
    
    data = request.json or {}
    
    required = ['side', 'facts', 'inference']
    for field in required:
        if not data.get(field):
            return jsonify({"error": f"Missing required field: {field}"}), 400
    
    post = debate_engine.submit_post(
        debate_id=current_debate.debate_id,
        side=data['side'],
        topic_id=data.get('topic_id', 't1'),
        facts=data['facts'],
        inference=data['inference'],
        counter_arguments=data.get('counter_arguments', '')
    )
    
    return jsonify({
        "post_id": post.post_id,
        "side": post.side.value,
        "topic_id": post.topic_id,
        "modulation_outcome": post.modulation_outcome.value,
        "block_reason": post.block_reason.value if post.block_reason else None,
        "timestamp": post.timestamp.isoformat()
    })


@app.route('/api/debate/snapshot', methods=['POST'])
def generate_snapshot():
    """Generate a new snapshot with scoring"""
    global current_debate
    
    if not current_debate:
        return jsonify({"error": "No active debate"}), 400
    
    data = request.json or {}
    trigger_type = data.get('trigger_type', 'manual')
    
    snapshot = debate_engine.generate_snapshot(
        debate_id=current_debate.debate_id,
        trigger_type=trigger_type
    )
    
    return jsonify({
        "snapshot_id": snapshot.snapshot_id,
        "timestamp": snapshot.timestamp.isoformat(),
        "trigger_type": snapshot.trigger_type,
        "template_name": snapshot.template_name,
        "template_version": snapshot.template_version,
        "allowed_count": snapshot.allowed_count,
        "blocked_count": snapshot.blocked_count,
        "block_reasons": {k.value: v for k, v in snapshot.block_reasons.items()},
        "overall_for": snapshot.overall_for,
        "overall_against": snapshot.overall_against,
        "margin_d": snapshot.margin_d,
        "ci_d": [snapshot.ci_d_lower, snapshot.ci_d_upper],
        "confidence": snapshot.confidence,
        "verdict": snapshot.verdict
    })


@app.route('/api/debate/snapshot', methods=['GET'])
def get_current_snapshot():
    """Get current snapshot data"""
    global current_debate
    
    if not current_debate:
        return jsonify({"error": "No active debate"}), 400
    
    if not current_debate.current_snapshot:
        # Generate initial snapshot
        debate_engine.generate_snapshot(current_debate.debate_id, "initial")
    
    snapshot = current_debate.current_snapshot
    
    return jsonify({
        "snapshot_id": snapshot.snapshot_id,
        "timestamp": snapshot.timestamp.isoformat(),
        "trigger_type": snapshot.trigger_type,
        "template_name": snapshot.template_name,
        "template_version": snapshot.template_version,
        "allowed_count": snapshot.allowed_count,
        "blocked_count": snapshot.blocked_count,
        "block_reasons": {k.value: v for k, v in snapshot.block_reasons.items()},
        "overall_for": snapshot.overall_for,
        "overall_against": snapshot.overall_against,
        "margin_d": snapshot.margin_d,
        "ci_d": [snapshot.ci_d_lower, snapshot.ci_d_upper],
        "confidence": snapshot.confidence,
        "verdict": snapshot.verdict
    })


@app.route('/api/debate/topics', methods=['GET'])
def get_topics():
    """Get all topics with scores"""
    global current_debate
    
    if not current_debate or not current_debate.current_snapshot:
        return jsonify({"error": "No snapshot available"}), 400
    
    snapshot = current_debate.current_snapshot
    
    topics_data = []
    for topic in snapshot.topics:
        tid = topic.topic_id
        
        # Get scores for both sides
        for_key = f"{tid}_FOR"
        against_key = f"{tid}_AGAINST"
        
        for_scores = snapshot.topic_scores.get(for_key)
        against_scores = snapshot.topic_scores.get(against_key)
        
        topics_data.append({
            "topic_id": tid,
            "name": topic.name,
            "scope": topic.scope,
            "relevance": topic.relevance,
            "drift_score": topic.drift_score,
            "coherence": topic.coherence,
            "distinctness": topic.distinctness,
            "summary_for": topic.summary_for,
            "summary_against": topic.summary_against,
            "scores": {
                "FOR": {
                    "factuality": for_scores.factuality if for_scores else 0.5,
                    "reasoning": for_scores.reasoning if for_scores else 0.5,
                    "coverage": for_scores.coverage if for_scores else 0.5,
                    "quality": for_scores.quality if for_scores else 0.5,
                    "reasoning_iqr": for_scores.reasoning_iqr if for_scores else 0.0,
                    "coverage_iqr": for_scores.coverage_iqr if for_scores else 0.0,
                },
                "AGAINST": {
                    "factuality": against_scores.factuality if against_scores else 0.5,
                    "reasoning": against_scores.reasoning if against_scores else 0.5,
                    "coverage": against_scores.coverage if against_scores else 0.5,
                    "quality": against_scores.quality if against_scores else 0.5,
                    "reasoning_iqr": against_scores.reasoning_iqr if against_scores else 0.0,
                    "coverage_iqr": against_scores.coverage_iqr if against_scores else 0.0,
                }
            }
        })
    
    return jsonify({"topics": topics_data})


@app.route('/api/debate/topics/<topic_id>/facts', methods=['GET'])
def get_topic_facts(topic_id):
    """Get facts for a topic"""
    global current_debate
    
    if not current_debate or not current_debate.current_snapshot:
        return jsonify({"error": "No snapshot available"}), 400
    
    snapshot = current_debate.current_snapshot
    facts = snapshot.canonical_facts.get(topic_id, [])
    
    return jsonify({
        "topic_id": topic_id,
        "facts": [
            {
                "canon_fact_id": f.canon_fact_id,
                "canon_fact_text": f.canon_fact_text,
                "p_true": f.p_true,
                "referenced_by": list(f.referenced_by_au_ids)
            }
            for f in facts
        ]
    })


@app.route('/api/debate/topics/<topic_id>/arguments', methods=['GET'])
def get_topic_arguments(topic_id):
    """Get arguments for a topic"""
    global current_debate
    
    if not current_debate or not current_debate.current_snapshot:
        return jsonify({"error": "No snapshot available"}), 400
    
    snapshot = current_debate.current_snapshot
    args = snapshot.canonical_arguments.get(topic_id, [])
    
    return jsonify({
        "topic_id": topic_id,
        "arguments": [
            {
                "canon_arg_id": a.canon_arg_id,
                "side": a.side.value,
                "inference_text": a.inference_text,
                "supporting_facts": list(a.supporting_facts),
                "reasoning_score": a.reasoning_score,
                "reasoning_iqr": a.reasoning_iqr
            }
            for a in args
        ]
    })


@app.route('/api/debate/verdict', methods=['GET'])
def get_verdict():
    """Get complete verdict data"""
    global current_debate
    
    if not current_debate or not current_debate.current_snapshot:
        return jsonify({"error": "No snapshot available"}), 400
    
    snapshot = current_debate.current_snapshot
    
    # Build topic contributions
    contributions = []
    for topic in snapshot.topics:
        tid = topic.topic_id
        for_key = f"{tid}_FOR"
        against_key = f"{tid}_AGAINST"
        
        for_scores = snapshot.topic_scores.get(for_key)
        against_scores = snapshot.topic_scores.get(against_key)
        
        if for_scores and against_scores:
            contribution = topic.relevance * (for_scores.quality - against_scores.quality)
            contributions.append({
                "topic_id": tid,
                "name": topic.name,
                "relevance": topic.relevance,
                "q_for": for_scores.quality,
                "q_against": against_scores.quality,
                "contribution_to_d": round(contribution, 4)
            })
    
    return jsonify({
        "snapshot_id": snapshot.snapshot_id,
        "overall_for": snapshot.overall_for,
        "overall_against": snapshot.overall_against,
        "margin_d": snapshot.margin_d,
        "ci_d": [snapshot.ci_d_lower, snapshot.ci_d_upper],
        "confidence": snapshot.confidence,
        "verdict": snapshot.verdict,
        "topic_contributions": contributions
    })


@app.route('/api/debate/audits', methods=['GET'])
def get_audits():
    """Get audit data"""
    global current_debate
    
    if not current_debate or not current_debate.current_snapshot:
        return jsonify({"error": "No snapshot available"}), 400
    
    snapshot = current_debate.current_snapshot
    
    # Calculate extraction stability (mock)
    fact_overlap = {
        "p10": 0.72,
        "p50": 0.83,
        "p90": 0.91,
        "iqr": 0.10
    }
    
    arg_overlap = {
        "p10": 0.69,
        "p50": 0.81,
        "p90": 0.89,
        "iqr": 0.13
    }
    
    # Calculate evaluator disagreement (mock)
    reasoning_scores = []
    coverage_scores = []
    for ts in snapshot.topic_scores.values():
        reasoning_scores.append(ts.reasoning)
        coverage_scores.append(ts.coverage)
    
    return jsonify({
        "snapshot_id": snapshot.snapshot_id,
        "topic_geometry": [
            {
                "topic_id": t.topic_id,
                "content_mass": t.relevance,
                "drift_score": t.drift_score,
                "coherence": t.coherence,
                "distinctness": t.distinctness,
                "operation": t.operation
            }
            for t in snapshot.topics
        ],
        "extraction_stability": {
            "fact_overlap": fact_overlap,
            "argument_overlap": arg_overlap
        },
        "evaluator_disagreement": {
            "reasoning_iqr_median": 0.19,
            "coverage_iqr_median": 0.16,
            "overall_iqr": 0.06
        },
        "label_symmetry": {
            "median_delta_d": -0.02,
            "iqr_delta_d": 0.11,
            "interpretation": "small asymmetry; contributes to confidence reduction"
        }
    })


@app.route('/api/debate/evidence', methods=['GET'])
def get_evidence_targets():
    """Get 'what evidence would change this' targets"""
    global current_debate
    
    if not current_debate or not current_debate.current_snapshot:
        return jsonify({"error": "No snapshot available"}), 400
    
    snapshot = current_debate.current_snapshot
    
    # Find high-leverage facts (those with p near 0.5)
    targets = []
    for tid, facts in snapshot.canonical_facts.items():
        for f in facts:
            decisiveness = abs(f.p_true - 0.5)
            if decisiveness < 0.15:  # Near 0.5
                targets.append({
                    "topic_id": tid,
                    "fact_id": f.canon_fact_id,
                    "fact_text": f.canon_fact_text,
                    "p_true": f.p_true,
                    "decisiveness": round(decisiveness, 2),
                    "why_matters": f"Fact with high uncertainty (p ≈ {f.p_true:.2f}). New evidence could significantly change the outcome.",
                    "evidence_needed": "Independent empirical studies with clear findings"
                })
    
    # Sort by decisiveness (lowest first = most uncertain)
    targets.sort(key=lambda x: x["decisiveness"])
    
    return jsonify({
        "high_leverage_targets": targets[:5],
        "update_triggers": [
            "If uncertain facts (p ≈ 0.5) move to strongly supported (p > 0.75), their supporting arguments gain leverage",
            "If high-leverage facts are contradicted (p < 0.3), their arguments lose significant weight",
            "New evidence on borderline facts can flip topic-level quality scores"
        ]
    })


# Static file serving
@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve_static(path):
    """Serve static frontend files"""
    if not path:
        path = 'index.html'
    
    frontend_dir = os.path.join(os.path.dirname(__file__), '..', 'frontend')
    
    # Try to serve from frontend directory
    try:
        return send_from_directory(frontend_dir, path)
    except:
        # Fallback to index.html for SPA routing
        return send_from_directory(frontend_dir, 'index.html')


if __name__ == '__main__':
    # Initialize with default debate
    current_debate = debate_engine.create_debate(
        "Resolved: AI should be banned.",
        "Whether AI development should be banned and the implications for safety, economics, and society."
    )
    
    # Generate initial snapshot
    debate_engine.generate_snapshot(current_debate.debate_id, "initial")
    
    print("=" * 60)
    print("Blind Debate Adjudicator Server")
    print("=" * 60)
    print(f"Debate ID: {current_debate.debate_id}")
    print(f"Resolution: {current_debate.resolution}")
    print("-" * 60)
    print("API available at: http://localhost:5000")
    print("Web UI available at: http://localhost:5000")
    print("=" * 60)
    
    app.run(host='0.0.0.0', port=5000, debug=True)
