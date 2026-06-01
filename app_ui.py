import streamlit as st
import json
import time
import datetime
import random
import string
import urllib.request
import urllib.parse
import re
import psycopg2
from streamlit_autorefresh import st_autorefresh

# =========================================================
# CONFIG
# =========================================================
st.set_page_config(
    page_title="AI Exam Security Pipeline",
    page_icon="🔐",
    layout="centered"
)

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
# DATABASE INTEGRATION (MIGRATED TO CLOUD POSTGRESQL)
# =========================================================
def get_db_connection():
    conn_str = st.secrets["postgres"]["db_url"]
    return psycopg2.connect(conn_str)

def execute_query(query, params=(), fetch=False, fetchone=False):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(query, params)
        if fetchone:
            result = cursor.fetchone()
        elif fetch:
            result = cursor.fetchall()
        else:
            conn.commit()
            result = None
        return result
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cursor.close()
        conn.close()

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
    text = fetch_text(topic)
    sentences = [s for s in text.split(".") if len(s) > 20]
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

if "auth" not in st.session_state:
    st.session_state.auth = False
if "answers" not in st.session_state:
    st.session_state.answers = {}

if "manual_date_str" not in st.session_state:
    st.session_state.manual_date_str = datetime.date.today().strftime("%Y-%m-%d")
if "manual_time_str" not in st.session_state:
    st.session_state.manual_time_str = datetime.datetime.now().strftime("%H:%M")

base_url = get_base_url()

# =========================================================
# ROUTE 1: HOST INDIVIDUAL RESULTS SHEET VIEW (&view=host)
# =========================================================
if review_mode and view_type == "host":
    if not is_admin:
        st.error("🔒 Access Denied. This page is locked for Admin Eyes Only.")
        st.stop()

    st.title("📋 Admin Dashboard: Individual Student Results")
    exam_data = execute_query("SELECT questions, points_per_question, password FROM exams WHERE exam_id=%s", (review_mode,), fetchone=True)
    
    if not exam_data:
        st.error("Invalid Exam ID.")
        st.stop()
        
    num_qs = len(json.loads(exam_data[0]))
    fixed_pts = exam_data[1]
    max_possible = num_qs * fixed_pts
    passwords_matrix = json.loads(exam_data[2])
    
    submissions_list = execute_query("SELECT username, final_score FROM submissions WHERE exam_id=%s", (review_mode,), fetch=True)
    submissions_dict = {row[0]: row[1] for row in submissions_list}
    
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
    leaderboard = execute_query("""
        SELECT username, final_score FROM submissions 
        WHERE exam_id=%s 
        ORDER BY final_score DESC, submitted_at ASC
    """, (review_mode,), fetch=True)
    
    if not leaderboard:
        st.info("No records completed yet.")
        st.stop()
        
    for idx, position in enumerate(leaderboard):
        user_lbl = position[0]
        val_score = position[1]
        
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
    exam_row = execute_query("SELECT questions, student_answers FROM exams WHERE exam_id=%s", (review_mode,), fetchone=True)
    qs = json.loads(exam_row[0])
    all_students_answers = json.loads(exam_row[1]) if exam_row[1] else {}
    
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
        target_count = execute_query("SELECT target_students FROM exams WHERE exam_id=%s", (review_mode,), fetchone=True)[0]
        current_count = execute_query("SELECT COUNT(*) FROM submissions WHERE exam_id=%s", (review_mode,), fetchone=True)[0]

        st.title("⚡ Admin Control Center Panel Router")
        st.write(f"**Progress Metrics:** {current_count} out of {target_count} students completed.")
        
        host_link = f"{base_url}/?review={review_mode}&view=host&admin=true"
        ranks_link = f"{base_url}/?review={review_mode}&view=ranks&admin=true"
        answers_link = f"{base_url}/?review={review_mode}&view=answers&admin=true"
        
        st.markdown(f"""
        <div class="token-box">
        🔹 <b>Individual Student Marks Layout:</b> <a href="{host_link}" target="_self">Open Scores Sheet</a><br><br>
        🔹 <b>Isolated Rankings Board Layout:</b> <a href="{ranks_link}" target="_self">Open Ranks Sheet</a><br><br>
        🔹 <b>Diagnostic Student Answer Sheets:</b> <a href="{answers_link}" target="_self">Open Individual Answer Sheets</a>
        </div>
        """, unsafe_allow_html=True)
        
        if st.button("Clear Cycle & Restart App"):
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
    num_q = st.number_input("Questions Count", 1, 50, 6)
    fixed_score_weight = st.number_input("Fixed Marks Per Question", 1.0, 100.0, 1.0)
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

            execute_query("""
            INSERT INTO exams (exam_id, username, password, questions, created_at, expires_at, consumed, exam_duration, student_answers, target_students, points_per_question, scheduled_start) 
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (exam, "MULTI_STUDENT", json.dumps(passwords_matrix), json.dumps(qs), now, now + 3600*2, 0, int(num_q)*45, json.dumps({}), int(student_headcount), float(fixed_score_weight), epoch_start_time))

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
# STUDENT SECURE PORTAL ENTRY MAPPINGS
# =========================================================
else:
    data = execute_query("SELECT exam_id, username, password, questions, created_at, expires_at, consumed, exam_duration, student_answers, target_students, points_per_question, scheduled_start FROM exams WHERE exam_id=%s", (exam_id,), fetchone=True)

    if not data:
        st.error("Invalid verification parameters.")
        st.stop()

    (eid, group_name, password_matrix_json, qs_json, created, expires, consumed, duration, raw_answers, target_students, points_per_question, scheduled_start) = data
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

    completed_rows = execute_query("SELECT username FROM submissions WHERE exam_id=%s", (exam_id,), fetch=True)
    completed_usernames = [row[0] for row in completed_rows]

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
                        already_done = execute_query("SELECT COUNT(*) FROM submissions WHERE exam_id=%s AND username=%s", (exam_id, selected_user), fetchone=True)[0]
                        if already_done > 0:
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
        st_autorefresh(interval=1000, key="exam")

        qs = st.session_state.questions
        elapsed = time.time() - st.session_state.start
        remaining = max(0, int(st.session_state.duration - elapsed))

        m, s = divmod(remaining, 60)
        st.warning(f"Time remaining: {m:02d}:{s:02d}")

        def process_and_submit_exam():
            existing_answers_raw = execute_query("SELECT student_answers FROM exams WHERE exam_id=%s", (exam_id,), fetchone=True)[0]
            master_answers_dict = json.loads(existing_answers_raw) if existing_answers_raw else {}
            
            student_profile_name = st.session_state.current_candidate_user
            master_answers_dict[student_profile_name] = {}
            for k, v in st.session_state.answers.items():
                master_answers_dict[student_profile_name][str(k)] = v
                
            execute_query("UPDATE exams SET student_answers=%s WHERE exam_id=%s", (json.dumps(master_answers_dict), exam_id))
            
            final_calculated_score = 0.0
            for index, question in enumerate(qs):
                student_choice = st.session_state.answers.get(index)
                correct_choice = question["correct"]
                if student_choice == correct_choice:
                    final_calculated_score += points_per_question
                elif student_choice is not None:
                    final_calculated_score -= 1.0
            
            execute_query("""
                INSERT INTO submissions (exam_id, username, final_score, submitted_at)
                VALUES (%s, %s, %s, %s)
            """, (exam_id, student_profile_name, final_calculated_score, time.time()))
            
            st.session_state.clear()
            st.query_params.clear()
            st.query_params["review"] = exam_id
            st.query_params["view"] = "submitted"
            st.rerun()

        if remaining == 0:
            process_and_submit_exam()

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
                label_visibility="collapsed"
            )

            if chosen_option != saved_choice:
                st.session_state.answers[i] = chosen_option
                st.rerun()
                
            st.write("---")

        if st.button("Finalize and Submit", type="primary"):
            process_and_submit_exam()
