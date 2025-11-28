# ingest_kb.py
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from kb_utils import ingest_docx

DOC = os.path.join(HERE, "assets", "kb", "how_billing_insurance_notes.docx")
print("DOC exists?", os.path.exists(DOC), "→", DOC)

ingest_docx(DOC)
print("KB built (data/kb.sqlite, data/kb.faiss)")
