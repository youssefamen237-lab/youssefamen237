"""
Anti-Duplicate Logic — ensures no question, title, thumbnail style, or CTA
is reused within the defined cooldown windows. Maintains a persistent log.
"""

import os
import json
import hashlib
from datetime import datetime, timedelta
from pathlib import Path

DEDUP_DIR = Path("data/dedup")
DEDUP_DIR.mkdir(parents=True, exist_ok=True)

QUESTIONS_DEDUP = DEDUP_DIR / "questions.json"
TITLES_DEDUP = DEDUP_DIR / "titles.json"
TEMPLATES_DEDUP = DEDUP_DIR / "templates.json"
CTAS_DEDUP = DEDUP_DIR / "ctas.json"


def _load(path):
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return []


def _save(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def _fingerprint(text):
    return hashlib.md5(text.strip().lower().encode()).hexdigest()


def _was_used_within(log, text, days):
    fp = _fingerprint(text)
    cutoff = datetime.now() - timedelta(days=days)
    for entry in log:
        if entry.get("fp") == fp:
            used = datetime.fromisoformat(entry.get("date", "2000-01-01"))
            if used > cutoff:
                return True
    return False


def _mark_used(path, text, extra=None):
    log = _load(path)
    entry = {
        "text": text[:200],
        "fp": _fingerprint(text),
        "date": datetime.now().isoformat(),
    }
    if extra:
        entry.update(extra)
    log.append(entry)
    # Keep only last 1000 entries
    if len(log) > 1000:
        log = log[-1000:]
    _save(path, log)


# ─── Question Dedup ───────────────────────────────────────────────────────────

QUESTION_COOLDOWN_DAYS = 15

def is_question_duplicate(question_text):
    log = _load(QUESTIONS_DEDUP)
    return _was_used_within(log, question_text, QUESTION_COOLDOWN_DAYS)


def mark_question_used(question_text, template=None, category=None):
    _mark_used(QUESTIONS_DEDUP, question_text, {
        "template": template,
        "category": category,
    })


# ─── Title Dedup ──────────────────────────────────────────────────────────────

TITLE_COOLDOWN_DAYS = 7

def is_title_duplicate(title):
    log = _load(TITLES_DEDUP)
    return _was_used_within(log, title, TITLE_COOLDOWN_DAYS)


def mark_title_used(title, video_type=None):
    _mark_used(TITLES_DEDUP, title, {"video_type": video_type})


# ─── Template Dedup ───────────────────────────────────────────────────────────

TEMPLATE_CONSECUTIVE_LIMIT = 1  # Never same template twice in a row

def get_last_used_template():
    log = _load(TEMPLATES_DEDUP)
    if log:
        return log[-1].get("text", "")
    return ""


def mark_template_used(template):
    _mark_used(TEMPLATES_DEDUP, template)


# ─── CTA Dedup ────────────────────────────────────────────────────────────────

CTA_COOLDOWN_DAYS = 3

def is_cta_duplicate(cta_text):
    log = _load(CTAS_DEDUP)
    return _was_used_within(log, cta_text, CTA_COOLDOWN_DAYS)


def mark_cta_used(cta_text):
    _mark_used(CTAS_DEDUP, cta_text)


# ─── Combined validation ──────────────────────────────────────────────────────

def validate_question_data(question_data):
    """Validate all fields of question data are unique within cooldown windows"""
    issues = []

    q = question_data.get("question", "")
    if is_question_duplicate(q):
        issues.append(f"Question recently used: {q[:50]}")

    t = question_data.get("template", "")
    last_tmpl = get_last_used_template()
    if t == last_tmpl:
        issues.append(f"Template same as last video: {t}")

    cta = question_data.get("cta", "")
    if cta and is_cta_duplicate(cta):
        issues.append(f"CTA recently used: {cta[:40]}")

    return issues


def register_question_published(question_data):
    """Mark all elements of a question as used"""
    mark_question_used(
        question_data.get("question", ""),
        template=question_data.get("template"),
        category=question_data.get("category"),
    )
    if question_data.get("template"):
        mark_template_used(question_data["template"])
    if question_data.get("cta"):
        mark_cta_used(question_data["cta"])


def register_video_published(title, video_type):
    mark_title_used(title, video_type=video_type)


def get_stats():
    """Return dedup stats"""
    q_log = _load(QUESTIONS_DEDUP)
    t_log = _load(TITLES_DEDUP)
    tmpl_log = _load(TEMPLATES_DEDUP)
    cta_log = _load(CTAS_DEDUP)

    return {
        "questions_tracked": len(q_log),
        "titles_tracked": len(t_log),
        "templates_tracked": len(tmpl_log),
        "ctas_tracked": len(cta_log),
        "last_template": get_last_used_template(),
    }


if __name__ == "__main__":
    print(json.dumps(get_stats(), indent=2))
