"""
Shared Pydantic schemas for Llama reasoning pipeline.

This module defines the contract between:
- Reasoner ① (JSON refinement, query generation, risk assessment)
- Reasoner ② (Structured fix plan generation)
- RAG retrieval system
- Frontend API responses

All schemas include statistical metrics for confidence tracking and reproducibility.
"""

from typing import Optional, Literal
from pydantic import BaseModel, Field


# ============================================================
# Statistical Analysis Models
# ============================================================

class StatisticalMetrics(BaseModel):
    """
    Statistical confidence metrics for reasoning outputs.
    Used to track uncertainty and reasoning quality.
    """
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Overall confidence in the reasoning (0.0 = no confidence, 1.0 = very confident)",
    )
    uncertainty_flags: list[str] = Field(
        default_factory=list,
        description="List of uncertainty sources (e.g., 'low_image_quality', 'ambiguous_symptom', 'missing_context')",
    )
    reasoning_steps: int = Field(
        ge=1,
        description="Number of reasoning steps taken to reach conclusion",
    )
    alternative_hypotheses_considered: int = Field(
        ge=0,
        description="Number of alternative explanations considered during reasoning",
    )


class VectorRetrievalMetrics(BaseModel):
    """
    Metrics from vector embedding retrieval (RAG/FAISS).
    """
    query_embedding_norm: Optional[float] = Field(
        None,
        description="L2 norm of the query embedding vector (useful for debugging embedding quality)",
    )
    avg_similarity_score: Optional[float] = Field(
        None,
        ge=0.0,
        le=1.0,
        description="Average cosine similarity of top-k retrieved documents",
    )
    min_similarity_score: Optional[float] = Field(
        None,
        ge=0.0,
        le=1.0,
        description="Minimum similarity score among retrieved docs (indicates retrieval quality floor)",
    )
    max_similarity_score: Optional[float] = Field(
        None,
        ge=0.0,
        le=1.0,
        description="Maximum similarity score among retrieved docs (best match quality)",
    )
    num_docs_retrieved: int = Field(
        ge=0,
        description="Number of documents successfully retrieved",
    )
    retrieval_latency_ms: Optional[float] = Field(
        None,
        ge=0.0,
        description="Time taken for vector retrieval in milliseconds",
    )


# ============================================================
# Reasoner ① Output (JSON Refinement + Query Generation)
# ============================================================

class RiskAssessment(BaseModel):
    """
    Detailed risk assessment from Llama Reasoner ①.
    """
    level: Literal["low", "medium", "high"] = Field(
        description="Overall risk level after logical reasoning",
    )
    reasoning: str = Field(
        min_length=10,
        max_length=500,
        description="Detailed reasoning for the risk level (why is it low/medium/high?)",
    )
    immediate_danger_present: bool = Field(
        description="Is there immediate danger requiring shutoff/evacuation?",
    )
    time_sensitivity: Literal["immediate", "hours", "days", "weeks"] = Field(
        description="How quickly must this issue be addressed?",
    )
    escalation_triggers: list[str] = Field(
        default_factory=list,
        description="Conditions that would require escalating to a professional (e.g., 'water near electrical', 'sewage backup')",
    )


class ReasonerOutput(BaseModel):
    """
    Output from Llama Reasoner ① (JSON Refinement + Query Generation).

    This is the contract between Vision LLM output and RAG retrieval.
    Reasoner ① takes raw vision JSON and produces:
    - Refined, logically consistent issue description
    - Risk re-assessment based on reasoning (not just vision)
    - Decision on whether RAG retrieval is necessary
    - Optimized query for vector search
    """
    refined_issue: str = Field(
        min_length=10,
        max_length=200,
        description="Refined issue name after logical reasoning (more precise than vision model output)",
    )
    refined_location: str = Field(
        min_length=5,
        max_length=100,
        description="Refined location with context (e.g., 'Bathroom toilet, residential unit')",
    )
    refined_fixture: str = Field(
        min_length=3,
        max_length=100,
        description="Specific fixture or component (e.g., 'Toilet bowl drain trap')",
    )

    risk_assessment: RiskAssessment = Field(
        description="Detailed risk assessment from reasoning",
    )

    requires_rag: bool = Field(
        description="Does this issue require manual/documentation retrieval? (False if trivial or already resolved)",
    )
    rag_query: str = Field(
        min_length=5,
        max_length=300,
        description="Optimized query for vector embedding search (semantic search friendly)",
    )
    rag_query_keywords: list[str] = Field(
        default_factory=list,
        max_length=10,
        description="Key technical terms for fallback keyword search (e.g., ['flapper', 'valve', 'clog'])",
    )

    statistical_metrics: StatisticalMetrics = Field(
        description="Statistical confidence metrics for this reasoning output",
    )

    reasoning_trace: str = Field(
        min_length=20,
        max_length=1000,
        description="Step-by-step reasoning trace showing how conclusions were reached (for transparency and debugging)",
    )


# ============================================================
# Reasoner ② Output (Structured Fix Plan Generation)
# ============================================================

class FixStep(BaseModel):
    """
    A single step in the fix plan.
    """
    step_number: int = Field(
        ge=1,
        description="Step number in sequence (1, 2, 3, ...)",
    )
    title: str = Field(
        min_length=5,
        max_length=100,
        description="Short title for this step (e.g., 'Turn off water supply')",
    )
    instruction: str = Field(
        min_length=10,
        max_length=500,
        description="Detailed instruction for this step",
    )
    safety_note: Optional[str] = Field(
        None,
        max_length=300,
        description="Safety warning or precaution for this step (if applicable)",
    )
    expected_outcome: str = Field(
        min_length=5,
        max_length=200,
        description="What should happen if this step is done correctly? (e.g., 'Water flow should stop within 2-3 seconds')",
    )
    estimated_time_minutes: Optional[int] = Field(
        None,
        ge=1,
        le=120,
        description="Estimated time to complete this step in minutes (optional, for user planning)",
    )
    tools_for_this_step: list[str] = Field(
        default_factory=list,
        description="Specific tools needed for this step only",
    )


class CitationTracker(BaseModel):
    """
    Tracks which retrieved documents were actually used in the fix plan.
    This is critical for hallucination detection.
    """
    cited_doc_indices: list[int] = Field(
        default_factory=list,
        description="List of document indices (from RAG retrieval) that were cited in the plan",
    )
    uncited_doc_indices: list[int] = Field(
        default_factory=list,
        description="List of retrieved documents that were NOT cited (useful for debugging retrieval quality)",
    )
    hallucination_risk_score: float = Field(
        ge=0.0,
        le=1.0,
        description="Risk score for hallucination (0.0 = all claims are cited, 1.0 = no citations/high risk)",
    )
    citation_coverage: float = Field(
        ge=0.0,
        le=1.0,
        description="Fraction of fix plan content that is backed by citations (1.0 = fully grounded)",
    )


class FixPlan(BaseModel):
    """
    Complete fix plan from Llama Reasoner ②.

    This is the final structured output that goes to the frontend.
    It includes:
    - Step-by-step instructions
    - Safety notes and escalation conditions
    - Citation tracking for hallucination detection
    - Statistical metrics for confidence
    """
    summary: str = Field(
        min_length=20,
        max_length=500,
        description="1-2 sentence summary of what's happening and the fix approach",
    )

    danger_level: Literal["low", "medium", "high"] = Field(
        description="Final danger level after reasoning + RAG retrieval",
    )

    steps: list[FixStep] = Field(
        min_length=1,
        max_length=15,
        description="Ordered list of fix steps (at least 1, max 15 for UX)",
    )

    call_pro_if: list[str] = Field(
        default_factory=list,
        description="Conditions that require calling a professional (e.g., 'Sewage backup continues', 'Gas smell persists')",
    )

    tools_needed: list[str] = Field(
        default_factory=list,
        description="All tools needed for the entire fix (aggregated from all steps)",
    )

    parts_needed: list[str] = Field(
        default_factory=list,
        description="Replacement parts that might be needed (e.g., 'Flapper valve', 'Wax ring')",
    )

    estimated_total_time_minutes: Optional[int] = Field(
        None,
        ge=1,
        le=300,
        description="Total estimated time for the entire fix in minutes",
    )

    citation_tracker: CitationTracker = Field(
        description="Citation tracking for hallucination detection",
    )

    statistical_metrics: StatisticalMetrics = Field(
        description="Statistical confidence metrics for this fix plan",
    )

    rag_retrieval_metrics: Optional[VectorRetrievalMetrics] = Field(
        None,
        description="Metrics from vector retrieval (if RAG was used)",
    )

    fallback_to_vision_only: bool = Field(
        default=False,
        description="True if RAG retrieval failed and plan is based only on vision model observation",
    )


# ============================================================
# API Response Models (for frontend)
# ============================================================

class SolutionResponseV2(BaseModel):
    """
    Enhanced /solution endpoint response with Llama reasoning pipeline.
    """
    success: bool
    session_id: str

    # Reasoner ① outputs
    reasoner_output: Optional[ReasonerOutput] = None

    # Reasoner ② outputs
    fix_plan: Optional[FixPlan] = None

    # Legacy fields (for backward compatibility)
    query: Optional[str] = None
    citations: Optional[list[dict]] = None
    solution: Optional[str] = None

    # Error handling
    error: Optional[str] = None
    error_stage: Optional[Literal["vision", "reasoner1", "rag", "reasoner2"]] = None

    # Performance metrics
    total_latency_ms: Optional[float] = None
    stage_latencies: Optional[dict[str, float]] = None
