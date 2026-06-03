import streamlit as st
import sqlite3
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
# CONFIG & TIMEZONE FIX
# =========================================================
st.set_page_config(
    page_title="AI Exam Security Pipeline",
    page_icon="🔐",
    layout="centered"
)

try:
    import zoneinfo
    LOCAL_TZ = zoneinfo.ZoneInfo("Asia/Kolkata")  
except ImportError:
    class IST(datetime.tzinfo):
        def utcoffset(self, dt): return datetime.timedelta(hours=5, minutes=30)
        def tzname(self, dt): return "IST"
        def dst(self, dt): return datetime.timedelta(0)
    LOCAL_TZ = IST()

def get_current_local_datetime():
    return datetime.datetime.now(LOCAL_TZ)

def get_current_local_epoch():
    return get_current_local_datetime().timestamp()

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
    margin-bottom: 15px;
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
# DATABASE INTEGRATION
# =========================================================
conn = sqlite3.connect("exams_v3.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS exams (
    exam_id TEXT PRIMARY KEY,
    username TEXT,
    password TEXT,
    questions TEXT,
    created_at REAL,
    expires_at REAL,
    consumed INTEGER,
    exam_duration INTEGER,
    student_answers TEXT,
    target_students INTEGER,
    points_per_question REAL,
    scheduled_start REAL
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS submissions (
    submission_id INTEGER PRIMARY KEY AUTOINCREMENT,
    exam_id TEXT,
    username TEXT,
    final_score REAL,
    submitted_at REAL
)
""")
conn.commit()

# =========================================================
# SYSTEM CORE HELPERS & GENERATION ENGINE
# =========================================================
def token(n=6):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=n))

@st.cache_data(ttl=600)
def fetch_text(topic):
    try:
        q = urllib.parse.quote(topic + " wiki summary structures")
        url = f"https://html.duckduckgo.com/html/?q={q}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as r:
            html = r.read().decode()
        snippets = re.findall(r'<a class="result__snippet"[^>]*>(.*?)</a>', html)
        return " ".join([re.sub(r"<.*?>", "", s) for s in snippets])
    except:
        return ""

def generate_questions(topic, n):
    raw_text = fetch_text(topic)
    
    backup_vocab = {
        "frameworks": ["Architecture", "Infrastructure", "Methodology", "Paradigm", "Protocol", "Ecosystem"],
        "analytics": ["Quantitative", "Assessment", "Metric", "Optimization", "Stochastic", "Evaluation"],
        "development": ["Integration", "Deployment", "Compilation", "Execution", "Automation", "Pipeline"]
    }
    all_pool = backup_vocab["frameworks"] + backup_vocab["analytics"] + backup_vocab["development"]
    
    sentences = [s.strip() for s in raw_text.split(".") if len(s.strip()) > 25]
    
    while len(sentences) < n:
        sentences.append(f"The core operational framework of {topic} enables high-performance execution patterns")
        sentences.append(f"Strategic application of {topic} principles establishes structural paradigm integrity")
        sentences.append(f"A key requirement in {topic} methodologies involves managing systemic lifecycle parameters")
        sentences.append(f"Advanced evaluation of {topic} designs optimizes processing throughput and analytics")

    questions = []
    difficulties = ["Easy", "Medium", "Hard"]

    for i in range(n):
        current_sentence = sentences[i % len(sentences)]
        words = [w.strip(".,()\"';:") for w in current_sentence.split() if len(w.strip(".,()\"';:")) > 4 and w.lower() != topic.lower()]
        
        if not words:
            words = random.sample(all_pool, k=3)
            
        answer = random.choice(words)
        q_type = "MCQ" if i % 2 == 0 else "FITB"
        
        if q_type == "MCQ":
            q_text = f"Regarding the architecture of {topic}, evaluate the context details to determine the matching concept:\n\n\"{current_sentence}\""
        else:
            pattern = re.compile(re.escape(answer), re.IGNORECASE)
            masked_sentence = pattern.sub("_______", current_sentence, count=1)
            q_text = f"Complete the following specialized statement concerning {topic} principles:\n\n\"{masked_sentence}\""

        remaining_pool = list(set([w for w in words if w.lower() != answer.lower()] + all_pool))
        distractors = random.sample(remaining_pool, k=min(3, len(remaining_pool)))
        
        while len(distractors) < 3:
            extra = random.choice(all_pool)
            if extra not in distractors and extra.lower() != answer.lower():
                distractors.append(extra)

        options = list(set(distractors + [answer]))
        random.shuffle(options)
        level = difficulties[i % 3] 

        questions.append({
            "q": q_text,
            "options": options,
            "correct": answer,
            "level": level,
            "type": q_type
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
# STATE INITIALIZATION
# =========================================================
exam_id = st.query_params.get("exam_id")
review_mode = st.query_params.get("review")
view_type = st.query_params.get("view") 
is_admin = st.query_params.get("admin") == "true"

if "current_tracking_id" not in st.session_state:
    st.session_state.current_tracking_id = exam_id or review_mode
else:
    active_id = exam_id or review_mode
    if st.session_state.current_tracking_id != active_id:
        st.session_state.clear()
        st.session_state.current_tracking_id = active_id
        st.rerun()

if "auth" not in st.session_state:
    st.session_state.auth = False
if "answers" not in st.session_state:
    st.session_state.answers = {}

base_url = get_base_url()

# =========================================================
# RUNTIME ROUTES (ADMIN & SUBMISSIONS VIEWS)
# =========================================================
if review_mode and view_type == "host":
    if not is_admin:
        st.error("🔒 Access Denied.")
        st.stop()
    st.title("📋 Admin Dashboard: Individual Student Results")
    cursor.execute("SELECT questions, points_per_question, password FROM exams WHERE exam_id=?", (review_mode,))
    exam_data = cursor.fetchone()
    if not exam_data:
        st.error("Invalid Exam ID.")
        st.stop()
        
    num_qs = len(json.loads(exam_data[0]))
    fixed_pts = exam_data[1]
    max_possible = num_qs * fixed_pts
    passwords_matrix = json.loads(exam_data[2])
    
    cursor.execute("SELECT username, final_score FROM submissions WHERE exam_id=?", (review_mode,))
    submissions_dict = {row[0]: row[1] for row in cursor.fetchall()}
    
    for student_username in sorted(passwords_matrix.keys()):
        if student_username in submissions_dict:
            score = submissions_dict[student_username]
            st.markdown(f'<div class="sheet-row"><div>Candidate Username: <strong>{student_username}</strong></div><div style="font-weight: bold; color: #1E3A8A;">{score} / {max_possible} Total Marks</div></div>', unsafe_allow_html=True)
        else:
            st.markdown(f'<div class="sheet-row" style="border-left: 5px solid #EF4444; background-color: #FEF2F2;"><div>Candidate Username: <strong>{student_username}</strong></div><div style="font-weight: bold; color: #EF4444; font-style: italic;">Absent / Not taking exam</div></div>', unsafe_allow_html=True)
        
    if st.button("Back to Control Router"):
        st.query_params.clear()
        st.query_params["review"] = review_mode
        st.query_params["view"] = "submitted"
        st.query_params["admin"] = "true"
        st.rerun()
    st.stop()

elif review_mode and view_type == "ranks":
    if not is_admin:
        st.error("🔒 Access Denied.")
        st.stop()
    st.title("🏆 Admin Dashboard: Student Leaderboard Ranks")
    cursor.execute("SELECT username, final_score FROM submissions WHERE exam_id=? ORDER BY final_score DESC, submitted_at ASC", (review_mode,))
    leaderboard = cursor.fetchall()
    if not leaderboard:
        st.info("No records completed yet.")
        st.stop()
        
    for idx, position in enumerate(leaderboard):
        st.markdown(f'<div class="sheet-row"><div><strong>Rank #{idx+1}</strong> — <code>{position[0]}</code></div><div style="font-weight: bold; color: #D97706;">Score: {position[1]} Marks</div></div>', unsafe_allow_html=True)
        
    if st.button("Back to Control Router"):
        st.query_params.clear()
        st.query_params["review"] = review_mode
        st.query_params["view"] = "submitted"
        st.query_params["admin"] = "true"
        st.rerun()
    st.stop()

elif review_mode and view_type == "answers":
    if not is_admin:
        st.error("🔒 Access Denied.")
        st.stop()
    st.title("🔍 Admin Dashboard: Student Answer Sheet Analytics")
    cursor.execute("SELECT questions, student_answers FROM exams WHERE exam_id=?", (review_mode,))
    exam_row = cursor.fetchone()
    qs = json.loads(exam_row[0])
    all_students_answers = json.loads(exam_row[1]) if exam_row[1] else {}
    if not all_students_answers:
        st.info("No answer analytics found.")
        st.stop()
        
    selected_student = st.selectbox("Select Student Profile:", list(all_students_answers.keys()))
    student_specific_answers = all_students_answers.get(selected_student, {})
    
    for i, q in enumerate(qs):
        user_choice = student_specific_answers.get(str(i))
        correct_choice = q["correct"]
        q_label = "Multiple-Choice" if q.get("type", "MCQ") == "MCQ" else "Fill-In-The-Blank"
        
        if user_choice is None:
            status_text, status_color = "⚠️ Unanswered", "#64748b"
        elif user_choice == correct_choice:
            status_text, status_color = f"✅ Correct Match ({q['correct']})", "#15803D"
        else:
            status_text, status_color = f"❌ Wrong Match (Selected: '{user_choice}' | Correct: '{correct_choice}')", "#B91C1C"
            
        st.markdown(f'<div class="sheet-row"><div><strong>Question {i+1} ({q_label})</strong></div><div style="color: {status_color}; font-weight: bold;">{status_text}</div></div>', unsafe_allow_html=True)
        
    if st.button("Back to Control Router"):
        st.query_params.clear()
        st.query_params["review"] = review_mode
        st.query_params["view"] = "submitted"
        st.query_params["admin"] = "true"
        st.rerun()
    st.stop()

elif review_mode and view_type == "submitted":
    cursor.execute("SELECT target_students, consumed FROM exams WHERE exam_id=?", (review_mode,))
    exam_db_row = cursor.fetchone()
    if not exam_db_row:
        st.error("Exam entry data not found.")
        st.stop()
        
    target_count = exam_db_row[0]
    is_force_closed = exam_db_row[1] == 1
    
    cursor.execute("SELECT COUNT(*) FROM submissions WHERE exam_id=?", (review_mode,))
    current_count = cursor.fetchone()[0]

    all_completed = (current_count >= target_count) or is_force_closed

    if not is_admin:
        st.title("📝 Submission Complete")
        st.success("Thank you! Your exam has been successfully submitted.")
        st.stop()
            
    st.title("⚡ Admin Control Center Panel Router")
    
    if not all_completed:
        st.write(f"📈 **Active Progress:** {current_count} out of {target_count} students completed.")
        st.write("---")
        st.subheader("🚨 Exam Lifecycle Management")
        st.info("If students are absent or cannot finish, click below to close the portal and lock the class scores out safely.")
        if st.button("⛔ Force Close Exam Right Now (Handle Absentees)", type="primary"):
            cursor.execute("UPDATE exams SET consumed=1 WHERE exam_id=?", (review_mode,))
            conn.commit()
            st.rerun()

    st.markdown("### 🛠️ Review Sheets Dashboards:")
    
    if st.button("📊 Open Individual Scores Sheet", use_container_width=True):
        st.query_params.clear()
        st.query_params["review"] = review_mode
        st.query_params["view"] = "host"
        st.query_params["admin"] = "true"
        st.rerun()
        
    if st.button("🏆 Open Rankings Leaderboard Sheet", use_container_width=True):
        st.query_params.clear()
        st.query_params["review"] = review_mode
        st.query_params["view"] = "ranks"
        st.query_params["admin"] = "true"
        st.rerun()
        
    if st.button("🔍 Open Individual Student Answer Sheets", use_container_width=True):
        st.query_params.clear()
        st.query_params["review"] = review_mode
        st.query_params["view"] = "answers"
        st.query_params["admin"] = "true"
        st.rerun()
        
    st.write("---")
    if st.button("♻️ Clear Cycle & Create New Exam", type="primary"):
        st.query_params.clear()
        st.session_state.clear()
        st.rerun()
    st.stop()

# =========================================================
# ROUTE 5: TEACHER CREATION PANEL
# =========================================================
elif not exam_id and not review_mode:
    st.title("🎓 AI MCQ & FITB Generator (Admin Panel)")

    topic = st.text_input("Topic Context", value="", placeholder="Enter your Topic")
    num_q = st.number_input("Questions Count", 2, 50, 6)
    fixed_score_weight = st.number_input("Fixed Marks Per Question", 1.0, 100.0, 1.0)
    student_headcount = st.number_input("Manually Add Student Count", 1, 100, 3)

    st.write("---")
    st.subheader("📅 Schedule Activation Configuration (Local Time)")
    
    if "admin_chosen_date" not in st.session_state or "admin_chosen_time" not in st.session_state:
        current_local = get_current_local_datetime()
        buffered_local = current_local + datetime.timedelta(minutes=5)
        st.session_state.admin_chosen_date = buffered_local.date()
        st.session_state.admin_chosen_time = buffered_local.time()
    
    col1, col2 = st.columns(2)
    with col1:
        chosen_date = st.date_input("Select Start Date", key="admin_chosen_date")
    with col2:
        # Step parameter added here to force 5-minute increments
        chosen_time = st.time_input("Select Start Time (24Hr format)", step=300, key="admin_chosen_time")

    if st.button("Generate Secure Exam Suite", type="primary"):
        if not topic.strip():
            st.error("🚨 Enter the text! Topic Context field cannot be left blank.")
        else:
            combined_naive = datetime.datetime.combine(chosen_date, chosen_time)
            combined_localized = combined_naive.replace(tzinfo=LOCAL_TZ)
            epoch_start_time = combined_localized.timestamp()

            qs = generate_questions(topic, int(num_q))
            exam = token(8)
            
            passwords_matrix = {}
            for idx in range(1, int(student_headcount) + 1):
                generated_username = f"CANDIDATE_{idx}"
                passwords_matrix[generated_username] = f"PASS_{token(4)}"
                
            now_epoch = get_current_local_epoch()

            cursor.execute("""
            INSERT INTO exams (exam_id, username, password, questions, created_at, expires_at, consumed, exam_duration, student_answers, target_students, points_per_question, scheduled_start) 
            VALUES (?,?,?,?,?,?,?,?, ?, ?, ?, ?)
            """, (exam, "MULTI_STUDENT", json.dumps(passwords_matrix), json.dumps(qs), now_epoch, now_epoch + 7200, 0, int(num_q)*45, json.dumps({}), int(student_headcount), float(fixed_score_weight), epoch_start_time))
            conn.commit()

            student_link = f"{base_url}/?exam_id={exam}"
            st.session_state.admin_exam_target = exam
            st.query_params.clear()

            if "admin_chosen_date" in st.session_state: del st.session_state.admin_chosen_date
            if "admin_chosen_time" in st.session_state: del st.session_state.admin_chosen_time

            st.success(f"Exam Suite Generated Successfully!")
            st.markdown(f"""
            <div class="token-box">
            <b>Shared Testing URL for Students:</b> <code>{student_link}</code><br>
            📅 Scheduled To Open (Your Local Time): <code>{combined_localized.strftime('%Y-%m-%d %H:%M:%S')}</code>
            </div>
            """, unsafe_allow_html=True)

    if "admin_exam_target" in st.session_state:
        st.write("---")
        st.write("### 🛠️ Administrative Navigation Access")
        if st.button("Go to Admin Results & Rankings Hub", type="secondary"):
            target = st.session_state.admin_exam_target
            st.query_params.clear()
            st.query_params["review"] = target
            st.query_params["view"] = "submitted"
            st.query_params["admin"] = "true"
            st.rerun()

# =========================================================
# ROUTE 6: STUDENT SECURE PORTAL
# =========================================================
else:
    cursor.execute("SELECT exam_id, username, password, questions, created_at, expires_at, consumed, exam_duration, student_answers, target_students, points_per_question, scheduled_start FROM exams WHERE exam_id=?", (exam_id,))
    data = cursor.fetchone()

    if not data:
        st.query_params.clear()
        st.query_params["review"] = exam_id
        st.query_params["view"] = "submitted"
        st.rerun()

    (eid, group_name, password_matrix_json, qs_json, created, expires, consumed, duration, raw_answers, target_students, points_per_question, scheduled_start) = data
    passwords_matrix = json.loads(password_matrix_json)
    
    current_local_epoch = get_current_local_epoch()

    if current_local_epoch < scheduled_start:
        st_autorefresh(interval=2000, key="empty_countdown_refresh")
        
        readable_target_time = datetime.datetime.fromtimestamp(scheduled_start, LOCAL_TZ).strftime('%Y-%m-%d %H:%M:%S')
        st.markdown(f"""
        <div class="empty-lock-screen">
            This exam will open at: {readable_target_time}
        </div>
        """, unsafe_allow_html=True)
        st.stop()

    if consumed == 1:
        st.title("❌ Session Terminated")
        st.error("The admin has closed this testing session. No further entries are allowed.")
        st.stop()

    if not st.session_state.auth and (current_local_epoch > (scheduled_start + 10800)):
        st.title("❌ Access Expired")
        st.error("The entrance window for this exam session has expired.")
        st.stop()

    cursor.execute("SELECT username FROM submissions WHERE exam_id=?", (exam_id,))
    completed_usernames = [row[0] for row in cursor.fetchall()]

    if not st.session_state.auth:
        st.title("🔐 Secure Access Environment")
        available_options = [user for user in passwords_matrix.keys() if user not in completed_usernames]
        
        if not available_options:
            st.title("📝 Session Complete")
            st.success("Thank you! Your exam has been successfully submitted.")
            st.stop()
            
        st.write("Select your Username from the dropdown menu to see your matching password:")
        options_with_placeholder = ["--- Select Your Username ---"] + available_options
        selected_user = st.selectbox("Choose Your Auto-Generated Username", options_with_placeholder, index=0)
        
        if selected_user != "--- Select Your Username ---":
            active_password = passwords_matrix.get(selected_user)
            
            st.markdown(f"""
            <div class="token-box" style="border-left-color: #D97706; margin-bottom: 20px;">
            👤 Username Selected: <code>{selected_user}</code><br>
            🔑 Match Password Keyphrase: <code>{active_password}</code>
            </div>
            """, unsafe_allow_html=True)

            with st.form("login"):
                p = st.text_input("Enter the Password Keyphrase shown above", type="password")
                ok = st.form_submit_button("Authenticate Workspace")

                if ok:
                    if p.strip() != active_password:
                        st.error("Access Control Warning: Password must match the selected username's passcode.")
                    else:
                        st.session_state.auth = True
                        st.session_state.current_candidate_user = selected_user
                        st.session_state.questions = json.loads(qs_json)
                        st.session_state.start = get_current_local_epoch()
                        st.session_state.duration = duration
                        st.rerun()
        else:
            st.info("Please expand the dropdown selector above to verify your account seating.")
    else:
        st.title(f"📝 Active Workspace: {st.session_state.current_candidate_user}")
        st_autorefresh(interval=1000, key="exam")

        qs = st.session_state.questions
        elapsed = get_current_local_epoch() - st.session_state.start
        remaining = max(0, int(st.session_state.duration - elapsed))

        m, s = divmod(remaining, 60)
        st.warning(f"Time remaining: {m:02d}:{s:02d}")

        def process_and_submit_exam():
            cursor.execute("SELECT student_answers FROM exams WHERE exam_id=?", (exam_id,))
            existing_answers_raw = cursor.fetchone()[0]
            master_answers_dict = json.loads(existing_answers_raw) if existing_answers_raw else {}
            
            student_profile_name = st.session_state.current_candidate_user
            master_answers_dict[student_profile_name] = {}
            for k in range(len(qs)):
                radio_key = f"radio_q_{k}"
                val = st.session_state.get(radio_key, st.session_state.answers.get(k))
                if val is not None:
                    master_answers_dict[student_profile_name][str(k)] = val
            
            cursor.execute("UPDATE exams SET student_answers=? WHERE exam_id=?", (json.dumps(master_answers_dict), exam_id))
            
            final_calculated_score = 0.0
            for index, question in enumerate(qs):
                radio_key = f"radio_q_{index}"
                student_choice = st.session_state.get(radio_key, st.session_state.answers.get(index))
                if student_choice == question["correct"]:
                    final_calculated_score += points_per_question
                elif student_choice is not None:
                    final_calculated_score -= 1.0
            
            cursor.execute("""
                INSERT INTO submissions (exam_id, username, final_score, submitted_at)
                VALUES (?, ?, ?, ?)
            """, (exam_id, student_profile_name, final_calculated_score, get_current_local_epoch()))
            conn.commit()
            
            st.query_params.clear()
            st.query_params["review"] = exam_id
            st.query_params["view"] = "submitted"
            st.session_state.auth = False
            st.rerun()

        if remaining == 0:
            process_and_submit_exam()

        def save_answer(q_idx):
            radio_key = f"radio_q_{q_idx}"
            if radio_key in st.session_state:
                st.session_state.answers[q_idx] = st.session_state[radio_key]

        for i, q in enumerate(qs):
            # Type labels variable removed to only feature the clean "Question X" text header format
            st.markdown(f'### Question {i+1}')
            st.write(q["q"])

            saved_choice = st.session_state.answers.get(i, None)
            default_index = q["options"].index(saved_choice) if saved_choice in q["options"] else None

            st.radio(
                label=f"Choose option for question {i+1}:",
                options=q["options"],
                index=default_index,
                key=f"radio_q_{i}",
                label_visibility="collapsed",
                on_change=save_answer,
                args=(i,)
            )
            st.write("---")

        if st.button("Finalize and Submit", type="primary"):
            process_and_submit_exam()