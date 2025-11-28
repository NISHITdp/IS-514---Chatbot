import os
import re
import time
import json
from typing import Dict, Any
from datetime import datetime
import bcrypt
import pandas as pd

from dotenv import load_dotenv
import streamlit as st
from openai import OpenAI
import sqlite3

import sys, os
_HERE = os.path.dirname(__file__)
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

API_KEY = st.secrets.get("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")
if not API_KEY:
    st.error("OPENAI_API_KEY is missing. Add it in Streamlit > Settings > Secrets.")
    st.stop()
client = OpenAI(api_key=API_KEY)


from kb_runtime import retrieve_context
from config import EQUITYPAY_LINKS, KNOWLEDGE_NOTE
from db_utils import init_db, log_chat_interaction, log_user_chat_interaction, create_user, fetch_user_chat_history, DB_PATH

# -------------------------------------------------------------------
# Environment & OpenAI client
# -------------------------------------------------------------------
def _is_bcrypt_hash(s: str) -> bool:
    return isinstance(s, str) and s.startswith("$2") and len(s) >= 40


def _fetch_logs(table: str, limit: int = 50):
    cols = {
        "chat_logs": """id, created_at, language, intent, needs_escalation, portal_link_key,
                        user_message, assistant_message, response_time_ms""",
        "user_chat_logs": """id, created_at, language, intent, needs_escalation, portal_link_key,
                             user_name, user_email, user_message, assistant_message, response_time_ms"""
    }
    q = f"SELECT {cols[table]} FROM {table} ORDER BY id DESC LIMIT ?;"
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(q, (limit,))
    rows = cur.fetchall()
    headers = [c.strip() for c in cols[table].split(",")]
    conn.close()
    return headers, rows

def fetch_df(table: str, limit: int) -> pd.DataFrame:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(f"SELECT * FROM {table} ORDER BY id DESC LIMIT ?;", (limit,))
    rows = cur.fetchall()
    cols = [d[0] for d in cur.description]  # <- real column names from SQLite
    conn.close()
    return pd.DataFrame(rows, columns=cols)


for k in list(os.environ.keys()):
    if "PROXY" in k.upper() or k in ("OPENAI_PROXY", "OPENAI_HTTP_PROXY"):
        os.environ.pop(k, None)

# load_dotenv()
# api_key = os.getenv("OPENAI_API_KEY")

st.set_page_config(
    page_title="SRP Billing Assistant (MVP)",
    page_icon="💬",
    layout="centered",
)

# if not api_key:
#     st.error("OPENAI_API_KEY not found. Add it to your .env at project root.")
#     st.stop()

client = OpenAI(api_key=api_key)

# Initialize DB (creates tables if not exist)
init_db()

# Create users auth table if not exists
conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()
cur.execute(
    """
    CREATE TABLE IF NOT EXISTS users (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
        user_name    TEXT NOT NULL,
        user_email   TEXT UNIQUE NOT NULL,
        user_password TEXT NOT NULL
    );
    """
)
conn.commit()
conn.close()

# -------------------------------------------------------------------
# Sidebar UI & Forms control
# -------------------------------------------------------------------

st.sidebar.title("SRP Assistant")
st.sidebar.markdown(
    "⚠️ Privacy Notice: No personal identifiers allowed. Only general billing and insurance guidance will be provided."
)

# Show session status if authenticated
if st.session_state.get("user_email"):
    st.sidebar.success(f"Logged in as: {st.session_state.get('user_name','User')}")

    # --- Logout button (shown only when logged in) ---
    if st.sidebar.button("Logout"):
        # clear auth + any open forms
        st.session_state.pop("user_name", None)
        st.session_state.pop("user_email", None)
        st.session_state.show_login_form = False
        st.session_state.show_create_form = False

        # (optional) also clear chat history on logout:
        # st.session_state.pop("messages", None)

        st.rerun()
else:
    # Auth buttons only when NOT logged in
    if st.sidebar.button("Login"):
        st.session_state.show_login_form = True
        st.session_state.show_create_form = False
    if st.sidebar.button("Create Account"):
        st.session_state.show_create_form = True
        st.session_state.show_login_form = False


lang = st.sidebar.radio("Language / Idioma", options=["English", "Español"], index=0)

st.sidebar.markdown("---")
st.sidebar.subheader("Portal Access")

if "show_login_form" not in st.session_state:
    st.session_state.show_login_form = False
if "show_create_form" not in st.session_state:
    st.session_state.show_create_form = False

# if not st.session_state.get("user_email"):
#     if st.sidebar.button("Login"):
#         st.session_state.show_login_form = True
#         st.session_state.show_create_form = False
#     if st.sidebar.button("Create Account"):
#         st.session_state.show_create_form = True
#         st.session_state.show_login_form = False

# -------------------------------------------------------------------
# Auth Forms
# -------------------------------------------------------------------

# Login
if st.session_state.show_login_form:
    st.sidebar.markdown("### Login")
    with st.sidebar.form("login_form", clear_on_submit=False):
        user_name = st.text_input("Name")
        user_email = st.text_input("Email")
        user_password = st.text_input("Password", type="password")
        submit_login = st.form_submit_button("Login")

    if submit_login:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()

        # ensure scalars for SQL
        user_email = user_email.strip()
        user_name = user_name.strip()
        user_password = user_password.strip()

        cur.execute(
            "SELECT user_password FROM users WHERE user_email = ? AND user_name = ?;",
            (user_email, user_name)
        )
        row = cur.fetchone()
        conn.close()

        if row is None:
            st.sidebar.error("No user found with these details.")
        else:
            stored_hash = row[0]
            ok = False
            rehash = False

            if _is_bcrypt_hash(stored_hash):
                # New accounts (bcrypt)
                ok = bcrypt.checkpw(user_password.encode("utf-8"), stored_hash.encode("utf-8"))
            else:
                # Legacy accounts (plain text stored) — compare directly, then migrate
                ok = (stored_hash == user_password)
                rehash = ok

            if ok:
                # If legacy, upgrade to bcrypt now
                if rehash:
                    try:
                        new_hash = bcrypt.hashpw(user_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
                        conn = sqlite3.connect(DB_PATH)
                        cur = conn.cursor()
                        cur.execute(
                            "UPDATE users SET user_password = ? WHERE user_email = ? AND user_name = ?;",
                            (new_hash, user_email, user_name),
                        )
                        conn.commit()
                        conn.close()
                    except Exception:
                        pass  # login still proceeds even if migration update fails

                st.session_state.user_name = user_name
                st.session_state.user_email = user_email

                # >>> hydrate prior chats <<<
                rows = fetch_user_chat_history(user_email, limit=200)
                st.session_state.messages = []
                for _, user_m, asst_m in rows:
                    if user_m:
                        st.session_state.messages.append({"role": "user", "content": user_m})
                    if asst_m:
                        st.session_state.messages.append({"role": "assistant", "content": asst_m})
                st.session_state.history_loaded_for = user_email
                # <<< hydrate prior chats >>>

                st.toast("Authenticated")
                st.session_state.show_login_form = False
                st.session_state.show_create_form = False
            else:
                st.sidebar.error("Incorrect password")


# Create Account
if st.session_state.show_create_form:
    st.sidebar.markdown("### Create Account")
    with st.sidebar.form("create_form", clear_on_submit=False):
        new_name = st.text_input("Name")
        new_email = st.text_input("Email")
        new_password = st.text_input("Password", type="password")
        submit_create = st.form_submit_button("Create")

    if submit_create:
        new_name = new_name.strip()
        new_email = new_email.strip()
        new_password = new_password.strip()

        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT id FROM users WHERE user_email = ?;", (new_email,))
        exists = cur.fetchone()
        conn.close()

        if exists:
            st.sidebar.error("User already exists, please login instead.")
        else:
            create_user(new_name, new_email, new_password)  # <-- Now hashing will happen

            st.session_state.user_name = new_name
            st.session_state.user_email = new_email
            st.toast("Authenticated")
            st.session_state.show_login_form = False
            st.session_state.show_create_form = False



# -------------------------------------------------------------------
# Quick portal links (preserve original modal logic)
# -------------------------------------------------------------------

st.sidebar.markdown("---")
if st.sidebar.button("Quick Portal Links"):
    portal_links_html = f"""
    <div style="padding:15px;border-radius:10px;background:#111;">
        <p>{EQUITYPAY_LINKS.get("pay_bill","")}</p>
        <p>{EQUITYPAY_LINKS.get("bill_explained","")}</p>
        <p>{EQUITYPAY_LINKS.get("insurance_info","")}</p>
        <p>{EQUITYPAY_LINKS.get("financial_support","")}</p>
        <p>{EQUITYPAY_LINKS.get("contact","")}</p>
    </div>
    """
    st.sidebar.markdown(portal_links_html, unsafe_allow_html=True)

# -------------------------------------------------------------------
# Router & Guardrails
# -------------------------------------------------------------------

PHI_PATTERN = re.compile(
    r"(account\s*number|ssn|social\s*security|dob|policy\s*number|member\s*id)",
    re.I,
)

# SYSTEM_EN = "You are SRP Billing Assistant. Keep responses simple."
# SYSTEM_ES = "Eres el asistente de facturación SRP. Explica simple y claro."
SYSTEM_EN = (
    "You are the SRP Billing & Insurance Assistant for patients. "
    "Explain in 4th-grade level English. Be brief, kind, and specific. "
    "Topics: understanding bills, insurance basics (deductible, copay, coinsurance, OOP max), "
    "what to do next, and where to click in the portal. "
    "Never ask for or process personal identifiers (account #, SSN, DOB). "
    "If the user asks for actions that require personal info or you are unsure, "
)

SYSTEM_ES = (
    "Eres el Asistente de Facturación y Seguros de SRP para pacientes. "
    "Explica en español sencillo (nivel primaria). Sé breve, amable y específico. "
    "Temas: entender la factura, conceptos de seguro (deducible, copago, coseguro, máximo de gasto), "
    "qué hacer después y a dónde ir en el portal. "
    "Nunca pidas datos personales (número de cuenta, SSN, fecha de nacimiento). "
    "Si la pregunta requiere datos personales o hay duda, "
)

SYSTEM = SYSTEM_ES if lang == "Español" else SYSTEM_EN

ROUTER_SCHEMA = """
You are a strict JSON router. Return ONLY a JSON object with keys:
- intent: one of ["payment_help","portal_navigation","cost_estimate","sensitive_info","other"]
- needs_escalation: boolean
- portal_link_key: one of ["pay_bill","bill_explained","insurance_info","financial_support","contact","login",""]
- brief_reason: short string

Routing rules:
- Payment/bill/amount/“pay my bill” → intent="payment_help", portal_link_key="pay_bill"
- “Where do I click”, “portal link”, “how to pay online”, “make payment” → intent="portal_navigation", portal_link_key="pay_bill"
- Definitions of deductible/copay/coinsurance/OOP/insurance basics → intent="other", portal_link_key=""
- “financial help”, “assistance program” → intent="portal_navigation", portal_link_key="financial_support"
- “call someone”, “support number”, “who to contact” → intent="portal_navigation", portal_link_key="contact"
- “login”, “can’t login”, “password reset” → intent="portal_navigation", portal_link_key="login"
- If the user mentions account #, SSN, DOB, policy/member ID → intent="sensitive_info", needs_escalation=true, portal_link_key="login"
- Otherwise → intent="other", portal_link_key=""

Return pure JSON. No prose, no code fences.
"""


def route_intent(message: str, language: str) -> Dict[str, Any]:
    try:
        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0,
            messages=[
                {"role": "system", "content": ROUTER_SCHEMA},
                {"role": "user", "content": f"Language: {language}\nMessage: {message}"}
            ],
        )
        raw = completion.choices[0].message.content.strip()
        # guard against accidental code fences
        if raw.startswith("```"):
            import re as _re
            raw = _re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=_re.S)
        parsed = json.loads(raw)
        # normalize any list-y weirdness
        if isinstance(parsed.get("intent"), list):
            parsed["intent"] = parsed["intent"][0] if parsed["intent"] else "other"
        if isinstance(parsed.get("portal_link_key"), list):
            parsed["portal_link_key"] = parsed["portal_link_key"][0] if parsed["portal_link_key"] else ""
        if parsed.get("intent") not in ["payment_help","portal_navigation","cost_estimate","sensitive_info","other"]:
            parsed["intent"] = "other"
        if parsed.get("portal_link_key") not in ["pay_bill","bill_explained","insurance_info","financial_support","contact","login",""]:
            parsed["portal_link_key"] = ""
        if not isinstance(parsed.get("needs_escalation"), bool):
            parsed["needs_escalation"] = False
        return parsed
    except Exception:
        return {"intent": "other", "needs_escalation": False, "portal_link_key": "", "brief_reason": "fallback"}

# -------------------------------------------------------------------
# Main Chat UI (preserve original core QA + DB logging)
# -------------------------------------------------------------------

st.title("💬 SRP Billing Assistant")
st.caption(KNOWLEDGE_NOTE)

if "messages" not in st.session_state:
    st.session_state.messages = []

for m in st.session_state.messages:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])

user_msg = st.chat_input("Ask me anything about your bill or insurance...")

if user_msg:
    st.session_state.messages.append({"role": "user", "content": user_msg})

    language_label = "Spanish" if lang == "Español" else "English"

    # Guardrail
    if PHI_PATTERN.search(user_msg):
        block_response = f"Please login via portal: {EQUITYPAY_LINKS.get('login','')}"
        st.session_state.messages.append({"role": "assistant", "content": block_response})

        log_chat_interaction(
            language=language_label,
            intent="sensitive_info",
            needs_escalation=True,
            portal_link_key="login",
            user_message=user_msg,
            assistant_message=block_response,
            response_time_ms=0,
        )
        st.rerun()

    route = route_intent(user_msg, language_label)
    intent = route.get("intent","other")

    nav_key = route.get("portal_link_key") or ""
    if isinstance(nav_key, list):
        nav_key = nav_key[0] if nav_key else ""

    # Escalation / Portal navigation branch (log + rerun)
    if route.get("needs_escalation") or (intent in ["payment_help","portal_navigation"] and nav_key):
        portal_target = EQUITYPAY_LINKS.get(nav_key,"") or EQUITYPAY_LINKS.get("contact","")
        redirect_text = f"Go to portal: {portal_target}" if lang=="English" else f"Visita el portal: {portal_target}"

        st.session_state.messages.append({"role": "assistant","content": redirect_text})

        # log generalized nav
        log_chat_interaction(
            language=language_label,
            intent=intent,
            needs_escalation=False,
            portal_link_key=nav_key,
            user_message=user_msg,
            assistant_message=redirect_text,
            response_time_ms=0,
        )
        st.rerun()

    # Normal answer branch (with DB logging)
    else:
        api_start = time.time()
        try:
            use_rag = intent not in ["payment_help", "portal_navigation", "sensitive_info"]

            # fetch up to 3 helpful snippets
            kb_chunks = retrieve_context(user_msg, k=3) if use_rag else []
            kb_context = "\n\n".join(f"- {c}" for c in kb_chunks) if kb_chunks else ""

            # build system prompt with optional KB context
            base_system = SYSTEM
            if kb_context:
                base_system += (
                    "\n\nYou also have the following notes from SRP’s billing/insurance guide. "
                    "Use them to keep answers accurate and concrete. Do not invent facts.\n"
                    f"{kb_context}\n"
                )
            llm = client.chat.completions.create(
                model="gpt-4o-mini",
                temperature=0.3,
                messages=[{"role":"system","content":base_system}] + st.session_state.messages,
            )
            assistant_text = llm.choices[0].message.content
        except Exception as e:
            assistant_text = f"OpenAI Error: {e}"
        elapsed_ms = int((time.time() - api_start) * 1000)

        st.session_state.messages.append({"role":"assistant","content":assistant_text})

        # Log to correct table based on auth state
        if "user_email" in st.session_state and st.session_state.get("user_email"):
            # Logged in user interaction
            log_user_chat_interaction(
                user_name=st.session_state.get("user_name",""),
                user_email=st.session_state.get("user_email",""),
                language=language_label,
                intent=intent,
                needs_escalation=False,
                portal_link_key=nav_key,
                user_message=user_msg,
                assistant_message=assistant_text,
                response_time_ms=elapsed_ms,
            )
        else:
            # Anonymous/general interaction
            log_chat_interaction(
                language=language_label,
                intent=intent,
                needs_escalation=False,
                portal_link_key=nav_key,
                user_message=user_msg,
                assistant_message=assistant_text,
                response_time_ms=elapsed_ms,
            )

        st.rerun()

# -------------------------------------------------------------------
# Debug utility view (optional, preserves earlier admin intent)
# -------------------------------------------------------------------

if st.sidebar.button("View row count"):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM chat_logs;")
    general_count = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM users;")
    user_count = cur.fetchone()[0]
    conn.close()
    st.sidebar.markdown(f"chat_logs rows: {general_count}\nusers rows: {user_count}")


st.sidebar.markdown("---")
with st.sidebar.expander("Admin: Recent Logs", expanded=False):
    table = st.selectbox(
        "Table",
        ["chat_logs", "user_chat_logs"],   # avoid exporting the users table
        index=0,
        key="tbl_sel"
    )
    limit = st.number_input("How many rows?", min_value=10, max_value=500, value=50, step=10, key="row_lim")

    if st.button("Show logs", key="show_logs_btn"):
        df = fetch_df(table, int(limit))
        st.session_state["admin_df"] = df
        st.session_state["admin_df_table"] = table

    df = st.session_state.get("admin_df")
    shown_from = st.session_state.get("admin_df_table")

    if df is not None and shown_from == table:
        st.caption(f"Last {len(df)} rows from `{table}`")
        st.dataframe(df, use_container_width=True)

        csv_bytes = df.to_csv(index=False).encode("utf-8")  # headers + no numeric index
        fname = datetime.now().strftime(f"%Y-%m-%dT%H-%M_export_{table}.csv")
        st.download_button(
            "Download CSV",
            data=csv_bytes,
            file_name=fname,
            mime="text/csv",
            key="dl_logs_btn"
        )
