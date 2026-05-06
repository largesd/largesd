"""Dossier blueprint — verdict, audits, decision dossier."""
import json
import os

from flask import Blueprint, g, jsonify

from backend import extensions
from backend.lsd_v1_2 import formula_registry
from backend.utils.decorators import optional_auth
from backend.utils.helpers import get_session_debate_id

dossier_bp = Blueprint('dossier', __name__)


@dossier_bp.route('/api/debate/verdict', methods=['GET'])
@optional_auth
def get_verdict():
    """Get verdict"""
    debate_id = get_session_debate_id()
    if not debate_id:
        return jsonify({'error': 'No active debate'}), 400

    snapshot = extensions.db.get_latest_snapshot(debate_id)
    if not snapshot:
        return jsonify({'error': 'No snapshot available'}), 404

    allowed_count = snapshot.get('allowed_count', 0) or 0
    has_scores = (
        snapshot.get('overall_for') is not None
        or snapshot.get('overall_against') is not None
        or snapshot.get('margin_d') is not None
    )
    if allowed_count == 0 or not has_scores:
        return jsonify({
            'snapshot_id': snapshot['snapshot_id'],
            'insufficient_data': True,
            'verdict': 'INSUFFICIENT_DATA',
            'message': 'Insufficient adjudication data. No allowed posts or scores are available for this debate.',
            'overall_for': None,
            'overall_against': None,
            'margin_d': None,
            'ci_d': [None, None],
            'confidence': None,
            'topic_contributions': [],
            'd_distribution': [],
            'replicate_composition_metadata': {
                'judge_count': int(os.getenv('NUM_JUDGES', '5')),
                'replicate_count': 0,
                'extraction_reruns': 2,
                'bootstrap_samples': 0,
                'structural_replicate_count': 0,
                'merge_sensitivity_channel': False,
            },
            'formula_metadata': formula_registry(),
            'factuality': {'tier_counts': {}},
        })

    topic_scores = json.loads(snapshot.get('topic_scores', '{}'))
    topics = extensions.db.get_topics_by_debate(debate_id)
    audits = extensions.debate_engine.get_audits_for_snapshot(snapshot['snapshot_id'])
    verdict_replicates = audits.get('verdict_replicates', {})
    dossier = audits.get('decision_dossier', {})

    contributions = []
    for topic in topics:
        tid = topic['topic_id']
        for_key = f"{tid}_FOR"
        against_key = f"{tid}_AGAINST"
        for_scores = topic_scores.get(for_key, {})
        against_scores = topic_scores.get(against_key, {})
        contribution = topic['relevance'] * (for_scores.get('quality', 0) - against_scores.get('quality', 0))
        contributions.append({
            'topic_id': tid,
            'name': topic['name'],
            'relevance': topic['relevance'],
            'q_for': for_scores.get('quality', 0),
            'q_against': against_scores.get('quality', 0),
            'contribution_to_d': round(contribution, 4)
        })

    return jsonify({
        'snapshot_id': snapshot['snapshot_id'],
        'overall_for': snapshot['overall_for'],
        'overall_against': snapshot['overall_against'],
        'margin_d': snapshot['margin_d'],
        'ci_d': [snapshot['ci_d_lower'], snapshot['ci_d_upper']],
        'confidence': snapshot['confidence'],
        'verdict': snapshot['verdict'],
        'topic_contributions': contributions,
        'd_distribution': verdict_replicates.get('d_distribution', []),
        'replicate_composition_metadata': {
            'judge_count': int(os.getenv('NUM_JUDGES', '5')),
            'replicate_count': verdict_replicates.get('replicate_composition', {}).get('replicate_count', len(verdict_replicates.get('d_distribution', []))),
            'extraction_reruns': 2,
            'bootstrap_samples': verdict_replicates.get('replicate_composition', {}).get('bootstrap_samples', len(verdict_replicates.get('d_distribution', []))),
            'structural_replicate_count': verdict_replicates.get('replicate_composition', {}).get('structural_replicate_count', 0),
            'merge_sensitivity_channel': bool(audits.get('topic_merge_sensitivity')),
        },
        'formula_metadata': formula_registry(),
        'factuality': {
            'tier_counts': {
                key: value.get('tier_distribution', {})
                for key, value in (dossier.get('evidence_gaps') or {}).items()
            }
        },
    })


@dossier_bp.route('/api/debate/audits', methods=['GET'])
@optional_auth
def get_audits():
    """Get audits"""
    debate_id = get_session_debate_id()
    if not debate_id:
        return jsonify({'error': 'No active debate'}), 400

    snapshot = extensions.db.get_latest_snapshot(debate_id)
    if not snapshot:
        return jsonify({'error': 'No snapshot available'}), 404

    audits = extensions.debate_engine.get_audits_for_snapshot(snapshot['snapshot_id'])
    topics = extensions.db.get_topics_by_debate(debate_id)

    topic_geometry = [
        {
            'topic_id': t['topic_id'],
            'name': t['name'],
            'content_mass': t['relevance'],
            'drift_score': t['drift_score'],
            'coherence': t['coherence'],
            'distinctness': t['distinctness'],
            'operation': t.get('operation', 'created'),
            'parent_topic_ids': json.loads(t.get('parent_topic_ids', '[]') or '[]')
        }
        for t in topics
    ]

    extraction_stability = audits.get('extraction_stability', {})
    label_symmetry = audits.get('side_label_symmetry', {})
    relevance_sensitivity = audits.get('relevance_sensitivity', {})
    topic_diag = audits.get('topic_diagnostics', {})

    return jsonify({
        'snapshot_id': snapshot['snapshot_id'],
        'audit_schema_version': __import__('backend.lsd_v1_2', fromlist=['AUDIT_SCHEMA_VERSION']).AUDIT_SCHEMA_VERSION,
        'timestamp': snapshot['timestamp'],
        'verdict': snapshot['verdict'],
        'confidence': snapshot['confidence'],
        'topic_geometry': topic_geometry,
        'topic_dominance': topic_diag.get('dominance', {}),
        'topic_concentration': {
            'micro_topic_rate': topic_diag.get('micro_topic_rate', 0.0),
            'mass_distribution_quantiles': topic_diag.get('mass_distribution_quantiles', {}),
            'gini_coefficient': topic_diag.get('gini_coefficient', 0.0),
        },
        'extraction_stability': {
            'fact_overlap': extraction_stability.get('fact_overlap', {}),
            'argument_overlap': extraction_stability.get('argument_overlap', {}),
            'mismatches': extraction_stability.get('mismatches', []),
            'num_runs': extraction_stability.get('num_runs', 0),
            'stability_score': extraction_stability.get('stability_score', 0)
        },
        'evaluator_disagreement': audits.get('evaluator_variance', {}),
        'label_symmetry': {
            'median_delta_d': label_symmetry.get('median_delta_d', 0),
            'abs_delta_d': label_symmetry.get('abs_delta_d', 0),
            'original_d': label_symmetry.get('original_d', 0),
            'swapped_d': label_symmetry.get('swapped_d', 0),
            'topic_deltas': label_symmetry.get('topic_deltas', {}),
            'interpretation': label_symmetry.get('interpretation', '')
        },
        'relevance_sensitivity': relevance_sensitivity,
        'frame_sensitivity': audits.get('frame_sensitivity', {}),
        'integrity_indicators': audits.get('integrity_indicators', {}),
        'participation_concentration': audits.get('participation_concentration', {}),
        'budget_adequacy': audits.get('budget_adequacy', {}),
        'centrality_cap_effect': audits.get('centrality_cap_effect', {}),
        'rarity_utilization': audits.get('rarity_utilization', {}),
        'merge_sensitivity': audits.get('topic_merge_sensitivity', {}),
        'coverage_adequacy_trace': audits.get('coverage_adequacy_trace', {}),
        'selection_transparency': audits.get('selection_transparency', {}),
        'formula_registry': audits.get('formula_registry', formula_registry()),
    })


@dossier_bp.route('/api/debate/decision-dossier', methods=['GET'])
@optional_auth
def get_decision_dossier():
    """Get decision dossier for current snapshot"""
    debate_id = get_session_debate_id()
    if not debate_id:
        return jsonify({'error': 'No active debate'}), 400

    snapshot = extensions.db.get_latest_snapshot(debate_id)
    if not snapshot:
        return jsonify({'error': 'No snapshot available'}), 404

    allowed_count = snapshot.get('allowed_count', 0) or 0
    has_scores = (
        snapshot.get('overall_for') is not None
        or snapshot.get('overall_against') is not None
        or snapshot.get('margin_d') is not None
    )
    if allowed_count == 0 or not has_scores:
        return jsonify({
            'snapshot_id': snapshot['snapshot_id'],
            'insufficient_data': True,
            'verdict': 'INSUFFICIENT_DATA',
            'message': 'Insufficient adjudication data. No allowed posts or scores are available for this debate.',
            'frame': extensions.debate_engine.get_frame_info(),
            'overall_for': None,
            'overall_against': None,
            'margin_d': None,
            'evidence_gaps': {},
            'evidence_gap_summary': {},
            'decisive_premises': [],
            'decisive_arguments': [],
            'counterfactuals': {},
            'priority_gaps': {},
            'insufficiency_sensitivity': {},
            'unselected_tail_summary': {},
            'formula_metadata': formula_registry(),
            'selection_diagnostics': {},
        })

    audits = extensions.debate_engine.get_audits_for_snapshot(snapshot['snapshot_id'])
    saved_dossier = audits.get('decision_dossier', {})
    topic_scores = json.loads(snapshot.get('topic_scores', '{}'))
    topics = extensions.db.get_topics_by_debate(debate_id)
    evidence_gaps = {}
    for topic in topics:
        tid = topic['topic_id']
        for side in ['FOR', 'AGAINST']:
            scores = topic_scores.get(f"{tid}_{side}", {})
            evidence_gaps[f"{tid}_{side}"] = {
                'insufficiency_rate': scores.get('insufficiency_rate', 0.0),
                'f_supported_only': scores.get('f_supported_only', 0.5),
                'f_all': scores.get('factuality', 0.5),
            }

    selection_diag = audits.get('selection_transparency', {})

    return jsonify({
        'snapshot_id': snapshot['snapshot_id'],
        'frame': extensions.debate_engine.get_frame_info(),
        'verdict': snapshot['verdict'],
        'confidence': snapshot['confidence'],
        'overall_for': snapshot['overall_for'],
        'overall_against': snapshot['overall_against'],
        'margin_d': snapshot['margin_d'],
        'evidence_gaps': saved_dossier.get('evidence_gaps', evidence_gaps),
        'evidence_gap_summary': saved_dossier.get('evidence_gaps', evidence_gaps),
        'decisive_premises': saved_dossier.get('decisive_premises', []),
        'decisive_arguments': saved_dossier.get('decisive_arguments', []),
        'counterfactuals': saved_dossier.get('counterfactuals', {}),
        'priority_gaps': saved_dossier.get('priority_gaps', {}),
        'insufficiency_sensitivity': saved_dossier.get('insufficiency_sensitivity', {}),
        'unselected_tail_summary': saved_dossier.get('unselected_tail_summary', {}),
        'formula_metadata': saved_dossier.get('formula_metadata', formula_registry()),
        'selection_diagnostics': selection_diag,
    })
