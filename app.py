
"""Topper Nest - complete version (v2)
 
Pages: Home, Syllabus, Planner, Practice, Mistakes, Notes, AI Tutor,
English Coach, Study Videos, Music, Files, Calculator, Usage Stats.
 
Run:
    pip install streamlit pandas anthropic
    streamlit run app.py
"""
import ast
import html
import json
import math
import operator
import os
import sqlite3
import time
from datetime import date, datetime, timedelta
from pathlib import Path
 
import pandas as pd
import streamlit as st
 
DB_FILE = "topper_nest.db"
FILES_DIR = Path("saved_files")
SONGS_DIR = Path("songs")
MODEL = "claude-sonnet-5-5"  # change here if you want another model
DEFAULT_DAILY_LIMIT = 30  # AI messages per day (keeps API cost under control)
IDLE_CAP = 300  # seconds; long idle gaps are not counted as study time
 
PAGES = [
    "Home", "Syllabus", "Planner", "Practice", "Mistakes", "Notes",
    "AI Tutor", "English Coach", "Study Videos", "Music", "Files",
    "Calculator", "Usage Stats",
]
ICONS = {
    "Home": "🏠", "Syllabus": "📚", "Planner": "🗓️", "Practice": "🎯",
    "Mistakes": "🧠", "Notes": "📝", "AI Tutor": "🤖", "English Coach": "💬",
    "Study Videos": "🎬", "Music": "🎵", "Files": "📁", "Calculator": "🧮",
    "Usage Stats": "📊",
}
STATUSES = ["Not started", "Studying", "Done"]
QTYPES = ["Objective (MCQ)", "Numerical", "Subjective"]
DIFFS = ["Easy", "Medium", "Hard", "Trap"]
 
 
# ====================== database helpers ======================
def db():
    return sqlite3.connect(DB_FILE)
 
 
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
    FILES_DIR.mkdir(exist_ok=True)
    SONGS_DIR.mkdir(exist_ok=True)
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
CSS = """
:root{--a1:#7f5af0;--a2:#2cb67d;--a3:#ff6b9d;--a4:#5b8def;}
@keyframes fadeUp{from{opacity:0;transform:translateY(16px)}to{opacity:1;transform:none}}
@keyframes floaty{0%,100%{transform:translateY(0) rotate(-5deg)}50%{transform:translateY(-14px) rotate(5deg)}}
@keyframes gradmove{0%{background-position:0% 50%}100%{background-position:100% 50%}}
@keyframes pop{0%{transform:scale(.6);opacity:0}70%{transform:scale(1.08)}100%{transform:scale(1);opacity:1}}
@property --p{syntax:'<number>';inherits:false;initial-value:0;}
@keyframes fillring{from{--p:0}}
.stApp{background-image:radial-gradient(900px 520px at 6% -6%,rgba(127,90,240,.22),transparent 60%),radial-gradient(800px 520px at 100% 0%,rgba(44,182,125,.17),transparent 60%),radial-gradient(760px 520px at 55% 112%,rgba(255,107,157,.15),transparent 60%);background-attachment:fixed}
[data-testid="stHeader"]{background:transparent}
[data-testid="stAppDeployButton"],#MainMenu,footer{display:none !important}
[data-testid="stElementContainer"],.element-container{animation:fadeUp .55s ease both}
[data-testid="stSidebar"]{background-image:linear-gradient(180deg,rgba(127,90,240,.16),rgba(44,182,125,.10));border-right:1px solid rgba(127,90,240,.18)}
[data-testid="stSidebar"] [role="radiogroup"] label{padding:7px 12px;border-radius:12px;transition:all .2s ease;margin-bottom:2px}
[data-testid="stSidebar"] [role="radiogroup"] label:hover{background:rgba(127,90,240,.16);transform:translateX(5px)}
.brand{font-size:1.45rem;font-weight:800;padding:6px 4px 14px;background:linear-gradient(90deg,var(--a1),var(--a2));-webkit-background-clip:text;background-clip:text;color:transparent;animation:pop .7s ease both}
.brand small{display:block;font-size:.72rem;font-weight:500;opacity:.8;-webkit-text-fill-color:currentColor}
.ph{margin:2px 0 12px;animation:fadeUp .5s ease both}
.ph .i{display:inline-block;font-size:2rem;margin-right:10px;animation:floaty 3.4s ease-in-out infinite}
.ph .t{font-size:2.15rem;font-weight:800;display:inline-block;background:linear-gradient(90deg,var(--a1),var(--a2));-webkit-background-clip:text;background-clip:text;color:transparent}
.ph .s{opacity:.7;margin-top:2px}
.hero{display:flex;align-items:center;gap:24px;padding:26px 30px;border-radius:28px;color:#fff;background:linear-gradient(120deg,#7f5af0,#5b8def,#2cb67d,#ff6b9d,#7f5af0);background-size:300% 300%;animation:gradmove 9s ease infinite alternate,fadeUp .6s ease both;box-shadow:0 16px 44px rgba(127,90,240,.38);margin-bottom:18px}
.mascot{font-size:84px;line-height:1;animation:floaty 3.2s ease-in-out infinite;filter:drop-shadow(0 10px 10px rgba(0,0,0,.28))}
.hero-title{font-size:2.3rem;font-weight:800;letter-spacing:.3px}
.hero-sub{opacity:.92;margin:2px 0 12px}
.bubble{display:inline-block;background:rgba(255,255,255,.2);border:1px solid rgba(255,255,255,.4);backdrop-filter:blur(6px);border-radius:18px;padding:10px 16px;font-weight:500}
.rings{display:flex;gap:34px;flex-wrap:wrap;justify-content:center;margin:14px 0 8px}
.ringbox{text-align:center;animation:pop .8s ease both}
.ringwrap{position:relative;width:124px;height:124px;margin:0 auto}
.ring{width:124px;height:124px;border-radius:50%;background:conic-gradient(var(--a1),var(--a2) calc(var(--p)*1%),rgba(127,127,127,.18) 0);-webkit-mask:radial-gradient(farthest-side,transparent calc(100% - 13px),#000 calc(100% - 12px));mask:radial-gradient(farthest-side,transparent calc(100% - 13px),#000 calc(100% - 12px));animation:fillring 1.4s ease-out}
.ringlabel{position:absolute;inset:0;display:grid;place-items:center;font-size:1.45rem;font-weight:800}
.ringcap{margin-top:8px;font-weight:600;opacity:.85}
[data-testid="stMetric"]{padding:16px 18px;border-radius:20px;background:color-mix(in srgb,currentColor 6%,transparent);border:1px solid color-mix(in srgb,currentColor 12%,transparent);transition:all .25s ease}
[data-testid="stMetric"]:hover{transform:translateY(-5px);box-shadow:0 12px 30px rgba(127,90,240,.25)}
.stButton>button,.stFormSubmitButton>button,.stDownloadButton>button{border-radius:14px;border:none;color:#fff;font-weight:600;padding:.5rem 1.2rem;background:linear-gradient(135deg,var(--a1),var(--a4));transition:all .2s ease}
.stButton>button:hover,.stFormSubmitButton>button:hover,.stDownloadButton>button:hover{transform:translateY(-2px) scale(1.04);box-shadow:0 10px 24px rgba(127,90,240,.45);color:#fff}
.stButton>button:active,.stFormSubmitButton>button:active{transform:scale(.96)}
[data-testid="stExpander"]{border-radius:18px;border:1px solid color-mix(in srgb,currentColor 13%,transparent);transition:all .25s ease;overflow:hidden}
[data-testid="stExpander"]:hover{border-color:var(--a1);box-shadow:0 8px 22px rgba(127,90,240,.18)}
[data-testid="stForm"]{border-radius:20px;border:1px solid color-mix(in srgb,currentColor 13%,transparent);background:color-mix(in srgb,currentColor 3%,transparent)}
[data-testid="stAlert"]{border-radius:16px}
[data-testid="stChatMessage"]{border-radius:18px;animation:fadeUp .4s ease both}
button[data-baseweb="tab"]{font-weight:600;border-radius:12px 12px 0 0;transition:all .2s ease}
button[data-baseweb="tab"]:hover{background:rgba(127,90,240,.12)}
[data-testid="stProgress"] [role="progressbar"]>div,div[data-baseweb="progress-bar"]>div>div{background-image:linear-gradient(90deg,var(--a1),var(--a2)) !important;border-radius:10px}
input,textarea{border-radius:12px !important}
::-webkit-scrollbar{width:9px}
::-webkit-scrollbar-thumb{background:linear-gradient(var(--a1),var(--a2));border-radius:9px}
"""
 
 
def style():
    st.markdown("<style>" + CSS + "</style>", unsafe_allow_html=True)
 
 
def fancy_header(icon, title, sub=""):
    sub_html = f'<div class="s">{html.escape(sub)}</div>' if sub else ""
    st.markdown(
        f'<div class="ph"><span class="i">{icon}</span><span class="t">{html.escape(title)}</span>{sub_html}</div>',
        unsafe_allow_html=True,
    )
 
 
def ring(pct, label):
    pct = max(0, min(100, int(round(pct))))
    return (
        f'<div class="ringbox"><div class="ringwrap"><div class="ring" style="--p:{pct}"></div>'
        f'<div class="ringlabel">{pct}%</div></div><div class="ringcap">{html.escape(label)}</div></div>'
    )
 
 
def flash(message, effect=None):
    """Show a toast (and optional balloons/snow) on the next run, even after st.rerun()."""
    st.session_state["flash"] = (message, effect)
 
 
def show_flash():
    f = st.session_state.pop("flash", None)
    if f:
        message, effect = f
        st.toast(message)
        if effect == "balloons":
            st.balloons()
        elif effect == "snow":
            st.snow()
 
 
# ====================== pages ======================
def page_home():
    today = date.today().isoformat()
    goals = rows("SELECT text, done FROM goals WHERE day=?", (today,))
    pending = [g[0] for g in goals if not g[1]]
    if not goals:
        msg = "No goals for today yet. Open Planner and add some!"
    elif not pending:
        msg = "All of today's goals are done. Great job!"
    else:
        msg = f"{len(pending)} goal(s) left today: " + ", ".join(pending)
    st.markdown(
        '<div class="hero"><div class="mascot">🦜</div><div>'
        '<div class="hero-title">Topper Nest</div>'
        '<div class="hero-sub">Your study space: notes, practice, goals and more.</div>'
        f'<div class="bubble">{html.escape(msg)}</div></div></div>',
        unsafe_allow_html=True,
    )
 
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
    fancy_header("📚", "Syllabus tracker", "Know exactly what is done and what is left")
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
                    flash("Topic finished! Great work", "balloons")
                st.rerun()
 
 
def page_planner():
    fancy_header("🗓️", "Daily planner and goals", "Small goals, every single day")
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
                    flash("Goal done ✅")
                else:
                    flash("All goals done today! You are on fire 🔥", "balloons")
            st.rerun()
    if goals:
        finished = sum(1 for g in goals if g[2])
        st.progress(finished / len(goals))
        st.caption(f"🦜 {finished} of {len(goals)} goals done today")
 
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
        st.toast("Correct! Keep going", icon="🎉")
    else:
        st.error(f"Not correct. Right answer: {correct_answer}")
        st.toast("Saved in Mistakes. You will beat it next time", icon="💪")
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
    fancy_header("🎯", "Practice", "Solve inside the app. Wrong answers are saved for you")
    t1, t2, t3 = st.tabs(["Solve", "Add question", "AI-generate"])
    with t1:
        tab_solve()
    with t2:
        tab_add_question()
    with t3:
        tab_generate()
 
 
def page_mistakes():
    fancy_header("🧠", "Mistakes", "Fix your mistakes and you grow faster")
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
                    flash("Mistake fixed. That is how you improve!", "balloons")
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
    fancy_header("📝", "Notes", "Write, search and keep all your notes here")
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
    fancy_header("🤖", "AI Tutor", "Ask any doubt, get a simple explanation")
    chat_ui(
        "chat_tutor",
        "You are a friendly study tutor for BSc IT and engineering students. Explain with simple "
        "words and a real-life example, keep answers short, then offer one practice question.",
        "Ask any doubt. Uses your daily AI limit.",
    )
 
 
def page_english():
    fancy_header("💬", "English Coach", "Chat in English and improve every day")
    chat_ui(
        "chat_english",
        "You are a friendly spoken-English coach. Reply in simple English. If the student makes a "
        "grammar mistake, show the corrected sentence in one line, then continue the conversation "
        "and ask one easy question.",
        "Practice English by chatting. Type like you would speak. (Voice can be added later.)",
    )
 
 
def page_videos():
    fancy_header("🎬", "Study Videos", "Only study videos, zero distraction")
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
    fancy_header("🎵", "Music", "Your own playlist while you study")
    with st.form("add_song", clear_on_submit=True):
        title = st.text_input("Song name")
        up = st.file_uploader("Upload a song file", type=["mp3", "wav", "ogg", "m4a"])
        link = st.text_input("...or a direct audio link (optional)")
        if st.form_submit_button("Add song") and title.strip():
            if up is not None:
                path = SONGS_DIR / f"{int(time.time())}_{Path(up.name).name}"
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
    fancy_header("📁", "Files", "All your study files in one place")
    st.caption("Save study photos and files here instead of WhatsApp or random folders.")
    with st.form("add_file", clear_on_submit=True):
        subject = st.text_input("Subject")
        ups = st.file_uploader("Choose files", accept_multiple_files=True)
        if st.form_submit_button("Save files") and ups:
            for up in ups:
                path = FILES_DIR / f"{int(time.time())}_{Path(up.name).name}"
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
    fancy_header("🧮", "Calculator", "Quick calculations without leaving the app")
    st.caption("Examples: 2*(3+4)**2    sqrt(16)    sin(pi/2)    log10(1000)")
    expr = st.text_input("Expression")
    if expr:
        try:
            st.success(f"Answer: {safe_eval(ast.parse(expr, mode='eval'))}")
        except Exception:
            st.error("Could not calculate that. Check the expression.")
 
 
def page_usage():
    fancy_header("📊", "Usage Stats", "See where your study time really goes")
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
    st.set_page_config(page_title="Topper Nest", layout="wide")
    init_db()
    style()
    st.sidebar.markdown(
        '<div class="brand">🪺 Topper Nest<small>study smarter, not harder</small></div>',
        unsafe_allow_html=True,
    )
    page = st.sidebar.radio("Menu", PAGES, format_func=lambda p: f"{ICONS[p]}  {p}")
    st.sidebar.divider()
    st.sidebar.text_input("Claude API key (for AI pages)", type="password", key="api_key")
    st.sidebar.number_input("AI messages allowed per day", 1, 500, DEFAULT_DAILY_LIMIT, key="ai_limit")
    track(page)
    {
        "Home": page_home, "Syllabus": page_syllabus, "Planner": page_planner,
        "Practice": page_practice, "Mistakes": page_mistakes, "Notes": page_notes,
        "AI Tutor": page_ai_tutor, "English Coach": page_english,
        "Study Videos": page_videos, "Music": page_music, "Files": page_files,
        "Calculator": page_calculator, "Usage Stats": page_usage,
    }[page]()
    show_flash()
 
 
if __name__ == "__main__":
    main()
 