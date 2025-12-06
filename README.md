SRP Billing Assistant — Streamlit MVP

Patient-friendly chatbot that explains medical billing & insurance in simple language, guides to EquityPay portal links, blocks PHI, and supports English/Spanish. Built with Streamlit, OpenAI (gpt-4o-mini), optional voice input, and an optional local RAG layer (FAISS + SQLite).

⚠️ Compliance: This MVP does not process PHI. It uses regex guardrails to block SSN/DOB/account numbers and redirects to verified EquityPay links. “HIPAA/SOC2-aligned design” here means the app avoids PHI and keeps secrets out of code; formal compliance requires enterprise deployment & audits.

Features

Clear billing education (deductible, copay, coinsurance, EOBs) at a ~4th-grade reading level

Portal navigation help with verified EquityPay links (no account actions)

Bilingual toggle: English 🇺🇸 / Español 🇪🇸

PHI guardrails: regex blocks SSN/DOB/account # → safe redirect

Optional voice input (microphone widget)

Session memory via Streamlit state

Optional RAG grounding against a local KB (FAISS index + SQLite text)

Tech Stack

Frontend: Streamlit

LLM: OpenAI gpt-4o-mini (chat), text-embedding-3-small (embeddings for RAG)

RAG (optional): FAISS (vector index) + SQLite (chunk store)

Auth & logs: SQLite (users, chat_logs), bcrypt (password hashing)

Voice input: streamlit-mic-recorder

Repo Structure (key files)
.
├─ main.py                  # Streamlit app (chat UI, routing, guardrails, logging)
├─ kb_runtime.py            # RAG helper (FAISS + SQLite loader & lookup)
├─ db_utils.py              # SQLite init & log helpers
├─ config.py                # Links & notes (EQUITYPAY_LINKS, KNOWLEDGE_NOTE)
├─ requirements.txt
└─ data/
   ├─ kb.faiss              # (optional) FAISS index file for RAG
   └─ kb.sqlite             # (optional) SQLite with chunk texts

Prerequisites

Python 3.10+

OpenAI API key with access to gpt-4o-mini & text-embedding-3-small

If using RAG: put data/kb.faiss and data/kb.sqlite in place (see below)

Quickstart (Local)

Clone & enter

git clone <your-repo-url>
cd <your-repo-folder>


Create venv & install

python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt


Set API key (either works)

.env file (local dev):

OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxx


OR export in shell:

export OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxx   # Windows: set OPENAI_API_KEY=...


(Optional) RAG files
Place your data/kb.faiss and data/kb.sqlite.

If these files are missing, kb_runtime.py will raise an error when retrieval is called. For a demo without RAG, keep the app but set k=0 inside the retrieve_context(...) call or temporarily comment the call in main.py.

Run

streamlit run main.py


Open browser (Streamlit will show a local URL)

Deploy on Streamlit Cloud

Push your repo to GitHub.

On share.streamlit.io
, create a new app → pick your repo/branch.

Secrets → add:

OPENAI_API_KEY="sk-xxxxxxxxxxxxxxxx"


(Optional RAG): upload data/kb.faiss and data/kb.sqlite to the repo (public) or host them privately and adjust kb_runtime.py to fetch at startup.

Deploy. Grant Microphone permission in the browser for voice input.

Configuration

EquityPay links & banner note → config.py
Update EQUITYPAY_LINKS keys (pay_bill, bill_explained, insurance_info, financial_support, contact, login) and KNOWLEDGE_NOTE.

Guardrails → PHI_PATTERN in main.py
Add additional patterns if needed.

Auth & Logs DB → db_utils.py creates chat_logs, user_chat_logs, and users (bcrypt-hashed).

Voice Input (Optional)

Requires streamlit-mic-recorder

In requirements.txt:

streamlit-mic-recorder


In main.py, the app imports:

from st_mic_recorder import mic_recorder, speech_to_text


Browser must allow microphone access. On Streamlit Cloud, use HTTPS.

Knowledge Base / RAG (Optional)

kb_runtime.py expects:

data/kb.faiss — FAISS index (inner product / cosine-like search)

data/kb.sqlite — table with chunk text (content/text/chunk_text)

The app calls retrieve_context(question, k=3) to add short grounded snippets into the system prompt.

To rebuild FAISS/SQLite, prepare embeddings with text-embedding-3-small, store vectors in FAISS and source text in SQLite (maintain a consistent rowid/id↔index mapping).

Security Notes

No PHI processed — messages containing SSN/DOB/account # are blocked and redirected to verified portal links.

API keys live in .env (local) or Streamlit Secrets (cloud) — never hardcode.

For enterprise compliance (HIPAA/SOC2), deploy in a controlled cloud (e.g., Azure) with formal policies, VPC, audit logging, and vendor BAAs.

Demo Prompts

Typing

“What is a deductible?”

“Explain coinsurance vs. copay in simple words.”

“Where do I go to set up a payment plan?”

Mic

“How do I see my statement and due date?”

“What is an out-of-pocket maximum?”

RAG (if KB present)

“Summarize the payment assistance steps mentioned in the SRP guide.”

“Where does EquityPay show financial support options?”

Troubleshooting

OPENAI_API_KEY is missing
Add to .env (local) or Secrets (Streamlit Cloud). Restart app.

FAISS index not found at data/kb.faiss
Add data/kb.faiss & data/kb.sqlite or temporarily set k=0 / comment the retrieval call.

Mic widget not available / None
Ensure streamlit-mic-recorder is in requirements.txt, rebuild, and allow microphone permission in the browser.

Repeated mic transcriptions
Use a single speech_to_text widget and gate it with a conditional so you append at most once per activation.

Model not found / permissions
Confirm your key supports gpt-4o-mini and text-embedding-3-small.

License

MIT (or your preferred license)

Credits

Built by Team B — Nishit Mistry (PM), Atharva Sathaye, Akshay Wagh, Jasmitha Duvvuru, Juhi Khare.
Special thanks to Salud Revenue Partners for domain guidance.
