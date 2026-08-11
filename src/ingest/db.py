"""SQLite schema for the document store: structured tables + prose chunks.

Tables survive ingestion as rows/cols with units kept separate from values
(constraint #4) so numeric compute never has to parse text to find a number.
"""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[2] / "index" / "doc_store.sqlite"

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    doc_id      TEXT PRIMARY KEY,
    filename    TEXT NOT NULL,
    title       TEXT,
    source_url  TEXT,
    num_pages   INTEGER
);

CREATE TABLE IF NOT EXISTS tables (
    doc_id  TEXT NOT NULL,
    page    INTEGER NOT NULL,
    table_id TEXT NOT NULL,
    row     INTEGER NOT NULL,
    col     INTEGER NOT NULL,
    value   TEXT,
    unit    TEXT,
    header  TEXT,
    FOREIGN KEY (doc_id) REFERENCES documents(doc_id)
);

CREATE TABLE IF NOT EXISTS chunks (
    doc_id    TEXT NOT NULL,
    chunk_id  TEXT PRIMARY KEY,
    page      INTEGER NOT NULL,
    text      TEXT NOT NULL,
    FOREIGN KEY (doc_id) REFERENCES documents(doc_id)
);

CREATE INDEX IF NOT EXISTS idx_tables_doc_page ON tables(doc_id, page);
CREATE INDEX IF NOT EXISTS idx_tables_table_id ON tables(doc_id, table_id);
CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(doc_id);
"""


def get_connection(db_path: Path = DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    return conn


def upsert_document(conn, doc_id, filename, title, source_url, num_pages):
    conn.execute(
        "INSERT OR REPLACE INTO documents (doc_id, filename, title, source_url, num_pages) "
        "VALUES (?, ?, ?, ?, ?)",
        (doc_id, filename, title, source_url, num_pages),
    )


def insert_table_cells(conn, rows):
    """rows: iterable of (doc_id, page, table_id, row, col, value, unit, header)."""
    conn.executemany(
        "INSERT INTO tables (doc_id, page, table_id, row, col, value, unit, header) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )


def insert_chunks(conn, rows):
    """rows: iterable of (doc_id, chunk_id, page, text)."""
    conn.executemany(
        "INSERT OR REPLACE INTO chunks (doc_id, chunk_id, page, text) VALUES (?, ?, ?, ?)",
        rows,
    )
