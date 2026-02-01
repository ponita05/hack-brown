# backend/query_builder.py
from typing import Dict, Any

def analysis_to_query(analysis: Dict[str, Any]) -> str:
    """
    analysis JSON -> retrieval-friendly query
    핵심: category/fixture/symptoms/top issue를 한 문장에 모아준다.
    """
    if not isinstance(analysis, dict):
        return "home repair troubleshooting steps"

    issues = analysis.get("prospected_issues") or []
    top = issues[0] if issues else {}
    issue_name = (top.get("issue_name") or "").strip()
    cause = (top.get("suspected_cause") or "").strip()
    category = (top.get("category") or analysis.get("category") or "").strip()

    fixture = (analysis.get("fixture") or "").strip()
    location = (analysis.get("location") or "").strip()
    symptoms = analysis.get("observed_symptoms") or []
    symptoms_txt = ", ".join([s for s in symptoms if isinstance(s, str)])[:220]

    danger = analysis.get("overall_danger_level") or ""
    shutoff = analysis.get("requires_shutoff")
    water = analysis.get("water_present")

    # query는 “문장 + 키워드”가 제일 잘 먹힘
    parts = []
    if category:
        parts.append(f"category: {category}")
    if fixture:
        parts.append(f"fixture: {fixture}")
    if location:
        parts.append(f"location: {location}")
    if issue_name:
        parts.append(f"likely issue: {issue_name}")
    if cause:
        parts.append(f"suspected cause: {cause}")
    if symptoms_txt:
        parts.append(f"symptoms: {symptoms_txt}")
    if danger:
        parts.append(f"danger: {danger}")
    if shutoff is True:
        parts.append("safety: shutoff recommended")
    if water is True:
        parts.append("water present")

    # 마지막에 “what to do” 키워드 추가하면 매뉴얼류가 잘 붙음
    parts.append("step-by-step fix, troubleshooting, tools checklist")

    return " | ".join(parts)
