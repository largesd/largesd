"""Topic blueprint — topics, modulation metadata, evidence targets."""
import json

from flask import Blueprint, current_app, g, jsonify, request

from backend import extensions
from backend.lsd_v1_2 import formula_registry
from backend.utils.decorators import optional_auth
from backend.utils.helpers import get_session_debate_id
from backend.utils.validators import ValidationError, validate_string

topic_bp = Blueprint('topic', __name__)


@topic_bp.route('/api/debate/topics', methods=['GET'])
@optional_auth
def get_topics():
    """Get all topics"""
    debate_id = get_session_debate_id()
    if not debate_id:
        return jsonify({'error': 'No active debate'}), 400

    topics = extensions.db.get_topics_by_debate(debate_id)
    snapshot = extensions.db.get_latest_snapshot(debate_id)
    topic_scores = {}
    topic_diag = {}
    merge_diag = {}
    current_topic_ids = set()

    if snapshot:
        topic_scores = json.loads(snapshot.get('topic_scores', '{}'))
        audits = extensions.debate_engine.get_audits_for_snapshot(snapshot['snapshot_id'])
        topic_diag = audits.get('topic_diagnostics', {})
        merge_diag = audits.get('topic_merge_sensitivity', {})
        current_topic_ids = {
            topic_id
            for topic_id, score_map in topic_scores.items()
            if isinstance(topic_id, str)
            and isinstance(score_map, dict)
            and score_map
            and all(isinstance(side_scores, dict) for side_scores in score_map.values())
        }
        if not current_topic_ids:
            current_topic_ids = (
                set((topic_diag.get('pre_mass') or {}).keys())
                | set((topic_diag.get('sel_mass') or {}).keys())
            )

    if current_topic_ids:
        topics = [topic for topic in topics if topic.get('topic_id') in current_topic_ids]

    topics.sort(
        key=lambda topic: (
            -float(topic.get('relevance', 0.0) or 0.0),
            str(topic.get('name') or ''),
            str(topic.get('topic_id') or ''),
        )
    )

    topics_data = []
    for topic in topics:
        tid = topic['topic_id']
        topics_data.append({
            'topic_id': tid,
            'name': topic['name'],
            'scope': topic['scope'],
            'relevance': topic['relevance'],
            'drift_score': topic['drift_score'],
            'coherence': topic['coherence'],
            'distinctness': topic['distinctness'],
            'summary_for': topic.get('summary_for', ''),
            'summary_against': topic.get('summary_against', ''),
            'operation': topic.get('operation', 'created'),
            'parent_topic_ids': json.loads(topic.get('parent_topic_ids', '[]') or '[]'),
            'pre_mass': (topic_diag.get('pre_mass') or {}).get(tid, 0.0),
            'sel_mass': (topic_diag.get('sel_mass') or {}).get(tid, 0.0),
            'pre_to_sel_ratio': (topic_diag.get('pre_to_sel_ratio') or {}).get(tid, 0.0),
            'relevance_formula_mode': topic_diag.get('relevance_formula_mode', 'legacy_linear'),
            'scores': {
                'FOR': topic_scores.get(f"{tid}_FOR", {}),
                'AGAINST': topic_scores.get(f"{tid}_AGAINST", {})
            }
        })

    return jsonify({
        'topics': topics_data,
        'diagnostics': topic_diag,
        'dominance': topic_diag.get('dominance', {}),
        'micro_topic_rate': topic_diag.get('micro_topic_rate', 0.0),
        'mass_distribution_quantiles': topic_diag.get('mass_distribution_quantiles', {}),
        'gini_coefficient': topic_diag.get('gini_coefficient', 0.0),
        'merge_sensitivity': merge_diag,
        'relevance_formula_mode': topic_diag.get('relevance_formula_mode', 'legacy_linear'),
    })


@topic_bp.route('/api/debate/topics/<topic_id>', methods=['GET'])
@optional_auth
def get_topic(topic_id):
    """Get specific topic details"""
    debate_id = get_session_debate_id()
    if not debate_id:
        return jsonify({'error': 'No active debate'}), 400
    if not topic_id or not __import__('re').match(r'^[a-zA-Z0-9_-]+$', topic_id):
        raise ValidationError("Invalid topic ID")

    topic = extensions.db.get_topic(topic_id, debate_id)
    if not topic:
        return jsonify({'error': 'Topic not found'}), 404

    facts = extensions.db.get_canonical_facts_by_topic(topic_id)
    args = extensions.db.get_canonical_arguments_by_topic(topic_id)
    snapshot = extensions.db.get_latest_snapshot(debate_id)
    topic_scores = {}
    if snapshot:
        topic_scores = json.loads(snapshot.get('topic_scores', '{}'))

    return jsonify({
        'topic_id': topic['topic_id'],
        'name': topic['name'],
        'scope': topic['scope'],
        'relevance': topic['relevance'],
        'drift_score': topic['drift_score'],
        'coherence': topic['coherence'],
        'distinctness': topic['distinctness'],
        'summary_for': topic.get('summary_for', ''),
        'summary_against': topic.get('summary_against', ''),
        'operation': topic.get('operation', 'created'),
        'parent_topic_ids': json.loads(topic.get('parent_topic_ids', '[]') or '[]'),
        'scores': {
            'FOR': topic_scores.get(f"{topic_id}_FOR", {}),
            'AGAINST': topic_scores.get(f"{topic_id}_AGAINST", {})
        },
        'facts': [
            {
                'canon_fact_id': f['canon_fact_id'],
                'canon_fact_text': f['canon_fact_text'],
                'side': f['side'],
                'p_true': f['p_true'],
                'fact_type': f.get('fact_type', 'empirical'),
                'operationalization': f.get('operationalization', ''),
                'normative_provenance': f.get('normative_provenance', ''),
                'evidence_tier_counts': json.loads(f.get('evidence_tier_counts_json', '{}') or '{}'),
                'member_count': len(json.loads(f.get('member_fact_ids', '[]'))),
                'v15_status': f.get('v15_status'),
                'v15_p': f.get('v15_p', f['p_true']),
                'v15_insufficiency_reason': f.get('v15_insufficiency_reason'),
                'v15_human_review_flags': json.loads(f.get('v15_human_review_flags_json', '[]') or '[]'),
                'v15_best_evidence_tier': f.get('v15_best_evidence_tier'),
            }
            for f in facts
        ],
        'arguments': [
            {
                'canon_arg_id': a['canon_arg_id'],
                'side': a['side'],
                'inference_text': a['inference_text'],
                'supporting_facts': json.loads(a.get('supporting_facts', '[]')),
                'member_count': len(json.loads(a.get('member_au_ids', '[]'))),
                'reasoning_score': a.get('reasoning_score', 0.5),
                'completeness_proxy': a.get('completeness_proxy', 0.0)
            }
            for a in args
        ]
    })


@topic_bp.route('/api/debate/modulation-info', methods=['GET'])
@optional_auth
def get_modulation_info():
    """Get the currently active modulation template metadata."""
    return jsonify(extensions.debate_engine.get_modulation_info())


@topic_bp.route('/api/debate/modulation-templates', methods=['GET'])
@optional_auth
def get_modulation_templates():
    """List builtin modulation templates and identify the active base template."""
    from backend.modulation import ModulationEngine
    active = extensions.db.get_active_moderation_template() or {}
    return jsonify({
        'templates': ModulationEngine.list_builtin_templates(),
        'active_base_template_id': active.get('base_template_id'),
    })


@topic_bp.route('/api/debate/evidence-targets', methods=['GET'])
@optional_auth
def get_evidence_targets():
    """Get evidence targets"""
    debate_id = get_session_debate_id()
    if not debate_id:
        return jsonify({'error': 'No active debate'}), 400
    snapshot_id = request.args.get('snapshot_id')
    try:
        targets = extensions.debate_engine.get_evidence_targets(debate_id, snapshot_id)
        return jsonify(targets)
    except Exception as e:
        current_app.logger.error(f"Evidence targets error: {str(e)}")
        return jsonify({'error': 'Failed to get evidence targets'}), 500
