# YouTube Nature & Science Automation System

A fully autonomous content factory that researches, scripts, voices,
assembles, verifies, and publishes nature/science Shorts and long-form
videos to YouTube — entirely on GitHub Actions, at zero infrastructure
cost. The system learns from its own YouTube Analytics data and adjusts
its own strategy over time via the Channel Operating System (`channel_os/`).

See [`CHANNEL_CONSTITUTION.md`](./CHANNEL_CONSTITUTION.md) for the
non-negotiable rules every component obeys.

---

## Architecture

```
storage/            Supabase, Cloudflare R2, Upstash Redis clients + cleanup
cascade/             Provider fallback chains (circuit breaker + backoff)
  llm/               Gemini -> Groq -> OpenRouter -> Together -> OpenAI
  tts/               ElevenLabs (3 keys) -> edge-tts
  footage/           Pexels -> Pixabay -> Coverr -> Internet Archive -> Vecteezy
  images/            Unsplash -> Pexels Photo -> Pixabay Photo -> Freepik
  ai_images/         GetImg -> Stability -> Dezgo -> AI Horde
engines/             13 production engines (topic, facts, script, voice,
                     media, subtitles, assembly, metadata, thumbnails,
                     quality gate, publisher, ...)
protection/          5 hard gates: duplicates, facts, visuals, copyright, policy
intelligence/        Hook selection, story-flow templates, music selection
youtube/upload/      3-key upload rotation + quota management + scheduling
youtube/management/  Read-only Analytics via isolated Key 4
pipelines/           short_pipeline, longform_pipeline, batch_runner
analytics/           performance_analyzer -> learning_memory
channel_os/          growth_manager, portfolio_manager, cos (the "brain")
data/seeds/          Topic Bank (~500 topics) + Music Library seeders
bootstrap/           One-time idempotent system initialization
.github/workflows/   6 scheduled workflows — the entire autonomous loop
```

---

## The Autonomous Loop

| Workflow | Schedule | Purpose |
|---|---|---|
| `daily_production.yml` | 03:00 UTC daily | Produces Shorts (5/day + buffer top-up, capped at 15) and a long-form video when the buffer is low. Every video passes through all 5 protection gates and the 75/100 quality gate before being marked `approved`. |
| `daily_publishing.yml` | every 4 hours | Uploads approved videos to YouTube via rotating credential sets (1–3), respecting the 5/day Shorts and ~1/2-day long-form cadence. |
| `storage_cleanup.yml` | 03:30 UTC daily | Deletes raw clips from R2 immediately after successful upload to stay within the free tier. |
| `queue_health_check.yml` | every 6 hours | Dead Man's Switch — fails (and emails the repo owner) if the buffer is critically low, the heartbeat is missing, or the 24h failure count is high. |
| `analytics_daily.yml` | 05:00 UTC daily | Pulls per-video YouTube Analytics via the isolated management key, records `performance_metrics`, and aggregates results into `learning_memory`. |
| `cos_weekly_review.yml` | Mondays 06:00 UTC | The Channel Operating System reads `learning_memory` and makes small, bounded adjustments to `category_allocation` / `voice_split` — never touching locked constitutional rules. |

---

## First-Time Setup

1. **Configure every secret below** in *Settings → Secrets and variables →
   Actions*. Exact names matter — all code reads `os.environ[...]`
   verbatim.
2. **Run the `Bootstrap Seed Data` workflow manually** (Actions tab →
   *Bootstrap Seed Data* → *Run workflow*). This populates the Topic Bank
   (~500 topics across all 6 categories) and the Music Library, and marks
   the system as initialized.
3. **That's it.** The six scheduled workflows above take over automatically.
   The first `daily_production.yml` run will begin filling the content
   buffer; the first `daily_publishing.yml` run after that will start
   publishing.

To re-seed (e.g. after wiping the Topic Bank), re-run `Bootstrap Seed Data`
with the `force` input set to `true`.

---

## Required GitHub Secrets

### Storage / Infrastructure
| Secret | Used by |
|---|---|
| `SUPABASE` | All modules (database) |
| `REDIS_CACHE` | Cascades, dedup, OAuth token cache, heartbeat |
| `ACCOUNT_ID_CLOUDFLARE_R2`, `S3_API_CLOUDFLARE_R2`, `CLOUDFLARE_TOKEN`, `CLOUDFLARE_API` | Cloudflare R2 object storage |

### LLM Cascade
| Secret | Provider |
|---|---|
| `GEMINI_API_KEY` | Gemini (primary LLM + Vision verification) |
| `GROQ_API_KEY` | Groq |
| `OPENROUTER_KEY` | OpenRouter |
| `TOGETHER_AI` | Together AI |
| `OPENAI_API_KEY` | OpenAI |

### TTS Cascade
| Secret | Provider |
|---|---|
| `ELEVEN_API_KEY`, `ELEVEN_API_KEY_2`, `ELEVEN_API_KEY_3` | ElevenLabs (3-key rotation) |
| `ELEVENLABS_VOICE_ID_FEMALE`, `ELEVENLABS_VOICE_ID_FEMALE_2_CASSIDY`, `ELEVENLABS_VOICE_ID_FEMALE_3_ALLISON` | Female voice profiles |
| `ELEVENLABS_VOICE_ID_MALE`, `ELEVENLABS_VOICE_ID_MALE_2_MARK`, `ELEVENLABS_VOICE_ID_MALE_3_YOUNG_JAMAL` | Male voice profiles |
| *(none — edge-tts free fallback requires no key)* | edge-tts |

### Footage Cascade
| Secret | Provider |
|---|---|
| `PEXELS_API_KEY` | Pexels Video |
| `PIXABAY_API_KEY` | Pixabay Video |
| `COVERR_API_ID`, `COVERR_API_KEY` | Coverr |
| `INTERNET_ARCHIVE_ACCESS_KEY`, `INTERNET_ARCHIVE_SECRET_KEY` | Internet Archive |
| `VECTEEZY_ID`, `VECTEEZY_SECRET_KEY` | Vecteezy |

### Still Images Cascade
| Secret | Provider |
|---|---|
| `UNSPLASH_ACCESS_KEY` | Unsplash (+ Pexels/Pixabay Photo reuse the video keys above) |
| `FREEPIK_API_KEY` | Freepik |

### AI Image Cascade
| Secret | Provider |
|---|---|
| `GETIMG_API_KEY`, `GETIMG_AI` | GetImg.AI |
| `STABILITY` | Stability AI |
| `DEZGO` | Dezgo |
| `AI_HORDE` | AI Horde |

### Fact Research
| Secret | Provider |
|---|---|
| `TAVILY_API_KEY` | Tavily search |
| `SERPAPI`, `ZENSERP` | SerpAPI fallback |

### Music Library
| Secret | Provider |
|---|---|
| `FREESOUND_API`, `FREESOUND_ID` | Freesound CC0 ambient tracks |

### YouTube — Upload Rotation (Shorts + Long-form publishing)
| Secret | Purpose |
|---|---|
| `YT_CLIENT_ID_1/2/3`, `YT_CLIENT_SECRET_1/2/3`, `YT_REFRESH_TOKEN_1/2/3` | Three independent OAuth credential sets, rotated by remaining daily quota |

### YouTube — Management (Analytics only, isolated)
| Secret | Purpose |
|---|---|
| `YT_CLIENT_ID_4`, `YT_CLIENT_SECRET_4`, `YT_REFRESH_TOKEN_4` | Read-only Analytics API access — never used for uploads |

---

## Database

The full schema (15 tables, RPC functions, views, and seed data) lives at
[`data/schemas/supabase_schema.sql`](./data/schemas/supabase_schema.sql).
Run it once against a new Supabase project before configuring secrets.

Key tables:

- **`topics`** — the Master Topic Bank. `engines/topic_selector.py` is the
  only consumer.
- **`facts`** — the Fact Bank, populated by `engines/fact_research.py` and
  filtered by `protection/fact_verifier.py`.
- **`growth_rules`** — every adjustable (and locked) strategy parameter.
  `channel_os/cos.py` is the only writer.
- **`learning_memory`** — everything the channel has learned about itself.
  `analytics/performance_analyzer.py` is the primary writer;
  `channel_os/growth_manager.py` is the primary reader.
- **`video_queue`** / **`published_log`** / **`performance_metrics`** — the
  full lifecycle of every video from creation to analytics.

---

## Local Development

```bash
pip install -r requirements.txt
python -m bootstrap.initial_setup          # one-time seed
python -m pipelines.short_pipeline         # produce one Short (ad-hoc)
python -m youtube.management.analytics_puller
python -m analytics.performance_analyzer
python -m channel_os.cos
```

All credentials are read from environment variables matching the exact
GitHub Secret names above — export them locally (e.g. via a `.env` file
loaded with `python-dotenv`, already in `requirements.txt`) before running
any module standalone.
