-- Single schema for the gallery database (data/cuadros.sqlite).
-- Used by both the PHP API (api/_common.php) and the Python engine (library_manager.py).
-- Every statement must be idempotent: it runs on every connection.

CREATE TABLE IF NOT EXISTS paintings (
    id TEXT PRIMARY KEY,
    title TEXT,
    original_title TEXT,
    artist TEXT,
    year TEXT,
    location TEXT,
    orientation TEXT,
    confidence_score REAL,
    confirmed INTEGER NOT NULL DEFAULT 0,
    info_data_source TEXT,
    file_path TEXT NOT NULL UNIQUE,          -- relative to paintings/
    file_size INTEGER,
    file_width INTEGER,
    file_height INTEGER,
    added_to_library TEXT,
    updated_on_library TEXT,
    status TEXT NOT NULL DEFAULT 'ready',    -- 'pending' = uploaded but not identified/reviewed yet
    extra TEXT                               -- JSON object with any other engine field
);

CREATE TABLE IF NOT EXISTS descriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    painting_id TEXT NOT NULL REFERENCES paintings(id) ON DELETE CASCADE ON UPDATE CASCADE,
    language TEXT NOT NULL,
    description TEXT NOT NULL,
    description_style TEXT,
    generated_at TEXT,
    comment_creator TEXT,
    max_length INTEGER,
    UNIQUE (painting_id, language, description, generated_at, comment_creator)
);

CREATE INDEX IF NOT EXISTS idx_descriptions_painting ON descriptions(painting_id, language, generated_at);

-- Period (época) and theme (temática) tags, from the vocabulary in engine/tags.py.
-- The format tag is paintings.orientation.
CREATE TABLE IF NOT EXISTS painting_tags (
    painting_id TEXT NOT NULL REFERENCES paintings(id) ON DELETE CASCADE ON UPDATE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('period', 'theme')),
    tag TEXT NOT NULL,
    position INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (painting_id, kind, tag)
);

-- Geocoding cache for paintings.location (exact string). status: ok | not_found | not_a_place
CREATE TABLE IF NOT EXISTS locations (
    name TEXT PRIMARY KEY,
    lat REAL,
    lon REAL,
    display_name TEXT,
    status TEXT NOT NULL,
    geocoded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    is_admin INTEGER NOT NULL DEFAULT 0,      -- legacy; the superadmin is ADMIN_USERNAME in api/_common.php
    can_upload INTEGER NOT NULL DEFAULT 0,    -- granted by the superadmin from the users dashboard
    last_login_at TEXT,
    theme TEXT,                               -- 'light' | 'dark' (null = follow the browser)
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS seen (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    painting_id TEXT NOT NULL REFERENCES paintings(id) ON DELETE CASCADE ON UPDATE CASCADE,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, painting_id)
);

CREATE TABLE IF NOT EXISTS favorites (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    painting_id TEXT NOT NULL REFERENCES paintings(id) ON DELETE CASCADE ON UPDATE CASCADE,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, painting_id)
);

-- Personal collections (private; viewable read-only by anyone who has the id link)
CREATE TABLE IF NOT EXISTS collections (
    id TEXT PRIMARY KEY,                      -- 16 random hex chars (also the share token)
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'custom',      -- 'custom' | 'favorites' (built-in, one per user, paintings = favorites table)
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS collection_paintings (
    collection_id TEXT NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
    painting_id TEXT NOT NULL REFERENCES paintings(id) ON DELETE CASCADE ON UPDATE CASCADE,
    added_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (collection_id, painting_id)
);
