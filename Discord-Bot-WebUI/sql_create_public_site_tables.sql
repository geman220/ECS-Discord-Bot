-- sql_create_public_site_tables.sql
--
-- Public marketing site (rebuilt ecspubleague.org) — base schema.
-- Reconstructed from app/models/public_site.py + app/models/calendar.py so the
-- schema is versioned in the repo (it was previously hand-run and never
-- committed). IDEMPOTENT: safe to run against a database where these already
-- exist (documents current prod state).
--
-- Run in pgAdmin as the ecs-admin user. The builder-era additions live in the
-- separate sql_public_site_builder.sql.

BEGIN;

CREATE TABLE IF NOT EXISTS news_post (
    id                   SERIAL PRIMARY KEY,
    slug                 VARCHAR(200) NOT NULL UNIQUE,
    title                VARCHAR(255) NOT NULL,
    excerpt              TEXT,
    body_html            TEXT,
    featured_image_url   VARCHAR(500),
    author_name          VARCHAR(120),
    status               VARCHAR(20)  NOT NULL DEFAULT 'draft',
    published_at         TIMESTAMP,
    category             VARCHAR(80),
    meta_title           VARCHAR(255),
    meta_description     VARCHAR(320),
    og_image_url         VARCHAR(500),
    announce_to_discord  BOOLEAN      NOT NULL DEFAULT FALSE,
    discord_announced_at TIMESTAMP,
    created_at           TIMESTAMP    NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMP    NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_news_post_slug         ON news_post (slug);
CREATE INDEX IF NOT EXISTS ix_news_post_status       ON news_post (status);
CREATE INDEX IF NOT EXISTS ix_news_post_published_at ON news_post (published_at);
CREATE INDEX IF NOT EXISTS ix_news_post_category     ON news_post (category);

CREATE TABLE IF NOT EXISTS faq (
    id           SERIAL PRIMARY KEY,
    question     TEXT        NOT NULL,
    answer_html  TEXT        NOT NULL,
    category     VARCHAR(80)          DEFAULT 'General',
    sort_order   INTEGER     NOT NULL DEFAULT 0,
    is_published BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at   TIMESTAMP   NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMP   NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_faq_category     ON faq (category);
CREATE INDEX IF NOT EXISTS ix_faq_sort_order   ON faq (sort_order);
CREATE INDEX IF NOT EXISTS ix_faq_is_published ON faq (is_published);

CREATE TABLE IF NOT EXISTS site_page (
    id               SERIAL PRIMARY KEY,
    slug             VARCHAR(120) NOT NULL UNIQUE,
    title            VARCHAR(255),
    body_html        TEXT,
    meta_title       VARCHAR(255),
    meta_description VARCHAR(320),
    og_image_url     VARCHAR(500),
    created_at       TIMESTAMP             DEFAULT NOW(),
    updated_at       TIMESTAMP    NOT NULL DEFAULT NOW(),
    updated_by_id    INTEGER REFERENCES users (id),
    deleted_at       TIMESTAMP,
    status           VARCHAR(20)  NOT NULL DEFAULT 'published',
    hero_json        TEXT
);
CREATE INDEX IF NOT EXISTS ix_site_page_slug       ON site_page (slug);
CREATE INDEX IF NOT EXISTS ix_site_page_deleted_at ON site_page (deleted_at);
CREATE INDEX IF NOT EXISTS ix_site_page_status     ON site_page (status);

CREATE TABLE IF NOT EXISTS media_asset (
    id             SERIAL PRIMARY KEY,
    filename       VARCHAR(255) NOT NULL,
    url            VARCHAR(500) NOT NULL,
    alt_text       VARCHAR(300),
    title          VARCHAR(255),
    mime           VARCHAR(80),
    size_bytes     INTEGER,
    uploaded_by_id INTEGER REFERENCES users (id),
    created_at     TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_media_asset_created_at ON media_asset (created_at);

CREATE TABLE IF NOT EXISTS site_page_revision (
    id            SERIAL PRIMARY KEY,
    page_id       INTEGER NOT NULL REFERENCES site_page (id),
    title         VARCHAR(255),
    body_html     TEXT,
    created_at    TIMESTAMP NOT NULL DEFAULT NOW(),
    created_by_id INTEGER REFERENCES users (id)
);
CREATE INDEX IF NOT EXISTS ix_site_page_revision_page_id    ON site_page_revision (page_id);
CREATE INDEX IF NOT EXISTS ix_site_page_revision_created_at ON site_page_revision (created_at);

CREATE TABLE IF NOT EXISTS redirect_rule (
    id          SERIAL PRIMARY KEY,
    source_path VARCHAR(500) NOT NULL UNIQUE,
    target_path VARCHAR(500) NOT NULL,
    is_active   BOOLEAN      NOT NULL DEFAULT TRUE,
    hits        INTEGER      NOT NULL DEFAULT 0,
    created_at  TIMESTAMP    NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_redirect_rule_source_path ON redirect_rule (source_path);
CREATE INDEX IF NOT EXISTS ix_redirect_rule_is_active   ON redirect_rule (is_active);

CREATE TABLE IF NOT EXISTS form_submission (
    id          SERIAL PRIMARY KEY,
    form_name   VARCHAR(120) NOT NULL DEFAULT 'contact',
    data_json   TEXT,
    source_page VARCHAR(300),
    created_at  TIMESTAMP NOT NULL DEFAULT NOW(),
    is_read     BOOLEAN   NOT NULL DEFAULT FALSE
);
CREATE INDEX IF NOT EXISTS ix_form_submission_form_name  ON form_submission (form_name);
CREATE INDEX IF NOT EXISTS ix_form_submission_created_at ON form_submission (created_at);
CREATE INDEX IF NOT EXISTS ix_form_submission_is_read    ON form_submission (is_read);

-- Public-calendar visibility toggle on league events (referenced by the
-- public /calendar page; previously in an uncommitted one-off file).
ALTER TABLE league_events ADD COLUMN IF NOT EXISTS is_public BOOLEAN NOT NULL DEFAULT TRUE;

COMMIT;
