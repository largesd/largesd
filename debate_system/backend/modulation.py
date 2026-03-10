"""
Template-based Modulation System

Per MSD §3: Admin-selectable, versioned templates for content moderation.
- Only Allowed posts influence Topics, Facts, Arguments, and scoring
- Template changes are versioned
- Block reasons are audited
"""

import re
from typing import List, Dict, Optional, Tuple, Any
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import json


class ModulationOutcome(Enum):
    ALLOWED = "allowed"
    BLOCKED = "blocked"


class BlockReason(Enum):
    OFF_TOPIC = "off_topic"
    PII = "pii"
    SPAM = "spam"
    HARASSMENT = "harassment"
    TOXICITY = "toxicity"
    PROMPT_INJECTION = "prompt_injection"
    LENGTH = "length"


@dataclass
class ModulationRule:
    """A single rule within a modulation template"""
    rule_id: str
    name: str
    rule_type: str  # keyword, regex, length, pii, etc.
    condition: Dict[str, Any]  # Rule-specific parameters
    action: str  # allow, block
    block_reason: Optional[BlockReason] = None
    priority: int = 100  # Lower = higher priority


@dataclass
class ModulationTemplate:
    """
    A versioned modulation template per MSD §3.
    
    Admin-selectable templates covering:
    - On-topic requirements
    - Toxicity / harassment / hate speech
    - PII restrictions
    - Spam limits
    - Length constraints
    - Prompt injection protection
    """
    template_id: str
    name: str
    version: str
    description: str
    rules: List[ModulationRule]
    created_at: str
    is_active: bool = True
    
    def get_version_string(self) -> str:
        """Return version identifier for audit trail"""
        return f"{self.name} v{self.version}"


class ModulationEngine:
    """
    Engine for applying modulation templates to posts.
    
    Per MSD §3:
    - Templates are visible to users
    - Template changes are versioned
    - Only Allowed posts influence downstream processing
    """
    
    # Standard built-in templates
    BUILTIN_TEMPLATES = {
        "standard_civility": {
            "name": "Standard Civility + PII Guard",
            "description": "Standard moderation with civility rules and PII protection",
            "rules": [
                {
                    "rule_id": "length_min",
                    "name": "Minimum Length",
                    "rule_type": "length",
                    "condition": {"min_chars": 20},
                    "action": "block",
                    "block_reason": "SPAM",
                    "priority": 10
                },
                {
                    "rule_id": "length_max",
                    "name": "Maximum Length",
                    "rule_type": "length",
                    "condition": {"max_chars": 10000},
                    "action": "block",
                    "block_reason": "SPAM",
                    "priority": 11
                },
                {
                    "rule_id": "pii_email",
                    "name": "PII - Email Detection",
                    "rule_type": "regex",
                    "condition": {"pattern": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"},
                    "action": "block",
                    "block_reason": "PII",
                    "priority": 20
                },
                {
                    "rule_id": "pii_phone",
                    "name": "PII - Phone Detection",
                    "rule_type": "regex",
                    "condition": {"pattern": r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b"},
                    "action": "block",
                    "block_reason": "PII",
                    "priority": 21
                },
                {
                    "rule_id": "toxicity_severe",
                    "name": "Severe Toxicity",
                    "rule_type": "keyword",
                    "condition": {"keywords": ["kill", "die", "rape", "murder"], "match_mode": "exact"},
                    "action": "block",
                    "block_reason": "TOXICITY",
                    "priority": 30
                },
                {
                    "rule_id": "harassment",
                    "name": "Harassment",
                    "rule_type": "keyword",
                    "condition": {"keywords": ["harass", "attack", "stalk", "threat"], "match_mode": "substring"},
                    "action": "block",
                    "block_reason": "HARASSMENT",
                    "priority": 31
                },
                {
                    "rule_id": "hate_speech",
                    "name": "Hate Speech Indicators",
                    "rule_type": "keyword",
                    "condition": {"keywords": ["slur", "inferior", "subhuman"], "match_mode": "substring"},
                    "action": "block",
                    "block_reason": "TOXICITY",
                    "priority": 32
                },
                {
                    "rule_id": "prompt_injection",
                    "name": "Prompt Injection Attempt",
                    "rule_type": "keyword",
                    "condition": {"keywords": ["ignore previous", "system prompt", "you are now", "disregard"], "match_mode": "substring"},
                    "action": "block",
                    "block_reason": "PROMPT_INJECTION",
                    "priority": 40
                },
                {
                    "rule_id": "spam_repetition",
                    "name": "Repetitive Content",
                    "rule_type": "repetition",
                    "condition": {"max_repeated_chars": 20},
                    "action": "block",
                    "block_reason": "SPAM",
                    "priority": 50
                }
            ]
        },
        "minimal": {
            "name": "Minimal (PII Only)",
            "description": "Only blocks obvious PII, minimal intervention",
            "rules": [
                {
                    "rule_id": "pii_email",
                    "name": "PII - Email Detection",
                    "rule_type": "regex",
                    "condition": {"pattern": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"},
                    "action": "block",
                    "block_reason": "PII",
                    "priority": 10
                },
                {
                    "rule_id": "length_min",
                    "name": "Minimum Length",
                    "rule_type": "length",
                    "condition": {"min_chars": 10},
                    "action": "block",
                    "block_reason": "SPAM",
                    "priority": 20
                }
            ]
        },
        "strict": {
            "name": "Strict Academic",
            "description": "Strict moderation for academic debate contexts",
            "rules": [
                {
                    "rule_id": "length_range",
                    "name": "Strict Length Requirements",
                    "rule_type": "length",
                    "condition": {"min_chars": 50, "max_chars": 5000},
                    "action": "block",
                    "block_reason": "SPAM",
                    "priority": 10
                },
                {
                    "rule_id": "pii_all",
                    "name": "All PII Detection",
                    "rule_type": "regex",
                    "condition": {"pattern": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b|\b\d{3}[-.]?\d{3}[-.]?\d{4}\b"},
                    "action": "block",
                    "block_reason": "PII",
                    "priority": 20
                },
                {
                    "rule_id": "toxicity_any",
                    "name": "Any Toxicity",
                    "rule_type": "keyword",
                    "condition": {"keywords": ["stupid", "idiot", "moron", "dumb", "kill", "hate", "attack", "harass"], "match_mode": "substring"},
                    "action": "block",
                    "block_reason": "TOXICITY",
                    "priority": 30
                },
                {
                    "rule_id": "civility_required",
                    "name": "Civility Check",
                    "rule_type": "keyword",
                    "condition": {"keywords": ["clearly", "obviously", "everyone knows"], "match_mode": "substring"},
                    "action": "block",
                    "block_reason": "HARASSMENT",
                    "priority": 40
                }
            ]
        }
    }
    
    def __init__(self, template: Optional[ModulationTemplate] = None):
        """
        Initialize with a modulation template.
        
        Args:
            template: The template to use. If None, uses standard_civility.
        """
        self.template = template or self.get_builtin_template("standard_civility")
        self.block_history: List[Dict] = []
    
    @classmethod
    def get_builtin_template(cls, template_id: str, version: str = "1.0") -> ModulationTemplate:
        """Get a built-in template by ID"""
        if template_id not in cls.BUILTIN_TEMPLATES:
            raise ValueError(f"Unknown template: {template_id}")
        
        config = cls.BUILTIN_TEMPLATES[template_id]
        rules = [ModulationRule(**rule_config) for rule_config in config["rules"]]
        
        return ModulationTemplate(
            template_id=template_id,
            name=config["name"],
            version=version,
            description=config["description"],
            rules=rules,
            created_at=datetime.now().isoformat()
        )
    
    @classmethod
    def list_builtin_templates(cls) -> List[Dict]:
        """List all available built-in templates"""
        return [
            {
                "template_id": tid,
                "name": config["name"],
                "description": config["description"]
            }
            for tid, config in cls.BUILTIN_TEMPLATES.items()
        ]
    
    def apply_modulation(self, post_data: Dict) -> Tuple[ModulationOutcome, Optional[BlockReason], List[str]]:
        """
        Apply modulation template to a post.
        
        Args:
            post_data: Dict with 'facts', 'inference', etc.
        
        Returns:
            Tuple of (outcome, block_reason, list of matched_rules)
        
        Per MSD §3: Rules are evaluated by priority (lowest first).
        First blocking rule wins.
        """
        combined_text = f"{post_data.get('facts', '')} {post_data.get('inference', '')}"
        
        # Sort rules by priority
        sorted_rules = sorted(self.template.rules, key=lambda r: r.priority)
        
        matched_rules = []
        
        for rule in sorted_rules:
            matched = self._evaluate_rule(rule, combined_text, post_data)
            if matched:
                matched_rules.append(rule.name)
                if rule.action == "block":
                    return ModulationOutcome.BLOCKED, rule.block_reason, matched_rules
        
        return ModulationOutcome.ALLOWED, None, matched_rules
    
    def _evaluate_rule(self, rule: ModulationRule, text: str, post_data: Dict) -> bool:
        """Evaluate a single rule against text"""
        rule_type = rule.rule_type
        condition = rule.condition
        
        if rule_type == "keyword":
            return self._evaluate_keyword_rule(text, condition)
        elif rule_type == "regex":
            return self._evaluate_regex_rule(text, condition)
        elif rule_type == "length":
            return self._evaluate_length_rule(text, condition)
        elif rule_type == "repetition":
            return self._evaluate_repetition_rule(text, condition)
        else:
            # Unknown rule type - log and ignore
            return False
    
    def _evaluate_keyword_rule(self, text: str, condition: Dict) -> bool:
        """Evaluate a keyword matching rule"""
        keywords = condition.get("keywords", [])
        match_mode = condition.get("match_mode", "substring")
        text_lower = text.lower()
        
        for keyword in keywords:
            keyword_lower = keyword.lower()
            if match_mode == "exact":
                # Match as whole word
                pattern = r'\b' + re.escape(keyword_lower) + r'\b'
                if re.search(pattern, text_lower):
                    return True
            else:  # substring
                if keyword_lower in text_lower:
                    return True
        
        return False
    
    def _evaluate_regex_rule(self, text: str, condition: Dict) -> bool:
        """Evaluate a regex matching rule"""
        pattern = condition.get("pattern", "")
        if not pattern:
            return False
        
        try:
            if re.search(pattern, text, re.IGNORECASE):
                return True
        except re.error:
            # Invalid regex - ignore
            pass
        
        return False
    
    def _evaluate_length_rule(self, text: str, condition: Dict) -> bool:
        """Evaluate a length constraint rule"""
        min_chars = condition.get("min_chars")
        max_chars = condition.get("max_chars")
        
        text_len = len(text.strip())
        
        if min_chars is not None and text_len < min_chars:
            return True
        if max_chars is not None and text_len > max_chars:
            return True
        
        return False
    
    def _evaluate_repetition_rule(self, text: str, condition: Dict) -> bool:
        """Evaluate a repetition detection rule"""
        max_repeated = condition.get("max_repeated_chars", 20)
        
        # Check for repeated characters (e.g., "aaaaaaaaaa")
        for char in set(text):
            count = text.count(char)
            if count > max_repeated:
                return True
        
        return False
    
    def get_audit_info(self) -> Dict:
        """
        Get audit information for the current template.
        
        Per MSD §3: Snapshot audit output includes:
        - template name + version
        - counts: allowed / blocked
        - block reasons histogram
        """
        return {
            "template_id": self.template.template_id,
            "template_name": self.template.name,
            "template_version": self.template.version,
            "template_description": self.template.description,
            "rule_count": len(self.template.rules),
            "rules": [
                {
                    "rule_id": r.rule_id,
                    "name": r.name,
                    "type": r.rule_type,
                    "action": r.action,
                    "block_reason": r.block_reason.value if r.block_reason else None,
                    "priority": r.priority
                }
                for r in self.template.rules
            ]
        }


def create_modulated_post(post_data: Dict, 
                          template_id: str = "standard_civility") -> Dict:
    """
    Convenience function to apply modulation to a post.
    
    Returns the post_data with modulation results added.
    """
    engine = ModulationEngine(ModulationEngine.get_builtin_template(template_id))
    outcome, block_reason, matched_rules = engine.apply_modulation(post_data)
    
    post_data['modulation_outcome'] = outcome.value
    post_data['block_reason'] = block_reason.value if block_reason else None
    post_data['modulation_matched_rules'] = matched_rules
    post_data['modulation_template'] = engine.template.get_version_string()
    
    return post_data
