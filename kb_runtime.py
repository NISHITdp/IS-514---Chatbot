# kb_runtime.py
import os
import sqlite3
from typing import List, Tuple, Optional

import numpy as np
import faiss
from dotenv import load_dotenv
from openai import OpenAI

# ---- OpenAI ----
load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ---- Paths (we use ./data) ----
HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
SQLITE_PATH = os.path.join(DATA_DIR, "kb.sqlite")
FAISS_PATH  = os.path.join(DATA_DIR, "kb.faiss")

# ---- FAISS singleton ----
_index = None

def _index_ok() -> faiss.IndexFlatIP:
    global _index
    if _index is None:
        if not os.path.exists(FAISS_PATH):
            raise FileNotFoundError(f"FAISS index not found at {FAISS_PATH}")
        _index = faiss.read_index(FAISS_PATH)
    return _index

# ---- SQLite helpers ----
def _tables(cur) -> List[str]:
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    return [r[0] for r in cur.fetchall()]

def _columns(cur, table: str) -> List[Tuple[str, str]]:
    cur.execute(f"PRAGMA table_info({table})")
    # name, type
    return [(c[1], c[2] or "") for c in cur.fetchall()]

def _pick_text_col(cur, table: str) -> Optional[str]:
    cols = _columns(cur, table)
    names = [c[0] for c in cols]
    for name in ("content", "text", "chunk_text"):
        if name in names:
            return name
    for name, ctype in cols:
        if "TEXT" in ctype.upper():
            return name
    return None

def _fetch_texts_by_rowids(rowids: List[int]) -> List[str]:
    """
    Map FAISS ids -> text chunks in SQLite.
    Tries strategies in order for each candidate table:
      A) rowid = faiss_id + 1
      B) chunk_idx = faiss_id
      C) id = faiss_id + 1 (then id = faiss_id)
      D) fallback: ORDER rows and index by position
    """
    if not rowids:
        return []

    conn = sqlite3.connect(SQLITE_PATH)
    cur  = conn.cursor()

    tables = _tables(cur)
    # prefer obvious names if present
    preferred = [t for t in tables if t in ("kb_chunks", "chunks")]
    if not preferred:
        preferred = [t for t in tables if "chunk" in t.lower()] or tables

    wanted_ids = [int(i) for i in rowids]
    placeholders = ",".join("?" * len(wanted_ids))

    for table in preferred:
        text_col = _pick_text_col(cur, table)
        if not text_col:
            continue

        colnames = [c[0] for c in _columns(cur, table)]
        mapping_attempts = []

        # A) rowid = faiss_id + 1
        try:
            q = f"SELECT rowid, {text_col} FROM {table} WHERE rowid IN ({placeholders})"
            cur.execute(q, [i+1 for i in wanted_ids])  # rowid is 1-based
            rows = cur.fetchall()
            if rows:
                conn.close()
                m = {rid-1: txt for (rid, txt) in rows}
                return [m.get(i, "") for i in wanted_ids]
            mapping_attempts.append("rowid=(faiss+1)")
        except Exception:
            mapping_attempts.append("rowid=(faiss+1)")

        # B) chunk_idx = faiss_id
        if "chunk_idx" in colnames:
            try:
                q = f"SELECT chunk_idx, {text_col} FROM {table} WHERE chunk_idx IN ({placeholders})"
                cur.execute(q, wanted_ids)
                rows = cur.fetchall()
                if rows:
                    conn.close()
                    m = {idx: txt for (idx, txt) in rows}
                    return [m.get(i, "") for i in wanted_ids]
                mapping_attempts.append("chunk_idx=faiss")
            except Exception:
                mapping_attempts.append("chunk_idx=faiss")

        # C) id = faiss_id + 1
        if "id" in colnames:
            try:
                q = f"SELECT id, {text_col} FROM {table} WHERE id IN ({placeholders})"
                cur.execute(q, [i+1 for i in wanted_ids])
                rows = cur.fetchall()
                if rows:
                    conn.close()
                    m = {idv-1: txt for (idv, txt) in rows}
                    return [m.get(i, "") for i in wanted_ids]
                mapping_attempts.append("id=(faiss+1)")
            except Exception:
                mapping_attempts.append("id=(faiss+1)")

            # id = faiss_id (rare, but try)
            try:
                q = f"SELECT id, {text_col} FROM {table} WHERE id IN ({placeholders})"
                cur.execute(q, wanted_ids)
                rows = cur.fetchall()
                if rows:
                    conn.close()
                    m = {idv: txt for (idv, txt) in rows}
                    return [m.get(i, "") for i in wanted_ids]
                mapping_attempts.append("id=faiss")
            except Exception:
                mapping_attempts.append("id=faiss")

        # D) fallback: order and index by position
        try:
            order_col = "chunk_idx" if "chunk_idx" in colnames else ("id" if "id" in colnames else "rowid")
            q = f"SELECT {text_col} FROM {table} ORDER BY {order_col}"
            cur.execute(q)
            all_txt = [r[0] for r in cur.fetchall()]
            if all_txt:
                conn.close()
                return [all_txt[i] if 0 <= i < len(all_txt) else "" for i in wanted_ids]
            mapping_attempts.append("ordered-scan")
        except Exception:
            mapping_attempts.append("ordered-scan")

        # If we got here, try next candidate table
        # (uncomment to debug)
        # print(f"[kb_runtime] table {table} had no matches via {mapping_attempts}")

    conn.close()
    raise RuntimeError("Could not read chunk texts from SQLite using any mapping strategy.")

def retrieve_context(question: str, k: int = 5) -> List[str]:
    q = (question or "").strip()
    if not q:
        return []

    # embed
    emb = client.embeddings.create(
        model="text-embedding-3-small",
        input=q
    ).data[0].embedding

    # search faiss
    index = _index_ok()
    xq = np.array([emb], dtype="float32")
    _, indices = index.search(xq, k)
    ids = [int(i) for i in indices[0] if i >= 0]

    # map ids -> chunk text
    return _fetch_texts_by_rowids(ids)
