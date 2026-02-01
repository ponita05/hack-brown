"""
Llama Reasoner ② - Structured Fix Plan Generation with Hallucination Detection.

This module implements the second reasoning stage in the Llama pipeline:
1. Takes refined JSON from Reasoner ① + retrieved RAG documents
2. Generates structured, step-by-step fix plan
3. Tracks citations to prevent hallucination
4. Calculates statistical confidence metrics
5. Ensures safety notes and escalation conditions

Key goals:
- Structured output enforcement via Pydantic schemas
- Hallucination detection via citation tracking
- Safety-first approach (escalate when uncertain)
- Reproducibility (deterministic LLM behavior)
"""

import json
import time
from typing import Any, Optional

from schemas import (
    FixPlan,
    FixStep,
    CitationTracker,
    StatisticalMetrics,
    VectorRetrievalMetrics,
    ReasonerOutput,
)
from llama_client import llama_reason_json


# ============================================================
# Main Planner (Reasoner ②) Function
# ============================================================

def generate_fix_plan(
    reasoner_output: ReasonerOutput,
    retrieved_docs: list[dict[str, Any]],
    retrieval_metrics: Optional[VectorRetrievalMetrics] = None,
    session_id: str = "unknown",
) -> tuple[bool, Optional[FixPlan], Optional[str]]:
    """
    Llama Reasoner ② - Generate structured fix plan with hallucination detection.

    Args:
        reasoner_output: Output from Reasoner ① (refined diagnosis, risk, query)
        retrieved_docs: List of RAG documents from FAISS/vector search
            Each doc should have: {rank, score, text, source}
        retrieval_metrics: Optional metrics from vector retrieval
        session_id: Session identifier for logging

    Returns:
        (success, fix_plan, error_message)
        - success: True if planning succeeded
        - fix_plan: FixPlan object with structured steps (or None if failed)
        - error_message: Error description (or None if succeeded)

    Example:
        >>> reasoner_output = ReasonerOutput(...)
        >>> docs = [{"rank": 1, "score": 0.85, "text": "...", "source": "manual.pdf"}]
        >>> success, plan, error = generate_fix_plan(reasoner_output, docs)
        >>> if success:
        ...     for step in plan.steps:
        ...         print(f"{step.step_number}. {step.title}")
    """
    t0 = time.time()

    # ============================================================
    # Step 1: Handle no-RAG case (trivial issues or no docs needed)
    # ============================================================
    if not reasoner_output.requires_rag or len(retrieved_docs) == 0:
        print(f"[Planner ②] No RAG retrieval (requires_rag={reasoner_output.requires_rag}, docs={len(retrieved_docs)})")
        # Generate simple plan without citations
        return _generate_fallback_plan(reasoner_output, session_id)

    # ============================================================
    # Step 2: Build detailed planning prompt with citations
    # ============================================================
    prompt = _build_planner_prompt(reasoner_output, retrieved_docs)

    # ============================================================
    # Step 3: Call Llama with JSON mode (deterministic)
    # ============================================================
    print(f"[Planner ②] Calling Llama for session {session_id} with {len(retrieved_docs)} docs...")
    result = llama_reason_json(prompt=prompt, temperature=0.1, max_tokens=4096)

    if not result["success"]:
        error_msg = f"Llama call failed: {result['error']}"
        print(f"❌ [Planner ②] {error_msg}")
        return False, None, error_msg

    latency_ms = (time.time() - t0) * 1000
    print(f"✅ [Planner ②] Llama responded in {latency_ms:.0f}ms (tokens: {result['tokens_used']})")

    # ============================================================
    # Step 4: Parse and validate Llama JSON output
    # ============================================================
    parsed_json = result["parsed_json"]
    if not parsed_json:
        error_msg = "Llama returned empty JSON"
        print(f"❌ [Planner ②] {error_msg}")
        return False, None, error_msg

    validation_error = _validate_fix_plan_json(parsed_json)
    if validation_error:
        print(f"❌ [Planner ②] Validation failed: {validation_error}")
        return False, None, validation_error

    # ============================================================
    # Step 5: Build FixPlan with citation tracking and metrics
    # ============================================================
    try:
        # Parse steps
        steps_data = parsed_json.get("steps", [])
        steps = []
        for s in steps_data:
            step = FixStep(
                step_number=s.get("step_number", 1),
                title=s.get("title", "Untitled step"),
                instruction=s.get("instruction", "No instruction provided"),
                safety_note=s.get("safety_note"),
                expected_outcome=s.get("expected_outcome", "Outcome not specified"),
                estimated_time_minutes=s.get("estimated_time_minutes"),
                tools_for_this_step=s.get("tools_for_this_step", []),
            )
            steps.append(step)

        # Calculate citation tracker
        cited_indices = parsed_json.get("cited_doc_indices", [])
        citation_tracker = _calculate_citation_tracker(
            cited_indices=cited_indices,
            total_docs=len(retrieved_docs),
            plan_text=json.dumps(steps_data),
        )

        # Calculate statistical metrics
        statistical_metrics = _calculate_planner_statistical_metrics(
            parsed_json=parsed_json,
            reasoner_confidence=reasoner_output.statistical_metrics.confidence,
            citation_tracker=citation_tracker,
        )

        # Aggregate tools and parts
        tools_needed = _aggregate_tools(steps)
        parts_needed = parsed_json.get("parts_needed", [])

        # Calculate total time
        total_time = sum(s.estimated_time_minutes or 0 for s in steps)

        # Build final FixPlan
        fix_plan = FixPlan(
            summary=parsed_json.get("summary", "Fix plan generated"),
            danger_level=parsed_json.get("danger_level", reasoner_output.risk_assessment.level),
            steps=steps,
            call_pro_if=parsed_json.get("call_pro_if", []),
            tools_needed=tools_needed,
            parts_needed=parts_needed,
            estimated_total_time_minutes=total_time if total_time > 0 else None,
            citation_tracker=citation_tracker,
            statistical_metrics=statistical_metrics,
            rag_retrieval_metrics=retrieval_metrics,
            fallback_to_vision_only=False,
        )

        print(f"✅ [Planner ②] Plan validated. Steps: {len(steps)}, Citation coverage: {citation_tracker.citation_coverage:.2f}, Hallucination risk: {citation_tracker.hallucination_risk_score:.2f}")
        return True, fix_plan, None

    except Exception as e:
        error_msg = f"Failed to build FixPlan: {type(e).__name__}: {str(e)}"
        print(f"❌ [Planner ②] {error_msg}")
        return False, None, error_msg


# ============================================================
# Prompt Engineering for Planner (Reasoner ②)
# ============================================================

def _build_planner_prompt(
    reasoner_output: ReasonerOutput,
    retrieved_docs: list[dict[str, Any]],
) -> str:
    """
    Build detailed planning prompt for Llama Reasoner ②.

    This prompt emphasizes:
    - Structured step-by-step plan
    - Citation tracking (every claim should reference a doc)
    - Safety-first approach
    - Hallucination prevention
    """
    # Format retrieved docs for prompt
    docs_text = ""
    for i, doc in enumerate(retrieved_docs):
        rank = doc.get("rank", i + 1)
        score = doc.get("score")
        text = doc.get("text", "")
        source = doc.get("source", "unknown")

        score_str = f"{score:.3f}" if score is not None else "n/a"
        docs_text += f"\n[DOC #{rank}] (similarity: {score_str}, source: {source})\n{text}\n"

    # Build prompt
    prompt = f"""You are FixDad, a careful home repair planning assistant.

Your task is to generate a **safe, structured, step-by-step fix plan** based on:
1. REFINED DIAGNOSIS from Reasoner ① (logical analysis of the issue)
2. RETRIEVED REPAIR MANUALS from vector search (FAISS)

REFINED DIAGNOSIS (from Reasoner ①):
```json
{reasoner_output.model_dump_json(indent=2)}
```

KEY DIAGNOSIS SUMMARY:
- Issue: {reasoner_output.refined_issue}
- Location: {reasoner_output.refined_location}
- Fixture: {reasoner_output.refined_fixture}
- Risk: {reasoner_output.risk_assessment.level} ({reasoner_output.risk_assessment.reasoning})
- Immediate danger: {reasoner_output.risk_assessment.immediate_danger_present}
- Time sensitivity: {reasoner_output.risk_assessment.time_sensitivity}

RETRIEVED REPAIR MANUALS ({len(retrieved_docs)} documents):
{docs_text}

PLANNING INSTRUCTIONS:

1. **Citation Requirement** (CRITICAL for hallucination prevention):
   - Every factual claim, procedure, or technical detail MUST come from the retrieved docs
   - If you cite information from a doc, include its number in cited_doc_indices[]
   - Example: If you mention "flapper valve replacement" and it comes from DOC #2, include 2 in cited_doc_indices
   - If you're uncertain or a doc doesn't cover a step, say so explicitly and suggest calling a pro

2. **Step-by-Step Plan**:
   - Break down the fix into 1-15 clear, actionable steps
   - Each step should have:
     * step_number (1, 2, 3, ...)
     * title (short, 5-100 chars)
     * instruction (detailed, 10-500 chars)
     * safety_note (if applicable, max 300 chars)
     * expected_outcome (what should happen if done correctly, 5-200 chars)
     * estimated_time_minutes (optional, 1-120 minutes)
     * tools_for_this_step (list of tools needed for this specific step)

3. **Safety-First Approach**:
   - If risk level is HIGH or immediate_danger_present=true:
     * First step should be safety action (shutoff, evacuate, ventilate, etc.)
     * Include explicit safety_note for dangerous steps
   - If uncertain about a step, add it to call_pro_if[] instead of guessing

4. **Escalation Conditions** (call_pro_if):
   - List conditions that require calling a professional
   - Examples: "Sewage backup continues after 2 attempts", "Gas smell persists", "Electrical sparking"
   - Be conservative: better to escalate than cause damage/injury

5. **Tools and Parts**:
   - List all tools needed (e.g., "Adjustable wrench", "Plunger", "Bucket")
   - List replacement parts that might be needed (e.g., "Flapper valve", "Wax ring")
   - Only list items mentioned in the retrieved docs or essential basics

6. **Summary**:
   - 1-2 sentences explaining what's happening and the fix approach
   - Example: "Toilet is clogged due to paper buildup. We'll use a plunger to clear the blockage, then test the flush."

OUTPUT FORMAT (strict JSON schema):
{{
  "summary": "1-2 sentence fix summary (20-500 chars)",
  "danger_level": "low|medium|high",

  "steps": [
    {{
      "step_number": 1,
      "title": "Step title",
      "instruction": "Detailed instruction",
      "safety_note": "Safety warning (optional)",
      "expected_outcome": "What should happen",
      "estimated_time_minutes": 5,  // optional
      "tools_for_this_step": ["tool1", "tool2"]
    }},
    ...
  ],

  "call_pro_if": ["condition 1", "condition 2", ...],
  "tools_needed": ["tool1", "tool2", ...],  // Will be auto-aggregated, but you can provide
  "parts_needed": ["part1", "part2", ...],

  "cited_doc_indices": [1, 2, 3, ...],  // Which DOC numbers did you cite?

  "statistical_metrics": {{
    "confidence": 0.0-1.0,  // How confident are you in this plan?
    "uncertainty_flags": ["flag1", ...],  // What's uncertain?
    "reasoning_steps": 1-20,
    "alternative_hypotheses_considered": 0-10
  }}
}}

CRITICAL RULES:
- Output ONLY valid JSON (no markdown, no commentary)
- Every step must be grounded in the retrieved docs (cite your sources!)
- If docs don't cover something, don't guess - add to call_pro_if[] instead
- Safety notes are mandatory for dangerous steps (electrical, gas, heights, chemicals, sewage)
- Be conservative: if uncertain, escalate to professional
- Danger level should match or be more conservative than Reasoner ① assessment

CITATION TRACKING EXAMPLE:
If DOC #1 says "Use a flange plunger" and DOC #3 says "Plunge 20-30 seconds", your cited_doc_indices should be [1, 3].

Now generate the structured fix plan JSON:
"""
    return prompt


# ============================================================
# Fallback Plan (No RAG)
# ============================================================

def _generate_fallback_plan(
    reasoner_output: ReasonerOutput,
    session_id: str,
) -> tuple[bool, Optional[FixPlan], Optional[str]]:
    """
    Generate a simple plan when RAG retrieval is not needed or failed.

    Used when:
    - requires_rag=false (trivial issue, no action needed)
    - RAG retrieval returned no documents
    - RAG retrieval failed entirely
    """
    print(f"[Planner ②] Generating fallback plan (vision-only) for session {session_id}")

    try:
        # Create minimal plan based on reasoner output
        if reasoner_output.risk_assessment.level == "high":
            # High risk: immediate escalation
            steps = [
                FixStep(
                    step_number=1,
                    title="Immediate action required",
                    instruction=reasoner_output.risk_assessment.reasoning,
                    safety_note="This is a high-risk situation. Follow safety procedures immediately.",
                    expected_outcome="Immediate danger mitigated",
                    tools_for_this_step=[],
                ),
                FixStep(
                    step_number=2,
                    title="Call a professional",
                    instruction="This issue requires professional expertise. Do not attempt DIY repair.",
                    expected_outcome="Professional scheduled or on-site",
                    tools_for_this_step=["Phone"],
                ),
            ]
            summary = f"High-risk issue detected: {reasoner_output.refined_issue}. Immediate professional help required."
            call_pro_if = ["Immediately - this is a high-risk situation"]

        else:
            # Low/medium risk or no issue: simple guidance
            steps = [
                FixStep(
                    step_number=1,
                    title="Assess the situation",
                    instruction=f"Issue: {reasoner_output.refined_issue}. Location: {reasoner_output.refined_location}. Check if the issue persists or worsens.",
                    expected_outcome="Clear understanding of issue status",
                    tools_for_this_step=[],
                ),
            ]

            if reasoner_output.risk_assessment.immediate_danger_present:
                steps.append(
                    FixStep(
                        step_number=2,
                        title="Take immediate safety action",
                        instruction=reasoner_output.risk_assessment.reasoning,
                        safety_note="Follow safety procedures before attempting any fix.",
                        expected_outcome="Safety measures in place",
                        tools_for_this_step=[],
                    )
                )

            summary = f"Issue: {reasoner_output.refined_issue}. Basic assessment provided. Detailed repair manual not available."
            call_pro_if = reasoner_output.risk_assessment.escalation_triggers or [
                "If issue worsens",
                "If you're uncertain about safety",
            ]

        # Citation tracker (no citations for fallback)
        citation_tracker = CitationTracker(
            cited_doc_indices=[],
            uncited_doc_indices=[],
            hallucination_risk_score=1.0,  # High risk since no docs
            citation_coverage=0.0,  # No coverage
        )

        # Statistical metrics (lower confidence for fallback)
        statistical_metrics = StatisticalMetrics(
            confidence=min(0.5, reasoner_output.statistical_metrics.confidence),  # Cap at 0.5
            uncertainty_flags=reasoner_output.statistical_metrics.uncertainty_flags + ["no_rag_docs", "fallback_plan"],
            reasoning_steps=1,
            alternative_hypotheses_considered=0,
        )

        fix_plan = FixPlan(
            summary=summary,
            danger_level=reasoner_output.risk_assessment.level,
            steps=steps,
            call_pro_if=call_pro_if,
            tools_needed=[],
            parts_needed=[],
            citation_tracker=citation_tracker,
            statistical_metrics=statistical_metrics,
            fallback_to_vision_only=True,
        )

        print(f"✅ [Planner ②] Fallback plan generated with {len(steps)} steps")
        return True, fix_plan, None

    except Exception as e:
        error_msg = f"Failed to generate fallback plan: {type(e).__name__}: {str(e)}"
        print(f"❌ [Planner ②] {error_msg}")
        return False, None, error_msg


# ============================================================
# Citation Tracking and Hallucination Detection
# ============================================================

def _calculate_citation_tracker(
    cited_indices: list[int],
    total_docs: int,
    plan_text: str,
) -> CitationTracker:
    """
    Calculate citation coverage and hallucination risk.

    Hallucination risk is high when:
    - No docs are cited (hallucination_risk = 1.0)
    - Few docs are cited relative to plan length
    - Many docs retrieved but not used
    """
    # Deduplicate cited indices
    cited_set = set(cited_indices)
    cited_list = sorted(cited_set)

    # Uncited docs
    all_indices = set(range(1, total_docs + 1))
    uncited_set = all_indices - cited_set
    uncited_list = sorted(uncited_set)

    # Citation coverage (fraction of plan backed by citations)
    # Heuristic: assume each citation covers ~100 chars of plan
    estimated_cited_chars = len(cited_list) * 100
    plan_chars = len(plan_text)
    citation_coverage = min(1.0, estimated_cited_chars / max(1, plan_chars))

    # Hallucination risk score (0.0 = all grounded, 1.0 = high risk)
    if len(cited_list) == 0:
        hallucination_risk = 1.0  # No citations = maximum risk
    elif citation_coverage >= 0.8:
        hallucination_risk = 0.0  # Excellent coverage
    elif citation_coverage >= 0.5:
        hallucination_risk = 0.3  # Good coverage
    elif citation_coverage >= 0.2:
        hallucination_risk = 0.6  # Moderate coverage
    else:
        hallucination_risk = 0.9  # Poor coverage

    return CitationTracker(
        cited_doc_indices=cited_list,
        uncited_doc_indices=uncited_list,
        hallucination_risk_score=hallucination_risk,
        citation_coverage=citation_coverage,
    )


# ============================================================
# Statistical Metrics Calculation
# ============================================================

def _calculate_planner_statistical_metrics(
    parsed_json: dict[str, Any],
    reasoner_confidence: float,
    citation_tracker: CitationTracker,
) -> StatisticalMetrics:
    """
    Calculate statistical confidence for the fix plan.

    Confidence is adjusted based on:
    - Reasoner ① confidence (inherited)
    - Citation coverage (more citations = more confidence)
    - Hallucination risk (high risk = lower confidence)
    """
    metrics_data = parsed_json.get("statistical_metrics", {})

    # Base confidence from Llama output
    llama_confidence = float(metrics_data.get("confidence", 0.5))
    llama_confidence = max(0.0, min(1.0, llama_confidence))

    # Adjust confidence based on citation coverage
    citation_adjustment = citation_tracker.citation_coverage * 0.2  # Up to +0.2
    hallucination_penalty = citation_tracker.hallucination_risk_score * 0.3  # Up to -0.3

    # Final confidence (blend of Llama, reasoner, and citation quality)
    final_confidence = (
        llama_confidence * 0.5 +
        reasoner_confidence * 0.3 +
        citation_adjustment -
        hallucination_penalty
    )
    final_confidence = max(0.0, min(1.0, final_confidence))

    # Extract uncertainty flags
    uncertainty_flags = metrics_data.get("uncertainty_flags", [])
    if not isinstance(uncertainty_flags, list):
        uncertainty_flags = []

    # Auto-add flags
    if citation_tracker.hallucination_risk_score > 0.5:
        if "high_hallucination_risk" not in uncertainty_flags:
            uncertainty_flags.append("high_hallucination_risk")

    if citation_tracker.citation_coverage < 0.3:
        if "low_citation_coverage" not in uncertainty_flags:
            uncertainty_flags.append("low_citation_coverage")

    # Reasoning quality
    reasoning_steps = int(metrics_data.get("reasoning_steps", 1))
    reasoning_steps = max(1, min(20, reasoning_steps))

    alternatives = int(metrics_data.get("alternative_hypotheses_considered", 0))
    alternatives = max(0, min(10, alternatives))

    return StatisticalMetrics(
        confidence=final_confidence,
        uncertainty_flags=uncertainty_flags,
        reasoning_steps=reasoning_steps,
        alternative_hypotheses_considered=alternatives,
    )


# ============================================================
# Helper Functions
# ============================================================

def _aggregate_tools(steps: list[FixStep]) -> list[str]:
    """Aggregate unique tools from all steps."""
    all_tools = set()
    for step in steps:
        all_tools.update(step.tools_for_this_step)
    return sorted(all_tools)


def _validate_fix_plan_json(parsed_json: dict[str, Any]) -> Optional[str]:
    """
    Validate Llama Planner output structure.

    Returns:
        Error message if validation fails, None if valid.
    """
    # Check required fields
    required = ["summary", "danger_level", "steps", "call_pro_if", "cited_doc_indices", "statistical_metrics"]
    for field in required:
        if field not in parsed_json:
            return f"Missing required field: {field}"

    # Validate danger_level
    if parsed_json.get("danger_level") not in ["low", "medium", "high"]:
        return f"Invalid danger_level: {parsed_json.get('danger_level')}"

    # Validate steps is a non-empty list
    steps = parsed_json.get("steps", [])
    if not isinstance(steps, list) or len(steps) == 0:
        return "steps must be a non-empty list"

    # Validate each step has required fields
    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            return f"steps[{i}] must be a dict"
        step_required = ["step_number", "title", "instruction", "expected_outcome"]
        for field in step_required:
            if field not in step:
                return f"steps[{i}] missing field: {field}"

    # All checks passed
    return None
