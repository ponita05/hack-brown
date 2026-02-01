from typing import Dict, Any

def analysis_to_query(a: Dict[str, Any]) -> str:
    if not a:
        return ""

    parts = []
    parts.append(a.get("location", ""))
    parts.append(a.get("fixture", ""))
    parts.append(a.get("overall_danger_level", ""))

    if a.get("requires_shutoff"):
        parts.append("shutoff required")
    if a.get("water_present"):
        parts.append("water present")

    symptoms = a.get("observed_symptoms") or []
    parts.extend(symptoms[:5])

    issues = a.get("prospected_issues") or []
    for it in issues[:2]:
        parts.append(it.get("category", ""))
        parts.append(it.get("issue_name", ""))
        parts.append(it.get("suspected_cause", ""))

    return " ".join([p for p in parts if isinstance(p, str) and p.strip()]).strip()
