-- sql_public_site_builder.sql
--
-- Public-site BUILDER schema: section/block composition, news drafts +
-- revisions, media renditions/focal/usage, site settings, form definitions,
-- slug history, and the least-privilege "Site Editor" role.
--
-- Run ONCE in pgAdmin (as ecs-admin) AFTER sql_create_public_site_tables.sql.
-- IDEMPOTENT: every statement is IF NOT EXISTS / ON CONFLICT DO NOTHING.
-- Additive only — nothing here drops or rewrites existing data.

BEGIN;

-- ---- site_page: section composition + scheduling -------------------------
ALTER TABLE site_page ADD COLUMN IF NOT EXISTS sections_draft      JSONB;
ALTER TABLE site_page ADD COLUMN IF NOT EXISTS sections_published  JSONB;
ALTER TABLE site_page ADD COLUMN IF NOT EXISTS draft_rev           INTEGER NOT NULL DEFAULT 0;
ALTER TABLE site_page ADD COLUMN IF NOT EXISTS draft_updated_at    TIMESTAMP;
ALTER TABLE site_page ADD COLUMN IF NOT EXISTS draft_updated_by_id INTEGER REFERENCES users (id);
ALTER TABLE site_page ADD COLUMN IF NOT EXISTS published_at        TIMESTAMP;
ALTER TABLE site_page ADD COLUMN IF NOT EXISTS publish_at          TIMESTAMP;
ALTER TABLE site_page ADD COLUMN IF NOT EXISTS unpublish_at        TIMESTAMP;
CREATE INDEX IF NOT EXISTS ix_site_page_publish_at   ON site_page (publish_at);
CREATE INDEX IF NOT EXISTS ix_site_page_unpublish_at ON site_page (unpublish_at);

-- ---- site_page_revision: section snapshots + kinds -----------------------
ALTER TABLE site_page_revision ADD COLUMN IF NOT EXISTS sections JSONB;
ALTER TABLE site_page_revision ADD COLUMN IF NOT EXISTS kind     VARCHAR(20) NOT NULL DEFAULT 'publish';
ALTER TABLE site_page_revision ADD COLUMN IF NOT EXISTS label    VARCHAR(60);
CREATE INDEX IF NOT EXISTS ix_site_page_revision_kind ON site_page_revision (kind);

-- ---- news_post_revision (new) --------------------------------------------
CREATE TABLE IF NOT EXISTS news_post_revision (
    id            SERIAL PRIMARY KEY,
    post_id       INTEGER     NOT NULL REFERENCES news_post (id),
    snapshot      JSONB       NOT NULL,
    kind          VARCHAR(20) NOT NULL DEFAULT 'publish',
    label         VARCHAR(60),
    created_at    TIMESTAMP   NOT NULL DEFAULT NOW(),
    created_by_id INTEGER REFERENCES users (id)
);
CREATE INDEX IF NOT EXISTS ix_news_post_revision_post_id    ON news_post_revision (post_id);
CREATE INDEX IF NOT EXISTS ix_news_post_revision_kind       ON news_post_revision (kind);
CREATE INDEX IF NOT EXISTS ix_news_post_revision_created_at ON news_post_revision (created_at);

-- ---- site_page_slug_history (new): auto-301 on rename --------------------
CREATE TABLE IF NOT EXISTS site_page_slug_history (
    id         SERIAL PRIMARY KEY,
    page_id    INTEGER      NOT NULL REFERENCES site_page (id),
    old_slug   VARCHAR(120) NOT NULL UNIQUE,
    created_at TIMESTAMP    NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_site_page_slug_history_page_id  ON site_page_slug_history (page_id);
CREATE INDEX IF NOT EXISTS ix_site_page_slug_history_old_slug ON site_page_slug_history (old_slug);

-- ---- media_asset: renditions / focal point / dedup / folders -------------
ALTER TABLE media_asset ADD COLUMN IF NOT EXISTS width        INTEGER;
ALTER TABLE media_asset ADD COLUMN IF NOT EXISTS height       INTEGER;
ALTER TABLE media_asset ADD COLUMN IF NOT EXISTS focal_x      DOUBLE PRECISION;
ALTER TABLE media_asset ADD COLUMN IF NOT EXISTS focal_y      DOUBLE PRECISION;
ALTER TABLE media_asset ADD COLUMN IF NOT EXISTS variants     JSONB;
ALTER TABLE media_asset ADD COLUMN IF NOT EXISTS content_hash VARCHAR(64);
ALTER TABLE media_asset ADD COLUMN IF NOT EXISTS folder       VARCHAR(120);
CREATE INDEX IF NOT EXISTS ix_media_asset_content_hash ON media_asset (content_hash);
CREATE INDEX IF NOT EXISTS ix_media_asset_folder       ON media_asset (folder);

-- ---- media_usage (new): derived "where is this asset used" index ---------
CREATE TABLE IF NOT EXISTS media_usage (
    id          SERIAL PRIMARY KEY,
    asset_id    INTEGER     NOT NULL REFERENCES media_asset (id),
    entity_type VARCHAR(40) NOT NULL,
    entity_id   INTEGER     NOT NULL DEFAULT 0,
    field       VARCHAR(60) NOT NULL DEFAULT '',
    CONSTRAINT uq_media_usage_ref UNIQUE (asset_id, entity_type, entity_id, field)
);
CREATE INDEX IF NOT EXISTS ix_media_usage_asset_id ON media_usage (asset_id);
CREATE INDEX IF NOT EXISTS ix_media_usage_entity   ON media_usage (entity_type, entity_id);

-- ---- site_settings (new): JSONB settings store ---------------------------
CREATE TABLE IF NOT EXISTS site_settings (
    key           VARCHAR(120) PRIMARY KEY,
    value         JSONB,
    updated_at    TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_by_id INTEGER REFERENCES users (id)
);

-- ---- form_definition (new): the ONE public forms system ------------------
CREATE TABLE IF NOT EXISTS form_definition (
    id                 SERIAL PRIMARY KEY,
    name               VARCHAR(120) NOT NULL UNIQUE,
    title              VARCHAR(200),
    fields             JSONB     NOT NULL DEFAULT '[]'::jsonb,
    notify_emails      VARCHAR(500),
    success_message    TEXT,
    mirror_to_feedback BOOLEAN   NOT NULL DEFAULT FALSE,
    is_active          BOOLEAN   NOT NULL DEFAULT TRUE,
    created_at         TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at         TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_form_definition_name      ON form_definition (name);
CREATE INDEX IF NOT EXISTS ix_form_definition_is_active ON form_definition (is_active);

-- ---- Site Editor role (least-privilege CMS authoring) --------------------
-- Web-only role: reaches ONLY the public-site CMS + site-editor routes.
-- sync_enabled FALSE keeps the Discord role calculators away from it.
INSERT INTO roles (name, description, sync_enabled)
VALUES ('Site Editor',
        'Can edit the public marketing site (pages, news, FAQs, media). No other admin access.',
        FALSE)
ON CONFLICT (name) DO NOTHING;

COMMIT;
