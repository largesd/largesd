"""
Topic Extraction and Management Engine
Handles dynamic topic extraction, clustering, and drift detection
"""
import uuid
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
import json
import numpy as np
from collections import defaultdict

from llm_client import LLMClient


@dataclass
class Topic:
    """A debate topic with metadata"""
    topic_id: str
    name: str
    scope: str
    frame_id: str = ""
    relevance: float = 0.0
    drift_score: float = 0.0
    coherence: float = 0.0
    distinctness: float = 0.0
    parent_topic_ids: List[str] = field(default_factory=list)
    operation: str = "created"  # created, merged, split, renamed, unchanged
    summary_for: str = ""
    summary_against: str = ""
    keywords: List[str] = field(default_factory=list)
    created_at: str = ""


class TopicEngine:
    """
    Engine for extracting and managing debate topics
    """
    
    # Target topic count bounds
    MIN_TOPICS = 3
    MAX_TOPICS = 7
    
    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm_client = llm_client or LLMClient()
        self.topic_history: Dict[str, List[Topic]] = {}  # debate_id -> topic history
    
    def extract_topics_from_posts(self, posts: List[Dict],
                                   debate_resolution: str) -> List[Topic]:
        """
        Extract topics dynamically from debate posts
        """
        if not posts:
            return self._create_default_topics(debate_resolution)
        
        # Prepare post texts
        post_texts = []
        for post in posts:
            text = f"{post.get('facts', '')} {post.get('inference', '')}"
            if text.strip():
                post_texts.append(text)
        
        if not post_texts:
            return self._create_default_topics(debate_resolution)
        
        # Use LLM to extract topics
        topics_data = self.llm_client.extract_topics(post_texts, debate_resolution)
        
        # Create Topic objects
        topics = []
        for i, t_data in enumerate(topics_data[:self.MAX_TOPICS]):  # Enforce max
            topic = Topic(
                topic_id=f"topic_{uuid.uuid4().hex[:8]}",
                name=t_data.get("name", f"Topic {i+1}"),
                scope=t_data.get("scope", ""),
                relevance=t_data.get("estimated_relevance", 0.25),
                keywords=t_data.get("keywords", []),
                created_at=datetime.now().isoformat()
            )
            topics.append(topic)
        
        # Enforce minimum topics
        if len(topics) < self.MIN_TOPICS:
            defaults = self._create_default_topics(debate_resolution)
            for i in range(len(topics), self.MIN_TOPICS):
                if i < len(defaults):
                    topics.append(defaults[i])
        
        # Compute topic metrics
        topics = self._compute_topic_metrics(topics, posts)
        
        return topics
    
    def _create_default_topics(self, debate_resolution: str) -> List[Topic]:
        """Create neutral default topics when extraction cannot yet infer clusters."""
        defaults = [
            Topic(
                topic_id=f"topic_t{uuid.uuid4().hex[:6]}",
                name="Definitions & interpretation",
                scope=(
                    "How the motion should be interpreted, which definitions are controlling, "
                    "and whether either side relies on a contested framing assumption."
                ),
                relevance=0.34,
                keywords=["definition", "interpretation", "frame", "meaning", "terms"],
                created_at=datetime.now().isoformat()
            ),
            Topic(
                topic_id=f"topic_t{uuid.uuid4().hex[:6]}",
                name="Evidence & causal impact",
                scope=(
                    "The main empirical claims and causal mechanisms that would make the motion true "
                    "or false under the current frame."
                ),
                relevance=0.28,
                keywords=["evidence", "impact", "cause", "outcome", "data"],
                created_at=datetime.now().isoformat()
            ),
            Topic(
                topic_id=f"topic_t{uuid.uuid4().hex[:6]}",
                name="Implementation & feasibility",
                scope=(
                    "Whether the proposed position is workable in practice, including incentives, "
                    "administration, enforceability, and likely real-world execution."
                ),
                relevance=0.22,
                keywords=["implementation", "feasibility", "enforcement", "incentives", "practical"],
                created_at=datetime.now().isoformat()
            ),
            Topic(
                topic_id=f"topic_t{uuid.uuid4().hex[:6]}",
                name="Trade-offs & decision relevance",
                scope=(
                    "Which side best handles the key trade-offs a neutral decision-maker should care "
                    "about under the active frame."
                ),
                relevance=0.16,
                keywords=["tradeoff", "decision", "balance", "cost", "benefit"],
                created_at=datetime.now().isoformat()
            )
        ]
        return defaults
    
    def _compute_topic_metrics(self, topics: List[Topic],
                               posts: List[Dict]) -> List[Topic]:
        """
        Compute coherence and distinctness for topics
        """
        # Assign posts to topics based on keyword matching
        topic_posts = defaultdict(list)
        
        for post in posts:
            post_text = f"{post.get('facts', '')} {post.get('inference', '')}".lower()
            best_topic = None
            best_score = 0
            
            for topic in topics:
                score = sum(1 for kw in topic.keywords if kw.lower() in post_text)
                if score > best_score:
                    best_score = score
                    best_topic = topic
            
            if best_topic:
                topic_posts[best_topic.topic_id].append(post_text)
        
        # Compute metrics for each topic
        for topic in topics:
            posts_in_topic = topic_posts.get(topic.topic_id, [])
            
            # Coherence: average similarity within topic (simplified)
            if len(posts_in_topic) > 1:
                topic.coherence = self._compute_coherence(posts_in_topic, topic.keywords)
            else:
                topic.coherence = 0.5
            
            # Distinctness: distance to nearest other topic
            topic.distinctness = self._compute_distinctness(topic, topics)
            
            # Relevance based on post count
            total_posts = len(posts)
            if total_posts > 0:
                topic.relevance = len(posts_in_topic) / total_posts
        
        # Normalize relevance to sum to 1
        total_rel = sum(t.relevance for t in topics)
        if total_rel > 0:
            for topic in topics:
                topic.relevance = round(topic.relevance / total_rel, 3)
        
        return topics
    
    def _compute_coherence(self, posts: List[str], keywords: List[str]) -> float:
        """
        Compute topic coherence (within-topic similarity)
        Simplified: measure keyword density consistency
        """
        if len(posts) < 2:
            return 0.5
        
        keyword_counts = []
        for post in posts:
            count = sum(post.lower().count(kw.lower()) for kw in keywords)
            keyword_counts.append(count)
        
        if not keyword_counts or sum(keyword_counts) == 0:
            return 0.5
        
        # Higher coherence if keyword distribution is consistent
        mean_count = np.mean(keyword_counts)
        std_count = np.std(keyword_counts)
        
        # Lower std = higher coherence
        coherence = max(0.3, min(0.9, 1.0 - (std_count / (mean_count + 1))))
        return round(coherence, 3)
    
    def _compute_distinctness(self, topic: Topic, all_topics: List[Topic]) -> float:
        """
        Compute distinctness (distance to nearest other topic)
        """
        other_topics = [t for t in all_topics if t.topic_id != topic.topic_id]
        
        if not other_topics:
            return 1.0
        
        # Compute keyword overlap with each other topic
        min_overlap = 1.0
        for other in other_topics:
            overlap = self._keyword_overlap(topic.keywords, other.keywords)
            min_overlap = min(min_overlap, overlap)
        
        # Lower overlap = higher distinctness
        distinctness = 1.0 - min_overlap
        return round(distinctness, 3)
    
    def _keyword_overlap(self, keywords1: List[str], keywords2: List[str]) -> float:
        """Compute Jaccard similarity of keyword sets"""
        if not keywords1 or not keywords2:
            return 0.0
        
        set1 = set(k.lower() for k in keywords1)
        set2 = set(k.lower() for k in keywords2)
        
        intersection = len(set1 & set2)
        union = len(set1 | set2)
        
        return intersection / union if union > 0 else 0.0
    
    def compute_topic_drift(self, current_topics: List[Topic],
                           previous_topics: List[Topic]) -> Dict:
        """
        Compute drift between current and previous topic sets
        """
        if not previous_topics:
            return {"overall_drift": 0.0, "topic_drifts": {}}
        
        topic_drifts = {}
        
        # Match topics by name similarity
        for curr_topic in current_topics:
            best_match = None
            best_score = 0
            
            for prev_topic in previous_topics:
                # Simple name similarity
                name_sim = self._text_similarity(curr_topic.name, prev_topic.name)
                if name_sim > best_score:
                    best_score = name_sim
                    best_match = prev_topic
            
            if best_match and best_score > 0.5:
                # Compute drift for matched topic
                scope_sim = self._text_similarity(curr_topic.scope, best_match.scope)
                drift = 1.0 - (best_score * 0.3 + scope_sim * 0.7)
                
                topic_drifts[curr_topic.topic_id] = {
                    "matched_topic_id": best_match.topic_id,
                    "drift_score": round(drift, 3),
                    "name_similarity": round(best_score, 3),
                    "scope_similarity": round(scope_sim, 3),
                    "operation": self._determine_operation(curr_topic, best_match)
                }
                
                curr_topic.drift_score = round(drift, 3)
                curr_topic.parent_topic_ids = [best_match.topic_id]
                curr_topic.operation = topic_drifts[curr_topic.topic_id]["operation"]
            else:
                # New topic
                topic_drifts[curr_topic.topic_id] = {
                    "matched_topic_id": None,
                    "drift_score": 1.0,  # Max drift for new topic
                    "operation": "created"
                }
                curr_topic.operation = "created"
        
        # Check for removed topics
        current_ids = {t.topic_id for t in current_topics}
        for prev_topic in previous_topics:
            if prev_topic.topic_id not in current_ids:
                # Check if it was merged into a new topic
                for curr_topic in current_topics:
                    if prev_topic.topic_id in curr_topic.parent_topic_ids:
                        break
                else:
                    # Truly removed
                    topic_drifts[f"removed_{prev_topic.topic_id}"] = {
                        "topic_id": prev_topic.topic_id,
                        "operation": "removed"
                    }
        
        overall_drift = np.mean([
            d.get("drift_score", 0) for d in topic_drifts.values()
            if "drift_score" in d
        ]) if topic_drifts else 0.0
        
        return {
            "overall_drift": round(overall_drift, 3),
            "topic_drifts": topic_drifts,
            "num_topics": len(current_topics),
            "num_previous": len(previous_topics)
        }
    
    def _text_similarity(self, text1: str, text2: str) -> float:
        """Simple text similarity using word overlap"""
        words1 = set(text1.lower().split())
        words2 = set(text2.lower().split())
        
        if not words1 or not words2:
            return 0.0
        
        intersection = len(words1 & words2)
        union = len(words1 | words2)
        
        return intersection / union if union > 0 else 0.0
    
    def _determine_operation(self, current: Topic, previous: Topic) -> str:
        """Determine what operation transformed previous into current"""
        name_sim = self._text_similarity(current.name, previous.name)
        scope_sim = self._text_similarity(current.scope, previous.scope)
        
        if name_sim > 0.8 and scope_sim > 0.8:
            return "unchanged"
        elif name_sim > 0.5 and scope_sim > 0.5:
            return "renamed" if name_sim < 0.8 else "refined"
        else:
            return "merged" if len(current.parent_topic_ids) > 1 else "evolved"
    
    def enforce_topic_bounds(self, topics: List[Topic],
                            posts: List[Dict],
                            debate_resolution: str) -> List[Topic]:
        """
        Enforce MIN/MAX topic bounds by merging or splitting
        """
        n = len(topics)
        
        if n > self.MAX_TOPICS:
            # Merge most similar topics
            topics = self._merge_topics(topics, target_count=self.MAX_TOPICS)
        elif n < self.MIN_TOPICS:
            # Split broadest topics
            topics = self._split_topics(topics, posts, debate_resolution,
                                        target_count=self.MIN_TOPICS)
        
        return topics
    
    def _merge_topics(self, topics: List[Topic],
                     target_count: int) -> List[Topic]:
        """Merge most similar topics until target count reached"""
        while len(topics) > target_count:
            # Find most similar pair
            best_pair = None
            best_sim = -1
            
            for i, t1 in enumerate(topics):
                for t2 in topics[i+1:]:
                    sim = self._text_similarity(t1.scope, t2.scope)
                    if sim > best_sim:
                        best_sim = sim
                        best_pair = (t1, t2)
            
            if not best_pair:
                break
            
            t1, t2 = best_pair
            
            # Create merged topic
            merged = Topic(
                topic_id=f"topic_{uuid.uuid4().hex[:8]}",
                name=f"{t1.name} / {t2.name}"[:50],
                scope=f"Combined topic covering: {t1.scope[:50]}... and {t2.scope[:50]}...",
                relevance=t1.relevance + t2.relevance,
                parent_topic_ids=[t1.topic_id, t2.topic_id],
                operation="merged",
                created_at=datetime.now().isoformat()
            )
            
            # Replace t1 and t2 with merged
            topics = [t for t in topics if t not in (t1, t2)]
            topics.append(merged)
        
        return topics
    
    def _split_topics(self, topics: List[Topic],
                     posts: List[Dict],
                     debate_resolution: str,
                     target_count: int) -> List[Topic]:
        """Split broad topics until target count reached"""
        # For now, just add generic topics
        while len(topics) < target_count:
            new_topic = Topic(
                topic_id=f"topic_{uuid.uuid4().hex[:8]}",
                name=f"Additional Consideration {len(topics) + 1}",
                scope="Additional aspect of the debate requiring consideration.",
                relevance=0.1,
                operation="created",
                created_at=datetime.now().isoformat()
            )
            topics.append(new_topic)
        
        return topics
    
    def assign_posts_to_topics(self, posts: List[Dict],
                               topics: List[Topic]) -> Dict[str, List[str]]:
        """
        Assign posts to topics based on content similarity
        Returns: {topic_id: [post_id, ...]}
        """
        assignments = defaultdict(list)
        
        for post in posts:
            post_text = f"{post.get('facts', '')} {post.get('inference', '')}".lower()
            
            # Score each topic
            best_topic = None
            best_score = 0
            
            for topic in topics:
                score = sum(1 for kw in topic.keywords if kw.lower() in post_text)
                # Boost by 0.5 if topic keywords match
                score = score + 0.5 if score > 0 else 0
                
                if score > best_score:
                    best_score = score
                    best_topic = topic
            
            # Assign to best matching topic, or first topic if no match
            if best_topic:
                assignments[best_topic.topic_id].append(post['post_id'])
            elif topics:
                assignments[topics[0].topic_id].append(post['post_id'])
        
        return dict(assignments)
