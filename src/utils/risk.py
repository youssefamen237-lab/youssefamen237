BLOCKED = {
    "violence",
    "hate",
    "adult",
    "drugs",
    "weapon",
    "terror",
}


def is_safe_text(text: str) -> bool:
    lowered = text.lower()
    return not any(word in lowered for word in BLOCKED)
