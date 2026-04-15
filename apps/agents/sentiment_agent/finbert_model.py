"""
finbert_model.py — Person 4 (Sentiment Agent)
==============================================
Loads ProsusAI/finbert exactly ONCE as a module-level singleton.

WHY SINGLETON?
  FinBERT is a 440 MB transformer model.  Loading it inside a Django
  view or pipeline function on every request would be catastrophically
  slow.  By loading at import time (module level), Django/Gunicorn loads
  it once per worker process and every request reuses the same object.

RULE (Architecture Rule 6):
  Never run heavy model inference inside Django views.
  FinBERT loads here once; get_sentiment() is called from
  sentiment_pipeline.py, NOT from any view.
"""

import logging
from transformers import pipeline

logger = logging.getLogger(__name__)

# ─── Singleton: loaded once when this module is first imported ────────────────

_finbert_pipeline = None  # Will hold the HuggingFace pipeline object


def _load_finbert():
    """
    Internal helper.  Loads ProsusAI/finbert from HuggingFace Hub (or local
    cache if already downloaded).  Called only once — the result is stored in
    the module-level _finbert_pipeline variable.
    """
    global _finbert_pipeline
    if _finbert_pipeline is None:
        try:
            logger.info("Loading ProsusAI/finbert — this may take a moment on first run...")
            _finbert_pipeline = pipeline(
                task="text-classification",
                model="ProsusAI/finbert",
                tokenizer="ProsusAI/finbert",
                # Return only the top-scoring label (same behaviour as Colab)
                top_k=1,
            )
            print("FinBERT loaded ✅")
            logger.info("FinBERT loaded successfully.")
        except Exception as exc:
            logger.error(f"FinBERT failed to load: {exc}")
            _finbert_pipeline = None  # Stay None so we return neutral gracefully
    return _finbert_pipeline


# ── Trigger load at import time ───────────────────────────────────────────────
_load_finbert()


# ─── Public API ───────────────────────────────────────────────────────────────

def get_sentiment(text: str) -> dict:
    """
    Run FinBERT inference on a single piece of text.

    Parameters
    ----------
    text : str
        The article text to classify. Will be truncated to 512 chars
        (same limit as the original Colab code) before being passed
        to the model (model itself handles token truncation internally).

    Returns
    -------
    dict  with keys:
        label  : str  — 'positive', 'negative', or 'neutral'
        score  : float — confidence score between 0 and 1

    Error handling:
        If the model is unavailable or crashes, returns a safe neutral
        default so the rest of the pipeline can continue without crashing.
    """
    # Defensive: truncate to 512 characters (matches original Colab code)
    text = text[:512]

    finbert = _finbert_pipeline

    if finbert is None:
        # Model did not load — return neutral so pipeline doesn't crash
        logger.warning("FinBERT is not loaded; returning neutral default.")
        return {"label": "neutral", "score": 0.0}

    try:
        # HuggingFace pipeline with top_k=1 returns: [[{"label": ..., "score": ...}]]
        result = finbert(text)
        # Unwrap nested list: [[{...}]] → {...}
        if isinstance(result, list) and len(result) > 0:
            inner = result[0]
            if isinstance(inner, list) and len(inner) > 0:
                return inner[0]   # {"label": "...", "score": 0.xx}
            elif isinstance(inner, dict):
                return inner
        # Fallback if shape is unexpected
        return {"label": "neutral", "score": 0.0}
    except Exception as exc:
        logger.error(f"FinBERT inference error: {exc}")
        # Same fallback used in original Colab get_sentiment()
        return {"label": "neutral", "score": 0.0}
