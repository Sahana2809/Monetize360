"""
Optional, config-driven ML-assist signals: demand prediction and anomaly
detection. These are deliberately simple, transparent models (a weighted
linear feature score; a z-score outlier test) rather than black boxes -
every number they produce is itself exposed in the price-driver
explanation, and the *same* declarative shape works for hotel demand,
ride-hailing demand, or e-commerce demand because it only ever reads
attribute names out of the context dict that the domain config names.

Swapping in a real trained model later means replacing the body of
predict_demand_index / detect_anomaly while keeping the same config shape
and return contract - rule configs never need to change.
"""
from __future__ import annotations

import statistics
from typing import Any, Dict, List, Optional, Tuple


def predict_demand_index(features: List[Dict[str, Any]], context: Dict[str, Any]) -> Tuple[float, List[Dict[str, Any]]]:
    """Weighted-feature linear score in [0, 1]. Each feature spec:
      {"attr": "occupancy_rate", "weight": 0.5}                -> raw value * weight (value assumed 0..1)
      {"attr": "day_type", "weight": 0.3, "match": ["weekend"]} -> weight if context[attr] in match else 0
      {"attr": "lead_time_days", "weight": 0.2, "max_threshold": 3} -> weight if value <= threshold else 0
      {"attr": "bookings_last_7d", "weight": 0.2, "min_threshold": 50} -> weight if value >= threshold else 0
    Returns (score, contributions) so the caller can show the breakdown.
    """
    total = 0.0
    contributions = []
    for f in features:
        attr = f["attr"]
        weight = f.get("weight", 0.0)
        value = context.get(attr)
        contribution = 0.0
        if value is not None:
            if "match" in f:
                contribution = weight if value in f["match"] else 0.0
            elif "max_threshold" in f:
                contribution = weight if value <= f["max_threshold"] else 0.0
            elif "min_threshold" in f:
                contribution = weight if value >= f["min_threshold"] else 0.0
            else:
                contribution = weight * float(value)
        total += contribution
        contributions.append({"attr": attr, "weight": weight, "raw_value": value, "contribution": round(contribution, 4)})
    score = max(0.0, min(1.0, total))
    return score, contributions


def detect_anomaly(value: Optional[float], history: Optional[List[float]], z_threshold: float = 2.5) -> Dict[str, Any]:
    """Simple z-score outlier test against a historical sample. Returns a
    dict with is_anomaly, z_score, mean and stdev so the explanation layer
    can show exactly why a signal was (or wasn't) flagged."""
    if value is None or not history or len(history) < 2:
        return {"is_anomaly": False, "z_score": None, "mean": None, "stdev": None}
    mean = statistics.mean(history)
    stdev = statistics.pstdev(history)
    if stdev == 0:
        return {"is_anomaly": False, "z_score": 0.0, "mean": mean, "stdev": stdev}
    z = (float(value) - mean) / stdev
    return {"is_anomaly": abs(z) >= z_threshold, "z_score": round(z, 3), "mean": round(mean, 2), "stdev": round(stdev, 2)}


def apply_signals(signals_config: Optional[Dict[str, Any]], context: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Returns (augmented_context, signal_trace). Non-destructive: the
    input context dict is not mutated."""
    context = dict(context)
    trace: Dict[str, Any] = {}
    if not signals_config:
        return context, trace

    dp = signals_config.get("demand_prediction")
    if dp:
        score, contributions = predict_demand_index(dp.get("features", []), context)
        output_attr = dp.get("output_attr", "demand_index")
        context[output_attr] = score
        trace["demand_prediction"] = {"output_attr": output_attr, "value": round(score, 4), "contributions": contributions}

    ad = signals_config.get("anomaly_detection")
    if ad:
        value = context.get(ad.get("attr"))
        history = context.get(ad.get("history_attr"))
        result = detect_anomaly(value, history, ad.get("z_threshold", 2.5))
        output_attr = ad.get("output_attr", "anomaly_flag")
        context[output_attr] = 1 if result["is_anomaly"] else 0
        trace["anomaly_detection"] = {"output_attr": output_attr, **result, "watched_attr": ad.get("attr")}

    return context, trace
