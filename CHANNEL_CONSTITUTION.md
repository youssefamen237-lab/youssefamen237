# Channel Constitution

This document is the supreme governing reference for the channel. Every
automated system, every AI model, and every human contributor reads this
before making any decision. Rules marked **[LOCKED]** correspond to
`growth_rules.is_locked = TRUE` in the database — `channel_os` cannot
change them under any circumstances; only a manual database edit by the
Founder can.

---

## 1. Mission

> Produce short, fact-driven nature and science videos that create genuine
> curiosity in a global audience, build a durable digital asset (Topic Bank,
> Fact Bank, Learning Memory, Media Library), and convert audience attention
> into sustainable monthly revenue — without manual intervention.

## 2. Identity

| Property            | Value                                                       |
|----------------------|--------------------------------------------------------------|
| Channel theme        | Nature & Science Facts (Ocean, Animals, Space, Nature, Birds, Insects) |
| Language             | English (global audience)                                   |
| Persona              | Curious Documentary — fast-paced, fact-led, never childish or academic |
| Shorts cadence       | 5 / day, 18–45 seconds, random natural publish times         |
| Long-form cadence    | 1 every ~2 days, 5–8 minutes, built from proven-winner shorts |
| Voice                | ElevenLabs, rotating profiles, female-leaning split           |

## 3. Values

1. **Accuracy** — every fact traces to ≥2 trusted sources before it enters the Fact Bank.
2. **Curiosity over information-dumping** — one strong idea per video, not ten weak ones.
3. **Consistency** — every video shares the same pacing, tone, and structure regardless of topic.
4. **Data over opinion** — `channel_os` adjusts strategy from `learning_memory`, never from assumption.
5. **Diversity by design** — no single category or voice is ever allowed to dominate, even after a viral success.

## 4. Non-Negotiable Rules **[LOCKED]**

These map directly to `is_locked = TRUE` rows in `growth_rules` and to
hard-coded thresholds in the protection/ and engines/ layers:

1. **Quality Gate threshold = 75/100** — a video failing the 5-gate score
   (`engines/quality_gate.py`) is rejected, never published, regardless of
   schedule pressure. *"Quality > Schedule."*
2. **Real-footage ratio ≥ 80%** — AI-generated visuals (`cascade/ai_images`)
   are a fallback only, used when real footage cannot be found.
3. **Multi-source verification** — no fact enters production without passing
   `protection/fact_verifier.py` (confidence ≥ 65, plausibility-checked
   against its cited source(s)).
4. **Visual truth** — `protection/visual_verifier.py` must confirm the
   footage plausibly matches the topic before it is used.
5. **No duplicate content** — `protection/duplicate_guard.py` blocks
   near-identical scripts (90-day window) and titles (60-day window).
6. **Banned subject matter** — `protection/policy_guard.py` permanently
   rejects: politics, religion, celebrities, crime, weapons, medical claims,
   and violence against humans. Categories outside
   {ocean, animals, space, nature, birds, insects} are rejected outright.
7. **Bounded strategic change only** — `channel_os/portfolio_manager.py`
   limits any single COS adjustment to ±2 points (category allocation) or
   ±3 points (voice split) per cycle, with hard floors (3% per category,
   20% per voice) and ceilings (40% per category, 80% per voice). No
   category or voice can ever be eliminated.

## 5. Governance — Who Decides What

| Layer | Authority | Cannot |
|---|---|---|
| `engines/quality_gate.py` | Final publish/reject verdict per video | Override its own 75-point threshold |
| `protection/*` | Hard veto on any single video | Be bypassed by schedule, COS, or buffer pressure |
| `pipelines/batch_runner.py` | How many videos to attempt per run | Force-publish a rejected video |
| `channel_os/growth_manager.py` | *Proposes* category/voice rebalancing from `learning_memory` | Apply changes directly |
| `channel_os/portfolio_manager.py` | Clamps every proposal to safe bounds | Be skipped |
| `channel_os/cos.py` | Applies clamped proposals via `update_rule()`, logs full audit trail | Touch any `is_locked = TRUE` rule |
| **Founder** | Edit any row in `growth_rules` directly, including `is_locked` | — (absolute authority) |

Every COS decision is recorded twice: in `growth_rules`
(`previous_value`, `reason_for_change`, `last_updated_by`) and as a
`channel_dna` entry in `learning_memory` (`latest_cos_decision`).

## 6. Fatal Mistakes — Never Do These

1. Optimize for video **count** instead of **retention**. One Short with
   500,000 views beats fifty Shorts with 500 views each.
2. Let any model pick a topic outside the Topic Bank.
3. Accept a fact from a single source.
4. Use footage that does not match the narration.
5. Generate a long-form video "from scratch" — it must be built from facts
   and angles already proven by successful Shorts.
6. Ignore what the data says in favor of what "feels" interesting.
7. Build any pipeline stage around a single API with no fallback —
   every cascade (LLM, TTS, footage, images, AI images) must degrade
   gracefully.
8. Let the content buffer run to zero. `queue_health_check.yml` exists to
   catch this before it happens.
9. React to one viral video by overhauling the channel's identity.
   `portfolio_manager.py` exists specifically to prevent this.
10. Publish a video because "the schedule says 5 today" when only 3 passed
    quality review. Three is correct. Five is wrong.

## 7. The One Rule

> **Decisions are made by data, not opinions.**

Everything else in this project — every cascade, every engine, every
protection gate, every line of `channel_os` — exists in service of this
single sentence.
