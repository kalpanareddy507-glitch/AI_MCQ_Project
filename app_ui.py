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
# CONFIG
# =========================================================
st.set_page_config(
    page_title="AI Exam Security Pipeline",
    page_icon="🔐",
    layout="centered"
)

# Initialize all required global state keys safely at root execution
if "admin_exam_target" not in st.session_state:
    st.session_state.admin_exam_target = None
if "auth" not in st.session_state:
    st.session_state.auth = False
if "answers" not in st.session_state:
    st.session_state.answers = {}
if "manual_date_str" not in st.session_state:
    st.session_state.manual_date_str = datetime.date.today().strftime("%Y-%m-%d")
if "manual_time_str" not in st.session_state:
    st.session_state.manual_time_str = datetime.datetime.now().strftime("%H:%M")
if "current_candidate_user" not in st.session_state:
    st.session_state.current_candidate_user = None
if "questions" not in st.session_state:
    st.session_state.questions = []
if "start" not in st.session_state:
    st.session_state.start = None
if "duration" not in st.session_state:
    st.session_state.duration = 0

# Initialize Supabase Database Connection
conn = st.connection("postgresql", type="sql")

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
/* Style to create an entirely clean, empty interface when an exam is locked */
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
# TRACK AND SANITIZE STATE MISMATCHES
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

base_url = get_base_url()

# =========================================================
# ROUTE 1: HOST INDIVIDUAL RESULTS SHEET VIEW (&view=host)
# =========================================================
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
        st.error("Invalid Exam ID.")
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
        st.query_params.clear()
        st.query_params["review"] = review_mode
        st.query_params["view"] = "submitted"
        st.query_params["admin"] = "true"
        st.rerun()
    st.stop()

# =========================================================
# ROUTE 2: SEPARATE RANKINGS LEADERBOARD VIEW (&view=ranks)
# =========================================================
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
    
    if leaderboard_df.empty:
        st.info("No records completed yet.")
        st.stop()
        
    for idx, row in leaderboard_df.iterrows():
        user_lbl = row["username"]
        val_score = row["final_score"]
        
        st.markdown(f"""
        <div class="sheet-row">
            <div><strong>Rank #{idx+1}</strong> — <code>{user_lbl}</code></div>
            <div style="font-weight: bold; color: #D97706;">Rank Position {idx+1} ({val_score} Marks)</div>
        </div>
        """, unsafe_allow_html=True)
        
    if st.button("Back to Control Router"):
        st.query_params.clear()
        st.query_params["review"] = review_mode
        st.query_params["view"] = "submitted"
        st.query_params["admin"] = "true"
        st.rerun()
    st.stop()

# =========================================================
# ROUTE 3: SEPARATE DIAGNOSTIC ANSWERS MATRIX (&view=answers)
# =========================================================
elif review_mode and view_type == "answers":
    if not is_admin:
        st.error("🔒 Access Denied. This page is locked for Admin Eyes Only.")
        st.stop()

    st.title("🔍 Admin Dashboard: Student Answer Sheet Analytics")
    
    exam_df = conn.query(
        "SELECT questions, student_answers FROM exams WHERE exam_id = :review_mode LIMIT 1;", 
        params={"review_mode": review_mode}, 
        ttl=0
    )
    
    if exam_df.empty:
        st.error("Invalid Exam Link context.")
        st.stop()
        
    exam_row = exam_df.iloc[0]
    qs = json.loads(exam_row["questions"])
    all_students_answers = json.loads(exam_row["student_answers"]) if exam_row["student_answers"] else {}
    
    if not all_students_answers:
        st.info("No answer analytics found.")
        st.stop()
        
    selected_student = st.selectbox("Select Student Profile to View Answer Sheet:", list(all_students_answers.keys()))
    
    st.subheader(f"Detailed Answer Sheet for User: {selected_student}")
    student_specific_answers = all_students_answers.get(selected_student, {})
    
    for i, q in enumerate(qs):
        user_choice = student_specific_answers.get(str(i))
        correct_choice = q["correct"]
        
        if user_choice is None:
            status_text, status_color = "⚠️ Unanswered", "#64748b"
        elif user_choice == correct_choice:
            status_text, status_color = f"✅ Correct Match ({q['correct']})", "#15803D"
        else:
            status_text, status_color = f"❌ Wrong Match (Selected: '{user_choice}' | Correct: '{correct_choice}')", "#B91C1C"
            
        st.markdown(f"""
        <div class="sheet-row">
            <div><strong>Question {i+1} Evaluation</strong></div>
            <div style="color: {status_color}; font-weight: bold;">{status_text}</div>
        </div>
        """, unsafe_allow_html=True)
        
    if st.button("Back to Control Router"):
        st.query_params.clear()
        st.query_params["review"] = review_mode
        st.query_params["view"] = "submitted"
        st.query_params["admin"] = "true"
        st.rerun()
    st.stop()

# =========================================================
# ROUTE 4: MASTER HUBS ROUTER PAGE SCREEN
# =========================================================
elif review_mode and view_type == "submitted":
    if not is_admin:
        st.title("📝 Submission Complete")
        st.success("Thank you! Your exam has been successfully submitted.")
        st.stop()
            
    if is_admin:
        target_df = conn.query(
            "SELECT target_students FROM exams WHERE exam_id = :review_mode LIMIT 1;", 
            params={"review_mode": review_mode}, 
            ttl=0
        )
        target_count = target_df.iloc[0]["target_students"] if not target_df.empty else 0
        
        count_df = conn.query(
            "SELECT COUNT(*) as count FROM submissions WHERE exam_id = :review_mode;", 
            params={"review_mode": review_mode}, 
            ttl=0
        )
        current_count = count_df.iloc[0]["count"] if not count_df.empty else 0

        st.title("⚡ Admin Control Center Panel Router")
        st.write(f"**Progress Metrics:** {current_count} out of {target_count} students completed.")
        
        # FIX: Replaced broken HTML link injection with error-free Streamlit native buttons
        st.markdown('<div class="token-box">🛠️ <b>Select an administrative view layout below to navigate instantly:</b></div>', unsafe_allow_html=True)
        
        if st.button("📊 Open Individual Student Scores Sheet", use_container_width=True):
            st.query_params.clear()
            st.query_params["review"] = review_mode
            st.query_params["view"] = "host"
            st.query_params["admin"] = "true"
            st.rerun()
            
        if st.button("🏆 Open Isolated Ranks Leaderboard", use_container_width=True):
            st.query_params.clear()
            st.query_params["review"] = review_mode
            st.query_params["view"] = "ranks"
            st.query_params["admin"] = "true"
            st.rerun()
            
        if st.button("🔍 Open Detailed Answer Sheet Analytics", use_container_width=True):
            st.query_params.clear()
            st.query_params["review"] = review_mode
            st.query_params["view"] = "answers"
            st.query_params["admin"] = "true"
            st.rerun()
            
        st.write("---")
        if st.button("🔄 Clear Cycle & Restart App Entirely", type="primary"):
            st.query_params.clear()
            st.session_state.clear()
            st.rerun()
        st.stop()

# =========================================================
# TEACHER PANEL
# =========================================================
elif not exam_id and not review_mode:
    st.title("🎓 AI MCQ Generator (Admin Panel)")

    topic = st.text_input("Topic Context", value="", placeholder="Enter your Topic")
    num_q = st.number_input("Questions Count", 1, 50, 5)
    fixed_score_weight = st.number_input("Fixed Marks Per Question", 1, 100, 1)
    student_headcount = st.number_input("Manually Add Student Count", 1, 100, 3)

    st.write("---")
    st.subheader("📅 Schedule Activation Configuration (Manual Entry)")
    col1, col2 = st.columns(2)
    
    with col1:
        input_date = st.text_input("Enter Date (YYYY-MM-DD)", value=st.session_state.manual_date_str)
        st.session_state.manual_date_str = input_date
    with col2:
        input_time = st.text_input("Enter Start Time (HH:MM - 24Hr format)", value=st.session_state.manual_time_str)
        st.session_state.manual_time_str = input_time

    if st.button("Generate Secure Exam Suite", type="primary"):
        if not topic.strip():
            st.error("🚨 Enter the text! Topic Context field cannot be left blank.")
        else:
            try:
                parsed_date = datetime.datetime.strptime(st.session_state.manual_date_str.strip(), "%Y-%m-%d").date()
                parsed_time = datetime.datetime.strptime(st.session_state.manual_time_str.strip(), "%H:%M").time()
                combined_dt = datetime.datetime.combine(parsed_date, parsed_time)
                epoch_start_time = combined_dt.timestamp()
            except Exception as e:
                st.error("❌ Invalid Format! Please enter the Date exactly as YYYY-MM-DD and Time as HH:MM.")
                st.stop()

            qs = generate_questions(topic, int(num_q))
            exam = token(8)
            
            passwords_matrix = {}
            for idx in range(1, int(student_headcount) + 1):
                generated_username = f"CANDIDATE_{idx}"
                passwords_matrix[generated_username] = f"PASS_{token(4)}"
                
            now = time.time()

            with conn.session as session:
                session.execute(
                    text("""
                        INSERT INTO exams (
                            exam_id, username, password, questions, created_at, 
                            expires_at, consumed, exam_duration, student_answers, 
                            target_students, points_per_question, scheduled_start
                        )
                        VALUES (
                            :exam, :user, :passwords, :qs, :now, 
                            :expires, :consumed, :duration, :answers, 
                            :target, :points, :start
                        )
                    """), 
                    {
                        "exam": exam,
                        "user": "MULTI_STUDENT",
                        "passwords": json.dumps(passwords_matrix),
                        "qs": json.dumps(qs),
                        "now": now,
                        "expires": now + 3600*2,
                        "consumed": 0,
                        "duration": int(num_q)*45,
                        "answers": json.dumps({}),
                        "target": int(student_headcount),
                        "points": float(fixed_score_weight),
                        "start": epoch_start_time
                    }
                )
                session.commit()

            student_link = f"{base_url}/?exam_id={exam}"
            st.session_state.admin_exam_target = exam
            st.query_params.clear()

            st.success(f"Exam Suite Generated Successfully!")
            st.markdown(f"""
            <div class="token-box">
            <b>Shared Testing URL for Students:</b> <code>{student_link}</code><br>
            📅 Scheduled To Open: <code>{combined_dt.strftime('%Y-%m-%d %H:%M:%S')}</code>
            </div>
            """, unsafe_allow_html=True)
            st.write("### Generated Student Passwords Credentials Matrix:")
            st.json(passwords_matrix)

    if st.session_state.admin_exam_target is not None:
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
# STUDENT SECURE PORTAL ENTRY MAPPINGS
# =========================================================
else:
    df_exam = conn.query(
        "SELECT * FROM exams WHERE exam_id = :exam_id LIMIT 1;", 
        params={"exam_id": exam_id}, 
        ttl=0
    )

    if df_exam.empty:
        st.error("Invalid verification parameters.")
        st.stop()

    data_row = df_exam.iloc[0]
    eid = data_row["exam_id"]
    group_name = data_row["username"]
    password_matrix_json = data_row["password"]
    qs_json = data_row["questions"]
    created = data_row["created_at"]
    expires = data_row["expires_at"]
    consumed = data_row["consumed"]
    duration = data_row["exam_duration"]
    raw_answers = data_row["student_answers"]
    target_students = data_row["target_students"]
    points_per_question = float(data_row["points_per_question"])
    scheduled_start = data_row["scheduled_start"]

    passwords_matrix = json.loads(password_matrix_json)
    current_server_time = time.time()

    if current_server_time < scheduled_start:
        st_autorefresh(interval=2000, key="empty_countdown_refresh")
        readable_target_time = datetime.datetime.fromtimestamp(scheduled_start).strftime('%Y-%m-%d %H:%M:%S')
        st.markdown(f"""
        <div class="empty-lock-screen">
            This exam will open at: {readable_target_time}
        </div>
        """, unsafe_allow_html=True)
        st.stop()

    if not st.session_state.auth and (current_server_time > (scheduled_start + 300)):
        st.title("❌ Access Expired")
        st.error("The entrance window for this exam closed 5 minutes after the scheduled start time. You are marked as absent.")
        st.stop()

    sub_users_df = conn.query(
        "SELECT username FROM submissions WHERE exam_id = :exam_id;", 
        params={"exam_id": exam_id}, 
        ttl=0
    )
    completed_usernames = sub_users_df["username"].tolist() if not sub_users_df.empty else []

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
                        check_sub = conn.query(
                            "SELECT COUNT(*) as count FROM submissions WHERE exam_id = :exam_id AND username = :user;", 
                            params={"exam_id": exam_id, "user": selected_user}, 
                            ttl=0
                        )
                        if check_sub.iloc[0]["count"] > 0:
                            st.error("This student username has already logged in or completed this evaluation session!")
                        else:
                            st.session_state.auth = True
                            st.session_state.current_candidate_user = selected_user
                            st.session_state.questions = json.loads(qs_json)
                            st.session_state.start = time.time()
                            st.session_state.duration = duration
                            st.rerun()
        else:
            st.info("Please expand the dropdown selector above to verify your account seating.")
    else:
        st.title(f"📝 Active Workspace: {st.session_state.current_candidate_user}")
        st.sidebar.markdown(f"**Logged in as:** `{st.session_state.current_candidate_user}`")
        st_autorefresh(interval=1000, key="exam_running_refresh")

        qs = st.session_state.questions
        elapsed = time.time() - st.session_state.start
        remaining = max(0, int(st.session_state.duration - elapsed))

        m, s = divmod(remaining, 60)
        st.warning(f"Time remaining: {m:02d}:{s:02d}")

        def process_and_submit_exam():
            exam_row_df = conn.query(
                "SELECT student_answers FROM exams WHERE exam_id = :exam_id LIMIT 1;", 
                params={"exam_id": exam_id}, 
                ttl=0
            )
            existing_answers_raw = exam_row_df.iloc[0]["student_answers"] if not exam_row_df.empty else "{}"
            master_answers_dict = json.loads(existing_answers_raw) if existing_answers_raw else {}
            
            student_profile_name = st.session_state.current_candidate_user
            master_answers_dict[student_profile_name] = {}
            
            for k, v in st.session_state.answers.items():
                master_answers_dict[student_profile_name][str(k)] = v
                
            final_calculated_score = 0.0
            for index, question in enumerate(qs):
                student_choice = st.session_state.answers.get(index)
                correct_choice = question["correct"]
                
                if student_choice == correct_choice:
                    final_calculated_score += points_per_question
                elif student_choice is not None:
                    final_calculated_score -= 1.0

            with conn.session as session:
                session.execute(
                    text("UPDATE exams SET student_answers = :answers WHERE exam_id = :exam_id;"),
                    {"answers": json.dumps(master_answers_dict), "exam_id": exam_id}
                )
                session.execute(
                    text("""
                        INSERT INTO submissions (exam_id, username, final_score, submitted_at)
                        VALUES (:exam_id, :user, :score, :now);
                    """),
                    {
                        "exam_id": exam_id,
                        "user": student_profile_name,
                        "score": final_calculated_score,
                        "now": time.time()
                    }
                )
                session.commit()
            
            st.session_state.clear()
            st.query_params.clear()
            st.query_params["review"] = exam_id
            st.query_params["view"] = "submitted"
            st.rerun()

        if remaining == 0:
            process_and_submit_exam()

        def update_answer(q_idx):
            st.session_state.answers[q_idx] = st.session_state[f"radio_q_{q_idx}"]

        for i, q in enumerate(qs):
            st.markdown(f'### Question {i+1}')
            st.write(q["q"])

            saved_choice = st.session_state.answers.get(i, None)
            default_index = q["options"].index(saved_choice) if saved_choice in q["options"] else None

            chosen_option = st.radio(
                label=f"Choose option for question {i+1}:",
                options=q["options"],
                index=default_index,
                key=f"radio_q_{i}",
                label_visibility="collapsed",
                on_change=update_answer,
                args=(i,)
            )
            st.write("---")

        if st.button("Finalize and Submit", type="primary"):
            process_and_submit_exam()
