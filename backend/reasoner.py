"""
Llama Reasoner ① - JSON Refinement, Risk Assessment, Query Generation.

This module implements the first reasoning stage in the Llama pipeline:
1. Takes raw observation JSON from Vision LLM (Gemini/GPT-4o)
2. Refines the JSON for logical consistency
3. Re-assesses risk using reasoning (not just pattern matching)
4. Decides whether RAG retrieval is necessary
5. Generates optimized queries for vector embedding search

Key goals:
- Ensure validity and reproducibility
- Leverage deterministic LLM behavior (temperature=0.1)
- Statistical analysis of confidence and uncertainty
- Semantic query optimization for FAISS/vector search
"""

import json
import time
from typing import Any, Optional

from schemas import (
    ReasonerOutput,
    RiskAssessment,
    StatisticalMetrics,
)
from llama_client import llama_reason_json


# ============================================================
# Main Reasoner ① Function
# ============================================================

def refine_observation_and_build_query(
    observation: dict[str, Any],
    session_id: str = "unknown",
) -> tuple[bool, Optional[ReasonerOutput], Optional[str]]:
    """
    Llama Reasoner ① - Refine vision JSON and generate RAG query.

    Args:
        observation: Raw JSON from Vision LLM (HomeIssueExtraction dict)
        session_id: Session identifier for logging

    Returns:
        (success, reasoner_output, error_message)
        - success: True if reasoning succeeded
        - reasoner_output: ReasonerOutput object (or None if failed)
        - error_message: Error description (or None if succeeded)

    Example:
        >>> observation = {
        ...     "fixture_type": "toilet",
        ...     "prospected_issues": [...],
        ...     "overall_danger_level": "medium",
        ...     ...
        ... }
        >>> success, output, error = refine_observation_and_build_query(observation)
        >>> if success:
        ...     print(f"Refined issue: {output.refined_issue}")
        ...     print(f"RAG needed: {output.requires_rag}")
        ...     print(f"Query: {output.rag_query}")
    """
    t0 = time.time()

    # ============================================================
    # Step 1: Build detailed reasoning prompt
    # ============================================================
    prompt = _build_reasoner1_prompt(observation)

    # ============================================================
    # Step 2: Call Llama with JSON mode (deterministic)
    # ============================================================
    print(f"[Reasoner ①] Calling Llama for session {session_id}...")
    result = llama_reason_json(prompt=prompt, temperature=0.1, max_tokens=3000)

    if not result["success"]:
        error_msg = f"Llama call failed: {result['error']}"
        print(f"❌ [Reasoner ①] {error_msg}")
        return False, None, error_msg

    latency_ms = (time.time() - t0) * 1000
    print(f"✅ [Reasoner ①] Llama responded in {latency_ms:.0f}ms (tokens: {result['tokens_used']})")

    # ============================================================
    # Step 3: Parse and validate Llama JSON output
    # ============================================================
    parsed_json = result["parsed_json"]
    if not parsed_json:
        error_msg = "Llama returned empty JSON"
        print(f"❌ [Reasoner ①] {error_msg}")
        return False, None, error_msg

    # Validate output structure
    validation_error = _validate_reasoner_output(parsed_json)
    if validation_error:
        print(f"❌ [Reasoner ①] Validation failed: {validation_error}")
        return False, None, validation_error

    # ============================================================
    # Step 4: Build ReasonerOutput with statistical metrics
    # ============================================================
    try:
        # Extract risk assessment
        risk_data = parsed_json.get("risk_assessment", {})
        risk_assessment = RiskAssessment(
            level=risk_data.get("level", "medium"),
            reasoning=risk_data.get("reasoning", "Risk assessment not provided"),
            immediate_danger_present=risk_data.get("immediate_danger_present", False),
            time_sensitivity=risk_data.get("time_sensitivity", "hours"),
            escalation_triggers=risk_data.get("escalation_triggers", []),
        )

        # Calculate statistical metrics
        statistical_metrics = _calculate_statistical_metrics(
            parsed_json=parsed_json,
            original_observation=observation,
            latency_ms=latency_ms,
        )

        # Build final output
        reasoner_output = ReasonerOutput(
            refined_issue=parsed_json.get("refined_issue", "Unknown issue"),
            refined_location=parsed_json.get("refined_location", "Unknown location"),
            refined_fixture=parsed_json.get("refined_fixture", "Unknown fixture"),
            risk_assessment=risk_assessment,
            requires_rag=parsed_json.get("requires_rag", True),
            rag_query=parsed_json.get("rag_query", ""),
            rag_query_keywords=parsed_json.get("rag_query_keywords", []),
            statistical_metrics=statistical_metrics,
            reasoning_trace=parsed_json.get("reasoning_trace", "No trace provided"),
        )

        print(f"✅ [Reasoner ①] Output validated. Confidence: {statistical_metrics.confidence:.2f}, RAG needed: {reasoner_output.requires_rag}")
        return True, reasoner_output, None

    except Exception as e:
        error_msg = f"Failed to build ReasonerOutput: {type(e).__name__}: {str(e)}"
        print(f"❌ [Reasoner ①] {error_msg}")
        return False, None, error_msg


# ============================================================
# Prompt Engineering for Reasoner ①
# ============================================================

def _build_reasoner1_prompt(observation: dict[str, Any]) -> str:
    """
    Build detailed reasoning prompt for Llama Reasoner ①.

    This prompt emphasizes:
    - Logical consistency checking
    - Risk re-assessment based on reasoning (not pattern matching)
    - Semantic query generation for vector search
    - Confidence and uncertainty tracking
    """
    # Extract key fields from vision observation
    fixture_type = observation.get("fixture_type", "unknown")
    location = observation.get("location", "unknown")
    fixture = observation.get("fixture", "unknown")
    prospected_issues = observation.get("prospected_issues", [])
    top_issue = prospected_issues[0] if prospected_issues else {}
    top_issue_name = top_issue.get("issue_name", "No issue detected")
    top_confidence = top_issue.get("confidence", 0.0)
    symptoms = observation.get("observed_symptoms", [])
    danger_level = observation.get("overall_danger_level", "low")
    no_issue = observation.get("no_issue_detected", False)

    # Build prompt
    prompt = f"""You are a careful reasoning agent for home repair diagnosis.

Your task is to analyze the OBSERVATION JSON from a vision model and perform logical reasoning to:
1. **Refine the diagnosis** - Check for inconsistencies, add context, improve precision
2. **Re-assess risk** - Use logical reasoning (not just pattern matching) to determine true risk level
3. **Decide if RAG is needed** - Does this issue require manual/documentation retrieval?
4. **Generate semantic query** - Optimize query for vector embedding search (FAISS)
5. **Track uncertainty** - Identify what's uncertain or ambiguous

OBSERVATION JSON (from Vision Model):
```json
{json.dumps(observation, indent=2, ensure_ascii=False)}
```

KEY OBSERVATIONS:
- Fixture type: {fixture_type}
- Location: {location}
- Top issue: {top_issue_name} (confidence: {top_confidence:.2f})
- Danger level (vision): {danger_level}
- No issue detected: {no_issue}
- Symptoms: {', '.join(symptoms) if symptoms else 'none'}

REASONING INSTRUCTIONS:

1. **Logical Consistency Check**:
   - Does the top issue match the symptoms?
   - Are the confidence scores reasonable?
   - Is the danger level consistent with the issue?
   - Any contradictions in the observation?

2. **Risk Re-Assessment** (use reasoning, not just vision output):
   - Is there immediate danger? (electrical + water, gas leak, structural collapse, sewage backup)
   - Time sensitivity: immediate / hours / days / weeks
   - What conditions would require escalating to a professional?
   - Consider: water damage risk, safety hazards, complexity

3. **RAG Decision**:
   - Set requires_rag=false if:
     * No issue detected (no_issue_detected=true)
     * Issue is trivial (e.g., cosmetic stain, already resolved)
     * User can safely ignore it
   - Set requires_rag=true if:
     * Issue requires repair steps
     * Professional knowledge needed
     * Safety procedures required

4. **Semantic Query Generation** (optimize for vector embedding):
   - Use technical terms (e.g., "toilet flapper valve replacement" not "toilet broken")
   - Include fixture type, issue type, and key symptoms
   - Make it semantic search friendly (how would a repair manual describe this?)
   - Example good queries:
     * "toilet clog paper blockage plunger technique"
     * "water heater pilot light won't stay lit troubleshooting"
     * "sink drain slow drainage hair clog removal"
   - Extract 3-5 keywords for fallback search

5. **Uncertainty Tracking**:
   - List uncertainty sources:
     * "low_image_quality" - blurry, dark, or unclear image
     * "ambiguous_symptom" - symptom could indicate multiple issues
     * "missing_context" - need more information (e.g., "does it make noise?")
     * "contradictory_signals" - vision output has inconsistencies
     * "edge_case" - unusual or rare scenario
   - Consider alternative hypotheses (what else could this be?)

6. **Confidence Scoring** (0.0 to 1.0):
   - High confidence (0.8-1.0): Clear symptoms, consistent data, common issue
   - Medium confidence (0.5-0.79): Some ambiguity, multiple possibilities
   - Low confidence (0.0-0.49): Unclear symptoms, contradictory data, rare issue

OUTPUT FORMAT (strict JSON schema):
{{
  "refined_issue": "Precise issue name (10-200 chars)",
  "refined_location": "Location with context (5-100 chars)",
  "refined_fixture": "Specific fixture/component (3-100 chars)",

  "risk_assessment": {{
    "level": "low|medium|high",
    "reasoning": "Detailed reasoning for risk level (10-500 chars)",
    "immediate_danger_present": true|false,
    "time_sensitivity": "immediate|hours|days|weeks",
    "escalation_triggers": ["condition 1", "condition 2", ...]
  }},

  "requires_rag": true|false,
  "rag_query": "Semantic query for vector search (5-300 chars)",
  "rag_query_keywords": ["keyword1", "keyword2", ...],  // 3-10 keywords

  "statistical_metrics": {{
    "confidence": 0.0-1.0,
    "uncertainty_flags": ["flag1", "flag2", ...],
    "reasoning_steps": 1-20,  // How many reasoning steps did you take?
    "alternative_hypotheses_considered": 0-10  // How many alternatives did you consider?
  }},

  "reasoning_trace": "Step-by-step reasoning showing how you reached these conclusions (20-1000 chars)"
}}

CRITICAL RULES:
- Output ONLY valid JSON (no markdown, no commentary)
- Be conservative with risk assessment (better safe than sorry)
- If uncertain, set appropriate uncertainty_flags
- For no_issue_detected=true cases: requires_rag=false, confidence=high, risk=low
- Reasoning trace must show your step-by-step logic (transparency for debugging)

Now analyze the observation and output your reasoning JSON:
"""
    return prompt


# ============================================================
# Statistical Metrics Calculation
# ============================================================

def _calculate_statistical_metrics(
    parsed_json: dict[str, Any],
    original_observation: dict[str, Any],
    latency_ms: float,
) -> StatisticalMetrics:
    """
    Calculate statistical confidence metrics from Llama output.

    This includes:
    - Confidence score validation
    - Uncertainty flag extraction
    - Reasoning quality metrics
    """
    metrics_data = parsed_json.get("statistical_metrics", {})

    # Extract or compute confidence
    confidence = float(metrics_data.get("confidence", 0.5))
    confidence = max(0.0, min(1.0, confidence))  # Clamp to [0, 1]

    # Extract uncertainty flags
    uncertainty_flags = metrics_data.get("uncertainty_flags", [])
    if not isinstance(uncertainty_flags, list):
        uncertainty_flags = []

    # Auto-add uncertainty flag if vision model had low confidence
    top_issue = original_observation.get("prospected_issues", [{}])[0]
    vision_confidence = float(top_issue.get("confidence", 0.0))
    if vision_confidence < 0.5 and "low_vision_confidence" not in uncertainty_flags:
        uncertainty_flags.append("low_vision_confidence")

    # Extract reasoning quality metrics
    reasoning_steps = int(metrics_data.get("reasoning_steps", 1))
    reasoning_steps = max(1, min(20, reasoning_steps))  # Clamp to [1, 20]

    alternatives_considered = int(metrics_data.get("alternative_hypotheses_considered", 0))
    alternatives_considered = max(0, min(10, alternatives_considered))  # Clamp to [0, 10]

    return StatisticalMetrics(
        confidence=confidence,
        uncertainty_flags=uncertainty_flags,
        reasoning_steps=reasoning_steps,
        alternative_hypotheses_considered=alternatives_considered,
    )


# ============================================================
# Validation Helpers
# ============================================================

def _validate_reasoner_output(parsed_json: dict[str, Any]) -> Optional[str]:
    """
    Validate Llama Reasoner ① output structure.

    Returns:
        Error message if validation fails, None if valid.
    """
    # Check required top-level fields
    required_fields = [
        "refined_issue",
        "refined_location",
        "refined_fixture",
        "risk_assessment",
        "requires_rag",
        "rag_query",
        "rag_query_keywords",
        "statistical_metrics",
        "reasoning_trace",
    ]

    for field in required_fields:
        if field not in parsed_json:
            return f"Missing required field: {field}"

    # Validate risk_assessment structure
    risk = parsed_json.get("risk_assessment", {})
    if not isinstance(risk, dict):
        return "risk_assessment must be a dict"

    risk_required = ["level", "reasoning", "immediate_danger_present", "time_sensitivity", "escalation_triggers"]
    for field in risk_required:
        if field not in risk:
            return f"risk_assessment missing field: {field}"

    # Validate risk level
    if risk.get("level") not in ["low", "medium", "high"]:
        return f"Invalid risk level: {risk.get('level')} (must be low/medium/high)"

    # Validate time sensitivity
    if risk.get("time_sensitivity") not in ["immediate", "hours", "days", "weeks"]:
        return f"Invalid time_sensitivity: {risk.get('time_sensitivity')}"

    # Validate statistical_metrics structure
    metrics = parsed_json.get("statistical_metrics", {})
    if not isinstance(metrics, dict):
        return "statistical_metrics must be a dict"

    if "confidence" not in metrics:
        return "statistical_metrics missing confidence"

    confidence = metrics.get("confidence")
    if not isinstance(confidence, (int, float)) or not (0.0 <= confidence <= 1.0):
        return f"Invalid confidence: {confidence} (must be 0.0-1.0)"

    # Validate rag_query_keywords is a list
    keywords = parsed_json.get("rag_query_keywords", [])
    if not isinstance(keywords, list):
        return "rag_query_keywords must be a list"

    # All checks passed
    return None
