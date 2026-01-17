from __future__ import annotations

import csv
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from .utils.text_utils import sanitize_text, stable_hash, normalize_for_dupe


@dataclass
class QA:
    question: str
    answer: str
    topic: str
    difficulty: str
    source_id: str
    choices: Optional[List[str]] = None
    correct_index: Optional[int] = None


def _read_csv(path: Path) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    with open(path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append({(k or '').strip(): (v or '').strip() for k, v in row.items()})
    return rows


class QuestionBank:
    """Data-driven question bank.

    - Questions/answers are derived from local datasets only.
    - No LLM-invented answers.
    """

    def __init__(self, data_dir: Path | str):
        self.data_dir = Path(data_dir)
        self._cache: Dict[str, List[Dict[str, str]]] = {}

    def _load(self, filename: str) -> List[Dict[str, str]]:
        if filename in self._cache:
            return self._cache[filename]
        path = self.data_dir / filename
        if not path.exists():
            self._cache[filename] = []
            return []
        rows = _read_csv(path)
        self._cache[filename] = rows
        return rows

    def _mcq(self, correct: str, distractors: Sequence[str], k: int = 3) -> Tuple[List[str], int]:
        correct_n = sanitize_text(correct)
        pool = list({sanitize_text(x) for x in distractors if sanitize_text(x) and sanitize_text(x) != correct_n})
        random.shuffle(pool)
        opts = pool[: max(0, k - 1)]
        opts.append(correct_n)
        random.shuffle(opts)
        return opts, opts.index(correct_n)

    # ----- Public API -----

    def fallback_qa(self) -> QA:
        return QA(question='What is 8 + 7?', answer='15', topic='Math', difficulty='Easy', source_id='fallback')

    def random_qa(self, template_id: Optional[str] = None) -> QA:
        """Pick a random QA suitable for the template."""
        if template_id == 'true_false':
            qa = self._gen_true_false() or self._gen_general_trivia() or self.fallback_qa()
        elif template_id == 'multiple_choice':
            qa = self._random_any()
            qa = self.make_multiple_choice(qa, choices_k=3)
        else:
            qa = self._random_any()

        qa.question = sanitize_text(qa.question)
        qa.answer = sanitize_text(qa.answer)
        return qa

    def random_episode_qas(self, count: int = 80) -> List[QA]:
        """Generate a mixed list for long-form episodes."""
        out: List[QA] = []
        seen: set[str] = set()
        attempts = 0
        while len(out) < count and attempts < count * 20:
            attempts += 1
            qa = self._random_any()
            key = stable_hash(normalize_for_dupe(qa.question) + '|' + normalize_for_dupe(qa.answer))
            if key in seen:
                continue
            seen.add(key)
            out.append(qa)
        if not out:
            out.append(self.fallback_qa())
        return out

    def long_title_from_topics(self, topics: List[str]) -> str:
        topics = [sanitize_text(t) for t in topics if sanitize_text(t)]
        if not topics:
            return 'Mixed Trivia Episode'
        # pick up to 2 most common topics
        from collections import Counter
        c = Counter(topics)
        top = [t for t,_ in c.most_common(2)]
        if len(top) == 1:
            return f'{top[0]} Trivia Episode'
        return f'Mixed Trivia: {top[0]} + {top[1]}'

    def long_description(self, title: str) -> str:
        title = sanitize_text(title)
        lines = [
            "Play along and keep score! Answer before the timer ends.",
            "Subscribe for more quiz episodes every week.",
            "",
            "#trivia #quiz #challenge",
        ]
        return "\n".join(lines)

    def long_tags(self) -> List[str]:
        base = ['trivia', 'quiz', 'challenge', 'knowledge', 'fun', 'episode', 'score', 'questions', 'learning']
        random.shuffle(base)
        return base[: random.randint(10, 15)]

    # ----- Generators -----

    def _random_any(self) -> QA:
        generators = [
            self._gen_capital,
            self._gen_currency,
            self._gen_planet_order,
            self._gen_element_symbol,
            self._gen_general_trivia,
            self._gen_true_false,
            self._gen_quick_math,
        ]
        random.shuffle(generators)
        for gen in generators:
            qa = gen()
            if qa is not None:
                return qa
        return self.fallback_qa()

    def _gen_capital(self) -> Optional[QA]:
        rows = self._load('countries_capitals.csv')
        if not rows:
            return None
        row = random.choice(rows)
        country = row.get('country', '').strip()
        capital = row.get('capital', '').strip()
        if not country or not capital:
            return None
        q = f'What is the capital of {country}?'
        a = capital
        return QA(question=q, answer=a, topic='Geography', difficulty='Easy', source_id='countries_capitals')

    def _gen_currency(self) -> Optional[QA]:
        rows = self._load('currencies.csv')
        if not rows:
            return None
        row = random.choice(rows)
        country = row.get('country', '').strip()
        currency = row.get('currency', '').strip()
        if not country or not currency:
            return None
        q = f'What currency is used in {country}?'
        a = currency
        return QA(question=q, answer=a, topic='Geography', difficulty='Easy', source_id='currencies')

    def _gen_planet_order(self) -> Optional[QA]:
        rows = self._load('planets.csv')
        if not rows:
            return None
        row = random.choice(rows)
        planet = row.get('planet', '').strip()
        order = row.get('order_from_sun', '').strip()
        if not planet or not order:
            return None
        q = f'{planet} is which number from the Sun?'
        a = order
        return QA(question=q, answer=a, topic='Space', difficulty='Easy', source_id='planets')

    def _gen_element_symbol(self) -> Optional[QA]:
        rows = self._load('elements.csv')
        if not rows:
            return None
        row = random.choice(rows)
        el = row.get('element', '').strip()
        sym = row.get('symbol', '').strip()
        if not el or not sym:
            return None
        q = f'What is the chemical symbol for {el}?'
        a = sym
        return QA(question=q, answer=a, topic='Science', difficulty='Medium', source_id='elements')

    def _gen_general_trivia(self) -> Optional[QA]:
        rows = self._load('general_trivia.csv')
        if not rows:
            return None
        row = random.choice(rows)
        q = row.get('question', '').strip()
        a = row.get('answer', '').strip()
        topic = row.get('topic', 'Trivia').strip() or 'Trivia'
        diff = row.get('difficulty', 'Easy').strip() or 'Easy'
        if not q or not a:
            return None
        return QA(question=q, answer=a, topic=topic, difficulty=diff, source_id='general_trivia')

    def _gen_true_false(self) -> Optional[QA]:
        rows = self._load('true_false.csv')
        if not rows:
            return None
        row = random.choice(rows)
        statement = row.get('statement', '').strip()
        ans = row.get('answer', '').strip()
        topic = row.get('topic', 'Trivia').strip() or 'Trivia'
        diff = row.get('difficulty', 'Easy').strip() or 'Easy'
        if not statement or ans.lower() not in {'true', 'false'}:
            return None
        q = f'True or False: {statement}'
        a = ans.title()
        return QA(question=q, answer=a, topic=topic, difficulty=diff, source_id='true_false')

    def _gen_quick_math(self) -> Optional[QA]:
        a = random.randint(3, 12)
        b = random.randint(3, 12)
        op = random.choice(['+', '-', 'x'])
        if op == '+':
            q = f'What is {a} + {b}?'
            ans = str(a + b)
        elif op == '-':
            x, y = max(a, b), min(a, b)
            q = f'What is {x} - {y}?'
            ans = str(x - y)
        else:
            q = f'What is {a} x {b}?'
            ans = str(a * b)
        return QA(question=q, answer=ans, topic='Math', difficulty='Easy', source_id='math')

    # ----- Helpers -----

    def make_multiple_choice(self, qa: QA, choices_k: int = 3) -> QA:
        """Attach choices derived from the same dataset when possible."""
        pool: List[str] = []
        if qa.source_id == 'countries_capitals':
            rows = self._load('countries_capitals.csv')
            pool = [r.get('capital', '').strip() for r in rows]
        elif qa.source_id == 'currencies':
            rows = self._load('currencies.csv')
            pool = [r.get('currency', '').strip() for r in rows]
        elif qa.source_id == 'elements':
            rows = self._load('elements.csv')
            pool = [r.get('symbol', '').strip() for r in rows]
        elif qa.source_id == 'planets':
            rows = self._load('planets.csv')
            pool = [r.get('order_from_sun', '').strip() for r in rows]

        if not pool:
            # numeric distractors if possible
            try:
                n = int(sanitize_text(qa.answer))
                pool = [str(n + i) for i in range(-6, 7) if i != 0]
            except Exception:
                pool = ['Option A', 'Option B', 'Option C', 'Option D', 'Option E']

        opts, idx = self._mcq(qa.answer, pool, k=choices_k)
        qa.choices = opts
        qa.correct_index = idx
        return qa
