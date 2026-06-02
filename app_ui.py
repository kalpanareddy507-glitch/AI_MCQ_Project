import streamlit as st
from sqlalchemy import text
import json
import time
import datetime
import random
import string
import urllib.request
import urllib.parse
import re
from streamlit_autorefresh import st_autorefresh

# =========================================================
# CONFIG & INITIALIZATION
# =========================================================
st.set_page_config(
    page_title="AI Exam Security Pipeline",
    page_icon="🔐",
    layout="centered"
)

# Crucial: Initialize ALL keys at root level. Never let them be completely wiped out.
DEFAULT_STATE = {
    "admin_exam_target": None,
    "auth": False,
    "answers": {},
    "manual_date_str": datetime.date.today().strftime("%Y-%m-%d"),
    "manual_time_str": datetime.datetime.now().strftime("%H:%M"),
    "current_candidate_user": None,
    "questions": [],
    "start": None,
    "duration": 0,
    "current_tracking_id": None
}

for key, val in DEFAULT_STATE.items():
    if key not in st.session_state:
        st.session_state[key] = val

# Initialize Supabase Database Connection Safely
try:
    conn = st.connection("postgresql", type="sql")
except Exception as e:
    st.error("Database Connection Error. Please verify your secrets.toml settings.")
    st.stop()

st.title("AI MCQ Generator & Security Pipeline")

# =========================================================
# CSS STYLE DEFINITIONS
# =========================================================
st.markdown("""
<style>
div.stButton > button[kind="primary"] {
    background-color: #1E3A8A !important;
    color: white !important;
    border-radius: 8px !important;
    width: 100% !important;
    padding: 10px;
}
.token-box {
    background: #f1f5f9;
    padding: 15px;
    border-left: 5px solid #1e3a8a;
    border-radius: 6px;
    margin-bottom: 20px;
}
.sheet-row {
    font-size: 18px !important;
    padding: 12px;
    margin: 6px 0px;
    border-radius: 6px;
    background-color: #f8fafc;
    border: 1px solid #e2e8f0;
    display: flex;
    justify-content: space-between;
}
.empty-lock-screen {
    position: fixed;
    top: 0; left: 0; width: 100vw; height: 100vh;
    background-color: #ffffff;
    z-index: 99999;
    display: flex;
    justify-content: center;
    align-items: center;
    font-family: sans-serif;
    font-size: 24px;
    color: #333333;
}
</style>
""", unsafe_allow_html=True)

# =========================================================
# SYSTEM CORE HELPERS
# =========================================================
def token(n=6):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=n))

@st.cache_data(ttl=600)
def fetch_text(topic):
    try:
        q = urllib.parse.quote(topic + " wiki summary")
        url = f"https://html.duckduckgo.com/html/?q={q}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as r:
            html = r.read().decode()
        snippets = re.findall(r'<a class="result__snippet"[^>]*>(.*?)</a>', html)
        return " ".join([re.sub(r"<.*?>", "", s) for s in snippets])
    except:
        return f"{topic} is an important concept."

def generate_questions(topic, n):
    text_data = fetch_text(topic)
    sentences = [s for s in text_data.split(".") if len(s) > 20]
    if not sentences:
        sentences = [f"{topic} concept explanation"]

    words = list(set(w.strip(".,()\"'") for s in sentences for w in s.split() if len(w) > 4))
    questions = []
    difficulties = ["Easy", "Medium", "Hard"]

    for i in range(n):
        s = sentences[i % len(sentences)]
        clean_words = [w.strip(".,()\"'") for w in s.split() if len(w) > 4]
        if not clean_words:
            clean_words = [topic]

        answer = clean_words[0]
        q = f"Identify key concept from:\n\n{s[:120]}..."
        distractors = random.sample(words, k=min(3, len(words))) if len(words) >= 3 else ["Framework","System","Process"]

        options = list(set(distractors + [answer]))
        random.shuffle(options)
        level = difficulties[i % 3] 

        questions.append({
            "q": q,
            "options": options,
            "correct": answer,
            "level": level
        })
    return questions

def get_base_url():
    try:
        headers = st.context.headers
        host = headers.get("Host", "localhost:8501")
        proto = headers.get("X-Forwarded-Proto", "http")
        return f"{proto}://{host}"
    except:
        return "http://localhost:8501"

# =========================================================
# ROUTING CONTROLLER
# =========================================================
exam_id = st.query_params.get("exam_id")
review_mode = st.query_params.get("review")
view_type = st.query_params.get("view") 
is_admin = st.query_params.get("admin") == "true"

base_url = get_base_url()

# Safe Navigation Helper that keeps state intact while updating variables
def safe_navigate(review, view, admin="true"):
    st.query_params["review"] = review
    st.query_params["view"] = view
    st.query_params["admin"] = admin
    st.rerun()

# ROUTE 1: HOST INDIVIDUAL RESULTS SHEET VIEW
if review_mode and view_type == "host":
    if not is_admin:
        st.error("🔒 Access Denied. This page is locked for Admin Eyes Only.")
        st.stop()

    st.title("📋 Admin Dashboard: Individual Student Results")
    
    exam_df = conn.query(
        "SELECT questions, points_per_question, password FROM exams WHERE exam_id = :review_mode LIMIT 1;", 
        params={"review_mode": review_mode}, 
        ttl=0
    )
    
    if exam_df.empty:
        st.error("Invalid Exam ID context.")
        if st.button("Return Home"):
            st.query_params.clear()
            st.rerun()
        st.stop()
        
    exam_data = exam_df.iloc[0]
    num_qs = len(json.loads(exam_data["questions"]))
    fixed_pts = float(exam_data["points_per_question"])
    max_possible = num_qs * fixed_pts
    passwords_matrix = json.loads(exam_data["password"])
    
    sub_df = conn.query(
        "SELECT username, final_score FROM submissions WHERE exam_id = :review_mode;", 
        params={"review_mode": review_mode}, 
        ttl=0
    )
    submissions_dict = {}
    if not sub_df.empty:
        submissions_dict = dict(zip(sub_df["username"], sub_df["final_score"]))
    
    st.write("### All Registered Student Performance")
    
    for student_username in sorted(passwords_matrix.keys()):
        if student_username in submissions_dict:
            score = submissions_dict[student_username]
            st.markdown(f"""
            <div class="sheet-row">
                <div>Candidate Username: <strong>{student_username}</strong></div>
                <div style="font-weight: bold; color: #1E3A8A;">{score} / {max_possible} Total Marks</div>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.markdown(f"""
            <div class="sheet-row" style="border-left: 5px solid #EF4444; background-color: #FEF2F2;">
                <div>Candidate Username: <strong>{student_username}</strong></div>
                <div style="font-weight: bold; color: #EF4444; font-style: italic;">Absent / Not taking exam</div>
            </div>
            """, unsafe_allow_html=True)
        
    if st.button("Back to Control Router"):
        safe_navigate(review_mode, "submitted")

# ROUTE 2: SEPARATE RANKINGS LEADERBOARD VIEW
elif review_mode and view_type == "ranks":
    if not is_admin:
        st.error("🔒 Access Denied. This page is locked for Admin Eyes Only.")
        st.stop()

    st.title("🏆 Admin Dashboard: Student Leaderboard Ranks")
    
    leaderboard_df = conn.query("""
        SELECT username, final_score FROM submissions 
        WHERE exam_id = :review_mode 
        ORDER BY final_score DESC, submitted_at ASC;
    """, params={"review_mode": review_mode}, ttl=0)
    
    if leaderboard_
