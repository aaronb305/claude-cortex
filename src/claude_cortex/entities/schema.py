"""SQLite schema for entity graph storage."""

ENTITIES_SCHEMA = """
-- Entities: files, functions, classes, constants
CREATE TABLE IF NOT EXISTS entities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL,        -- 'file', 'function', 'class', 'constant'
    name TEXT NOT NULL,               -- Entity name
    qualified_name TEXT NOT NULL,     -- Full path (file:function or file:class)
    file_path TEXT NOT NULL,          -- Source file (absolute or project-relative)
    start_line INTEGER,               -- Line number (1-indexed)
    end_line INTEGER,                 -- End line number
    content_hash TEXT,                -- For change detection
    last_indexed TEXT,                -- ISO timestamp
    metadata TEXT                     -- JSON blob for language-specific data
);

-- Relationships between entities
CREATE TABLE IF NOT EXISTS relationships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER NOT NULL,
    target_id INTEGER NOT NULL,
    relationship_type TEXT NOT NULL,  -- 'imports', 'defines', 'calls', 'inherits'
    weight REAL DEFAULT 1.0,          -- For future ranking
    metadata TEXT,                    -- JSON blob (line number, context)
    FOREIGN KEY (source_id) REFERENCES entities(id) ON DELETE CASCADE,
    FOREIGN KEY (target_id) REFERENCES entities(id) ON DELETE CASCADE,
    UNIQUE (source_id, target_id, relationship_type)
);

-- Indexes for efficient queries
CREATE INDEX IF NOT EXISTS idx_entities_file ON entities(file_path);
CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(entity_type);
CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(name);
CREATE INDEX IF NOT EXISTS idx_entities_qualified ON entities(qualified_name);
CREATE INDEX IF NOT EXISTS idx_relationships_source ON relationships(source_id);
CREATE INDEX IF NOT EXISTS idx_relationships_target ON relationships(target_id);
CREATE INDEX IF NOT EXISTS idx_relationships_type ON relationships(relationship_type);

-- FTS5 for entity name search
CREATE VIRTUAL TABLE IF NOT EXISTS entities_fts USING fts5(
    name,
    qualified_name,
    content=entities,
    content_rowid=id,
    tokenize='porter unicode61'
);

-- Triggers to keep FTS in sync
CREATE TRIGGER IF NOT EXISTS entities_ai AFTER INSERT ON entities BEGIN
    INSERT INTO entities_fts(rowid, name, qualified_name)
    VALUES (new.id, new.name, new.qualified_name);
END;

CREATE TRIGGER IF NOT EXISTS entities_ad AFTER DELETE ON entities BEGIN
    INSERT INTO entities_fts(entities_fts, rowid, name, qualified_name)
    VALUES ('delete', old.id, old.name, old.qualified_name);
END;

CREATE TRIGGER IF NOT EXISTS entities_au AFTER UPDATE ON entities BEGIN
    INSERT INTO entities_fts(entities_fts, rowid, name, qualified_name)
    VALUES ('delete', old.id, old.name, old.qualified_name);
    INSERT INTO entities_fts(rowid, name, qualified_name)
    VALUES (new.id, new.name, new.qualified_name);
END;
"""

LEARNING_ENTITIES_SCHEMA = """
-- Links learnings to relevant entities (P2 feature)
CREATE TABLE IF NOT EXISTS learning_entities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    learning_id TEXT NOT NULL,        -- UUID from ledger
    entity_id INTEGER NOT NULL,
    relevance_type TEXT NOT NULL,     -- 'about', 'modifies', 'references'
    confidence REAL DEFAULT 0.5,
    created_at TEXT,
    FOREIGN KEY (entity_id) REFERENCES entities(id) ON DELETE CASCADE,
    UNIQUE (learning_id, entity_id)
);

CREATE INDEX IF NOT EXISTS idx_learning_entities_learning ON learning_entities(learning_id);
CREATE INDEX IF NOT EXISTS idx_learning_entities_entity ON learning_entities(entity_id);
"""


def get_full_schema() -> str:
    """Get the complete schema for entity graph database."""
    return ENTITIES_SCHEMA + "\n" + LEARNING_ENTITIES_SCHEMA
