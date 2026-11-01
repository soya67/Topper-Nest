"""Topper Nest - complete version (v2)

Pages: Home, Syllabus, Planner, Practice, Mistakes, Notes, AI Tutor,
English Coach, Study Videos, Music, Files, Calculator, Usage Stats.

Run:
    pip install streamlit pandas anthropic
    streamlit run app.py
"""
import ast
import base64
import hashlib
import hmac
import html
import json
import math
import operator
import os
import re
import shutil
import sqlite3
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

LEGACY_DB = "topper_nest.db"  # data saved before accounts existed
USERS_DB = "users.db"  # login details of every account
DATA_DIR = Path("users_data")  # one private folder per account
MODEL = "claude-sonnet-5-5"  # change here if you want another model
DEFAULT_DAILY_LIMIT = 30  # AI messages per day (keeps API cost under control)
IDLE_CAP = 300  # seconds; long idle gaps are not counted as study time

PAGES = [
    "Home", "Syllabus", "Planner", "Practice", "Mistakes", "Notes",
    "AI Tutor", "English Coach", "Study Videos", "Music", "Files",
    "Calculator", "Usage Stats", "Profile",
]
STATUSES = ["Not started", "Studying", "Done"]
QTYPES = ["Objective (MCQ)", "Numerical", "Subjective"]
DIFFS = ["Easy", "Medium", "Hard", "Trap"]


# ====================== database helpers ======================
def user_dir():
    d = DATA_DIR / st.session_state["user"]
    d.mkdir(parents=True, exist_ok=True)
    return d


def files_dir():
    d = user_dir() / "saved_files"
    d.mkdir(exist_ok=True)
    return d


def songs_dir():
    d = user_dir() / "songs"
    d.mkdir(exist_ok=True)
    return d


def db():
    return sqlite3.connect(user_dir() / "topper_nest.db")


def urun(sql, params=()):
    c = sqlite3.connect(USERS_DB)
    try:
        with c:
            c.execute(sql, params)
    finally:
        c.close()


def urows(sql, params=()):
    c = sqlite3.connect(USERS_DB)
    try:
        return c.execute(sql, params).fetchall()
    finally:
        c.close()


def run(sql, params=()):
    c = db()
    try:
        with c:
            c.execute(sql, params)
    finally:
        c.close()


def rows(sql, params=()):
    c = db()
    try:
        return c.execute(sql, params).fetchall()
    finally:
        c.close()


def now_text():
    return datetime.now().isoformat(timespec="minutes")


def init_db():
    files_dir()
    songs_dir()
    statements = [
        """CREATE TABLE IF NOT EXISTS notes(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject TEXT, title TEXT, body TEXT, created TEXT)""",
        """CREATE TABLE IF NOT EXISTS mistakes(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject TEXT, question TEXT, my_answer TEXT,
            correct_answer TEXT, fixed INTEGER DEFAULT 0, created TEXT)""",
        """CREATE TABLE IF NOT EXISTS usage(
            day TEXT, feature TEXT,
            seconds REAL DEFAULT 0, opens INTEGER DEFAULT 0,
            PRIMARY KEY (day, feature))""",
        """CREATE TABLE IF NOT EXISTS topics(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject TEXT, topic TEXT, status TEXT DEFAULT 'Not started',
            updated TEXT)""",
        """CREATE TABLE IF NOT EXISTS goals(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            day TEXT, text TEXT, done INTEGER DEFAULT 0)""",
        """CREATE TABLE IF NOT EXISTS questions(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject TEXT, qtype TEXT, difficulty TEXT,
            question TEXT, options TEXT, answer TEXT)""",
        """CREATE TABLE IF NOT EXISTS attempts(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            qid INTEGER, correct INTEGER, day TEXT)""",
        """CREATE TABLE IF NOT EXISTS videos(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT, subject TEXT, url TEXT)""",
        """CREATE TABLE IF NOT EXISTS songs(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT, source TEXT)""",
        """CREATE TABLE IF NOT EXISTS files(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT, subject TEXT, path TEXT, created TEXT)""",
        """CREATE TABLE IF NOT EXISTS ai_calls(
            day TEXT PRIMARY KEY, count INTEGER DEFAULT 0)""",
    ]
    for s in statements:
        run(s)


# ====================== usage tracking ======================
def track(page):
    """Add the time since the last click to the page the student was on."""
    now = time.time()
    prev = st.session_state.get("page")
    last = st.session_state.get("last_tick", now)
    today = date.today().isoformat()
    if prev:
        run(
            """INSERT INTO usage(day, feature, seconds, opens) VALUES(?,?,?,0)
               ON CONFLICT(day, feature) DO UPDATE SET seconds = seconds + excluded.seconds""",
            (today, prev, min(now - last, IDLE_CAP)),
        )
    if page != prev:
        run(
            """INSERT INTO usage(day, feature, seconds, opens) VALUES(?,?,0,1)
               ON CONFLICT(day, feature) DO UPDATE SET opens = opens + 1""",
            (today, page),
        )
    st.session_state.page = page
    st.session_state.last_tick = now


# ====================== AI helpers ======================
def ai_calls_today():
    r = rows("SELECT count FROM ai_calls WHERE day=?", (date.today().isoformat(),))
    return r[0][0] if r else 0


def ask_ai(messages, system):
    """Returns (text, error). Error is None when everything worked."""
    key = st.session_state.get("api_key") or os.getenv("ANTHROPIC_API_KEY")
    if not key:
        return None, "Paste your Claude API key in the left sidebar first."
    limit = int(st.session_state.get("ai_limit", DEFAULT_DAILY_LIMIT))
    if ai_calls_today() >= limit:
        return None, f"Daily AI limit ({limit}) reached. Raise it in the sidebar or try tomorrow."
    try:
        import anthropic
    except ImportError:
        return None, "Run this in the terminal first:  pip install anthropic"
    try:
        client = anthropic.Anthropic(api_key=key)
        resp = client.messages.create(
            model=MODEL, max_tokens=1000, system=system, messages=messages
        )
        run(
            """INSERT INTO ai_calls(day, count) VALUES(?,1)
               ON CONFLICT(day) DO UPDATE SET count = count + 1""",
            (date.today().isoformat(),),
        )
        return resp.content[0].text, None
    except Exception as e:
        return None, f"AI error: {e}"


def chat_ui(history_key, system, intro):
    st.caption(intro)
    hist = st.session_state.setdefault(history_key, [])
    for m in hist:
        with st.chat_message(m["role"]):
            st.write(m["content"])
    prompt = st.chat_input("Type your message")
    if prompt:
        hist.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.write(prompt)
        with st.chat_message("assistant"):
            reply, err = ask_ai(hist, system)
            if err:
                hist.pop()
                st.error(err)
            else:
                hist.append({"role": "assistant", "content": reply})
                st.write(reply)
    if hist and st.button("Clear chat", key=f"clear_{history_key}"):
        st.session_state[history_key] = []
        st.rerun()


def parse_json_list(text):
    text = text.strip()
    start, end = text.find("["), text.rfind("]")
    return json.loads(text[start:end + 1])


# ====================== safe calculator ======================
OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.Pow: operator.pow, ast.Mod: operator.mod,
    ast.FloorDiv: operator.floordiv, ast.USub: operator.neg, ast.UAdd: operator.pos,
}
MATH_FUNCS = {k: getattr(math, k) for k in dir(math)
              if not k.startswith("_") and callable(getattr(math, k))}
MATH_CONSTS = {"pi": math.pi, "e": math.e, "tau": math.tau}


def safe_eval(node):
    if isinstance(node, ast.Expression):
        return safe_eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in OPS:
        left, right = safe_eval(node.left), safe_eval(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > 1000:
            raise ValueError("exponent too large")
        return OPS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in OPS:
        return OPS[type(node.op)](safe_eval(node.operand))
    if isinstance(node, ast.Name) and node.id in MATH_CONSTS:
        return MATH_CONSTS[node.id]
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id in MATH_FUNCS and not node.keywords):
        return MATH_FUNCS[node.func.id](*[safe_eval(a) for a in node.args])
    raise ValueError("not allowed")


# ====================== look and feel ======================
THEME_TOML = """[theme]
base = "light"
primaryColor = "#2f8f46"
backgroundColor = "#f3f9f5"
secondaryBackgroundColor = "#e3f0e7"
textColor = "#0f2a1f"
"""

CSS = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
:root{--forest:#0a2e1f;--forest2:#0f3d2a;--green:#2f8f46;--mint:#7fd69a;--ink:#0f2a1f;}
html,body,.stApp,.stApp p,.stApp label,.stApp li,.stApp h1,.stApp h2,.stApp h3,.stApp h4,button,input,textarea,[data-baseweb]{font-family:'Inter',system-ui,'Segoe UI',Roboto,sans-serif !important}
@keyframes glassIn{from{opacity:0;transform:translateY(12px) scale(.985)}to{opacity:1;transform:none}}
@keyframes bgshift{from{background-position:0% 0%,100% 0%,50% 100%}to{background-position:10% 16%,90% 12%,42% 90%}}
@keyframes sweep{0%{left:-60%}55%,100%{left:140%}}
@property --p{syntax:'<number>';inherits:false;initial-value:0;}
@keyframes fillring{from{--p:0}}
.stApp{background-color:#f3f9f5;color:var(--ink);background-image:radial-gradient(800px 520px at 8% -8%,rgba(47,143,70,.30),transparent 62%),radial-gradient(760px 520px at 100% 6%,rgba(127,214,154,.36),transparent 62%),radial-gradient(900px 560px at 45% 115%,rgba(10,46,31,.20),transparent 60%);background-size:140% 140%;background-attachment:fixed;animation:bgshift 24s ease-in-out infinite alternate}
[data-testid="stHeader"]{background:transparent}
[data-testid="stAppDeployButton"],#MainMenu,footer{display:none !important}
[data-testid="stElementContainer"],.element-container{animation:glassIn .5s ease backwards}
.block-container h1,.block-container h2,.block-container h3,.block-container h4,.block-container label,.block-container li,.block-container [data-testid="stMarkdownContainer"] p{color:var(--ink)}
.block-container h1,.block-container h2,.block-container h3{letter-spacing:-.02em;font-weight:700}
[data-testid="stSidebar"]{background-image:linear-gradient(185deg,#0a2e1f 0%,#0f3d2a 55%,#14532d 100%);border-right:1px solid rgba(255,255,255,.08)}
[data-testid="stSidebar"] p,[data-testid="stSidebar"] label,[data-testid="stSidebar"] span,[data-testid="stSidebar"] small,[data-testid="stSidebar"] h1,[data-testid="stSidebar"] h2,[data-testid="stSidebar"] h3{color:#e9f6ee !important}
[data-testid="stSidebar"] [role="radiogroup"]{gap:4px}
[data-testid="stSidebar"] [role="radiogroup"] label{padding:9px 14px;margin:0;border-radius:12px;border:1px solid transparent;transition:all .25s ease}
[data-testid="stSidebar"] [role="radiogroup"] label:hover{background:rgba(255,255,255,.08);border-color:rgba(255,255,255,.14);transform:translateX(3px)}
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked){background:rgba(255,255,255,.14);border-color:rgba(127,214,154,.55);box-shadow:inset 0 1px 0 rgba(255,255,255,.18),0 6px 18px rgba(0,0,0,.18);-webkit-backdrop-filter:blur(8px);backdrop-filter:blur(8px)}
[data-testid="stSidebar"] input{background:transparent !important;color:#fff !important}
[data-testid="stSidebar"] div[data-baseweb="input"]{background:rgba(255,255,255,.08);border:1px solid rgba(255,255,255,.18);border-radius:10px}
.brand{display:flex;align-items:center;gap:11px;font-size:1.3rem;font-weight:800;letter-spacing:-.02em;color:#fff;padding:6px 4px 16px}
.brand .logo{width:32px;height:32px;border-radius:10px;background-image:linear-gradient(135deg,#9ee6b4,#2f8f46);box-shadow:0 6px 16px rgba(0,0,0,.28),inset 0 1px 0 rgba(255,255,255,.5)}
.brand small{display:block;font-size:.72rem;font-weight:500;opacity:.75;letter-spacing:0}
.hero{position:relative;overflow:hidden;text-align:center;padding:56px 34px 48px;border-radius:30px;color:#fff;background-image:radial-gradient(600px 300px at 15% 0%,rgba(127,214,154,.38),transparent 60%),radial-gradient(500px 300px at 95% 100%,rgba(47,143,70,.55),transparent 60%),linear-gradient(135deg,#0a2e1f,#0f3d2a 55%,#14532d);border:1px solid rgba(255,255,255,.14);box-shadow:0 24px 60px rgba(10,46,31,.35),inset 0 1px 0 rgba(255,255,255,.2);animation:glassIn .7s ease backwards;margin-bottom:22px}
.hero::after{content:"";position:absolute;top:0;left:-60%;width:40%;height:100%;background:linear-gradient(100deg,transparent,rgba(255,255,255,.10),transparent);transform:skewX(-20deg);animation:sweep 7s ease-in-out infinite;pointer-events:none}
.badge{display:inline-block;padding:7px 16px;border-radius:999px;font-size:.85rem;font-weight:600;background:rgba(255,255,255,.12);border:1px solid rgba(255,255,255,.28);-webkit-backdrop-filter:blur(8px);backdrop-filter:blur(8px);color:#d9f5e3}
.hero-title{font-size:3.1rem;line-height:1.08;font-weight:800;letter-spacing:-.035em;margin:20px 0 10px;color:#fff}
.grad{background-image:linear-gradient(90deg,#9ee6b4,#ffffff 75%);-webkit-background-clip:text;background-clip:text;color:transparent}
.hero-sub{font-size:1.1rem;color:rgba(255,255,255,.82);max-width:640px;margin:0 auto}
.ph{margin:4px 0 18px;animation:glassIn .5s ease backwards}
.ph .t{font-size:2.5rem;font-weight:800;letter-spacing:-.03em;line-height:1.1;display:inline-block;background-image:linear-gradient(90deg,#0a2e1f,#2f8f46);-webkit-background-clip:text;background-clip:text;color:transparent}
.ph .s{opacity:.7;margin-top:6px;font-size:1.02rem}
.ph .bar{width:54px;height:4px;border-radius:4px;margin-top:12px;background-image:linear-gradient(90deg,#2f8f46,#7fd69a)}
.rings{display:flex;gap:46px;flex-wrap:wrap;justify-content:center;padding:26px;margin:6px 0 18px;border-radius:24px;background:rgba(255,255,255,.55);-webkit-backdrop-filter:blur(18px) saturate(150%);backdrop-filter:blur(18px) saturate(150%);border:1px solid rgba(255,255,255,.8);box-shadow:0 10px 34px rgba(15,61,42,.10),inset 0 1px 0 rgba(255,255,255,.9)}
.ringbox{text-align:center}
.ringwrap{position:relative;width:124px;height:124px;margin:0 auto}
.ring{width:124px;height:124px;border-radius:50%;background:conic-gradient(#2f8f46,#7fd69a calc(var(--p)*1%),rgba(15,61,42,.12) 0);-webkit-mask:radial-gradient(farthest-side,transparent calc(100% - 13px),#000 calc(100% - 12px));mask:radial-gradient(farthest-side,transparent calc(100% - 13px),#000 calc(100% - 12px));animation:fillring 1.4s ease-out}
.ringlabel{position:absolute;inset:0;display:grid;place-items:center;font-size:1.4rem;font-weight:800;color:var(--ink)}
.ringcap{margin-top:8px;font-weight:600;color:var(--ink);opacity:.8}
[data-testid="stMetric"],[data-testid="stExpander"],[data-testid="stForm"]{position:relative;overflow:hidden;background:rgba(255,255,255,.55);-webkit-backdrop-filter:blur(18px) saturate(150%);backdrop-filter:blur(18px) saturate(150%);border:1px solid rgba(255,255,255,.8);border-radius:20px;box-shadow:0 10px 34px rgba(15,61,42,.10),inset 0 1px 0 rgba(255,255,255,.9);transition:transform .3s ease,box-shadow .3s ease,border-color .3s ease}
[data-testid="stMetric"]{padding:16px 20px}
[data-testid="stExpander"] details{border:none !important;background:transparent}
[data-testid="stMetric"]:hover,[data-testid="stExpander"]:hover{transform:translateY(-3px);border-color:rgba(47,143,70,.5);box-shadow:0 18px 44px rgba(15,61,42,.18),inset 0 1px 0 rgba(255,255,255,.9)}
[data-testid="stMetric"]::after,[data-testid="stExpander"]::after{content:"";position:absolute;top:0;left:-130%;width:55%;height:100%;background:linear-gradient(100deg,transparent,rgba(255,255,255,.65),transparent);transform:skewX(-18deg);transition:left .9s ease;pointer-events:none}
[data-testid="stMetric"]:hover::after,[data-testid="stExpander"]:hover::after{left:150%}
.stButton>button,.stFormSubmitButton>button,.stDownloadButton>button{position:relative;overflow:hidden;width:100%;border-radius:12px;border:1px solid rgba(255,255,255,.25);font-weight:600;letter-spacing:.01em;padding:.55rem 1.3rem;background-image:linear-gradient(135deg,#2f8f46,#1f6b34);box-shadow:0 8px 22px rgba(47,143,70,.32),inset 0 1px 0 rgba(255,255,255,.35);transition:transform .2s ease,box-shadow .2s ease}
.stButton>button p,.stFormSubmitButton>button p,.stDownloadButton>button p{color:#fff !important}
.stButton>button:hover,.stFormSubmitButton>button:hover,.stDownloadButton>button:hover{transform:translateY(-2px);box-shadow:0 14px 30px rgba(47,143,70,.42),inset 0 1px 0 rgba(255,255,255,.35);border-color:rgba(255,255,255,.4)}
.stButton>button:active,.stFormSubmitButton>button:active{transform:translateY(0) scale(.98)}
.stButton>button::after,.stFormSubmitButton>button::after,.stDownloadButton>button::after{content:"";position:absolute;top:0;left:-120%;width:50%;height:100%;background:linear-gradient(100deg,transparent,rgba(255,255,255,.35),transparent);transform:skewX(-18deg);transition:left .7s ease;pointer-events:none}
.stButton>button:hover::after,.stFormSubmitButton>button:hover::after,.stDownloadButton>button:hover::after{left:140%}
[class*="st-key-go_"] button{background-image:none;background-color:rgba(255,255,255,.6);-webkit-backdrop-filter:blur(14px);backdrop-filter:blur(14px);border:1px solid rgba(255,255,255,.85);box-shadow:0 8px 24px rgba(15,61,42,.12),inset 0 1px 0 rgba(255,255,255,.9)}
[class*="st-key-go_"] button p{color:#0f3d2a !important}
[class*="st-key-go_"] button:hover{background-color:rgba(255,255,255,.85);box-shadow:0 14px 32px rgba(15,61,42,.2)}
div[data-baseweb="input"],div[data-baseweb="textarea"],div[data-baseweb="select"]>div{border-radius:12px !important;transition:box-shadow .2s ease,border-color .2s ease}
.block-container div[data-baseweb="input"],.block-container div[data-baseweb="textarea"],.block-container div[data-baseweb="select"]>div{background-color:rgba(255,255,255,.7) !important;border:1px solid rgba(15,61,42,.14) !important}
.block-container div[data-baseweb="input"]:focus-within,.block-container div[data-baseweb="textarea"]:focus-within{border-color:#2f8f46 !important;box-shadow:0 0 0 3px rgba(47,143,70,.18)}
[data-testid="stAlert"]{border-radius:16px;-webkit-backdrop-filter:blur(10px);backdrop-filter:blur(10px)}
[data-testid="stChatMessage"]{border-radius:18px;background:rgba(255,255,255,.55);-webkit-backdrop-filter:blur(14px);backdrop-filter:blur(14px);border:1px solid rgba(255,255,255,.8);animation:glassIn .4s ease backwards}
button[data-baseweb="tab"]{font-weight:600;border-radius:12px 12px 0 0;transition:all .2s ease}
button[data-baseweb="tab"]:hover{background:rgba(47,143,70,.10)}
button[data-baseweb="tab"][aria-selected="true"]{color:#2f8f46}
[data-baseweb="tab-highlight"]{background-color:#2f8f46 !important}
[data-testid="stProgress"] [role="progressbar"]>div,div[data-baseweb="progress-bar"]>div>div{background-image:linear-gradient(90deg,#2f8f46,#7fd69a) !important;border-radius:10px}
::-webkit-scrollbar{width:9px}
::-webkit-scrollbar-thumb{background:linear-gradient(#2f8f46,#7fd69a);border-radius:9px}
.chip{display:flex;align-items:center;gap:12px;padding:10px 12px;margin-bottom:14px;border-radius:16px;color:#fff;background:rgba(255,255,255,.08);border:1px solid rgba(255,255,255,.16);-webkit-backdrop-filter:blur(8px);backdrop-filter:blur(8px)}
.chip .av{width:40px;height:40px;border-radius:50%;object-fit:cover;display:grid;place-items:center;flex:none;font-weight:800;color:#0a2e1f;background-image:linear-gradient(135deg,#9ee6b4,#d9f5e3)}
.chip .nm{font-weight:700;line-height:1.15;color:#fff}
.chip small{display:block;opacity:.7;font-weight:500;color:#fff}
.bigav{width:150px;height:150px;border-radius:50%;display:grid;place-items:center;font-size:3.4rem;font-weight:800;color:#fff;background-image:linear-gradient(135deg,#2f8f46,#0f3d2a);box-shadow:0 14px 34px rgba(15,61,42,.3),inset 0 1px 0 rgba(255,255,255,.35)}
.st-key-avatarbox img{border-radius:50%;aspect-ratio:1;object-fit:cover}
.login-head{text-align:center;margin:0 0 18px;animation:glassIn .6s ease backwards}
.login-head .logo{width:54px;height:54px;border-radius:16px;margin:0 auto 14px;background-image:linear-gradient(135deg,#9ee6b4,#2f8f46);box-shadow:0 12px 28px rgba(47,143,70,.4),inset 0 1px 0 rgba(255,255,255,.5)}
.login-head .lt{font-size:2.2rem;font-weight:800;letter-spacing:-.03em;line-height:1.15;color:var(--ink)}
.login-head .grad2{background-image:linear-gradient(90deg,#0a2e1f,#2f8f46);-webkit-background-clip:text;background-clip:text;color:transparent}
.login-head .ls{opacity:.7;margin-top:6px}
"""


def style():
    st.markdown("<style>" + CSS + "</style>", unsafe_allow_html=True)


def ensure_theme():
    """One-time: writes a light green theme file; Streamlit reads it on the next start."""
    cfg = Path(".streamlit") / "config.toml"
    if not cfg.exists():
        try:
            cfg.parent.mkdir(exist_ok=True)
            cfg.write_text(THEME_TOML, encoding="utf-8")
        except OSError:
            pass


def fancy_header(title, sub=""):
    sub_html = f'<div class="s">{html.escape(sub)}</div>' if sub else ""
    st.markdown(
        f'<div class="ph"><span class="t">{html.escape(title)}</span>{sub_html}<div class="bar"></div></div>',
        unsafe_allow_html=True,
    )


def ring(pct, label):
    pct = max(0, min(100, int(round(pct))))
    return (
        f'<div class="ringbox"><div class="ringwrap"><div class="ring" style="--p:{pct}"></div>'
        f'<div class="ringlabel">{pct}%</div></div><div class="ringcap">{html.escape(label)}</div></div>'
    )


def go(page):
    """Button callback: jump to another page from the Home screen."""
    st.session_state["menu"] = page


def flash(message, effect=None):
    """Show a toast on the next run, even after st.rerun()."""
    st.session_state["flash"] = (message, effect)


def show_flash():
    f = st.session_state.pop("flash", None)
    if f:
        st.toast(f[0])


# ====================== accounts and profile ======================
PW_ROUNDS = 200_000


def init_users():
    urun(
        """CREATE TABLE IF NOT EXISTS users(
            username TEXT PRIMARY KEY, salt TEXT, pw_hash TEXT,
            name TEXT, college TEXT, course TEXT, semester TEXT,
            goal_hours REAL DEFAULT 2, about TEXT, created TEXT)"""
    )


def hash_pw(password, salt=None):
    salt = salt or os.urandom(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PW_ROUNDS)
    return salt.hex(), h.hex()


def check_pw(password, salt_hex, hash_hex):
    h = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), PW_ROUNDS)
    return hmac.compare_digest(h.hex(), hash_hex)


def get_profile(username):
    r = urows(
        "SELECT name, college, course, semester, goal_hours, about FROM users WHERE username=?",
        (username,),
    )
    if not r:
        return {}
    return dict(zip(["name", "college", "course", "semester", "goal_hours", "about"], r[0]))


def greeting():
    u = st.session_state.get("user", "")
    name = (get_profile(u).get("name") or u).strip()
    return f"Hi {name.split()[0] if name else u}  ·  "


def avatar_path(username):
    for f in (DATA_DIR / username).glob("avatar.*"):
        return f
    return None


def avatar_html(username, name):
    av = avatar_path(username)
    if av:
        mime = "image/png" if av.suffix.lower() == ".png" else "image/jpeg"
        data = base64.b64encode(av.read_bytes()).decode()
        return f'<img class="av" src="data:{mime};base64,{data}">'
    return f'<div class="av">{html.escape((name or username)[:1].upper())}</div>'


def migrate_legacy(username):
    """The first account adopts the notes and files saved before accounts existed."""
    if not Path(LEGACY_DB).exists():
        return False
    d = DATA_DIR / username
    d.mkdir(parents=True, exist_ok=True)
    shutil.copy2(LEGACY_DB, d / "topper_nest.db")
    for old in ("saved_files", "songs"):
        if Path(old).is_dir():
            shutil.copytree(old, d / old, dirs_exist_ok=True)
    c = sqlite3.connect(d / "topper_nest.db")
    try:
        with c:
            for table, col, folder in (("files", "path", "saved_files"), ("songs", "source", "songs")):
                try:
                    for rid, val in c.execute(f"SELECT id, {col} FROM {table}").fetchall():
                        p = Path(val)
                        if p.parts and p.parts[0] == folder:
                            c.execute(f"UPDATE {table} SET {col}=? WHERE id=?", (str(d / p), rid))
                except sqlite3.OperationalError:
                    pass
    finally:
        c.close()
    return True


def do_signup(username, name, password, confirm):
    u = username.strip().lower()
    if not re.fullmatch(r"[a-z0-9_]{3,20}", u):
        return "Username must be 3 to 20 letters, numbers or underscores (no spaces)."
    if len(password) < 6:
        return "Password must be at least 6 characters."
    if password != confirm:
        return "The two passwords do not match."
    if urows("SELECT 1 FROM users WHERE username=?", (u,)):
        return "That username is already taken."
    first_user = not urows("SELECT 1 FROM users LIMIT 1")
    salt, h = hash_pw(password)
    urun(
        "INSERT INTO users(username, salt, pw_hash, name, course, created) VALUES(?,?,?,?,?,?)",
        (u, salt, h, name.strip() or u, "BSc IT", now_text()),
    )
    st.session_state["user"] = u
    if first_user and migrate_legacy(u):
        flash("Your earlier notes and files were moved into this account")
    return None


def do_login(username, password):
    if st.session_state.get("fails", 0) >= 5:
        return "Too many wrong attempts. Refresh the page to try again."
    u = username.strip().lower()
    r = urows("SELECT salt, pw_hash FROM users WHERE username=?", (u,))
    if not r or not check_pw(password, r[0][0], r[0][1]):
        st.session_state["fails"] = st.session_state.get("fails", 0) + 1
        time.sleep(0.5)
        return "Wrong username or password."
    st.session_state["user"] = u
    st.session_state["fails"] = 0
    return None


def login_screen():
    st.markdown(
        "<style>[data-testid='stSidebar'],[data-testid='stSidebarCollapsedControl'],"
        "[data-testid='collapsedControl']{display:none !important}"
        ".block-container{max-width:560px !important;padding-top:7vh !important}</style>"
        '<div class="login-head"><div class="logo"></div>'
        '<div class="lt">Welcome to <span class="grad2">Topper Nest</span></div>'
        '<div class="ls">Log in or create an account to continue</div></div>',
        unsafe_allow_html=True,
    )
    t_in, t_up = st.tabs(["Log in", "Sign up"])
    with t_in:
        with st.form("login_form"):
            u = st.text_input("Username", key="li_user")
            pw = st.text_input("Password", type="password", key="li_pass")
            if st.form_submit_button("Log in"):
                err = do_login(u, pw)
                if err:
                    st.error(err)
                else:
                    st.rerun()
    with t_up:
        with st.form("signup_form"):
            u = st.text_input("Choose a username", key="su_user")
            name = st.text_input("Your name", key="su_name")
            pw = st.text_input("Password", type="password", key="su_pass")
            pw2 = st.text_input("Confirm password", type="password", key="su_pass2")
            if st.form_submit_button("Create account"):
                err = do_signup(u, name, pw, pw2)
                if err:
                    st.error(err)
                else:
                    st.rerun()
    st.caption("Everything stays on this computer. Each account has its own private notes, files and progress.")


def page_profile():
    u = st.session_state["user"]
    p = get_profile(u)
    fancy_header("Profile", "Your details and study summary")

    left, right = st.columns([1, 2])
    with left:
        with st.container(key="avatarbox"):
            av = avatar_path(u)
            if av:
                st.image(str(av), width=150)
            else:
                st.markdown(f'<div class="bigav">{html.escape((p.get("name") or u)[:1].upper())}</div>',
                            unsafe_allow_html=True)
        photo = st.file_uploader("Profile photo", type=["png", "jpg", "jpeg"], key="avatar_up")
        if photo is not None and st.button("Save photo", key="save_photo"):
            if photo.size > 2 * 1024 * 1024:
                st.warning("Photo must be smaller than 2 MB.")
            else:
                for old in (DATA_DIR / u).glob("avatar.*"):
                    old.unlink()
                (user_dir() / f"avatar{Path(photo.name).suffix.lower()}").write_bytes(photo.getbuffer())
                st.rerun()
        st.caption(f"Username: {u}")

    with right:
        t1, t2 = st.tabs(["Details", "Password"])
        with t1:
            with st.form("profile_form"):
                name = st.text_input("Name", value=p.get("name") or "")
                college = st.text_input("College", value=p.get("college") or "")
                c1, c2 = st.columns(2)
                course = c1.text_input("Course", value=p.get("course") or "")
                semester = c2.text_input("Semester", value=p.get("semester") or "")
                goal = st.number_input("Daily study goal (hours)", 0.5, 16.0,
                                       float(p.get("goal_hours") or 2), step=0.5)
                about = st.text_area("About me", value=p.get("about") or "", height=100)
                if st.form_submit_button("Save details"):
                    urun(
                        "UPDATE users SET name=?, college=?, course=?, semester=?, goal_hours=?, about=? "
                        "WHERE username=?",
                        (name.strip() or u, college.strip(), course.strip(), semester.strip(), goal,
                         about.strip(), u),
                    )
                    flash("Profile saved")
                    st.rerun()
        with t2:
            with st.form("password_form", clear_on_submit=True):
                cur = st.text_input("Current password", type="password")
                new = st.text_input("New password", type="password")
                new2 = st.text_input("Confirm new password", type="password")
                if st.form_submit_button("Change password"):
                    r = urows("SELECT salt, pw_hash FROM users WHERE username=?", (u,))
                    if not check_pw(cur, r[0][0], r[0][1]):
                        st.error("Current password is wrong.")
                    elif len(new) < 6:
                        st.error("New password must be at least 6 characters.")
                    elif new != new2:
                        st.error("The new passwords do not match.")
                    else:
                        salt, h = hash_pw(new)
                        urun("UPDATE users SET salt=?, pw_hash=? WHERE username=?", (salt, h, u))
                        st.success("Password changed")

    st.subheader("Your study summary")
    secs = rows("SELECT COALESCE(SUM(seconds),0) FROM usage")[0][0]
    days = rows("SELECT COUNT(DISTINCT day) FROM usage")[0][0]
    n_notes = rows("SELECT COUNT(*) FROM notes")[0][0]
    tot = rows("SELECT COUNT(*), COALESCE(SUM(correct),0) FROM attempts")[0]
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Time in the app", f"{round(secs / 3600, 1)} h")
    m2.metric("Days active", days)
    m3.metric("Notes written", n_notes)
    m4.metric("Practice accuracy", f"{round(100 * tot[1] / tot[0])}%" if tot[0] else "-")


# ====================== pages ======================
def page_home():
    today = date.today().isoformat()
    goals = rows("SELECT text, done FROM goals WHERE day=?", (today,))
    pending = [g[0] for g in goals if not g[1]]
    if not goals:
        status = "No goals set for today"
    elif not pending:
        status = "All of today's goals are complete"
    else:
        status = f"{len(pending)} goal(s) left today"
    st.markdown(
        '<div class="hero">'
        f'<span class="badge">{html.escape(greeting() + status)}</span>'
        '<div class="hero-title">Study smarter with <span class="grad">Topper Nest</span></div>'
        '<div class="hero-sub">Notes, practice, goals and your syllabus, together in one calm workspace.</div>'
        '</div>',
        unsafe_allow_html=True,
    )

    q1, q2, q3, q4 = st.columns(4)
    q1.button("Write a note", key="go_notes", on_click=go, args=("Notes",))
    q2.button("Practice questions", key="go_practice", on_click=go, args=("Practice",))
    q3.button("Plan today", key="go_planner", on_click=go, args=("Planner",))
    q4.button("Track syllabus", key="go_syllabus", on_click=go, args=("Syllabus",))

    n_notes = rows("SELECT COUNT(*) FROM notes")[0][0]
    n_open = rows("SELECT COUNT(*) FROM mistakes WHERE fixed=0")[0][0]
    total_t = rows("SELECT COUNT(*) FROM topics")[0][0]
    done_t = rows("SELECT COUNT(*) FROM topics WHERE status='Done'")[0][0]
    tot = rows("SELECT COUNT(*), COALESCE(SUM(correct),0) FROM attempts")[0]

    goal_pct = 100 * (len(goals) - len(pending)) / len(goals) if goals else 0
    syl_pct = 100 * done_t / total_t if total_t else 0
    acc_pct = 100 * tot[1] / tot[0] if tot[0] else 0
    st.markdown(
        '<div class="rings">' + ring(goal_pct, "Today's goals") + ring(syl_pct, "Syllabus done")
        + ring(acc_pct, "Practice accuracy") + "</div>",
        unsafe_allow_html=True,
    )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Notes saved", n_notes)
    c2.metric("Mistakes to fix", n_open)
    c3.metric("Syllabus done", f"{done_t}/{total_t}")
    c4.metric("AI messages today", ai_calls_today())
    if total_t - done_t > 0:
        st.warning(f"{total_t - done_t} syllabus topic(s) are not finished yet. Open Syllabus.")


def page_syllabus():
    fancy_header("Syllabus tracker", "Know exactly what is done and what is left")
    with st.form("add_topics", clear_on_submit=True):
        subject = st.text_input("Subject")
        topics = st.text_area("Topics (one topic per line)", height=120)
        if st.form_submit_button("Add to syllabus") and subject.strip():
            for line in topics.splitlines():
                if line.strip():
                    run("INSERT INTO topics(subject, topic, updated) VALUES(?,?,?)",
                        (subject.strip(), line.strip(), now_text()))
            st.success("Added")

    data = rows("SELECT id, subject, topic, status FROM topics ORDER BY subject, id")
    if not data:
        st.info("Your syllabus is empty. Add a subject and its topics above.")
        return

    left = [d for d in data if d[3] == "Not started"]
    if left:
        with st.expander(f"Reminder: {len(left)} topic(s) not started yet"):
            for _, subj, topic, _ in left:
                st.write(f"- {subj}: {topic}")

    for subj in dict.fromkeys(d[1] for d in data):
        items = [d for d in data if d[1] == subj]
        done = sum(1 for d in items if d[3] == "Done")
        st.subheader(f"{subj}  ({done}/{len(items)})")
        st.progress(done / len(items))
        for tid, _, topic, status in items:
            new = st.selectbox(topic, STATUSES, index=STATUSES.index(status), key=f"st_{tid}")
            if new != status:
                run("UPDATE topics SET status=?, updated=? WHERE id=?", (new, now_text(), tid))
                if new == "Done":
                    flash("Topic finished. Great work")
                st.rerun()


def page_planner():
    fancy_header("Daily planner and goals", "Small goals, every single day")
    today = date.today()
    with st.form("goal_form", clear_on_submit=True):
        text = st.text_input("Goal")
        start = st.date_input("Start date", value=today)
        days = st.number_input("For how many days", min_value=1, max_value=365, value=1)
        if st.form_submit_button("Add goal") and text.strip():
            for i in range(int(days)):
                run("INSERT INTO goals(day, text) VALUES(?,?)",
                    ((start + timedelta(days=i)).isoformat(), text.strip()))
            st.success("Goal added")

    st.subheader("Today")
    goals = rows("SELECT id, text, done FROM goals WHERE day=? ORDER BY id", (today.isoformat(),))
    if not goals:
        st.info("No goals for today.")
    for gid, text, done in goals:
        val = st.checkbox(text, value=bool(done), key=f"goal_{gid}")
        if val != bool(done):
            run("UPDATE goals SET done=? WHERE id=?", (int(val), gid))
            if val:
                left = rows("SELECT 1 FROM goals WHERE day=? AND done=0", (today.isoformat(),))
                if left:
                    flash("Goal completed")
                else:
                    flash("All goals for today are complete")
            st.rerun()
    if goals:
        finished = sum(1 for g in goals if g[2])
        st.progress(finished / len(goals))
        st.caption(f"{finished} of {len(goals)} goals done today")

    st.subheader("Next 7 days")
    nxt = rows(
        "SELECT day, text, done FROM goals WHERE day>? AND day<=? ORDER BY day",
        (today.isoformat(), (today + timedelta(days=7)).isoformat()),
    )
    if nxt:
        df = pd.DataFrame(nxt, columns=["Day", "Goal", "Done"])
        df["Done"] = df["Done"].map({0: "No", 1: "Yes"})
        st.dataframe(df, hide_index=True)
    else:
        st.caption("Nothing planned for the next 7 days.")


def add_question(subject, qtype, diff, question, options, answer):
    run(
        """INSERT INTO questions(subject, qtype, difficulty, question, options, answer)
           VALUES(?,?,?,?,?,?)""",
        (subject.strip(), qtype, diff, question.strip(), json.dumps(options), str(answer).strip()),
    )


def record(qid, subject, question, my_answer, correct_answer, ok):
    run("INSERT INTO attempts(qid, correct, day) VALUES(?,?,?)",
        (qid, int(ok), date.today().isoformat()))
    if ok:
        st.success("Correct!")
        st.toast("Correct! Keep going", icon=":material/check_circle:")
    else:
        st.error(f"Not correct. Right answer: {correct_answer}")
        st.toast("Saved in Mistakes. You will beat it next time", icon=":material/bookmark:")
        exists = rows("SELECT id FROM mistakes WHERE question=? AND fixed=0", (question,))
        if not exists:
            run(
                """INSERT INTO mistakes(subject, question, my_answer, correct_answer, created)
                   VALUES(?,?,?,?,?)""",
                (subject, question, str(my_answer), str(correct_answer), now_text()),
            )
            st.caption("Saved in the Mistakes section.")


def num_ok(a, b):
    try:
        return math.isclose(float(a), float(b), rel_tol=1e-2, abs_tol=1e-6)
    except ValueError:
        return False


def tab_solve():
    subjects = [r[0] for r in rows("SELECT DISTINCT subject FROM questions ORDER BY subject")]
    if not subjects:
        st.info("No questions yet. Add some in the next tab, or let the AI generate them.")
        return
    c1, c2, c3 = st.columns(3)
    f_sub = c1.selectbox("Subject", ["All"] + subjects)
    f_diff = c2.selectbox("Difficulty", ["All"] + DIFFS)
    f_type = c3.selectbox("Type", ["All"] + QTYPES)

    sql = "SELECT id, subject, qtype, difficulty, question, options, answer FROM questions WHERE 1=1"
    params = []
    for col, val in (("subject", f_sub), ("difficulty", f_diff), ("qtype", f_type)):
        if val != "All":
            sql += f" AND {col}=?"
            params.append(val)
    items = rows(sql + " ORDER BY id DESC LIMIT 30", tuple(params))

    tot = rows("SELECT COUNT(*), COALESCE(SUM(correct),0) FROM attempts")[0]
    if tot[0]:
        st.caption(f"Your accuracy so far: {round(100 * tot[1] / tot[0])}% ({tot[1]}/{tot[0]})")

    for qid, subject, qtype, diff, question, options, answer in items:
        with st.expander(f"[{diff}] {subject}: {question[:70]}"):
            st.write(question)
            if qtype == "Objective (MCQ)":
                opts = json.loads(options)
                choice = st.radio("Choose one", opts, index=None, key=f"mcq_{qid}")
                if st.button("Check", key=f"chk_{qid}"):
                    if choice is None:
                        st.warning("Pick an option first.")
                    else:
                        record(qid, subject, question, choice, answer, choice == answer)
            elif qtype == "Numerical":
                val = st.text_input("Your answer (number)", key=f"num_{qid}")
                if st.button("Check", key=f"chk_{qid}"):
                    if not val.strip():
                        st.warning("Type your answer first.")
                    else:
                        record(qid, subject, question, val, answer, num_ok(val, answer))
            else:
                mine = st.text_area("Your answer", key=f"sub_{qid}")
                if st.button("Check with AI", key=f"ai_{qid}"):
                    reply, err = ask_ai(
                        [{"role": "user", "content":
                          f"Question: {question}\nModel answer: {answer}\nStudent answer: {mine}"}],
                        "You are a strict examiner. Start your reply with exactly one word: "
                        "CORRECT, PARTIAL or WRONG. Then give 2-3 short lines of feedback.",
                    )
                    if err:
                        st.error(err)
                    else:
                        st.write(reply)
                        ok = reply.strip().upper().startswith("CORRECT")
                        record(qid, subject, question, mine, answer, ok)
                if st.checkbox("No AI? Show model answer and check myself", key=f"sh_{qid}"):
                    st.info(answer)
                    b1, b2 = st.columns(2)
                    if b1.button("I got it right", key=f"r_{qid}"):
                        record(qid, subject, question, mine, answer, True)
                    if b2.button("I got it wrong", key=f"w_{qid}"):
                        record(qid, subject, question, mine, answer, False)


def tab_add_question():
    with st.form("add_q", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        subject = c1.text_input("Subject")
        qtype = c2.selectbox("Type", QTYPES)
        diff = c3.selectbox("Difficulty", DIFFS)
        question = st.text_area("Question")
        options = st.text_area("Options, one per line (only for Objective)")
        correct_no = st.number_input("Correct option number (only for Objective)", 1, 6, 1)
        answer = st.text_input("Answer (number for Numerical, model answer for Subjective)")
        if st.form_submit_button("Save question"):
            if not subject.strip() or not question.strip():
                st.warning("Subject and question are required.")
            elif qtype == "Objective (MCQ)":
                opts = [o.strip() for o in options.splitlines() if o.strip()]
                if len(opts) < 2 or correct_no > len(opts):
                    st.warning("Give at least 2 options and a valid correct option number.")
                else:
                    add_question(subject, qtype, diff, question, opts, opts[int(correct_no) - 1])
                    st.success("Question saved")
            elif not answer.strip():
                st.warning("Please add the answer.")
            else:
                add_question(subject, qtype, diff, question, [], answer)
                st.success("Question saved")


def tab_generate():
    st.caption("The AI writes questions and saves them in your question bank. Uses your AI limit.")
    c1, c2 = st.columns(2)
    subject = c1.text_input("Subject", key="gen_subject")
    topic = c2.text_input("Topic", key="gen_topic")
    c3, c4, c5 = st.columns(3)
    qtype = c3.selectbox("Type", QTYPES, key="gen_type")
    diff = c4.selectbox("Difficulty", DIFFS, key="gen_diff")
    n = c5.number_input("How many", 1, 5, 3, key="gen_n")
    if st.button("Generate questions"):
        if not subject.strip() or not topic.strip():
            st.warning("Fill subject and topic.")
            return
        prompt = (
            f"Create {int(n)} {diff} {qtype} exam questions for subject '{subject}', topic '{topic}'. "
            "Return ONLY a JSON array, nothing else. Each item has the keys "
            "\"question\", \"options\" and \"answer\". "
            "For Objective: options is a list of 4 strings and answer is exactly one of them. "
            "For Numerical: options is an empty list and answer is just the number. "
            "For Subjective: options is an empty list and answer is a short model answer. "
            "For difficulty Trap, make tricky questions where common mistakes happen."
        )
        reply, err = ask_ai([{"role": "user", "content": prompt}], "You write accurate exam questions.")
        if err:
            st.error(err)
            return
        try:
            items = parse_json_list(reply)
        except Exception:
            st.error("The AI reply could not be read. Try again.")
            return
        saved = 0
        for it in items:
            q, opts, ans = it.get("question", ""), it.get("options", []), it.get("answer", "")
            if not q or not str(ans).strip():
                continue
            if qtype == "Objective (MCQ)" and ans not in opts:
                continue
            add_question(subject, qtype, diff, q, opts if qtype == "Objective (MCQ)" else [], ans)
            saved += 1
        st.success(f"{saved} question(s) saved. Open the Solve tab.")


def page_practice():
    fancy_header("Practice", "Solve inside the app. Wrong answers are saved for you")
    t1, t2, t3 = st.tabs(["Solve", "Add question", "AI-generate"])
    with t1:
        tab_solve()
    with t2:
        tab_add_question()
    with t3:
        tab_generate()


def page_mistakes():
    fancy_header("Mistakes", "Fix your mistakes and you grow faster")
    st.caption("Wrong answers from Practice are saved here automatically. You can add your own too.")
    with st.form("new_mistake", clear_on_submit=True):
        subject = st.text_input("Subject / topic")
        question = st.text_area("Question")
        my_answer = st.text_input("My answer")
        correct = st.text_input("Correct answer")
        if st.form_submit_button("Save mistake") and question.strip():
            run("""INSERT INTO mistakes(subject,question,my_answer,correct_answer,created)
                   VALUES(?,?,?,?,?)""",
                (subject.strip(), question.strip(), my_answer, correct, now_text()))
            st.success("Mistake saved")

    show = st.radio("Show", ["Still to fix", "Fixed", "All"], horizontal=True)
    sql = "SELECT id,subject,question,my_answer,correct_answer,fixed FROM mistakes"
    if show == "Still to fix":
        sql += " WHERE fixed=0"
    elif show == "Fixed":
        sql += " WHERE fixed=1"
    for mid, subject, question, mine, correct, fixed in rows(sql + " ORDER BY id DESC"):
        with st.expander(f"{'[fixed] ' if fixed else ''}{subject or 'No topic'}: {question[:60]}"):
            st.write(question)
            st.write(f"My answer: {mine}")
            st.write(f"Correct answer: {correct}")
            b1, b2 = st.columns(2)
            if b1.button("Mark as not fixed" if fixed else "Mark as fixed", key=f"fix_{mid}"):
                run("UPDATE mistakes SET fixed=? WHERE id=?", (0 if fixed else 1, mid))
                if not fixed:
                    flash("Mistake fixed. That is how you improve")
                st.rerun()
            if b2.button("Explain with AI", key=f"exp_{mid}"):
                reply, err = ask_ai(
                    [{"role": "user", "content":
                      f"Question: {question}\nMy answer: {mine}\nCorrect answer: {correct}\n"
                      "Explain simply why my answer is wrong and how to avoid this mistake."}],
                    "You are a patient tutor. Keep it short and clear.",
                )
                st.error(err) if err else st.write(reply)


def page_notes():
    fancy_header("Notes", "Write, search and keep all your notes here")
    with st.form("new_note", clear_on_submit=True):
        subject = st.text_input("Subject")
        title = st.text_input("Title")
        body = st.text_area("Write your note", height=200)
        if st.form_submit_button("Save note") and title.strip():
            run("INSERT INTO notes(subject,title,body,created) VALUES(?,?,?,?)",
                (subject.strip(), title.strip(), body, now_text()))
            st.success("Note saved")
    search = st.text_input("Search notes")
    for nid, subject, title, body, created in rows(
            "SELECT id,subject,title,body,created FROM notes ORDER BY id DESC"):
        if search and search.lower() not in (title + subject + body).lower():
            continue
        with st.expander(f"{title}  |  {subject or 'No subject'}  |  {created}"):
            st.write(body)
            if st.button("Delete", key=f"del_note_{nid}"):
                run("DELETE FROM notes WHERE id=?", (nid,))
                st.rerun()


def page_ai_tutor():
    fancy_header("AI Tutor", "Ask any doubt, get a simple explanation")
    chat_ui(
        "chat_tutor",
        "You are a friendly study tutor for BSc IT and engineering students. Explain with simple "
        "words and a real-life example, keep answers short, then offer one practice question.",
        "Ask any doubt. Uses your daily AI limit.",
    )


def page_english():
    fancy_header("English Coach", "Chat in English and improve every day")
    chat_ui(
        "chat_english",
        "You are a friendly spoken-English coach. Reply in simple English. If the student makes a "
        "grammar mistake, show the corrected sentence in one line, then continue the conversation "
        "and ask one easy question.",
        "Practice English by chatting. Type like you would speak. (Voice can be added later.)",
    )


def page_videos():
    fancy_header("Study Videos", "Only study videos, zero distraction")
    st.caption("Only the videos you add here show up, so there are no distractions.")
    with st.form("add_video", clear_on_submit=True):
        title = st.text_input("Title")
        subject = st.text_input("Subject")
        url = st.text_input("YouTube link")
        if st.form_submit_button("Add video") and title.strip() and url.strip():
            run("INSERT INTO videos(title, subject, url) VALUES(?,?,?)",
                (title.strip(), subject.strip(), url.strip()))
            st.success("Video added")
    for vid, title, subject, url in rows("SELECT id,title,subject,url FROM videos ORDER BY id DESC"):
        with st.expander(f"{title}  |  {subject or 'No subject'}"):
            st.video(url)
            if st.button("Remove", key=f"del_vid_{vid}"):
                run("DELETE FROM videos WHERE id=?", (vid,))
                st.rerun()


def page_music():
    fancy_header("Music", "Your own playlist while you study")
    with st.form("add_song", clear_on_submit=True):
        title = st.text_input("Song name")
        up = st.file_uploader("Upload a song file", type=["mp3", "wav", "ogg", "m4a"])
        link = st.text_input("...or a direct audio link (optional)")
        if st.form_submit_button("Add song") and title.strip():
            if up is not None:
                path = songs_dir() / f"{int(time.time())}_{Path(up.name).name}"
                path.write_bytes(up.getbuffer())
                run("INSERT INTO songs(title, source) VALUES(?,?)", (title.strip(), str(path)))
                st.success("Song added")
            elif link.strip():
                run("INSERT INTO songs(title, source) VALUES(?,?)", (title.strip(), link.strip()))
                st.success("Song added")
            else:
                st.warning("Upload a file or give a link.")
    for sid, title, source in rows("SELECT id,title,source FROM songs ORDER BY id DESC"):
        st.write(f"**{title}**")
        st.audio(source)
        if st.button("Remove", key=f"del_song_{sid}"):
            run("DELETE FROM songs WHERE id=?", (sid,))
            st.rerun()


def page_files():
    fancy_header("Files", "All your study files in one place")
    st.caption("Save study photos and files here instead of WhatsApp or random folders.")
    with st.form("add_file", clear_on_submit=True):
        subject = st.text_input("Subject")
        ups = st.file_uploader("Choose files", accept_multiple_files=True)
        if st.form_submit_button("Save files") and ups:
            for up in ups:
                path = files_dir() / f"{int(time.time())}_{Path(up.name).name}"
                path.write_bytes(up.getbuffer())
                run("INSERT INTO files(name, subject, path, created) VALUES(?,?,?,?)",
                    (Path(up.name).name, subject.strip(), str(path), now_text()))
            st.success("Saved")
    for fid, name, subject, path, created in rows(
            "SELECT id,name,subject,path,created FROM files ORDER BY id DESC"):
        p = Path(path)
        c1, c2, c3 = st.columns([4, 1, 1])
        c1.write(f"{name}  |  {subject or 'No subject'}  |  {created}")
        if p.exists():
            c2.download_button("Download", p.read_bytes(), file_name=name, key=f"dl_{fid}")
        if c3.button("Delete", key=f"del_file_{fid}"):
            if p.exists():
                p.unlink()
            run("DELETE FROM files WHERE id=?", (fid,))
            st.rerun()


def page_calculator():
    fancy_header("Calculator", "Quick calculations without leaving the app")
    st.caption("Examples: 2*(3+4)**2    sqrt(16)    sin(pi/2)    log10(1000)")
    expr = st.text_input("Expression")
    if expr:
        try:
            st.success(f"Answer: {safe_eval(ast.parse(expr, mode='eval'))}")
        except Exception:
            st.error("Could not calculate that. Check the expression.")


def page_usage():
    fancy_header("Usage Stats", "See where your study time really goes")
    with db() as c:
        df = pd.read_sql_query("SELECT day, feature, seconds, opens FROM usage", c)
    if df.empty:
        st.info("No usage recorded yet. Use the app for a bit and come back.")
        return
    df["minutes"] = (df["seconds"] / 60).round(1)
    today = date.today().isoformat()
    tdf = df[df["day"] == today]
    st.subheader("Today")
    st.metric("Total time today (minutes)", round(tdf["minutes"].sum(), 1))
    if not tdf.empty:
        st.bar_chart(tdf.set_index("feature")["minutes"])
    st.subheader("All days")
    st.bar_chart(df.groupby("feature")["minutes"].sum())
    st.dataframe(
        df.sort_values(["day", "feature"], ascending=[False, True])[["day", "feature", "minutes", "opens"]],
        hide_index=True,
    )


# ====================== main ======================
def main():
    st.set_page_config(page_title="Topper Nest", layout="wide", initial_sidebar_state="expanded")
    ensure_theme()
    init_users()
    style()
    user = st.session_state.get("user")
    if not user:
        login_screen()
        return
    init_db()
    prof = get_profile(user)
    st.sidebar.markdown(
        '<div class="brand"><div class="logo"></div><div>Topper Nest<small>your study workspace</small></div></div>'
        f'<div class="chip">{avatar_html(user, prof.get("name"))}'
        f'<div class="nm">{html.escape(prof.get("name") or user)}<small>@{html.escape(user)}</small></div></div>',
        unsafe_allow_html=True,
    )
    page = st.sidebar.radio("Menu", PAGES, key="menu")
    st.sidebar.divider()
    st.sidebar.text_input("Claude API key (for AI pages)", type="password", key="api_key")
    st.sidebar.number_input("AI messages allowed per day", 1, 500, DEFAULT_DAILY_LIMIT, key="ai_limit")
    if st.sidebar.button("Log out", key="logout"):
        st.session_state.clear()
        st.rerun()
    track(page)
    {
        "Home": page_home, "Syllabus": page_syllabus, "Planner": page_planner,
        "Practice": page_practice, "Mistakes": page_mistakes, "Notes": page_notes,
        "AI Tutor": page_ai_tutor, "English Coach": page_english,
        "Study Videos": page_videos, "Music": page_music, "Files": page_files,
        "Calculator": page_calculator, "Usage Stats": page_usage, "Profile": page_profile,
    }[page]()
    show_flash()


if __name__ == "__main__":
    main()