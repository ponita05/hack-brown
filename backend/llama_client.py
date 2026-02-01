"""
Groq API client for Llama 3.3 70B reasoning.

This module provides deterministic, reproducible LLM reasoning using:
- Llama 3.3 70B Versatile via Groq (fast inference)
- Low temperature (0.1) for deterministic behavior
- JSON mode for structured output
- Retry logic for robustness
- Token usage tracking for cost monitoring

Why Groq?
- Free tier with generous limits
- Extremely fast inference (< 2s for most queries)
- Native JSON mode support
- Llama 3.3 70B has excellent reasoning capabilities

Why temperature=0.1?
- Not 0.0 because that can cause repetition/degeneration
- 0.1 gives near-deterministic output while avoiding edge cases
- Reproducibility: same input → same output (99%+ of the time)
"""

import os
import time
import json
from typing import Optional, Any
from groq import Groq, RateLimitError, APIError

# ============================================================
# Configuration
# ============================================================

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
if not GROQ_API_KEY:
    print("⚠️ GROQ_API_KEY not found in environment. Llama reasoning will fail.")
    print("   Get your key at: https://console.groq.com/keys")

# Groq client (singleton)
groq_client: Optional[Groq] = None
if GROQ_API_KEY:
    groq_client = Groq(api_key=GROQ_API_KEY)

# Model configuration
LLAMA_MODEL = "llama-3.3-70b-versatile"
DETERMINISTIC_TEMPERATURE = 0.1  # Near-deterministic (not 0.0 to avoid degeneration)
MAX_TOKENS = 4096  # Generous limit for detailed reasoning
RETRY_ATTEMPTS = 3  # Number of retries on transient errors
RETRY_DELAY_SECONDS = 1.0  # Initial delay between retries (exponential backoff)


# ============================================================
# Core Llama Reasoning Function
# ============================================================

def llama_reason(
    prompt: str,
    json_mode: bool = False,
    temperature: float = DETERMINISTIC_TEMPERATURE,
    max_tokens: int = MAX_TOKENS,
    system_prompt: Optional[str] = None,
    retry_attempts: int = RETRY_ATTEMPTS,
) -> dict[str, Any]:
    """
    Call Llama 3.3 70B via Groq with deterministic settings.

    Args:
        prompt: The user prompt (main reasoning task)
        json_mode: If True, force JSON output format
        temperature: Sampling temperature (default 0.1 for deterministic behavior)
        max_tokens: Maximum tokens in response
        system_prompt: Optional system prompt (defaults to reasoning-focused prompt)
        retry_attempts: Number of retry attempts on transient errors

    Returns:
        {
            "success": bool,
            "content": str,  # The LLM response text
            "parsed_json": dict | None,  # Parsed JSON if json_mode=True
            "error": str | None,
            "tokens_used": int,
            "latency_ms": float,
            "model": str,
            "temperature": float,
        }

    Example:
        >>> result = llama_reason("Analyze this: {json_data}", json_mode=True)
        >>> if result["success"]:
        >>>     analysis = result["parsed_json"]
        >>>     print(f"Confidence: {analysis['confidence']}")
    """
    if not groq_client:
        return {
            "success": False,
            "content": "",
            "parsed_json": None,
            "error": "Groq client not initialized (missing GROQ_API_KEY)",
            "tokens_used": 0,
            "latency_ms": 0.0,
            "model": LLAMA_MODEL,
            "temperature": temperature,
        }

    # Default system prompt emphasizes reasoning and accuracy
    if system_prompt is None:
        if json_mode:
            system_prompt = (
                "You are a precise reasoning assistant. "
                "Always output valid JSON. "
                "Be logical, step-by-step, and grounded in facts. "
                "If uncertain, acknowledge limitations. "
                "Never hallucinate or invent information."
            )
        else:
            system_prompt = (
                "You are a careful reasoning assistant. "
                "Think step-by-step. Be logical and grounded. "
                "Acknowledge uncertainty when appropriate."
            )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt},
    ]

    # Build request kwargs
    kwargs: dict[str, Any] = {
        "model": LLAMA_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    # Enable JSON mode if requested
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    # Retry loop with exponential backoff
    last_error: Optional[Exception] = None
    for attempt in range(1, retry_attempts + 1):
        try:
            t0 = time.time()
            response = groq_client.chat.completions.create(**kwargs)
            latency_ms = (time.time() - t0) * 1000

            content = response.choices[0].message.content or ""
            tokens_used = response.usage.total_tokens if response.usage else 0

            # Parse JSON if json_mode is enabled
            parsed_json = None
            if json_mode and content.strip():
                try:
                    parsed_json = json.loads(content)
                except json.JSONDecodeError as e:
                    return {
                        "success": False,
                        "content": content,
                        "parsed_json": None,
                        "error": f"JSON parse error: {str(e)}. Raw content: {content[:200]}",
                        "tokens_used": tokens_used,
                        "latency_ms": latency_ms,
                        "model": LLAMA_MODEL,
                        "temperature": temperature,
                    }

            return {
                "success": True,
                "content": content,
                "parsed_json": parsed_json,
                "error": None,
                "tokens_used": tokens_used,
                "latency_ms": latency_ms,
                "model": LLAMA_MODEL,
                "temperature": temperature,
            }

        except RateLimitError as e:
            last_error = e
            if attempt < retry_attempts:
                delay = RETRY_DELAY_SECONDS * (2 ** (attempt - 1))  # Exponential backoff
                print(f"⚠️ Groq rate limit hit (attempt {attempt}/{retry_attempts}). Retrying in {delay:.1f}s...")
                time.sleep(delay)
            else:
                return {
                    "success": False,
                    "content": "",
                    "parsed_json": None,
                    "error": f"Rate limit exceeded after {retry_attempts} attempts: {str(e)}",
                    "tokens_used": 0,
                    "latency_ms": 0.0,
                    "model": LLAMA_MODEL,
                    "temperature": temperature,
                }

        except APIError as e:
            last_error = e
            # Retry on transient API errors (5xx)
            if attempt < retry_attempts and (500 <= getattr(e, "status_code", 0) < 600):
                delay = RETRY_DELAY_SECONDS * (2 ** (attempt - 1))
                print(f"⚠️ Groq API error {getattr(e, 'status_code', '?')} (attempt {attempt}/{retry_attempts}). Retrying in {delay:.1f}s...")
                time.sleep(delay)
            else:
                return {
                    "success": False,
                    "content": "",
                    "parsed_json": None,
                    "error": f"Groq API error: {str(e)}",
                    "tokens_used": 0,
                    "latency_ms": 0.0,
                    "model": LLAMA_MODEL,
                    "temperature": temperature,
                }

        except Exception as e:
            # Non-retryable error
            return {
                "success": False,
                "content": "",
                "parsed_json": None,
                "error": f"Unexpected error: {type(e).__name__}: {str(e)}",
                "tokens_used": 0,
                "latency_ms": 0.0,
                "model": LLAMA_MODEL,
                "temperature": temperature,
            }

    # Should never reach here, but just in case
    return {
        "success": False,
        "content": "",
        "parsed_json": None,
        "error": f"Failed after {retry_attempts} attempts: {str(last_error)}",
        "tokens_used": 0,
        "latency_ms": 0.0,
        "model": LLAMA_MODEL,
        "temperature": temperature,
    }


# ============================================================
# Convenience Wrappers
# ============================================================

def llama_reason_json(
    prompt: str,
    temperature: float = DETERMINISTIC_TEMPERATURE,
    max_tokens: int = MAX_TOKENS,
) -> dict[str, Any]:
    """
    Shortcut for JSON mode reasoning.

    Returns:
        Same as llama_reason(), but json_mode=True is enforced.
    """
    return llama_reason(
        prompt=prompt,
        json_mode=True,
        temperature=temperature,
        max_tokens=max_tokens,
    )


def llama_reason_text(
    prompt: str,
    temperature: float = DETERMINISTIC_TEMPERATURE,
    max_tokens: int = MAX_TOKENS,
) -> dict[str, Any]:
    """
    Shortcut for text mode reasoning (no JSON enforcement).

    Returns:
        Same as llama_reason(), but json_mode=False.
    """
    return llama_reason(
        prompt=prompt,
        json_mode=False,
        temperature=temperature,
        max_tokens=max_tokens,
    )


# ============================================================
# Health Check
# ============================================================

def test_groq_connection() -> bool:
    """
    Test Groq API connection with a simple query.

    Returns:
        True if connection successful, False otherwise.
    """
    result = llama_reason("Say 'OK' if you can read this.", json_mode=False, max_tokens=10)
    if result["success"]:
        print(f"✅ Groq API connection OK (latency: {result['latency_ms']:.0f}ms, tokens: {result['tokens_used']})")
        return True
    else:
        print(f"❌ Groq API connection failed: {result['error']}")
        return False


# ============================================================
# Module-level initialization check
# ============================================================

if __name__ == "__main__":
    # Run connection test when module is executed directly
    print("Testing Groq API connection...")
    test_groq_connection()
