# kb_utils.py
import os, sqlite3, re, math, json
from typing import List, Tuple
from docx import Document
import tiktoken
import numpy as np

from dotenv import load_dotenv
from openai import OpenAI

# Paths
KB_DB = "data/kb.sqlite"
KB_FAISS = "data/kb.faiss"

# --- Embeddings ---
EMBED_MODEL = "text-embedding-3-small"  # cheap, good
EMBED_DIM = 1536

def _client():
    load_dotenv()
    return OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# --- DB init ---
def init_kb():
    os.makedirs("data", exist_ok=True)
    conn = sqlite3.connect(KB_DB)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS kb_chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            section TEXT,
            chunk_idx INTEGER,
            content TEXT NOT NULL
        );
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_kb_source ON kb_chunks(source);")
    conn.commit()
    conn.close()

# --- simple chunker ---
def _docx_to_text_sections(path: str) -> List[Tuple[str, str]]:
    """Return list of (section_title, paragraph_text) from a .docx."""
    doc = Document(path)
    sections = []
    current = ("", [])
    for p in doc.paragraphs:
        txt = p.text.strip()
        if not txt: 
            continue
        # very light 'heading' guess: all-caps lines or short titley lines
        if len(txt) < 120 and (txt.isupper() or re.match(r'^[A-Z][A-Za-z0-9 ,:/&\-\(\)]{0,80}$', txt)):
            # flush previous
            if current[1]:
                sections.append((current[0], "\n".join(current[1])))
            current = (txt, [])
        else:
            current[1].append(txt)
    if current[1]:
        sections.append((current[0], "\n".join(current[1])))
    return sections

def _token_chunks(text: str, max_tokens=350, overlap=60) -> List[str]:
    enc = tiktoken.get_encoding("cl100k_base")
    toks = enc.encode(text)
    out = []
    i = 0
    while i < len(toks):
        win = toks[i:i+max_tokens]
        out.append(enc.decode(win))
        i += max_tokens - overlap
    return out

def _embed_texts(texts: List[str]) -> np.ndarray:
    cli = _client()
    # Batch to avoid very long payloads
    embs = []
    B = 64
    for i in range(0, len(texts), B):
        batch = texts[i:i+B]
        res = cli.embeddings.create(model=EMBED_MODEL, input=batch)
        embs.extend([d.embedding for d in res.data])
    return np.array(embs, dtype="float32")

# --- FAISS helpers (no import until needed) ---
def _save_faiss(index, path: str):
    import faiss
    faiss.write_index(index, path)

def _load_faiss(path: str):
    import faiss
    return faiss.read_index(path)

def rebuild_faiss_index():
    """Rebuild FAISS from kb_chunks in SQLite."""
    conn = sqlite3.connect(KB_DB)
    cur = conn.cursor()
    cur.execute("SELECT id, content FROM kb_chunks ORDER BY id;")
    rows = cur.fetchall()
    conn.close()
    if not rows:
        raise RuntimeError("kb_chunks empty. Ingest a document first.")
    ids = [r[0] for r in rows]
    texts = [r[1] for r in rows]
    X = _embed_texts(texts)
    import faiss
    index = faiss.IndexFlatIP(EMBED_DIM)  # cosine via normalized vectors
    # normalize
    faiss.normalize_L2(X)
    index.add(X)
    _save_faiss(index, KB_FAISS)
    # also save mapping
    with open(KB_FAISS + ".map.json", "w") as f:
        json.dump(ids, f)

def ingest_docx(source_path: str):
    """Parse -> chunk -> store chunks in SQLite -> build FAISS."""
    init_kb()
    sections = _docx_to_text_sections(source_path)
    rows = []
    for sec_title, sec_text in sections:
        for idx, chunk in enumerate(_token_chunks(sec_text)):
            rows.append((os.path.basename(source_path), sec_title or "", idx, chunk))
    conn = sqlite3.connect(KB_DB)
    cur = conn.cursor()
    # wipe existing for this source (idempotent reloads)
    cur.execute("DELETE FROM kb_chunks WHERE source = ?;", (os.path.basename(source_path),))
    cur.executemany(
        "INSERT INTO kb_chunks(source, section, chunk_idx, content) VALUES (?,?,?,?);",
        rows
    )
    conn.commit()
    conn.close()
    rebuild_faiss_index()

def retrieve(query: str, k: int = 4) -> List[dict]:
    """Return top-k chunks [{'id', 'content', 'section', 'source'}]."""
    import faiss
    with open(KB_FAISS + ".map.json") as f:
        id_map = json.load(f)
    index = _load_faiss(KB_FAISS)
    # embed + normalize
    qv = _embed_texts([query])
    faiss.normalize_L2(qv)
    D, I = index.search(qv, k)
    ids = [id_map[i] for i in I[0]]
    conn = sqlite3.connect(KB_DB)
    cur = conn.cursor()
    qmarks = ",".join("?" for _ in ids)
    cur.execute(f"SELECT id, source, section, content FROM kb_chunks WHERE id IN ({qmarks});", ids)
    out = [
        {"id": r[0], "source": r[1], "section": r[2], "content": r[3]}
        for r in cur.fetchall()
    ]
    conn.close()
    return out
