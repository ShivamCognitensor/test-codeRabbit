"""
Post-Call Transcript Analysis Service  (Local / Private inference)
==================================================================
pip install transformers torch sentence-transformers fastapi pydantic uvicorn

Models used (downloaded once, then cached locally):
  • Sentiment   : distilbert/distilbert-base-uncased-finetuned-sst-2-english
                  ↳ swap with a fine-tuned finance-domain model later
  • Embeddings  : sentence-transformers/all-MiniLM-L6-v2
                  ↳ swap with a domain-tuned bi-encoder for better accuracy

WHY Transformers over NLTK/VADER?
  - VADER is a lexicon + rule system trained on social-media slang.
    It understands ":(", "ROFL", etc. – but not nuanced loan-sales dialogue
    like "I'm interested but busy right now".
  - Transformer models (e.g. DistilBERT fine-tuned on SST-2) learn contextual
    representations, so "not interested" ≠ "interested" even though both
    contain the word "interested".

WHY Sentence Transformers for callback intent?
  - Exact keyword matching fails on paraphrases:
      "ring me tomorrow"   → no keyword match for "call me back"
      "could you reach out later?" → missed entirely
  - Sentence Transformers encode both the user utterance AND a set of
    reference intents into the same vector space, then use cosine similarity
    to detect semantic closeness.  This generalises to unseen phrasings.

HOW backend rules decide the final callback flag:
  - We combine THREE signals:
      1. semantic_callback  (Sentence Transformer similarity ≥ threshold)
      2. keyword_callback   (exact phrase matching as safety net)
      3. negative_override  (if customer says "stop calling" → force False)
  - The rule engine in `_decide_callback()` merges these into one boolean.
  - `show_callback_button` in the response is derived ONLY from
    `callback_requested`, NOT from sentiment.
"""

from __future__ import annotations

import logging
import re
import uuid
from functools import lru_cache
from typing import Optional

from fastapi import APIRouter, FastAPI
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Lazy-loaded ML models (download once → cached in ~/.cache/huggingface)
# ---------------------------------------------------------------------------

_sentiment_pipeline = None
_sentence_model = None

logger = logging.getLogger(__name__)


def _get_sentiment_pipeline():
    """Load HuggingFace sentiment pipeline on first call."""
    global _sentiment_pipeline
    if _sentiment_pipeline is None:
        from transformers import pipeline  # heavy import – deferred

        # ── Swap this model with a fine-tuned finance-domain classifier ──
        _sentiment_pipeline = pipeline(
            "sentiment-analysis",
            model="distilbert/distilbert-base-uncased-finetuned-sst-2-english",
            top_k=None,          # return all labels with scores
            truncation=True,
            max_length=512,
        )
        print("sentiment pipeline loaded",_sentiment_pipeline)
        logger.info("Loaded HF sentiment pipeline")
    return _sentiment_pipeline


def _get_sentence_model():
    """Load Sentence Transformer model on first call."""
    global _sentence_model
    if _sentence_model is None:
        from sentence_transformers import SentenceTransformer  # deferred

        # ── Swap this with a domain-tuned bi-encoder for better accuracy ──
        _sentence_model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
        logger.info("Loaded SentenceTransformer model")
    return _sentence_model


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class AnalyzeRequest(BaseModel):
    """Incoming request payload for transcript analysis."""

    call_id: str = Field(..., examples=["call_123"])
    transcript: str = Field(..., min_length=1)


class AnalysisResult(BaseModel):
    """Core analysis output produced by the analysis engine."""

    sentiment: str = Field(..., examples=["neutral_positive"])
    satisfaction_score: int = Field(..., ge=0, le=100)
    interest_level: str = Field(..., examples=["high"])
    callback_requested: bool
    human_handoff_recommended: bool
    preferred_callback_time: Optional[str] = None
    objection_type: Optional[str] = None
    customer_cooperative: bool
    confidence: float = Field(..., ge=0.0, le=1.0)
    summary: str


class UIFlags(BaseModel):
    """Frontend-consumable flags derived from analysis."""

    show_callback_button: bool


class AnalyzeResponse(BaseModel):
    """Top-level API response returned to clients."""

    call_id: str
    analysis: AnalysisResult
    ui_flags: UIFlags


# ---------------------------------------------------------------------------
# Dummy transcript (realistic LiveKit-style loan-sales call)
# ---------------------------------------------------------------------------

DUMMY_TRANSCRIPT: str = (
    "Agent: Good morning! Am I speaking with Mr. Sharma?\n"
    "Customer: Yes, this is Sharma.\n"
    "Agent: Sir, I'm calling from Roinet Finance regarding a pre-approved "
    "personal loan offer of up to five lakh rupees at an attractive interest "
    "rate. Would you be interested in hearing the details?\n"
    "Customer: Actually, I am interested, but I'm in a meeting right now. "
    "Can you call me back tomorrow after 6 PM?\n"
    "Agent: Absolutely, sir. I'll have someone call you tomorrow evening "
    "after 6 PM.\n"
    "Customer: Yes, please do that. And make sure it's a person, not a bot.\n"
    "Agent: Sure, sir. We'll arrange a callback with one of our loan "
    "advisors. Thank you for your time.\n"
    "Customer: Thank you."
)

# ---------------------------------------------------------------------------
# Reference intents for semantic matching  (Sentence Transformers)
# ---------------------------------------------------------------------------

# Callback-positive reference sentences
_CALLBACK_INTENTS: list[str] = [
    "please call me back later",
    "can you call me tomorrow",
    "have someone call me",
    "I'd like a callback",
    "ring me later",
    "reach out to me again",
    "call me after work hours",
    "could you phone me tomorrow evening",
    "I want a person to call me",
    "speak to a human agent",
]

# Callback-negative reference sentences
_NO_CALLBACK_INTENTS: list[str] = [
    "I'm not interested",
    "don't call me again",
    "stop calling me",
    "remove me from your list",
    "I don't want any calls",
]

# Similarity threshold for semantic callback detection
_CALLBACK_SIM_THRESHOLD: float = 0.45

# ---------------------------------------------------------------------------
# Keyword rule sets  (safety-net for exact-match coverage)
# ---------------------------------------------------------------------------

_CALLBACK_PHRASES: list[str] = [
    "call me later", "call me back", "have someone call me",
    "have a person call me", "call tomorrow", "speak to a human",
]

_NEGATIVE_PHRASES: list[str] = [
    "not interested", "don't call again", "stop calling",
]

_WRONG_NUMBER_PHRASES: list[str] = [
    "wrong number", "you have the wrong person",
]

_POSITIVE_WORDS: list[str] = [
    "interested", "great", "sounds good", "yes please",
    "thank you", "sure", "absolutely",
]

_NEGATIVE_WORDS: list[str] = [
    "angry", "frustrated", "terrible", "horrible",
    "worst", "waste", "scam",
]

_BUSY_PHRASES: list[str] = [
    "in a meeting", "busy right now", "can't talk",
    "not a good time", "call me later",
]

_HUMAN_HANDOFF_PHRASES: list[str] = [
    "speak to a human", "talk to a person", "not a bot", "a person call me",
]

# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------


def _contains_any(text: str, phrases: list[str]) -> bool:
    """Case-insensitive multi-phrase check."""
    lowered = text.lower()
    return any(p in lowered for p in phrases)


def _extract_callback_time(text: str) -> Optional[str]:
    """Try to pull a preferred callback time from the transcript."""
    patterns: list[str] = [
        r"(?:call\s+(?:me\s+)?(?:back\s+)?)?tomorrow\s+(?:after|around|at)"
        r"\s+\d{1,2}\s*(?:am|pm)?",
        r"(?:after|around|at)\s+\d{1,2}\s*(?:am|pm)\s*(?:tomorrow)?",
        r"tomorrow\s+(?:evening|morning|afternoon)",
    ]
    print("pattern",patterns)
    lowered = text.lower()
    print("lowered",lowered)
    for pattern in patterns:
        match = re.search(pattern, lowered)
        if match:
            return match.group(0).strip()
    if "tomorrow" in lowered:
        return "tomorrow"
    return None


def _compute_satisfaction(
    positive_hits: int, negative_hits: int, cooperative: bool,
    hf_positive_score: float,
) -> int:
    """Heuristic satisfaction score (0–100), boosted by HF model confidence."""
    base = 50
    base += positive_hits * 8
    base -= negative_hits * 12
    if cooperative:
        base += 10
    # Blend in the transformer sentiment score (0-1 range → 0-20 bonus)
    base += int((hf_positive_score - 0.5) * 40)
    return max(0, min(100, base))


# ---------------------------------------------------------------------------
# Transformer-based sentiment analysis
# ---------------------------------------------------------------------------


def _classify_sentiment(text: str) -> tuple[str, float]:
    """
    Use the HuggingFace pipeline to classify overall sentiment.
    Returns (label, positive_score).

    The SST-2 model returns POSITIVE / NEGATIVE.  We map into a
    finer-grained label set used by the API:
      positive | neutral_positive | neutral | neutral_negative | negative
    """
    pipe = _get_sentiment_pipeline()

    # Run inference on customer turns only (strip agent lines)
    customer_lines = [
        line.split(":", 1)[1].strip()
        for line in text.split("\n")
        if line.lower().startswith("customer:")
    ]
    # Fallback: use the whole transcript if no labelled turns
    input_text = " ".join(customer_lines) if customer_lines else text

    results = pipe(input_text[:512])  # truncate for model max-length

    # `top_k=None` returns list-of-list; flatten
    scores = {r["label"]: r["score"] for r in (results[0] if isinstance(results[0], list) else results)}
    pos = scores.get("POSITIVE", 0.0)
    neg = scores.get("NEGATIVE", 0.0)

    # Map to finer-grained labels
    if pos >= 0.80:
        label = "positive"
    elif pos >= 0.60:
        label = "neutral_positive"
    elif pos >= 0.40:
        label = "neutral"
    elif pos >= 0.25:
        label = "neutral_negative"
    else:
        label = "negative"

    return label, pos


# ---------------------------------------------------------------------------
# Sentence-Transformer callback intent detection
# ---------------------------------------------------------------------------


def _semantic_callback_check(text: str) -> tuple[bool, float]:
    """
    Encode customer utterances and compare against reference callback intents.
    Returns (is_callback_intent, max_similarity_score).

    This catches paraphrases that keywords miss, e.g.:
      "ring me tomorrow" → semantically close to "call me back later"
    """
    model = _get_sentence_model()

    # Extract customer turns
    customer_lines = [
        line.split(":", 1)[1].strip()
        for line in text.split("\n")
        if line.lower().startswith("customer:")
    ]
    if not customer_lines:
        return False, 0.0

    # Encode customer utterances + reference intents
    from sentence_transformers import util  # deferred import

    cust_embeddings = model.encode(customer_lines, convert_to_tensor=True)
    pos_embeddings = model.encode(_CALLBACK_INTENTS, convert_to_tensor=True)
    neg_embeddings = model.encode(_NO_CALLBACK_INTENTS, convert_to_tensor=True)

    # Max similarity against positive callback intents
    pos_scores = util.cos_sim(cust_embeddings, pos_embeddings)
    max_pos = float(pos_scores.max())

    # Max similarity against negative (anti-callback) intents
    neg_scores = util.cos_sim(cust_embeddings, neg_embeddings)
    max_neg = float(neg_scores.max())

    # Positive intent wins only if it clearly exceeds the negative
    is_callback = (max_pos >= _CALLBACK_SIM_THRESHOLD) and (max_pos > max_neg + 0.05)

    return is_callback, max_pos


# ---------------------------------------------------------------------------
# Rule engine: final callback decision
# ---------------------------------------------------------------------------


def _decide_callback(
    semantic_callback: bool,
    keyword_callback: bool,
    negative_override: bool,
) -> bool:
    """
    Merge three signals into one boolean.

    Rules:
      1. If negative override is active → always False
      2. If EITHER semantic OR keyword detects callback → True
      3. Otherwise → False

    Callback is intentionally INDEPENDENT of sentiment.
    A customer can be unhappy but still request a callback.
    """
    if negative_override:
        return False
    return semantic_callback or keyword_callback


# ---------------------------------------------------------------------------
# Core analysis engine
# ---------------------------------------------------------------------------


def analyze_transcript(transcript: str) -> AnalysisResult:
    """
    Full analysis pipeline:
      1. HuggingFace Transformer → sentiment classification
      2. Sentence Transformer   → semantic callback intent
      3. Keyword rules           → safety-net + objection detection
      4. Rule engine             → final callback decision
    """
    text_lower = transcript.lower()

    # ── 1. Transformer sentiment ──────────────────────────────────────────
    sentiment_label, hf_positive_score = _classify_sentiment(transcript)

    # ── 2. Negative override check (keywords) ────────────────────────────
    negative_override = _contains_any(text_lower, _NEGATIVE_PHRASES)

    if negative_override:
        return AnalysisResult(
            sentiment="negative",
            satisfaction_score=15,
            interest_level="none",
            callback_requested=False,
            human_handoff_recommended=False,
            preferred_callback_time=None,
            objection_type="not_interested",
            customer_cooperative=False,
            confidence=0.88,
            summary=(
                "Customer explicitly expressed disinterest or "
                "requested no further contact."
            ),
        )

    # ── 3. Semantic callback detection (Sentence Transformer) ────────────
    semantic_callback, sem_score = _semantic_callback_check(transcript)

    # ── 4. Keyword callback detection (safety net) ────────────────────────
    keyword_callback = _contains_any(text_lower, _CALLBACK_PHRASES)

    # ── 5. Rule engine → final callback decision ─────────────────────────
    callback_requested = _decide_callback(
        semantic_callback=semantic_callback,
        keyword_callback=keyword_callback,
        negative_override=False,  # already handled above
    )

    preferred_callback_time = (
        _extract_callback_time(transcript) if callback_requested else None
    )

    # ── 6. Human handoff ─────────────────────────────────────────────────
    human_handoff = _contains_any(text_lower, _HUMAN_HANDOFF_PHRASES)

    # ── 7. Objection type ────────────────────────────────────────────────
    objection_type: Optional[str] = None
    if _contains_any(text_lower, _WRONG_NUMBER_PHRASES):
        objection_type = "wrong_number"
    elif _contains_any(text_lower, _BUSY_PHRASES):
        objection_type = "busy"

    # ── 8. Interest level ────────────────────────────────────────────────
    if "interested" in text_lower or "tell me more" in text_lower:
        interest_level = "high"
    elif callback_requested:
        interest_level = "medium"
    else:
        interest_level = "low"

    # ── 9. Cooperative customer ──────────────────────────────────────────
    cooperative = any(
        w in text_lower for w in ("thank", "sure", "please", "okay", "ok")
    )

    # ── 10. Satisfaction score (blends keywords + HF confidence) ─────────
    positive_hits = sum(1 for w in _POSITIVE_WORDS if w in text_lower)
    negative_hits = sum(1 for w in _NEGATIVE_WORDS if w in text_lower)
    satisfaction_score = _compute_satisfaction(
        positive_hits, negative_hits, cooperative, hf_positive_score,
    )

    # ── 11. Confidence (composite of HF score + signal density) ──────────
    signal_count = (
        positive_hits + negative_hits
        + int(callback_requested) + int(human_handoff)
    )
    confidence = round(
        min(0.95, 0.50 + hf_positive_score * 0.20 + signal_count * 0.05), 2,
    )

    # ── 12. Summary generation ───────────────────────────────────────────
    parts: list[str] = []
    if interest_level == "high":
        parts.append("Customer is interested")
    elif interest_level == "medium":
        parts.append("Customer shows moderate interest")
    else:
        parts.append("Customer shows low interest")

    parts.append(f"sentiment is {sentiment_label}")

    if callback_requested:
        time_str = (
            f" ({preferred_callback_time})" if preferred_callback_time else ""
        )
        cb_source = (
            "semantic+keyword" if (semantic_callback and keyword_callback)
            else "semantic" if semantic_callback
            else "keyword"
        )
        parts.append(f"requested a callback{time_str} [detected via {cb_source}]")
    if human_handoff:
        parts.append("prefers speaking to a human agent")
    if objection_type:
        parts.append(f"objection: {objection_type}")

    summary = ". ".join(parts) + "." if parts else "No significant signals."

    return AnalysisResult(
        sentiment=sentiment_label,
        satisfaction_score=satisfaction_score,
        interest_level=interest_level,
        callback_requested=callback_requested,
        human_handoff_recommended=human_handoff,
        preferred_callback_time=preferred_callback_time,
        objection_type=objection_type,
        customer_cooperative=cooperative,
        confidence=confidence,
        summary=summary,
    )

