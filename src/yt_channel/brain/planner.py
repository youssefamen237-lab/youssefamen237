from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from ..config.settings import Settings
from ..state.db import StateDB
from .bandit import BetaBandit


@dataclass(frozen=True)
class PlannedVideo:
    kind: str  # "short" or "long"
    publish_at: Optional[str]  # ISO-8601 UTC string or None for immediate
    privacy_status: str  # "public" or "private"/scheduled
    template_id: str
    topic: str
    countdown_seconds: int
    answer_seconds: float
    voice_gender: str
    with_music: bool
    slot: str


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _weekday_utc(dt: datetime) -> str:
    return dt.strftime("%a").upper()[:3]


def _add_jitter(rng: random.Random, dt: datetime, max_minutes: int) -> datetime:
    if max_minutes <= 0:
        return dt
    jitter = rng.randint(-max_minutes, max_minutes)
    return dt + timedelta(minutes=jitter, seconds=rng.randint(0, 59))


def _parse_time_slot(slot: str) -> tuple[int, int]:
    hh, mm = slot.strip().split(":")
    return int(hh), int(mm)


class Planner:
    TEMPLATES = ["classic", "mcq", "true_false", "two_step", "zoom_reveal"]

    def __init__(self, *, settings: Settings, db: StateDB, bandit: BetaBandit, rng: random.Random) -> None:
        self.settings = settings
        self.db = db
        self.bandit = bandit
        self.rng = rng

    def _total_shorts(self) -> int:
        cur = self.db.conn.execute("SELECT COUNT(1) AS c FROM videos WHERE kind='short'")
        row = cur.fetchone()
        return int(row["c"] if row else 0)

    def _select_templates(self) -> List[str]:
        total = self._total_shorts()
        if total < 20:
            start = total % len(self.TEMPLATES)
            seq = []
            for i in range(self.settings.shorts_per_day):
                seq.append(self.TEMPLATES[(start + i) % len(self.TEMPLATES)])
            return seq

        # Thompson sampling — pick top N templates each day.
        scored = []
        for t in self.TEMPLATES:
            s = self.bandit.sample_arm(arm_type="template", arm_value=t)
            scored.append((s.sample, t))
        scored.sort(reverse=True)
        top = [t for _, t in scored[: self.settings.shorts_per_day]]

        # Exploration to avoid fingerprinting
        if self.rng.random() < 0.2:
            start = total % len(self.TEMPLATES)
            rot = []
            for i in range(self.settings.shorts_per_day):
                rot.append(self.TEMPLATES[(start + i) % len(self.TEMPLATES)])
            return rot

        # Ensure no duplicates in one day
        uniq = []
        for t in top:
            if t not in uniq:
                uniq.append(t)
        while len(uniq) < self.settings.shorts_per_day:
            # Fill from rotation
            for t in self.TEMPLATES:
                if t not in uniq:
                    uniq.append(t)
                if len(uniq) >= self.settings.shorts_per_day:
                    break
        return uniq[: self.settings.shorts_per_day]

    def _voice_plan_for_day(self) -> List[str]:
        total = self._total_shorts()
        # First 28 shorts = A/B test week (2F, 2M per day).
        if total < 28:
            plan = ["female", "male", "female", "male"]
            self.rng.shuffle(plan)
            return plan[: self.settings.shorts_per_day]

        # After week: choose winner with bandit (90% exploit, 10% explore)
        winner = self.bandit.choose(arm_type="voice", choices=["female", "male"])
        other = "male" if winner == "female" else "female"
        plan = []
        for _ in range(self.settings.shorts_per_day):
            if self.rng.random() < 0.1:
                plan.append(other)
            else:
                plan.append(winner)
        return plan

    def _music_plan_for_day(self, templates: List[str]) -> List[bool]:
        plan: List[bool] = []
        for t in templates:
            if t == "zoom_reveal":
                plan.append(False)
                continue
            # First runs: mostly on, some off.
            if self._total_shorts() < 20:
                plan.append(self.rng.random() < 0.75)
                continue
            choice = self.bandit.choose(arm_type="music", choices=["music_on", "music_off"])
            if self.rng.random() < 0.1:
                choice = "music_off" if choice == "music_on" else "music_on"
            plan.append(choice == "music_on")
        return plan

    def _publish_times_for_today(self) -> List[datetime]:
        now = _utc_now()
        times: List[datetime] = []
        for slot in self.settings.shorts_time_slots_utc[: self.settings.shorts_per_day]:
            hh, mm = _parse_time_slot(slot)
            dt = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            # Ensure not in the past (for manual runs). Push forward if too close.
            if dt < now + timedelta(minutes=20):
                dt = now + timedelta(minutes=35 + len(times) * 90)
            dt = _add_jitter(self.rng, dt, self.settings.jitter_minutes)
            times.append(dt)

        # Ensure strictly increasing times (spacing)
        times_sorted: List[datetime] = []
        last = None
        for t in sorted(times):
            if last and t <= last + timedelta(minutes=35):
                t = last + timedelta(minutes=35)
            times_sorted.append(t)
            last = t
        return times_sorted

    def plan_daily(self) -> List[PlannedVideo]:
        if not self.settings.run_enabled:
            return []

        templates = self._select_templates()
        voices = self._voice_plan_for_day()
        musics = self._music_plan_for_day(templates)
        times = self._publish_times_for_today()

        first_run = self._total_shorts() == 0

        plans: List[PlannedVideo] = []
        for i in range(self.settings.shorts_per_day):
            template_id = templates[i]
            voice = voices[i]
            with_music = musics[i]
            publish_dt = times[i]
            slot_label = publish_dt.strftime("%H:%M")

            privacy = "private"
            publish_at = _iso(publish_dt)

            if first_run and i == 0:
                # First run: publish one real short immediately.
                privacy = "public"
                publish_at = None
                slot_label = "NOW"

            # Topic mapping per template
            if template_id == "classic":
                topic = self.bandit.choose(arm_type="topic", choices=["capital", "flag", "currency", "planets", "math"])
            elif template_id == "mcq":
                topic = "mcq_capitals"
            elif template_id == "true_false":
                topic = "true_false"
            elif template_id == "two_step":
                topic = "two_step"
            elif template_id == "zoom_reveal":
                topic = "capital"
            else:
                topic = "capital"

            plans.append(
                PlannedVideo(
                    kind="short",
                    publish_at=publish_at,
                    privacy_status=privacy,
                    template_id=template_id,
                    topic=topic,
                    countdown_seconds=self.settings.short_countdown_seconds,
                    answer_seconds=self.settings.short_answer_seconds,
                    voice_gender=voice,
                    with_music=with_music,
                    slot=slot_label,
                )
            )

        # Long video plan for today
        now = _utc_now()
        today_code = _weekday_utc(now)
        if today_code in self.settings.long_days_utc:
            hh, mm = _parse_time_slot(self.settings.long_time_slot_utc)
            dt = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if dt < now + timedelta(minutes=30):
                dt = now + timedelta(minutes=60)
            dt = _add_jitter(self.rng, dt, max(3, self.settings.jitter_minutes // 2))
            plans.append(
                PlannedVideo(
                    kind="long",
                    publish_at=_iso(dt),
                    privacy_status="private",
                    template_id="long_episode",
                    topic="episode_mix",
                    countdown_seconds=self.settings.long_countdown_seconds,
                    answer_seconds=self.settings.long_answer_seconds,
                    voice_gender=self.bandit.choose(arm_type="voice", choices=["female", "male"]),
                    with_music=True,
                    slot=dt.strftime("%H:%M"),
                )
            )

        # Hard cap safety
        return plans[: self.settings.daily_hard_cap_uploads]
