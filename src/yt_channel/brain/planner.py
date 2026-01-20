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
        """Count uploaded shorts (video_id present).

        Use uploaded count (not merely planned rows) so a failed run doesn't
        disable first-run behavior or A/B scheduling.
        """
        cur = self.db.conn.execute(
            "SELECT COUNT(1) AS c FROM videos WHERE kind='short' AND video_id IS NOT NULL AND video_id<>''"
        )
        row = cur.fetchone()
        return int(row["c"] if row else 0)

    def _total_longs(self) -> int:
        """Count uploaded longs (video_id present)."""
        cur = self.db.conn.execute(
            "SELECT COUNT(1) AS c FROM videos WHERE kind='long' AND video_id IS NOT NULL AND video_id<>''"
        )
        row = cur.fetchone()
        return int(row["c"] if row else 0)


    def _uploaded_longs_in_last_days(self, days_back: int) -> int:
        since = _utc_now() - timedelta(days=int(days_back))
        cur = self.db.conn.execute(
            "SELECT COUNT(1) AS c FROM videos "
            "WHERE kind='long' AND video_id IS NOT NULL AND video_id<>'' AND created_at >= ?",
            (_iso(since),),
        )
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


    def _choose_short_slots_for_today(self) -> List[str]:
        slots = [str(s).strip() for s in (self.settings.shorts_time_slots_utc or []) if str(s).strip()]
        if not slots:
            slots = ["09:15", "13:15", "17:15", "21:15"]

        # Thompson sampling — pick best N time slots.
        if len(slots) <= self.settings.shorts_per_day:
            chosen = list(slots)
        else:
            scored = []
            for s in slots:
                a = self.bandit.sample_arm(arm_type="short_time_slot", arm_value=s)
                scored.append((a.sample, s))
            scored.sort(reverse=True)
            chosen = [s for _, s in scored[: self.settings.shorts_per_day]]

            # Exploration to avoid fingerprinting (20%): rotate a contiguous window.
            if self.rng.random() < 0.2:
                start = (self._total_shorts() * self.settings.shorts_per_day) % len(slots)
                rot = []
                for i in range(self.settings.shorts_per_day):
                    rot.append(slots[(start + i) % len(slots)])
                chosen = rot

        # Ensure unique + stable chronological order
        seen = set()
        uniq = []
        for s in chosen:
            if s not in seen:
                uniq.append(s)
                seen.add(s)

        # Fill if needed
        if len(uniq) < self.settings.shorts_per_day:
            for s in slots:
                if s not in seen:
                    uniq.append(s)
                    seen.add(s)
                if len(uniq) >= self.settings.shorts_per_day:
                    break

        uniq.sort(key=lambda x: _parse_time_slot(x))
        return uniq[: self.settings.shorts_per_day]

    def _publish_times_for_today(self, slot_keys: List[str]) -> List[datetime]:
        now = _utc_now()
        times: List[datetime] = []
        for i, slot in enumerate(slot_keys):
            hh, mm = _parse_time_slot(slot)
            dt = now.replace(hour=hh, minute=mm, second=0, microsecond=0)

            # Ensure not in the past (manual runs) and keep minimum lead time for scheduling.
            if dt < now + timedelta(minutes=20):
                dt = now + timedelta(minutes=35 + i * 90)

            dt = _add_jitter(self.rng, dt, self.settings.jitter_minutes)

            # Ensure strictly increasing times (spacing)
            if times:
                min_dt = times[-1] + timedelta(minutes=35)
                if dt < min_dt:
                    dt = min_dt

            # Never schedule in the immediate past due to jitter
            if dt < now + timedelta(minutes=10):
                dt = now + timedelta(minutes=35 + i * 90)

            times.append(dt)

        return times



    def _choose_long_slot_for_today(self) -> str:
        slots = []
        try:
            slots = [str(s).strip() for s in (self.settings.long_time_slots_utc or []) if str(s).strip()]
        except Exception:
            slots = []
        if not slots:
            slots = [str(getattr(self.settings, "long_time_slot_utc", "19:30")).strip() or "19:30"]

        # Thompson sampling — pick best long slot
        scored = []
        for s in slots:
            a = self.bandit.sample_arm(arm_type="long_time_slot", arm_value=s)
            scored.append((a.sample, s))
        scored.sort(reverse=True)
        best = scored[0][1] if scored else slots[0]

        # Small exploration
        if len(slots) > 1 and self.rng.random() < 0.15:
            others = [s for s in slots if s != best]
            if others:
                return self.rng.choice(others)
        return best


    def plan_daily(self) -> List[PlannedVideo]:
        if not self.settings.run_enabled:
            return []

        templates = self._select_templates()
        voices = self._voice_plan_for_day()
        musics = self._music_plan_for_day(templates)
        slot_keys = self._choose_short_slots_for_today()
        times = self._publish_times_for_today(slot_keys)

        first_run = self._total_shorts() == 0

        plans: List[PlannedVideo] = []
        for i in range(self.settings.shorts_per_day):
            template_id = templates[i]
            voice = voices[i]
            with_music = musics[i]
            publish_dt = times[i]
            slot_label = slot_keys[i]

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

        # Long video plan for today (3/week) + first-run bootstrap
        now = _utc_now()
        today_code = _weekday_utc(now)
        first_long = self._total_longs() == 0

        if first_long:
            # Bootstrap: publish one long immediately so you can verify the pipeline.
            plans.append(
                PlannedVideo(
                    kind="long",
                    publish_at=None,
                    privacy_status="public",
                    template_id="long_episode",
                    topic="episode_mix",
                    countdown_seconds=self.settings.long_countdown_seconds,
                    answer_seconds=self.settings.long_answer_seconds,
                    voice_gender=self.bandit.choose(arm_type="voice", choices=["female", "male"]),
                    with_music=True,
                    slot="NOW",
                )
            )
        elif today_code in self.settings.long_days_utc and self._uploaded_longs_in_last_days(7) < self.settings.longs_per_week:
            slot_key = self._choose_long_slot_for_today()
            hh, mm = _parse_time_slot(slot_key)
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
                    slot=slot_key,
                )
            )

# Hard cap safety
        return plans[: self.settings.daily_hard_cap_uploads]
