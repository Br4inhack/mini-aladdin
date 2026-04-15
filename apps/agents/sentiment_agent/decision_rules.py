"""
decision_rules.py — Person 4 (Sentiment Agent)
===============================================
Rule-based decision engine.  Combines Person 4's sentiment output with
Person 3's market risk band to decide what action to recommend.

Entry point:
  apply_rules(sentiment_result: dict, market_risk_data: dict) -> dict

The 7 rules run in PRIORITY ORDER — first matching rule wins.

Input signals:
  sentiment_result  — from sentiment_pipeline.run_pipeline()
  market_risk_data  — latest AgentOutput row where agent_name='market_risk'
                       (may be {} if Person 3 hasn't run yet → default HOLD)

Output:
  {
    'action'    : str   — HOLD / REDUCE / EXIT / INCREASE / REALLOCATE
    'confidence': float — 0.1 to 0.95 (clamped)
    'reasoning' : str   — human-readable explanation
  }
"""

import logging

logger = logging.getLogger(__name__)

# ─── Confidence calculation constants ────────────────────────────────────────

_EVENT_RISK_PENALTY      = 0.15   # deduct if event_risk_flag is True
_MARKET_RISK_CONF_PENALTY = 0.10  # deduct if Person 3's confidence < 0.5
_CONF_MIN = 0.10
_CONF_MAX = 0.95


def _calculate_confidence(
    finbert_confidence: float,
    event_risk_flag: bool,
    market_risk_data: dict,
) -> float:
    """
    Calculates the final confidence score for the decision.

    Formula:
      base = FinBERT confidence score
      if event_risk_flag       : base -= 0.15  (high uncertainty)
      if market_risk_conf < 0.5: base -= 0.10  (Person 3's model is uncertain)
      clamped to [0.10, 0.95]

    Parameters
    ----------
    finbert_confidence : float — average FinBERT score from pipeline
    event_risk_flag    : bool
    market_risk_data   : dict — Person 3's AgentOutput raw_data

    Returns
    -------
    float — confidence in [0.10, 0.95]
    """
    base = finbert_confidence

    if event_risk_flag:
        base -= _EVENT_RISK_PENALTY

    # Person 3 stores their confidence inside raw_data.probabilities or similar
    # We check a 'confidence' key if present
    market_conf = market_risk_data.get("confidence", 1.0)
    if market_conf < 0.5:
        base -= _MARKET_RISK_CONF_PENALTY

    # Clamp to allowed range
    base = max(_CONF_MIN, min(_CONF_MAX, base))
    return round(base, 4)


# ─── apply_rules ─────────────────────────────────────────────────────────────

def apply_rules(sentiment_result: dict, market_risk_data: dict) -> dict:
    """
    Applies the 7 decision rules in priority order.
    First matching rule wins.

    Parameters
    ----------
    sentiment_result : dict  — output of sentiment_pipeline.run_pipeline()
        Keys used: sentiment_score, event_risk_flag, confidence, band

    market_risk_data : dict  — latest AgentOutput for agent_name='market_risk'
        Expected keys: band (str), score (float), confidence (float, optional)
        Defaults to HOLD if dict is empty (Person 3 hasn't run yet).

    Returns
    -------
    dict:
        action    : str   — HOLD / REDUCE / EXIT / INCREASE / REALLOCATE
        confidence: float — 0.10 to 0.95
        reasoning : str   — human-readable reason
    """
    # ── Extract sentiment signals ─────────────────────────────────────────────
    sentiment_score  = sentiment_result.get("sentiment_score", 0.0)
    event_risk_flag  = sentiment_result.get("event_risk_flag", False)
    finbert_conf     = sentiment_result.get("confidence", 0.5)

    # ── Extract market risk signals (from Person 3) ───────────────────────────
    market_risk_band = market_risk_data.get("band", "").upper() if market_risk_data else ""

    # ── Default: no market risk data from Person 3 yet ───────────────────────
    if not market_risk_band:
        confidence = _calculate_confidence(finbert_conf, event_risk_flag, {})
        reasoning = (
            f"No market risk data available from Person 3's agent. "
            f"Defaulting to HOLD. "
            f"Sentiment score={sentiment_score:.3f}, "
            f"event_risk={event_risk_flag}."
        )
        logger.info(f"[apply_rules] No market risk data → HOLD")
        return {"action": "HOLD", "confidence": confidence, "reasoning": reasoning}

    # ── 7 Rules in priority order ─────────────────────────────────────────────

    # Rule 1 → EXIT
    # event_risk_flag is True AND market is already stressed (HIGH or CRITICAL)
    if event_risk_flag and market_risk_band in ("HIGH", "CRITICAL"):
        action    = "EXIT"
        reasoning = (
            f"Rule 1: Event risk flag is True AND market_risk_band={market_risk_band}. "
            f"Immediate exit recommended."
        )

    # Rule 2 → EXIT
    # Market is CRITICAL and sentiment is very negative
    elif market_risk_band == "CRITICAL" and sentiment_score < -0.5:
        action    = "EXIT"
        reasoning = (
            f"Rule 2: market_risk_band=CRITICAL AND sentiment_score={sentiment_score:.3f} < -0.5. "
            f"Exit position."
        )

    # Rule 3 → REDUCE
    # Market is HIGH and sentiment is meaningfully negative
    elif market_risk_band == "HIGH" and sentiment_score < -0.3:
        action    = "REDUCE"
        reasoning = (
            f"Rule 3: market_risk_band=HIGH AND sentiment_score={sentiment_score:.3f} < -0.3. "
            f"Reduce position."
        )

    # Rule 4 → REDUCE
    # Market is CRITICAL but sentiment is not deeply negative (hold is too risky)
    elif market_risk_band == "CRITICAL" and sentiment_score >= -0.3:
        action    = "REDUCE"
        reasoning = (
            f"Rule 4: market_risk_band=CRITICAL AND sentiment_score={sentiment_score:.3f} >= -0.3. "
            f"Reduce exposure due to critical market risk."
        )

    # Rule 5 → INCREASE
    # Market is safe and sentiment is clearly positive
    elif market_risk_band == "LOW" and sentiment_score > 0.3:
        action    = "INCREASE"
        reasoning = (
            f"Rule 5: market_risk_band=LOW AND sentiment_score={sentiment_score:.3f} > 0.3. "
            f"Favourable conditions — increase position."
        )

    # Rule 6 → REALLOCATE
    # Medium market risk but strong positive sentiment — opportunity to shift capital
    elif market_risk_band == "MEDIUM" and sentiment_score > 0.4:
        action    = "REALLOCATE"
        reasoning = (
            f"Rule 6: market_risk_band=MEDIUM AND sentiment_score={sentiment_score:.3f} > 0.4. "
            f"Consider reallocating capital to this asset."
        )

    # Rule 7 → HOLD (default — catches everything else)
    else:
        action    = "HOLD"
        reasoning = (
            f"Rule 7 (default): No exit/reduce/increase condition met. "
            f"market_risk_band={market_risk_band}, "
            f"sentiment_score={sentiment_score:.3f}, "
            f"event_risk={event_risk_flag}. "
            f"Holding current position."
        )

    confidence = _calculate_confidence(finbert_conf, event_risk_flag, market_risk_data)

    logger.info(
        f"[apply_rules] action={action} confidence={confidence:.3f} "
        f"market_band={market_risk_band} sentiment={sentiment_score:.3f}"
    )

    return {
        "action"    : action,
        "confidence": confidence,
        "reasoning" : reasoning,
    }
