"""
polls_engine.py
Posts 2 community polls per day to YouTube Community tab.
Questions are sourced from shorts published ~7 days ago.
This engine aggressively grows subscribers via YouTube's poll recommendation algorithm.
"""

import os
import json
import random
import datetime

from content_generator import generate_question, TEMPLATES, QUESTION_CATEGORIES
from youtube_uploader import post_community_poll

POLLS_LOG = "data/polls_log.json"


def _load_polls_log() -> list:
    if os.path.exists(POLLS_LOG):
        with open(POLLS_LOG, "r") as f:
            return json.load(f)
    return []


def _save_polls_log(log: list):
    os.makedirs(os.path.dirname(POLLS_LOG), exist_ok=True)
    with open(POLLS_LOG, "w") as f:
        json.dump(log, f, indent=2)


def _load_recent_shorts(days_ago: int = 7) -> list:
    """Loads shorts metadata from the last N days."""
    log_path = "data/videos_log.json"
    if not os.path.exists(log_path):
        return []
    with open(log_path, "r") as f:
        all_videos = json.load(f)

    cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=days_ago)
    recent = []
    for v in all_videos:
        try:
            published = datetime.datetime.fromisoformat(v.get("published_at", ""))
            if published >= cutoff and v.get("type") == "short":
                recent.append(v)
        except Exception:
            pass
    return recent


def _build_poll_from_question(q: dict) -> tuple:
    """
    Returns (poll_question, choices) from a question dict.
    """
    question_text = q.get("question", "")
    answer = q.get("answer", "")
    choices = q.get("choices", [])

    if choices and len(choices) >= 4:
        # Use existing Multiple Choice options
        return question_text, choices[:4]

    if str(answer).lower() in ["true", "false"]:
        # True/False poll
        return question_text, ["True ✅", "False ❌", "I'm not sure 🤔", "Both! 🤯"]

    # Generate distractor choices for non-MC questions
    distractors = _generate_distractors(answer)
    all_choices = [answer] + distractors[:3]
    random.shuffle(all_choices)
    return question_text, all_choices[:4]


def _generate_distractors(correct_answer: str) -> list:
    """Generates plausible wrong answers based on the correct one."""
    # Simple heuristic distractors
    base_distractors = [
        "I don't know 🤷",
        "Something else entirely",
        "None of the above",
    ]

    # If answer is a number, generate nearby numbers
    try:
        num = float(correct_answer.replace(",", "").split()[0])
        return [
            str(int(num * random.uniform(0.5, 0.8))),
            str(int(num * random.uniform(1.2, 2.0))),
            "I don't know 🤷",
        ]
    except Exception:
        pass

    return base_distractors


def run_polls_engine(polls_per_day: int = 2):
    """
    Posts the daily community polls.
    Called by the polls workflow.
    """
    print(f"[PollsEngine] Starting daily polls run: {polls_per_day} polls")

    polls_log = _load_polls_log()
    today_polls = [
        p for p in polls_log
        if p.get("date") == datetime.date.today().isoformat()
    ]

    if len(today_polls) >= polls_per_day:
        print(f"[PollsEngine] Already posted {len(today_polls)} polls today. Skipping.")
        return

    polls_to_post = polls_per_day - len(today_polls)
    print(f"[PollsEngine] Posting {polls_to_post} new polls...")

    # Try to get questions from recent shorts
    recent_shorts = _load_recent_shorts(days_ago=7)

    for i in range(polls_to_post):
        try:
            if recent_shorts and i < len(recent_shorts):
                # Reuse question from a recent short
                short_data = recent_shorts[i % len(recent_shorts)]
                q = {
                    "question": short_data.get("question", ""),
                    "answer": short_data.get("answer", ""),
                    "choices": short_data.get("choices", []),
                }
                if not q["question"]:
                    raise ValueError("Empty question from shorts log")
            else:
                # Generate fresh question
                q = generate_question(
                    template=random.choice(["Multiple Choice", "True / False"]),
                    category=random.choice(QUESTION_CATEGORIES)
                )

            poll_question, choices = _build_poll_from_question(q)
            poll_text = f"🎯 Daily Quiz Challenge!\n\n{poll_question}"

            success = post_community_poll(
                question=poll_text,
                choices=choices,
                credential_set=1
            )

            if success:
                poll_record = {
                    "date": datetime.date.today().isoformat(),
                    "question": poll_question,
                    "choices": choices,
                    "posted_at": datetime.datetime.utcnow().isoformat(),
                }
                polls_log.append(poll_record)
                _save_polls_log(polls_log)
                print(f"[PollsEngine] Poll {i+1} posted successfully")
            else:
                print(f"[PollsEngine] Poll {i+1} failed to post")

            import time, random as rnd
            time.sleep(rnd.uniform(60, 180))  # Avoid spam patterns

        except Exception as e:
            print(f"[PollsEngine] Error posting poll {i+1}: {e}")
            continue

    print("[PollsEngine] Daily polls run complete.")


if __name__ == "__main__":
    run_polls_engine()
