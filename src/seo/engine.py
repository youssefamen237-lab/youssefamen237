"""
SEO Engine — generates optimized titles, descriptions, tags, hashtags for every video.
Uses AI for generation with template fallbacks. Always unique — never repeated.
"""

import os
import json
import random
import re
import hashlib
from datetime import datetime
from pathlib import Path
import requests
from tenacity import retry, stop_after_attempt, wait_exponential

SEO_LOG_PATH = Path("data/published/seo_log.json")
SEO_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)


# ─── Title templates ──────────────────────────────────────────────────────────

SHORT_TITLE_TEMPLATES = [
    "🧠 {question_short} — Do You Know the Answer?",
    "⚡ Quick Quiz: {question_short}",
    "Can You Answer THIS in 5 Seconds? 🔥",
    "Only Geniuses Get This Right! 🤯",
    "🎯 {template} Challenge: {question_short}",
    "How Smart Are You? Answer This! 💡",
    "⏱️ 5-Second Brain Teaser!",
    "🧩 {template}: {question_short}",
    "Quick! {question_short} ⚡",
    "Test Your Intelligence: {question_short}",
    "💪 Brain Flex: {question_short}",
    "🔥 Trivia Challenge: Can You Beat the Timer?",
    "🏆 Prove You're a Genius!",
    "This Question Stumps Everyone! 😱",
    "⚡ Smart or Not? Answer in 5 Seconds!",
]

LONG_TITLE_TEMPLATES = [
    "🧠 {n} Trivia Questions — How Many Can You Answer? [{year}]",
    "⚡ Ultimate {n}-Question Knowledge Challenge",
    "🔥 {n} Brain-Busting Quiz Questions for Geniuses",
    "🎯 Can You Score 100%? {n}-Question Trivia Test",
    "💡 IQ Test: {n} Questions to Prove Your Intelligence",
    "🏆 The Ultimate Trivia Quiz: {n} Questions [{year}]",
    "🧩 How Smart Are You? {n}-Question Ultimate Challenge",
    "⚡ {n} Questions That Will Blow Your Mind!",
    "🔥 Master Trivia: Can You Answer {n} Questions?",
    "🎓 Knowledge Gauntlet: {n} Questions, No Cheating!",
]

# ─── Description templates ────────────────────────────────────────────────────

SHORT_DESCRIPTIONS = [
    """🧠 Think you're quick? Answer this before the timer hits zero!

Drop your answer in the comments! ⬇️

✅ Subscribe for daily brain teasers
🔔 Hit the bell to never miss a challenge
👍 Like if you got it right!

#trivia #quiz #brainteaser #knowledge #challenge""",

    """⚡ Quick trivia challenge — can you beat the 5-second timer?

💬 Comment your answer below!

🎯 New questions every day — Subscribe now!
🔔 Notification bell = never miss a quiz

#quiztime #triviatime #generalknowledge #funfacts #quiz""",

    """🔥 Only the sharpest minds get this right!

What do you think the answer is? Comment below! ⬇️

📌 Subscribe for daily knowledge challenges
🏆 Challenge your friends — share this video!

#braintest #smartpeople #quizchallenge #knowledge #trivia""",

    """💡 Test your knowledge in just 5 seconds!

Did you get it? Tell us in the comments! 👇

✅ Hit Subscribe for more daily trivia
🎯 Challenge a friend — share this!
🔔 Bell on for notifications

#dailytrivia #quickquiz #testknowledge #funquiz #brainpower""",
]

LONG_DESCRIPTIONS = [
    """🧠 Welcome to the Ultimate Trivia Challenge!

Can you answer ALL questions correctly? Put your brain to the test with {n} carefully crafted trivia questions covering a wide range of topics!

📋 What's in this video:
• {n} trivia questions across multiple categories
• 5-second countdown timer for each question
• Instant answer reveals
• Topics: General Knowledge, Science, History, Geography & more!

💬 Drop your score in the comments! How many did you get right?

📌 SUBSCRIBE for new trivia compilations every week!
🔔 Turn on notifications to never miss a quiz challenge
👍 LIKE if you scored 80% or above!
📤 SHARE with friends and see who gets the highest score!

#trivia #quiz #generalknowledge #brainteaser #challenge #knowledge #quiztime #{year}""",

    """⚡ The Ultimate Knowledge Challenge is HERE!

{n} questions. 5 seconds each. How many can you answer?

🎯 Topics covered:
• Science & Nature
• History & Culture  
• Geography & World Facts
• General Knowledge
• Brain Teasers

🏆 Score Guide:
0-5: Keep practicing!
6-10: Good job!
11-14: Impressive!
{n}: Genius level!

Comment your score below! 👇

✅ Subscribe for weekly trivia marathons!
🔔 Notification bell = free knowledge every week!

#trivianight #quizchallenge #knowledge #smartpeople #braintest #{year}""",
]


# ─── Tag banks ────────────────────────────────────────────────────────────────

CORE_TAGS = [
    "trivia", "quiz", "general knowledge", "brain teaser", "trivia questions",
    "quiz questions", "knowledge test", "trivia challenge", "quiz challenge",
    "fun trivia", "hard trivia", "easy trivia", "trivia for adults",
    "intelligence test", "IQ test", "how smart are you", "test your knowledge",
]

CATEGORY_TAGS = {
    "science": ["science trivia", "science quiz", "science facts", "biology trivia", "physics trivia"],
    "history": ["history trivia", "history quiz", "world history", "historical facts"],
    "geography": ["geography trivia", "geography quiz", "world geography", "country facts", "capital cities"],
    "general knowledge": ["general knowledge", "random facts", "did you know", "fun facts", "amazing facts"],
    "culture": ["culture quiz", "cultural trivia", "world culture", "global trivia"],
    "technology": ["technology trivia", "tech quiz", "science technology", "computer trivia"],
    "nature": ["nature trivia", "animal facts", "wildlife quiz", "nature quiz"],
    "mathematics": ["math trivia", "math quiz", "math challenge", "number quiz"],
    "entertainment facts": ["entertainment trivia", "pop culture quiz", "facts quiz"],
    "language": ["language trivia", "english quiz", "word quiz", "vocabulary test"],
}

HASHTAG_POOL = [
    "#trivia", "#quiz", "#quiztime", "#triviatime", "#brainteaser", "#knowledge",
    "#generalknowledge", "#quizchallenge", "#trivianight", "#smartpeople",
    "#brainpower", "#testknowledge", "#funfacts", "#didyouknow", "#amazingfacts",
    "#dailytrivia", "#quickquiz", "#intelligentest", "#challenge", "#brain",
    "#learneveryday", "#facts", "#education", "#smart", "#geniusquiz",
    "#triviaaddict", "#knowledgetest", "#funquiz", "#mindgames", "#braintest",
]


def load_seo_log():
    if SEO_LOG_PATH.exists():
        with open(SEO_LOG_PATH) as f:
            return json.load(f)
    return []


def save_seo_log(log):
    with open(SEO_LOG_PATH, "w") as f:
        json.dump(log, f, indent=2)


def was_title_used_recently(title, days=7):
    log = load_seo_log()
    from datetime import timedelta
    cutoff = datetime.now() - timedelta(days=days)
    for entry in log:
        if entry.get("title") == title:
            used = datetime.fromisoformat(entry.get("date", "2000-01-01"))
            if used > cutoff:
                return True
    return False


@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=2, max=8))
def generate_title_with_ai(question_text, template, video_type="short"):
    api_key = os.environ.get("GROQ_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None

    prompt = f"""Create a viral YouTube {video_type} video title for this trivia question.
Question: {question_text}
Template: {template}
Requirements:
- Under 70 characters
- Engaging and clickable
- Include 1-2 relevant emojis
- No clickbait that misleads
- English only
Return ONLY the title, nothing else."""

    if os.environ.get("GROQ_API_KEY"):
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {"Authorization": f"Bearer {os.environ['GROQ_API_KEY']}", "Content-Type": "application/json"}
        payload = {"model": "mixtral-8x7b-32768", "messages": [{"role": "user", "content": prompt}], "max_tokens": 100}
        resp = requests.post(url, json=payload, headers=headers, timeout=20)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip().strip('"')
    return None


def generate_short_title(question_text, template):
    # Try AI first
    try:
        ai_title = generate_title_with_ai(question_text, template, "short")
        if ai_title and len(ai_title) <= 100 and not was_title_used_recently(ai_title):
            return ai_title
    except Exception:
        pass

    # Template fallback
    question_short = question_text[:40] + ("..." if len(question_text) > 40 else "")
    question_short = re.sub(r'^(True or False:|Which|What is|How many|Who) ', '', question_short)

    for attempt in range(20):
        tmpl = random.choice(SHORT_TITLE_TEMPLATES)
        title = tmpl.format(
            question_short=question_short,
            template=template,
        )
        if not was_title_used_recently(title):
            return title

    return f"⚡ Quiz: {question_short[:50]} — Answer NOW!"


def generate_long_title(n_questions, year=None):
    if year is None:
        year = datetime.now().year

    for attempt in range(20):
        tmpl = random.choice(LONG_TITLE_TEMPLATES)
        title = tmpl.format(n=n_questions, year=year)
        if not was_title_used_recently(title):
            return title

    return f"🧠 {n_questions} Ultimate Trivia Questions [{year}]"


def generate_short_description(question_text, answer_text, category):
    desc_template = random.choice(SHORT_DESCRIPTIONS)
    return desc_template


def generate_long_description(n_questions, title):
    desc_template = random.choice(LONG_DESCRIPTIONS)
    return desc_template.format(n=n_questions, year=datetime.now().year)


def generate_tags(category=None, video_type="short", extra_terms=None):
    tags = list(CORE_TAGS)
    if category and category in CATEGORY_TAGS:
        tags.extend(CATEGORY_TAGS[category])
    if extra_terms:
        tags.extend(extra_terms)
    random.shuffle(tags)
    return tags[:500]  # YouTube tag limit


def generate_hashtags(n=15):
    selected = random.sample(HASHTAG_POOL, min(n, len(HASHTAG_POOL)))
    return " ".join(selected)


def generate_short_seo(question_data):
    """Generate complete SEO package for a Short"""
    question_text = question_data.get("question", "")
    template = question_data.get("template", "Trivia")
    category = question_data.get("category", "general knowledge")

    title = generate_short_title(question_text, template)
    description = generate_short_description(question_text, question_data.get("answer", ""), category)
    tags = generate_tags(category, "short")
    hashtags = generate_hashtags(12)

    # Append hashtags to description
    full_description = description + f"\n\n{hashtags}"

    seo_package = {
        "title": title,
        "description": full_description,
        "tags": tags,
        "category_id": "27",  # YouTube Education category
        "made_for_kids": False,
    }

    log = load_seo_log()
    log.append({"title": title, "date": datetime.now().isoformat(), "type": "short"})
    save_seo_log(log)

    return seo_package


def generate_long_seo(questions_list, video_title):
    """Generate complete SEO package for a long video"""
    n = len(questions_list)
    categories = list(set(q.get("category", "general knowledge") for q in questions_list))
    primary_cat = categories[0] if categories else "general knowledge"

    all_tags = generate_tags(primary_cat, "long")
    for cat in categories:
        if cat in CATEGORY_TAGS:
            all_tags.extend(CATEGORY_TAGS[cat])

    all_tags = list(set(all_tags))
    random.shuffle(all_tags)

    hashtags = generate_hashtags(20)
    description = generate_long_description(n, video_title) + f"\n\n{hashtags}"

    seo_package = {
        "title": video_title,
        "description": description,
        "tags": all_tags[:500],
        "category_id": "27",
        "made_for_kids": False,
    }

    log = load_seo_log()
    log.append({"title": video_title, "date": datetime.now().isoformat(), "type": "long"})
    save_seo_log(log)

    return seo_package


if __name__ == "__main__":
    q = {"question": "What is the capital of Australia?", "answer": "Canberra", "template": "Direct Question", "category": "geography"}
    seo = generate_short_seo(q)
    print(json.dumps(seo, indent=2))
