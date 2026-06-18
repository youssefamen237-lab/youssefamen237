-- ============================================================
-- YouTube Automation System — Complete Database Schema
-- Platform: Supabase (PostgreSQL 15+)
-- Run this entire file in: Supabase Dashboard → SQL Editor
-- ============================================================

-- ── Extensions ────────────────────────────────────────────────
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ── Utility: auto-update updated_at on every write ────────────
CREATE OR REPLACE FUNCTION trigger_set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ============================================================
-- TABLE 1: TOPICS  (Master Topic Bank)
-- ============================================================
CREATE TABLE IF NOT EXISTS topics (
    topic_id             UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    topic_name           VARCHAR(255) NOT NULL,
    category             VARCHAR(50)  NOT NULL,
    subcategory          VARCHAR(100),

    -- Scoring dimensions (0–100)
    curiosity_score      SMALLINT     NOT NULL DEFAULT 50,
    visual_availability  SMALLINT     NOT NULL DEFAULT 50,
    evergreen_score      SMALLINT     NOT NULL DEFAULT 50,
    competition_score    SMALLINT     NOT NULL DEFAULT 50,
    revenue_score        SMALLINT     NOT NULL DEFAULT 50,

    -- Lifecycle
    status               VARCHAR(30)  NOT NULL DEFAULT 'new',
    parent_topic_id      UUID         REFERENCES topics(topic_id) ON DELETE SET NULL,

    -- Production counters
    fact_count           INTEGER      NOT NULL DEFAULT 0,
    shorts_created       INTEGER      NOT NULL DEFAULT 0,
    long_videos_created  INTEGER      NOT NULL DEFAULT 0,

    -- Performance (updated by analytics engine)
    avg_retention        DECIMAL(5,2) NOT NULL DEFAULT 0.0,
    avg_ctr              DECIMAL(5,2) NOT NULL DEFAULT 0.0,
    total_views          BIGINT       NOT NULL DEFAULT 0,

    -- Scheduling / cooldown
    last_published_at    TIMESTAMPTZ,
    cooldown_days        INTEGER      NOT NULL DEFAULT 30,

    -- Media search helpers
    visual_keywords      TEXT[]       NOT NULL DEFAULT ARRAY[]::TEXT[],

    -- Structured emotional profile for this topic
    -- Example: {"danger":90,"intelligence":40,"size":80,"mystery":60,"speed":20}
    topic_dna            JSONB        NOT NULL DEFAULT '{}'::JSONB,

    created_at           TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_topic_name            UNIQUE (topic_name),
    CONSTRAINT chk_topics_category      CHECK (category IN ('ocean','animals','space','nature','birds','insects')),
    CONSTRAINT chk_topics_status        CHECK (status IN ('new','testing','winner','evergreen','retired','archived')),
    CONSTRAINT chk_curiosity_score      CHECK (curiosity_score     BETWEEN 0 AND 100),
    CONSTRAINT chk_visual_availability  CHECK (visual_availability BETWEEN 0 AND 100),
    CONSTRAINT chk_evergreen_score      CHECK (evergreen_score     BETWEEN 0 AND 100),
    CONSTRAINT chk_competition_score    CHECK (competition_score   BETWEEN 0 AND 100),
    CONSTRAINT chk_revenue_score        CHECK (revenue_score       BETWEEN 0 AND 100)
);

CREATE TRIGGER trg_topics_updated_at
    BEFORE UPDATE ON topics
    FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();

CREATE INDEX IF NOT EXISTS idx_topics_category        ON topics(category);
CREATE INDEX IF NOT EXISTS idx_topics_status          ON topics(status);
CREATE INDEX IF NOT EXISTS idx_topics_last_published  ON topics(last_published_at);
CREATE INDEX IF NOT EXISTS idx_topics_production_ready
    ON topics(status, visual_availability, last_published_at, cooldown_days);

-- ============================================================
-- TABLE 2: FACTS  (Fact Bank)
-- ============================================================
CREATE TABLE IF NOT EXISTS facts (
    fact_id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    topic_id         UUID        NOT NULL REFERENCES topics(topic_id) ON DELETE CASCADE,
    fact_text        TEXT        NOT NULL,
    fact_type        VARCHAR(50),

    -- Scoring
    curiosity_level  SMALLINT    NOT NULL DEFAULT 50,
    visual_potential SMALLINT    NOT NULL DEFAULT 50,
    evergreen_score  SMALLINT    NOT NULL DEFAULT 100,
    viral_potential  SMALLINT    NOT NULL DEFAULT 50,
    confidence_score SMALLINT    NOT NULL DEFAULT 80,

    -- Source verification
    source_ids       UUID[]      NOT NULL DEFAULT ARRAY[]::UUID[],
    source_count     SMALLINT    NOT NULL DEFAULT 0,
    is_verified      BOOLEAN     NOT NULL DEFAULT FALSE,
    is_gold          BOOLEAN     NOT NULL DEFAULT FALSE,

    -- Lifecycle
    status           VARCHAR(20) NOT NULL DEFAULT 'new',
    usage_count      INTEGER     NOT NULL DEFAULT 0,

    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_facts_type CHECK (
        fact_type IS NULL OR fact_type IN (
            'size','speed','intelligence','danger','hunting',
            'survival','family','communication','mystery',
            'record','comparison','biology','behavior','habitat'
        )
    ),
    CONSTRAINT chk_facts_status     CHECK (status IN ('new','verified','used','gold','retired')),
    CONSTRAINT chk_facts_curiosity  CHECK (curiosity_level  BETWEEN 0 AND 100),
    CONSTRAINT chk_facts_visual     CHECK (visual_potential BETWEEN 0 AND 100),
    CONSTRAINT chk_facts_confidence CHECK (confidence_score BETWEEN 0 AND 100)
);

CREATE TRIGGER trg_facts_updated_at
    BEFORE UPDATE ON facts
    FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();

CREATE INDEX IF NOT EXISTS idx_facts_topic_id ON facts(topic_id);
CREATE INDEX IF NOT EXISTS idx_facts_status   ON facts(status);
CREATE INDEX IF NOT EXISTS idx_facts_verified ON facts(is_verified);
CREATE INDEX IF NOT EXISTS idx_facts_gold     ON facts(is_gold);
CREATE INDEX IF NOT EXISTS idx_facts_ready
    ON facts(topic_id, is_verified, status, curiosity_level DESC);

-- ============================================================
-- TABLE 3: SOURCES  (Source Registry)
-- ============================================================
CREATE TABLE IF NOT EXISTS sources (
    source_id                UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    source_name              VARCHAR(255) NOT NULL,
    base_url                 VARCHAR(500) NOT NULL,
    trust_score              SMALLINT     NOT NULL DEFAULT 85,
    tier                     SMALLINT     NOT NULL,
    specializations          TEXT[]       NOT NULL DEFAULT ARRAY[]::TEXT[],

    -- Usage tracking
    fact_count               INTEGER      NOT NULL DEFAULT 0,
    successful_verifications INTEGER      NOT NULL DEFAULT 0,
    failed_verifications     INTEGER      NOT NULL DEFAULT 0,

    is_active                BOOLEAN      NOT NULL DEFAULT TRUE,
    last_used_at             TIMESTAMPTZ,
    notes                    TEXT,

    created_at               TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at               TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_source_name   UNIQUE (source_name),
    CONSTRAINT chk_sources_tier  CHECK (tier BETWEEN 1 AND 4),
    CONSTRAINT chk_sources_trust CHECK (trust_score BETWEEN 0 AND 100)
);

CREATE TRIGGER trg_sources_updated_at
    BEFORE UPDATE ON sources
    FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();

-- ============================================================
-- TABLE 4: HOOKS  (Hook Library)
-- ============================================================
CREATE TABLE IF NOT EXISTS hooks (
    hook_id         UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    hook_text       TEXT        NOT NULL,
    hook_type       VARCHAR(50) NOT NULL,
    template_slots  TEXT[]      NOT NULL DEFAULT ARRAY[]::TEXT[],

    -- Performance
    avg_ctr         DECIMAL(5,2) NOT NULL DEFAULT 0.0,
    avg_retention   DECIMAL(5,2) NOT NULL DEFAULT 0.0,
    usage_count     INTEGER      NOT NULL DEFAULT 0,

    is_gold         BOOLEAN     NOT NULL DEFAULT FALSE,
    is_banned       BOOLEAN     NOT NULL DEFAULT FALSE,
    best_categories TEXT[]      NOT NULL DEFAULT ARRAY[]::TEXT[],

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_hooks_type CHECK (
        hook_type IN (
            'danger','size','speed','mystery','intelligence',
            'survival','comparison','impossible','weirdness',
            'record','behavior','discovery'
        )
    )
);

CREATE TRIGGER trg_hooks_updated_at
    BEFORE UPDATE ON hooks
    FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();

CREATE INDEX IF NOT EXISTS idx_hooks_type   ON hooks(hook_type);
CREATE INDEX IF NOT EXISTS idx_hooks_active ON hooks(is_banned, is_gold);

-- ============================================================
-- TABLE 5: TITLES  (Title Pattern Library)
-- ============================================================
CREATE TABLE IF NOT EXISTS titles (
    title_id        UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    title_pattern   TEXT        NOT NULL,
    title_type      VARCHAR(50) NOT NULL,
    template_slots  TEXT[]      NOT NULL DEFAULT ARRAY[]::TEXT[],

    avg_ctr         DECIMAL(5,2) NOT NULL DEFAULT 0.0,
    usage_count     INTEGER      NOT NULL DEFAULT 0,

    is_gold         BOOLEAN     NOT NULL DEFAULT FALSE,
    is_banned       BOOLEAN     NOT NULL DEFAULT FALSE,
    last_used_at    TIMESTAMPTZ,
    best_categories TEXT[]      NOT NULL DEFAULT ARRAY[]::TEXT[],

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_titles_type CHECK (
        title_type IN (
            'curiosity','mystery','comparison','scale',
            'danger','intelligence','question','revelation',
            'impossibility','record'
        )
    )
);

CREATE INDEX IF NOT EXISTS idx_titles_type ON titles(title_type);

-- ============================================================
-- TABLE 6: CTAS  (Call-to-Action Library)
-- ============================================================
CREATE TABLE IF NOT EXISTS ctas (
    cta_id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    cta_text                TEXT        NOT NULL,
    cta_type                VARCHAR(50) NOT NULL,

    avg_retention_impact    DECIMAL(5,2) NOT NULL DEFAULT 0.0,
    usage_count             INTEGER      NOT NULL DEFAULT 0,
    is_banned               BOOLEAN      NOT NULL DEFAULT FALSE,

    created_at              TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_ctas_type CHECK (
        cta_type IN (
            'question','challenge','next_video',
            'subscribe','poll','curiosity','fact_reveal'
        )
    )
);

-- ============================================================
-- TABLE 7: MUSIC_TRACKS
-- ============================================================
CREATE TABLE IF NOT EXISTS music_tracks (
    track_id         UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    track_name       VARCHAR(255) NOT NULL,
    r2_path          VARCHAR(500),
    source_url       VARCHAR(500),

    category         VARCHAR(50)  NOT NULL,
    mood             VARCHAR(50)  NOT NULL,
    bpm              SMALLINT,
    duration_seconds INTEGER,
    license_type     VARCHAR(100),
    freesound_id     VARCHAR(100),

    is_downloaded    BOOLEAN      NOT NULL DEFAULT FALSE,
    is_active        BOOLEAN      NOT NULL DEFAULT TRUE,

    created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_music_category CHECK (
        category IN (
            'ocean','animals','space','nature','birds',
            'insects','predators','mystery','adventure','general'
        )
    ),
    CONSTRAINT chk_music_mood CHECK (
        mood IN ('calm','mysterious','tense','epic','documentary','wonder','uplifting','dark')
    )
);

CREATE INDEX IF NOT EXISTS idx_music_category ON music_tracks(category);
CREATE INDEX IF NOT EXISTS idx_music_active   ON music_tracks(is_active, is_downloaded);

-- ============================================================
-- TABLE 8: COMPETITORS
-- ============================================================
CREATE TABLE IF NOT EXISTS competitors (
    competitor_id       UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    channel_name        VARCHAR(255) NOT NULL,
    channel_url         VARCHAR(500),
    youtube_channel_id  VARCHAR(100),

    subscriber_count    BIGINT       NOT NULL DEFAULT 0,
    avg_views_per_video BIGINT       NOT NULL DEFAULT 0,
    category            VARCHAR(50),
    content_style       VARCHAR(100),
    posting_frequency   VARCHAR(50),

    -- JSON arrays/objects for flexible analytics storage
    top_videos          JSONB        NOT NULL DEFAULT '[]'::JSONB,
    top_hooks           TEXT[]       NOT NULL DEFAULT ARRAY[]::TEXT[],
    top_topics          TEXT[]       NOT NULL DEFAULT ARRAY[]::TEXT[],

    last_analyzed_at    TIMESTAMPTZ,
    is_active           BOOLEAN      NOT NULL DEFAULT TRUE,

    created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_competitor_name UNIQUE (channel_name)
);

CREATE TRIGGER trg_competitors_updated_at
    BEFORE UPDATE ON competitors
    FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();

-- ============================================================
-- TABLE 9: VIDEO_QUEUE  (Production & Publishing Queue)
-- ============================================================
CREATE TABLE IF NOT EXISTS video_queue (
    queue_id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    topic_id              UUID        NOT NULL REFERENCES topics(topic_id),
    video_type            VARCHAR(20) NOT NULL,

    -- Production status
    status                VARCHAR(30) NOT NULL DEFAULT 'pending',
    priority              SMALLINT    NOT NULL DEFAULT 5,

    -- Script payload
    -- Structure: {hook, segments:[{sentence, search_query, visual_type, fact_id}], cta, full_text}
    script                JSONB,

    -- Voice selection
    voice_gender          VARCHAR(10),
    voice_id              VARCHAR(100),

    -- R2 storage paths
    audio_r2_path         VARCHAR(500),
    video_r2_path         VARCHAR(500),
    thumbnail_r2_path     VARCHAR(500),
    subtitle_r2_path      VARCHAR(500),
    final_video_r2_path   VARCHAR(500),

    -- YouTube metadata
    title                 VARCHAR(255),
    description           TEXT,
    hashtags              TEXT[]      NOT NULL DEFAULT ARRAY[]::TEXT[],
    playlist_id           VARCHAR(100),

    -- YouTube publish result
    youtube_video_id      VARCHAR(50),
    upload_key_used       SMALLINT,

    -- Quality gate results
    quality_score         SMALLINT,
    gate_scores           JSONB,       -- {gate1:18, gate2:20, gate3:17, gate4:19, gate5:9}
    rejection_reason      TEXT,

    -- Scheduling
    publish_at            TIMESTAMPTZ,
    published_at          TIMESTAMPTZ,

    -- Error handling
    retry_count           SMALLINT    NOT NULL DEFAULT 0,
    error_log             JSONB       NOT NULL DEFAULT '[]'::JSONB,

    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_queue_video_type   CHECK (video_type IN ('short','long')),
    CONSTRAINT chk_queue_voice_gender CHECK (voice_gender IS NULL OR voice_gender IN ('male','female')),
    CONSTRAINT chk_queue_status       CHECK (
        status IN (
            'pending','researching','scripting','voicing',
            'fetching_media','assembling','quality_check',
            'approved','scheduled','published','rejected','failed'
        )
    ),
    CONSTRAINT chk_queue_priority   CHECK (priority BETWEEN 1 AND 10),
    CONSTRAINT chk_queue_upload_key CHECK (upload_key_used IS NULL OR upload_key_used IN (1,2,3))
);

CREATE TRIGGER trg_queue_updated_at
    BEFORE UPDATE ON video_queue
    FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();

CREATE INDEX IF NOT EXISTS idx_queue_status     ON video_queue(status);
CREATE INDEX IF NOT EXISTS idx_queue_type       ON video_queue(video_type);
CREATE INDEX IF NOT EXISTS idx_queue_topic      ON video_queue(topic_id);
CREATE INDEX IF NOT EXISTS idx_queue_publish_at ON video_queue(publish_at);
CREATE INDEX IF NOT EXISTS idx_queue_approved   ON video_queue(status, video_type, priority DESC)
    WHERE status = 'approved';

-- ============================================================
-- TABLE 10: PUBLISHED_LOG  (Immutable record of every upload)
-- ============================================================
CREATE TABLE IF NOT EXISTS published_log (
    log_id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    queue_id         UUID        REFERENCES video_queue(queue_id),
    topic_id         UUID        REFERENCES topics(topic_id),
    youtube_video_id VARCHAR(50) NOT NULL,

    video_type       VARCHAR(20),
    title            VARCHAR(255),
    category         VARCHAR(50),
    voice_gender     VARCHAR(10),
    voice_id         VARCHAR(100),
    duration_seconds INTEGER,
    quality_score    SMALLINT,

    hook_id          UUID REFERENCES hooks(hook_id),
    title_pattern_id UUID REFERENCES titles(title_id),
    cta_id           UUID REFERENCES ctas(cta_id),
    music_track_id   UUID REFERENCES music_tracks(track_id),

    published_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    upload_key_used  SMALLINT,
    publish_window   VARCHAR(50),

    CONSTRAINT uq_published_yt_id UNIQUE (youtube_video_id)
);

CREATE INDEX IF NOT EXISTS idx_published_yt_id   ON published_log(youtube_video_id);
CREATE INDEX IF NOT EXISTS idx_published_at      ON published_log(published_at DESC);
CREATE INDEX IF NOT EXISTS idx_published_category ON published_log(category);

-- ============================================================
-- TABLE 11: PERFORMANCE_METRICS  (YouTube Analytics)
-- ============================================================
CREATE TABLE IF NOT EXISTS performance_metrics (
    metric_id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    youtube_video_id           VARCHAR(50) NOT NULL REFERENCES published_log(youtube_video_id),
    recorded_at                TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    views                      BIGINT      NOT NULL DEFAULT 0,
    unique_views               BIGINT      NOT NULL DEFAULT 0,
    watch_time_minutes         DECIMAL(14,2) NOT NULL DEFAULT 0,
    avg_view_duration_seconds  INTEGER     NOT NULL DEFAULT 0,
    retention_percentage       DECIMAL(5,2) NOT NULL DEFAULT 0,
    ctr                        DECIMAL(5,2) NOT NULL DEFAULT 0,

    likes                      INTEGER     NOT NULL DEFAULT 0,
    comments                   INTEGER     NOT NULL DEFAULT 0,
    shares                     INTEGER     NOT NULL DEFAULT 0,
    subscribers_gained         INTEGER     NOT NULL DEFAULT 0,

    estimated_revenue_usd      DECIMAL(12,4) NOT NULL DEFAULT 0,
    rpm                        DECIMAL(10,4) NOT NULL DEFAULT 0,
    cpm                        DECIMAL(10,4) NOT NULL DEFAULT 0,

    impressions                BIGINT      NOT NULL DEFAULT 0,
    card_clicks                INTEGER     NOT NULL DEFAULT 0,
    end_screen_clicks          INTEGER     NOT NULL DEFAULT 0,

    traffic_source             JSONB       NOT NULL DEFAULT '{}'::JSONB
);

CREATE INDEX IF NOT EXISTS idx_metrics_yt_id    ON performance_metrics(youtube_video_id);
CREATE INDEX IF NOT EXISTS idx_metrics_recorded ON performance_metrics(recorded_at DESC);

-- ============================================================
-- TABLE 12: LEARNING_MEMORY  (Channel DNA & Pattern Storage)
-- ============================================================
CREATE TABLE IF NOT EXISTS learning_memory (
    memory_id    UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    memory_type  VARCHAR(60)  NOT NULL,
    memory_key   VARCHAR(255) NOT NULL,
    memory_value JSONB        NOT NULL,

    confidence   DECIMAL(5,2) NOT NULL DEFAULT 50.0,
    data_points  INTEGER      NOT NULL DEFAULT 1,
    impact_score DECIMAL(5,2) NOT NULL DEFAULT 0.0,
    is_active    BOOLEAN      NOT NULL DEFAULT TRUE,

    created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_memory_key UNIQUE (memory_type, memory_key),
    CONSTRAINT chk_memory_type CHECK (
        memory_type IN (
            'winner_pattern','failure_pattern','topic_insight',
            'voice_insight','hook_insight','title_insight',
            'timing_insight','category_insight','cta_insight',
            'thumbnail_insight','music_insight','length_insight',
            'retention_benchmark','channel_dna'
        )
    )
);

CREATE TRIGGER trg_memory_updated_at
    BEFORE UPDATE ON learning_memory
    FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();

CREATE INDEX IF NOT EXISTS idx_memory_type   ON learning_memory(memory_type);
CREATE INDEX IF NOT EXISTS idx_memory_active ON learning_memory(is_active);

-- ============================================================
-- TABLE 13: GROWTH_RULES  (Dynamic Strategy — owned by COS)
-- ============================================================
CREATE TABLE IF NOT EXISTS growth_rules (
    rule_id           UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    rule_name         VARCHAR(255) NOT NULL,
    rule_category     VARCHAR(60)  NOT NULL,

    current_value     JSONB        NOT NULL,
    previous_value    JSONB,
    reason_for_change TEXT,

    confidence        DECIMAL(5,2) NOT NULL DEFAULT 50.0,
    last_updated_by   VARCHAR(50)  NOT NULL DEFAULT 'cos',
    is_locked         BOOLEAN      NOT NULL DEFAULT FALSE,

    created_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_rule_name    UNIQUE (rule_name),
    CONSTRAINT chk_rules_category CHECK (
        rule_category IN (
            'category_allocation','voice_split','publish_timing',
            'content_length','quality_threshold','topic_priority',
            'hook_preference','cta_preference','music_preference',
            'buffer_targets','cooldown_policy'
        )
    )
);

CREATE TRIGGER trg_rules_updated_at
    BEFORE UPDATE ON growth_rules
    FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();

-- ============================================================
-- TABLE 14: VISUAL_ASSETS  (Verified Clip & Image Registry)
-- ============================================================
CREATE TABLE IF NOT EXISTS visual_assets (
    asset_id          UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    file_hash         VARCHAR(64)  NOT NULL,

    source_provider   VARCHAR(50)  NOT NULL,
    source_id         VARCHAR(255),
    r2_path           VARCHAR(500),

    asset_type        VARCHAR(20)  NOT NULL,
    topic_tags        TEXT[]       NOT NULL DEFAULT ARRAY[]::TEXT[],
    search_query_used VARCHAR(500),
    visual_match_score SMALLINT,

    width             INTEGER,
    height            INTEGER,
    duration_seconds  DECIMAL(8,2),
    file_size_bytes   BIGINT,

    is_ai_generated   BOOLEAN      NOT NULL DEFAULT FALSE,
    license_type      VARCHAR(100),
    has_watermark     BOOLEAN      NOT NULL DEFAULT FALSE,

    usage_count       INTEGER      NOT NULL DEFAULT 0,
    last_used_at      TIMESTAMPTZ,
    is_gold           BOOLEAN      NOT NULL DEFAULT FALSE,

    created_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_file_hash        UNIQUE (file_hash),
    CONSTRAINT chk_assets_type     CHECK (asset_type IN ('video','image')),
    CONSTRAINT chk_assets_provider CHECK (
        source_provider IN (
            'pexels','pixabay','unsplash','coverr','internet_archive',
            'vecteezy','freepik','ai_getimg','ai_stability','ai_dezgo',
            'ai_deep_ai','ai_leonardo','ai_replicate','ai_together',
            'ai_runway','ai_pika','ai_minimax','ai_models_lab'
        )
    )
);

CREATE INDEX IF NOT EXISTS idx_assets_topic_tags ON visual_assets USING GIN(topic_tags);
CREATE INDEX IF NOT EXISTS idx_assets_provider   ON visual_assets(source_provider);
CREATE INDEX IF NOT EXISTS idx_assets_type       ON visual_assets(asset_type);
CREATE INDEX IF NOT EXISTS idx_assets_gold       ON visual_assets(is_gold);

-- ============================================================
-- TABLE 15: CHANNEL_CONFIG  (Global System Settings)
-- ============================================================
CREATE TABLE IF NOT EXISTS channel_config (
    config_id    UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    config_key   VARCHAR(255) NOT NULL,
    config_value JSONB        NOT NULL,
    description  TEXT,
    is_locked    BOOLEAN      NOT NULL DEFAULT FALSE,
    updated_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_config_key UNIQUE (config_key)
);

-- ============================================================
-- VIEWS
-- ============================================================

-- Executive War Room Dashboard (single-row snapshot)
CREATE OR REPLACE VIEW channel_war_room AS
SELECT
    -- Content buffer
    (SELECT COUNT(*) FROM video_queue WHERE status = 'approved' AND video_type = 'short')::INT AS shorts_ready,
    (SELECT COUNT(*) FROM video_queue WHERE status = 'approved' AND video_type = 'long')::INT  AS longs_ready,
    (SELECT COUNT(*) FROM video_queue
     WHERE status IN ('pending','researching','scripting','voicing','fetching_media','assembling','quality_check')
    )::INT AS in_production,
    (SELECT COUNT(*) FROM video_queue
     WHERE status = 'failed' AND updated_at > NOW() - INTERVAL '24 hours'
    )::INT AS failed_last_24h,
    (SELECT COUNT(*) FROM video_queue
     WHERE status = 'rejected' AND updated_at > NOW() - INTERVAL '24 hours'
    )::INT AS rejected_last_24h,

    -- Publishing stats
    (SELECT COUNT(*) FROM published_log WHERE published_at > NOW() - INTERVAL '24 hours')::INT AS published_today,
    (SELECT COUNT(*) FROM published_log WHERE published_at > NOW() - INTERVAL '7 days')::INT  AS published_last_7d,
    (SELECT COUNT(*) FROM published_log)::INT AS total_published,

    -- Topic bank health
    (SELECT COUNT(*) FROM topics WHERE status = 'new')::INT                              AS topics_new,
    (SELECT COUNT(*) FROM topics WHERE status IN ('new','testing'))::INT                  AS topics_available,
    (SELECT COUNT(*) FROM facts  WHERE is_verified = TRUE AND status IN ('new','verified'))::INT AS facts_ready,

    -- Performance: last 7 days
    COALESCE((
        SELECT SUM(pm.views)
        FROM performance_metrics pm
        JOIN published_log pl ON pm.youtube_video_id = pl.youtube_video_id
        WHERE pl.published_at > NOW() - INTERVAL '7 days'
    ), 0)::BIGINT AS views_last_7d,

    COALESCE((
        SELECT AVG(pm.retention_percentage)::DECIMAL(5,2)
        FROM performance_metrics pm
        JOIN published_log pl ON pm.youtube_video_id = pl.youtube_video_id
        WHERE pl.published_at > NOW() - INTERVAL '7 days'
    ), 0) AS avg_retention_7d,

    COALESCE((
        SELECT AVG(pm.ctr)::DECIMAL(5,2)
        FROM performance_metrics pm
        JOIN published_log pl ON pm.youtube_video_id = pl.youtube_video_id
        WHERE pl.published_at > NOW() - INTERVAL '7 days'
    ), 0) AS avg_ctr_7d,

    -- Revenue: last 30 days
    COALESCE((
        SELECT SUM(pm.estimated_revenue_usd)
        FROM performance_metrics pm
        JOIN published_log pl ON pm.youtube_video_id = pl.youtube_video_id
        WHERE pl.published_at > NOW() - INTERVAL '30 days'
    ), 0)::DECIMAL(12,4) AS revenue_last_30d,

    -- Best/worst category by retention (last 30 days)
    (
        SELECT pl.category
        FROM performance_metrics pm
        JOIN published_log pl ON pm.youtube_video_id = pl.youtube_video_id
        WHERE pl.published_at > NOW() - INTERVAL '30 days' AND pl.category IS NOT NULL
        GROUP BY pl.category
        ORDER BY AVG(pm.retention_percentage) DESC
        LIMIT 1
    ) AS best_category,

    (
        SELECT pl.category
        FROM performance_metrics pm
        JOIN published_log pl ON pm.youtube_video_id = pl.youtube_video_id
        WHERE pl.published_at > NOW() - INTERVAL '30 days' AND pl.category IS NOT NULL
        GROUP BY pl.category
        ORDER BY AVG(pm.retention_percentage) ASC
        LIMIT 1
    ) AS worst_category,

    NOW() AS snapshot_at;


-- Topics ready for immediate production
CREATE OR REPLACE VIEW topics_ready_for_production AS
SELECT
    t.*,
    (t.curiosity_score + t.visual_availability + t.evergreen_score
     + t.revenue_score - t.competition_score) AS computed_value
FROM topics t
WHERE
    t.status IN ('new','testing','winner','evergreen')
    AND (
        t.last_published_at IS NULL
        OR t.last_published_at < NOW() - (t.cooldown_days || ' days')::INTERVAL
    )
    AND t.visual_availability >= 40
ORDER BY
    (t.curiosity_score + t.visual_availability + t.evergreen_score
     + t.revenue_score - t.competition_score) DESC,
    t.curiosity_score DESC;


-- Category performance summary (last 30 days)
CREATE OR REPLACE VIEW category_performance_summary AS
SELECT
    pl.category,
    COUNT(DISTINCT pm.youtube_video_id)::INT          AS video_count,
    COALESCE(AVG(pm.views), 0)::BIGINT                AS avg_views,
    COALESCE(AVG(pm.retention_percentage), 0)::DECIMAL(5,2) AS avg_retention,
    COALESCE(AVG(pm.ctr), 0)::DECIMAL(5,2)            AS avg_ctr,
    COALESCE(SUM(pm.estimated_revenue_usd), 0)::DECIMAL(12,4) AS total_revenue,
    COALESCE(AVG(pm.estimated_revenue_usd), 0)::DECIMAL(10,4) AS avg_revenue_per_video
FROM published_log pl
LEFT JOIN performance_metrics pm ON pl.youtube_video_id = pm.youtube_video_id
WHERE pl.published_at > NOW() - INTERVAL '30 days'
  AND pl.category IS NOT NULL
GROUP BY pl.category
ORDER BY avg_retention DESC;


-- ============================================================
-- FUNCTIONS
-- ============================================================

-- Returns the highest-value topic ready for production
CREATE OR REPLACE FUNCTION get_next_topic(
    p_category    VARCHAR  DEFAULT NULL,
    p_exclude_ids UUID[]   DEFAULT ARRAY[]::UUID[]
)
RETURNS TABLE (
    topic_id          UUID,
    topic_name        VARCHAR,
    category          VARCHAR,
    subcategory       VARCHAR,
    computed_value    INTEGER,
    visual_keywords   TEXT[],
    topic_dna         JSONB
)
LANGUAGE SQL STABLE AS $$
    SELECT
        t.topic_id,
        t.topic_name,
        t.category,
        t.subcategory,
        (t.curiosity_score + t.visual_availability + t.evergreen_score
         + t.revenue_score - t.competition_score)::INTEGER AS computed_value,
        t.visual_keywords,
        t.topic_dna
    FROM topics t
    WHERE
        t.status IN ('new','testing','winner','evergreen')
        AND (p_category IS NULL OR t.category = p_category)
        AND (
            t.last_published_at IS NULL
            OR t.last_published_at < NOW() - (t.cooldown_days || ' days')::INTERVAL
        )
        AND t.visual_availability >= 40
        AND NOT (t.topic_id = ANY(p_exclude_ids))
    ORDER BY
        (t.curiosity_score + t.visual_availability + t.evergreen_score
         + t.revenue_score - t.competition_score) DESC,
        t.curiosity_score DESC
    LIMIT 1;
$$;


-- Returns queue health as a JSON object (used by Dead Man's Switch)
CREATE OR REPLACE FUNCTION get_queue_health()
RETURNS JSONB
LANGUAGE SQL STABLE AS $$
    SELECT jsonb_build_object(
        'shorts_ready',   (SELECT COUNT(*) FROM video_queue WHERE status = 'approved' AND video_type = 'short'),
        'longs_ready',    (SELECT COUNT(*) FROM video_queue WHERE status = 'approved' AND video_type = 'long'),
        'in_production',  (SELECT COUNT(*) FROM video_queue WHERE status NOT IN ('approved','published','rejected','failed')),
        'failed_24h',     (SELECT COUNT(*) FROM video_queue WHERE status = 'failed' AND updated_at > NOW() - INTERVAL '24 hours'),
        'total_published',(SELECT COUNT(*) FROM published_log),
        'snapshot_at',    NOW()
    );
$$;


-- ============================================================
-- SEED DATA: Sources (Tier 1 & 2 only — immutable)
-- ============================================================
INSERT INTO sources (source_name, base_url, trust_score, tier, specializations, notes) VALUES
    ('NASA',
     'https://www.nasa.gov', 100, 1,
     ARRAY['space','astronomy','physics','solar_system'],
     'Official US space agency. Highest authority for space content. Use nasa.gov/topics for structured data.'),
    ('NOAA',
     'https://www.noaa.gov', 100, 1,
     ARRAY['ocean','weather','climate','marine_life','deep_sea'],
     'National Oceanic and Atmospheric Administration. Primary authority for ocean facts and marine science.'),
    ('National Geographic',
     'https://www.nationalgeographic.com', 97, 1,
     ARRAY['animals','ocean','space','nature','birds','insects','geography'],
     'Premium editorial science content. Excellent for curiosity-driven facts and stunning visuals.'),
    ('Smithsonian Institution',
     'https://www.si.edu', 96, 1,
     ARRAY['animals','nature','science','paleontology','biology'],
     'Smithsonian Institution. One of the most reliable scientific references globally.'),
    ('Britannica',
     'https://www.britannica.com', 94, 2,
     ARRAY['animals','ocean','space','nature','birds','insects','general'],
     'Encyclopedia Britannica. Strong all-round science reference. Cross-verify numerical claims.'),
    ('Wikipedia',
     'https://www.wikipedia.org', 83, 2,
     ARRAY['general','animals','ocean','space','nature','birds','insects'],
     'Use as starting reference and to discover primary sources. Never sole source for any fact.'),
    ('BBC Earth',
     'https://www.bbcearth.com', 92, 2,
     ARRAY['animals','nature','ocean','birds','insects','behavior'],
     'BBC natural history editorial. High-quality, well-researched. Excellent for behavioral facts.'),
    ('Live Science',
     'https://www.livescience.com', 79, 3,
     ARRAY['science','animals','space','nature','health'],
     'Tier 3: use only for secondary confirmation. Never as sole source.')
ON CONFLICT (source_name) DO NOTHING;


-- ============================================================
-- SEED DATA: Growth Rules (Initial Strategy — from Constitution)
-- ============================================================
INSERT INTO growth_rules (rule_name, rule_category, current_value, reason_for_change, last_updated_by, is_locked) VALUES
    ('category_allocation', 'category_allocation',
     '{"ocean":30,"animals":25,"space":20,"nature":15,"birds":7,"insects":3}'::JSONB,
     'Initial allocation from channel constitution. Ocean leads for visual richness.', 'constitution', FALSE),

    ('voice_split', 'voice_split',
     '{"female":70,"male":30}'::JSONB,
     'Female voice shows higher retention in similar nature channels. Reviewed by COS monthly.', 'constitution', FALSE),

    ('voice_consecutive_limit', 'voice_split',
     '{"max_same_gender_consecutive":7,"max_same_voice_id_consecutive":3}'::JSONB,
     'Prevents audio monotony. Forces rotation before limits are hit.', 'constitution', FALSE),

    ('publish_timing_shorts', 'publish_timing',
     '{"slots_utc":["09:00","12:30","15:45","18:15","21:00"],"variance_minutes":23,"primary_timezone":"US/Eastern"}'::JSONB,
     'Targeting US prime-time viewing hours. Variance prevents robotic publishing pattern.', 'constitution', FALSE),

    ('publish_timing_long', 'publish_timing',
     '{"slots_utc":["16:00","18:30"],"variance_minutes":15,"primary_timezone":"US/Eastern"}'::JSONB,
     'Long-form performs best during US late afternoon / evening.', 'constitution', FALSE),

    ('quality_threshold', 'quality_threshold',
     '{"min_publish_score":75,"hard_reject_below":50,"gate_weights":{"topic":20,"facts":20,"visual":20,"script_audio":20,"metadata":20}}'::JSONB,
     'Constitution minimum. Non-negotiable. No video publishes below 75.', 'constitution', TRUE),

    ('content_buffer_targets', 'buffer_targets',
     '{"shorts_minimum":30,"longs_minimum":10,"emergency_pause_below_shorts":5,"emergency_pause_below_longs":2}'::JSONB,
     'Buffer prevents publishing gaps during production failures.', 'constitution', FALSE),

    ('daily_production_target', 'buffer_targets',
     '{"shorts_per_day":5,"longs_per_two_days":1,"max_failed_before_alert":3}'::JSONB,
     'Production targets from constitution.', 'constitution', FALSE),

    ('shorts_duration_policy', 'content_length',
     '{"min_seconds":18,"max_seconds":45,"target_durations":[20,24,28,32,38,44]}'::JSONB,
     'Variable duration looks organic. Range from constitution.', 'constitution', FALSE),

    ('long_duration_policy', 'content_length',
     '{"min_seconds":300,"max_seconds":480,"target_seconds":390}'::JSONB,
     '5-8 minutes is optimal for long-form nature content.', 'constitution', FALSE),

    ('topic_cooldown_policy', 'cooldown_policy',
     '{"default_days":30,"winner_days":45,"evergreen_days":60,"failed_days":90}'::JSONB,
     'Prevents topic saturation. Winners get longer cooldown to avoid milking.', 'constitution', FALSE),

    ('real_vs_ai_footage_ratio', 'content_length',
     '{"real_footage_ratio":0.80,"ai_footage_ratio":0.20}'::JSONB,
     '80/20 split. Real footage always preferred. AI is strict fallback only.', 'constitution', TRUE)
ON CONFLICT (rule_name) DO NOTHING;


-- ============================================================
-- SEED DATA: Channel Config (Global constants)
-- ============================================================
INSERT INTO channel_config (config_key, config_value, description) VALUES
    ('channel_niche',          '"nature_science"'::JSONB,          'Primary channel niche identifier'),
    ('channel_language',       '"en"'::JSONB,                       'Content language — English only'),
    ('target_countries',       '["US","GB","CA","AU","NZ"]'::JSONB, 'Primary target audience countries'),
    ('active_categories',      '["ocean","animals","space","nature","birds","insects"]'::JSONB, 'Categories enabled for production'),
    ('monetization_requirements',
     '{"subscribers":1000,"watch_hours_12m":4000,"shorts_views_90d":10000000}'::JSONB,
     'YouTube Partner Program requirements to track toward'),
    ('subtitle_style',
     '{"font_size":52,"font_weight":"bold","position":"center","word_highlight_color":"#FFFFFF","background_opacity":0.75,"background_color":"#000000"}'::JSONB,
     'Subtitle visual settings applied to all videos'),
    ('thumbnail_style',
     '{"max_words":4,"font_bold":true,"animal_focus":"close_up_face","contrast":"high","banned_text":["Facts About","Did You Know","Top 10"]}'::JSONB,
     'Thumbnail composition rules enforced by quality gate'),
    ('r2_bucket_name',         '"youtube-automation-media"'::JSONB, 'Cloudflare R2 bucket name for all media'),
    ('r2_retention_days_final','"30"'::JSONB,                       'Days to retain final rendered videos in R2 after YouTube upload'),
    ('r2_retention_days_raw',  '"1"'::JSONB,                        'Days to retain raw downloaded clips (deleted after assembly)'),
    ('max_retry_attempts',     '"3"'::JSONB,                        'Max production retries before marking a job failed'),
    ('system_version',         '"1.0.0"'::JSONB,                    'Current system version'),
    ('initialized_at',         'null'::JSONB,                       'Timestamp of first successful bootstrap run (set by bootstrap script)')
ON CONFLICT (config_key) DO NOTHING;


-- ============================================================
-- SEED DATA: Hook Library (20 gold starter hooks)
-- ============================================================
INSERT INTO hooks (hook_text, hook_type, template_slots, best_categories) VALUES
    ('This [ANIMAL] hunts great white sharks.',                          'danger',       ARRAY['[ANIMAL]'],             ARRAY['ocean','animals']),
    ('Scientists still cannot explain how this [CREATURE] does this.',   'mystery',      ARRAY['[CREATURE]'],           ARRAY['ocean','animals','insects']),
    ('This [ANIMAL] is larger than a school bus.',                       'size',         ARRAY['[ANIMAL]'],             ARRAY['ocean','animals']),
    ('This [ANIMAL] is smarter than most humans realize.',               'intelligence', ARRAY['[ANIMAL]'],             ARRAY['animals','ocean','birds']),
    ('[ANIMAL1] vs [ANIMAL2] — only one survives this encounter.',        'comparison',   ARRAY['[ANIMAL1]','[ANIMAL2]'],ARRAY['animals','ocean']),
    ('The deepest known creature on Earth lives here.',                  'mystery',      ARRAY[]::TEXT[],               ARRAY['ocean']),
    ('This [OBJECT] is moving faster than a speeding bullet right now.', 'speed',        ARRAY['[OBJECT]'],             ARRAY['space','animals']),
    ('This object in space is so large it should not exist.',            'size',         ARRAY[]::TEXT[],               ARRAY['space']),
    ('This [ANIMAL] can survive without oxygen for [DURATION].',         'survival',     ARRAY['[ANIMAL]','[DURATION]'],ARRAY['animals','ocean','insects']),
    ('Nothing would survive two minutes next to this [CREATURE].',       'danger',       ARRAY['[CREATURE]'],           ARRAY['animals','ocean','insects']),
    ('This [ANIMAL] communicates in ways science is still decoding.',    'intelligence', ARRAY['[ANIMAL]'],             ARRAY['animals','ocean','birds']),
    ('Nothing on Earth should be able to do what this [CREATURE] does.', 'impossible',   ARRAY['[CREATURE]'],           ARRAY['animals','ocean','insects']),
    ('Even [PREDATOR] runs from this [CREATURE].',                       'danger',       ARRAY['[PREDATOR]','[CREATURE]'],ARRAY['animals','ocean']),
    ('This [PHENOMENON] in nature cannot be fully explained by science.','mystery',      ARRAY['[PHENOMENON]'],         ARRAY['nature','space']),
    ('This [ANIMAL] migrates [DISTANCE] every single year.',             'record',       ARRAY['[ANIMAL]','[DISTANCE]'],ARRAY['animals','birds','ocean']),
    ('The most venomous creature on Earth is not what you think.',        'mystery',      ARRAY[]::TEXT[],               ARRAY['animals','ocean','insects']),
    ('This [PLANET] has a feature that makes no scientific sense.',      'mystery',      ARRAY['[PLANET]'],             ARRAY['space']),
    ('This [ANIMAL] has outlived the dinosaurs by millions of years.',   'record',       ARRAY['[ANIMAL]'],             ARRAY['animals','ocean','insects']),
    ('A single [CREATURE] of this species could end your life in minutes.','danger',     ARRAY['[CREATURE]'],           ARRAY['animals','ocean','insects']),
    ('What this [ANIMAL] does with its brain is terrifying.',            'intelligence', ARRAY['[ANIMAL]'],             ARRAY['animals','ocean'])
ON CONFLICT DO NOTHING;


-- ============================================================
-- SEED DATA: CTA Library (15 rotating endings)
-- ============================================================
INSERT INTO ctas (cta_text, cta_type) VALUES
    ('Would you survive an encounter with this creature?',         'question'),
    ('Which animal should we cover next?',                         'poll'),
    ('Can you name an animal that could beat this one?',           'challenge'),
    ('What fact surprised you most? Drop it below.',               'question'),
    ('Follow for a new nature fact every single day.',             'subscribe'),
    ('We covered something even more extreme last week.',          'next_video'),
    ('Nature is stranger than any fiction. Follow to see why.',    'subscribe'),
    ('Think you know nature? Wait until tomorrow''s video.',       'curiosity'),
    ('How close would you get to this creature?',                  'question'),
    ('The next one is even harder to believe.',                    'curiosity'),
    ('Drop your location. Would this animal survive near you?',    'poll'),
    ('Tag someone who needs to see this.',                         'subscribe'),
    ('Comment the first animal that comes to mind.',               'poll'),
    ('We are just getting started. Follow for more.',              'subscribe'),
    ('Nature does not care about your survival. Prove us wrong.',  'challenge')
ON CONFLICT DO NOTHING;


-- ============================================================
-- SEED DATA: Title Pattern Library (15 starter patterns)
-- ============================================================
INSERT INTO titles (title_pattern, title_type, template_slots, best_categories) VALUES
    ('Why [PREDATOR] Fear This [ANIMAL]',                    'curiosity',    ARRAY['[PREDATOR]','[ANIMAL]'],     ARRAY['animals','ocean']),
    ('The [ANIMAL] That Hunts [TARGET]',                     'revelation',   ARRAY['[ANIMAL]','[TARGET]'],       ARRAY['animals','ocean']),
    ('Scientists Discovered Something Terrifying About [ANIMAL]', 'mystery', ARRAY['[ANIMAL]'],                  ARRAY['animals','ocean','space']),
    ('[ANIMAL]: Nature''s Most Misunderstood Predator',      'curiosity',    ARRAY['[ANIMAL]'],                  ARRAY['animals','ocean']),
    ('This Object in Space Is Bigger Than You Can Imagine',  'scale',        ARRAY[]::TEXT[],                    ARRAY['space']),
    ('The Deepest [CREATURE] Ever Discovered',               'record',       ARRAY['[CREATURE]'],                ARRAY['ocean']),
    ('How [ANIMAL] Became the Ocean''s Most Feared Creature','curiosity',    ARRAY['[ANIMAL]'],                  ARRAY['ocean']),
    ('[ANIMAL1] vs [ANIMAL2]: Only One Walks Away',          'comparison',   ARRAY['[ANIMAL1]','[ANIMAL2]'],     ARRAY['animals','ocean']),
    ('The [ANIMAL] That Can Survive Anything',               'impossibility',ARRAY['[ANIMAL]'],                  ARRAY['animals','insects','ocean']),
    ('Why Nothing on Earth Messes With [ANIMAL]',            'danger',       ARRAY['[ANIMAL]'],                  ARRAY['animals','ocean']),
    ('The Truth About [ANIMAL] Nobody Tells You',            'revelation',   ARRAY['[ANIMAL]'],                  ARRAY['animals','ocean','birds']),
    ('[PHENOMENON]: The Natural Event That Defies Explanation','mystery',    ARRAY['[PHENOMENON]'],              ARRAY['nature','space']),
    ('How Smart Is The [ANIMAL] Really?',                    'intelligence', ARRAY['[ANIMAL]'],                  ARRAY['animals','ocean','birds']),
    ('The [ANIMAL] With the Most Deadly Weapon in Nature',   'danger',       ARRAY['[ANIMAL]'],                  ARRAY['animals','ocean','insects']),
    ('Inside [SPACE_OBJECT]: What Scientists Found Shocked Everyone', 'mystery', ARRAY['[SPACE_OBJECT]'],       ARRAY['space'])
ON CONFLICT DO NOTHING;


-- ============================================================
-- CONFIRMATION BLOCK
-- ============================================================
DO $$
DECLARE
    v_tables  INT;
    v_views   INT;
    v_sources INT;
    v_rules   INT;
    v_config  INT;
    v_hooks   INT;
    v_ctas    INT;
    v_titles  INT;
BEGIN
    SELECT COUNT(*) INTO v_tables  FROM information_schema.tables
        WHERE table_schema = 'public' AND table_type = 'BASE TABLE';
    SELECT COUNT(*) INTO v_views   FROM information_schema.views
        WHERE table_schema = 'public';
    SELECT COUNT(*) INTO v_sources FROM sources;
    SELECT COUNT(*) INTO v_rules   FROM growth_rules;
    SELECT COUNT(*) INTO v_config  FROM channel_config;
    SELECT COUNT(*) INTO v_hooks   FROM hooks;
    SELECT COUNT(*) INTO v_ctas    FROM ctas;
    SELECT COUNT(*) INTO v_titles  FROM titles;

    RAISE NOTICE '=================================================';
    RAISE NOTICE '  YouTube Automation — Schema Setup Complete';
    RAISE NOTICE '=================================================';
    RAISE NOTICE '  Tables created : %', v_tables;
    RAISE NOTICE '  Views created  : %', v_views;
    RAISE NOTICE '  Sources seeded : %', v_sources;
    RAISE NOTICE '  Growth rules   : %', v_rules;
    RAISE NOTICE '  Config entries : %', v_config;
    RAISE NOTICE '  Hooks seeded   : %', v_hooks;
    RAISE NOTICE '  CTAs seeded    : %', v_ctas;
    RAISE NOTICE '  Title patterns : %', v_titles;
    RAISE NOTICE '=================================================';
    RAISE NOTICE '  STATUS: READY FOR BOOTSTRAP';
    RAISE NOTICE '=================================================';
END;
$$;
