from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from ytquiz.config import Config
from ytquiz.log import Log
from ytquiz.optimizer.bandit import CategoricalBandit
from ytquiz.state import StateDB
from ytquiz.utils import UTC, clamp, now_utc, weighted_choice


DEFAULT_SHORT_TOPICS = [
    "capitals",
    "continents",
    "currencies",
    "elements",
    "science",
    "math",
    "truefalse",
]


@dataclass
class ShortPlan:
    template_id: int
    topic_id: str
    voice_gender: str
    music_mode: str
    cd_bucket: int | None
    scheduled_at: datetime
    publish_immediately: bool
    slot_id: str


@dataclass
class LongPlan:
    voice_gender: str
    music_mode: str
    scheduled_at: datetime
    slot_id: str


@dataclass
class DayPlans:
    shorts: list[ShortPlan]
    long: LongPlan | None


class Planner:
    def __init__(self, *, cfg: Config, state: StateDB, log: Log) -> None:
        self.cfg = cfg
        self.state = state
        self.log = log

    def plan_day(self, day: datetime) -> DayPlans:
        rng = random.Random()
        rng.seed(int(day.timestamp()) ^ 0xC0FFEE)

        scored = self.state.list_scored_videos(days=180)
        template_bandit = CategoricalBandit([str(i) for i in range(1, self.cfg.templates_count + 1)])
        topic_bandit = CategoricalBandit(DEFAULT_SHORT_TOPICS)
        slot_bandit = CategoricalBandit([f"S{i}" for i in range(len(self.cfg.short_time_windows))])
        voice_bandit = CategoricalBandit(["female", "male"])
        music_bandit = CategoricalBandit(["on", "off"])

        for r in scored:
            score = r["score"]
            if score is None:
                continue
            reward = float(clamp(float(score), 0.0, 1.0))
            template_bandit.update(str(r["template_id"]), reward)
            topic_bandit.update(str(r["topic_id"]), reward)
            voice_bandit.update(str(r["voice_gender"]), reward)
            music_bandit.update(str(r["music_mode"]), reward)
            features = r["features_json"]
            try:
                feat = features and __import__("json").loads(features)
            except Exception:
                feat = {}
            slot_id = str(feat.get("slot_id") or "")
            if slot_id:
                slot_bandit.update(slot_id, reward)

        now = now_utc()
        publish_first_immediately = self.state.video_count() == 0

        voice_mode = self._pick_voice_mode(now)

        voice_schedule: list[str] | None = None
        if str(voice_mode.get("mode")) == "ab":
            half = max(1, self.cfg.shorts_per_day // 2)
            voice_schedule = ["female"] * half + ["male"] * (self.cfg.shorts_per_day - half)
            rng.shuffle(voice_schedule)

        windows = list(self.cfg.short_time_windows)
        rng.shuffle(windows)
        picked_windows = windows[: self.cfg.shorts_per_day]
        if len(picked_windows) < self.cfg.shorts_per_day:
            while len(picked_windows) < self.cfg.shorts_per_day:
                picked_windows.append(rng.choice(self.cfg.short_time_windows))

        short_plans: list[ShortPlan] = []
        used_topics: set[str] = set()
        used_templates: set[int] = set()

        top_patterns = self._top_patterns(now, limit=6)

        for i in range(self.cfg.shorts_per_day):
            scheduled = picked_windows[i].pick_datetime(day, rng)
            scheduled = self._ensure_future(scheduled, now, mins_ahead=15)
            scheduled = scheduled + timedelta(seconds=rng.randint(0, int(self.cfg.jitter_seconds)))

            slot_id = f"S{self.cfg.short_time_windows.index(picked_windows[i])}"

            use_pattern = (rng.random() < 0.60) and bool(top_patterns)
            plan_from_pattern: dict[str, Any] | None = None
            if use_pattern:
                keys = [p["key"] for p in top_patterns]
                weights = [p["w"] for p in top_patterns]
                chosen = weighted_choice(rng, keys, weights)
                plan_from_pattern = next((p for p in top_patterns if p["key"] == chosen), None)

            if plan_from_pattern:
                template_id = int(plan_from_pattern.get("template_id") or rng.randint(1, self.cfg.templates_count))
                topic_id = str(plan_from_pattern.get("topic_id") or rng.choice(DEFAULT_SHORT_TOPICS))
                cd_bucket = int(plan_from_pattern.get("cd_bucket") or 0) or None
                voice_gender = str(plan_from_pattern.get("voice_gender") or "female")
                music_mode = str(plan_from_pattern.get("music_mode") or "on")
            else:
                template_id = int(template_bandit.best(rng))
                topic_id = str(topic_bandit.best(rng))
                cd_bucket = None
                voice_gender = self._pick_voice_for_plan(rng, voice_mode, preferred=str(voice_bandit.best(rng)))
                music_mode = self._pick_music_mode(rng, preferred=str(music_bandit.best(rng)))

            if template_id in used_templates and len(used_templates) < min(self.cfg.templates_count, self.cfg.shorts_per_day):
                alt = self._pick_distinct_template(template_bandit, rng, used_templates)
                template_id = alt
            used_templates.add(template_id)

            if topic_id in used_topics and len(used_topics) < min(len(DEFAULT_SHORT_TOPICS), self.cfg.shorts_per_day):
                topic_id = self._pick_distinct_topic(topic_bandit, rng, used_topics)
            used_topics.add(topic_id)

            if voice_schedule:
                voice_gender = voice_schedule[i]

            publish_immediately = publish_first_immediately and i == 0
            short_plans.append(
                ShortPlan(
                    template_id=template_id,
                    topic_id=topic_id,
                    voice_gender=voice_gender,
                    music_mode=music_mode,
                    cd_bucket=cd_bucket,
                    scheduled_at=scheduled,
                    publish_immediately=publish_immediately,
                    slot_id=slot_id,
                )
            )

        short_plans.sort(key=lambda p: p.scheduled_at)

        long_plan = None
        if self.cfg.long_enabled and now.weekday() in self.cfg.long_days:
            scheduled = self.cfg.long_time_window.pick_datetime(day, rng)
            scheduled = self._ensure_future(scheduled, now, mins_ahead=30)
            scheduled = scheduled + timedelta(seconds=rng.randint(0, int(self.cfg.jitter_seconds)))
            voice_gender = self._pick_voice_for_plan(rng, voice_mode, preferred=str(voice_bandit.best(rng)))
            music_mode = self._pick_music_mode(rng, preferred=str(music_bandit.best(rng)))
            long_plan = LongPlan(voice_gender=voice_gender, music_mode=music_mode, scheduled_at=scheduled, slot_id="L0")

        return DayPlans(shorts=short_plans, long=long_plan)

    def _ensure_future(self, dt: datetime, now: datetime, mins_ahead: int) -> datetime:
        min_dt = now + timedelta(minutes=mins_ahead)
        if dt <= min_dt:
            return min_dt
        return dt

    def _pick_distinct_template(self, bandit: CategoricalBandit, rng: random.Random, used: set[int]) -> int:
        candidates = [i for i in range(1, self.cfg.templates_count + 1) if i not in used]
        if not candidates:
            return int(bandit.best(rng))
        samples = []
        for c in candidates:
            samples.append((bandit.mean(str(c)), c))
        samples.sort(reverse=True)
        top = [c for _, c in samples[: min(3, len(samples))]]
        return rng.choice(top)

    def _pick_distinct_topic(self, bandit: CategoricalBandit, rng: random.Random, used: set[str]) -> str:
        candidates = [t for t in DEFAULT_SHORT_TOPICS if t not in used]
        if not candidates:
            return str(bandit.best(rng))
        scored = [(bandit.mean(t), t) for t in candidates]
        scored.sort(reverse=True)
        top = [t for _, t in scored[: min(3, len(scored))]]
        return rng.choice(top)

    def _pick_voice_mode(self, now: datetime) -> dict[str, Any]:
        start = self.state.get_kv("voice_ab_start_date")
        if not start:
            self.state.set_kv("voice_ab_start_date", now.date().isoformat())
            return {"mode": "ab", "winner": "", "winner_score": 0.0}

        try:
            start_date = datetime.fromisoformat(str(start)).date()
        except Exception:
            start_date = now.date()

        days = (now.date() - start_date).days
        if days < self.cfg.voice_ab_days:
            return {"mode": "ab", "winner": "", "winner_score": 0.0}

        scored = self.state.list_scored_videos(days=60)
        sums = {"female": 0.0, "male": 0.0}
        cnts = {"female": 0, "male": 0}
        for r in scored:
            g = str(r["voice_gender"] or "")
            s = r["score"]
            if g not in sums or s is None:
                continue
            sums[g] += float(s)
            cnts[g] += 1

        if cnts["female"] < 5 and cnts["male"] < 5:
            return {"mode": "winner", "winner": "female", "explore": self.cfg.voice_explore_pct}

        female_avg = sums["female"] / max(1, cnts["female"])
        male_avg = sums["male"] / max(1, cnts["male"])
        winner = "female" if female_avg >= male_avg else "male"
        return {"mode": "winner", "winner": winner, "explore": self.cfg.voice_explore_pct}

    def _pick_voice_for_plan(self, rng: random.Random, voice_mode: dict[str, Any], preferred: str) -> str:
        mode = str(voice_mode.get("mode") or "")
        if mode == "ab":
            return "female" if rng.random() < 0.5 else "male"
        winner = str(voice_mode.get("winner") or "female")
        explore = float(voice_mode.get("explore") or 0.10)
        if rng.random() < explore:
            return "male" if winner == "female" else "female"
        if preferred in {"female", "male"} and rng.random() < 0.10:
            return preferred
        return winner

    def _pick_music_mode(self, rng: random.Random, preferred: str) -> str:
        if rng.random() < self.cfg.music_test_pct:
            return "off"
        if preferred in {"on", "off"} and rng.random() < 0.10:
            return preferred
        return "on"

    def _top_patterns(self, now: datetime, limit: int = 6) -> list[dict[str, Any]]:
        scored = self.state.list_scored_videos(days=45)
        if not scored:
            return []

        buckets: dict[str, dict[str, Any]] = {}
        for r in scored:
            s = r["score"]
            if s is None:
                continue
            template_id = int(r["template_id"])
            topic_id = str(r["topic_id"])
            voice = str(r["voice_gender"])
            music = str(r["music_mode"])
            try:
                feat = __import__("json").loads(r["features_json"] or "{}")
            except Exception:
                feat = {}
            cd_bucket = int(feat.get("cd_bucket") or 0)
            key = f"{template_id}|{topic_id}|{voice}|{music}|{cd_bucket}"
            b = buckets.get(key)
            if not b:
                buckets[key] = {
                    "key": key,
                    "template_id": template_id,
                    "topic_id": topic_id,
                    "voice_gender": voice,
                    "music_mode": music,
                    "cd_bucket": cd_bucket if cd_bucket != 0 else None,
                    "sum": float(s),
                    "n": 1,
                }
            else:
                b["sum"] += float(s)
                b["n"] += 1

        scored_patterns: list[dict[str, Any]] = []
        for b in buckets.values():
            if b["n"] < 3:
                continue
            avg = b["sum"] / max(1, b["n"])
            w = float(clamp(avg, 0.0, 1.0)) * (1.0 + min(0.6, math.log(1 + b["n"]) / 6.0))
            scored_patterns.append(
                {
                    "key": b["key"],
                    "template_id": b["template_id"],
                    "topic_id": b["topic_id"],
                    "voice_gender": b["voice_gender"],
                    "music_mode": b["music_mode"],
                    "cd_bucket": b["cd_bucket"],
                    "w": w,
                    "avg": avg,
                    "n": b["n"],
                }
            )

        scored_patterns.sort(key=lambda x: x["w"], reverse=True)
        return scored_patterns[:limit]
