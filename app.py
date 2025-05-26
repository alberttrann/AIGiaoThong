import streamlit as st
import os
import json
import re
from pathlib import Path
import sqlite3 
import uuid 
import time 

from google import genai as google_genai_sdk 
from google.genai import types as google_genai_types
from google.api_core.exceptions import PermissionDenied, InvalidArgument, NotFound, GoogleAPIError

# --- Configuration ---
DOC_DIR = Path("documents") 
PDF_FILENAMES = ["tuyen_duong_sat_do_thi_hcm.pdf", "xe_dap_cong_cong_xe_dien_4_banh_va_xe_buyt_duong_song.pdf", "xe_buyt.pdf"]
GEMINI_API_KEY_FILE = Path("gemini_api_key.json")
DATABASE_PATH = Path("chat_sessions.db") 

GEMINI_MODEL_ID = "gemini-2.0-flash" 

GEMINI_CLIENT = None
UPLOADED_FILES_CACHE = {} 

# --- Database Helper Functions ---
def init_db():
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY, name TEXT NOT NULL,
            created_at INTEGER NOT NULL, last_updated_at INTEGER NOT NULL,
            pdfs_uploaded INTEGER DEFAULT 0 ) ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY, session_id TEXT NOT NULL, role TEXT NOT NULL,
            content TEXT NOT NULL, timestamp INTEGER NOT NULL,
            gemini_grounding_metadata_json TEXT, 
            FOREIGN KEY (session_id) REFERENCES sessions (id) ON DELETE CASCADE ) ''')
    cursor.execute('''CREATE INDEX IF NOT EXISTS idx_messages_session_id_timestamp ON messages (session_id, timestamp);''')
    conn.commit(); conn.close()

def create_new_session_db(session_name_prefix="Trò chuyện mới"):
    session_id = str(uuid.uuid4()); conn = sqlite3.connect(DATABASE_PATH); cursor = conn.cursor()
    count = 0; session_name = f"{session_name_prefix}"
    while True:
        cursor.execute("SELECT COUNT(*) FROM sessions WHERE name = ?", (session_name,))
        if cursor.fetchone()[0] == 0: break
        count += 1; session_name = f"{session_name_prefix} ({count})"
    current_time = int(time.time())
    cursor.execute("INSERT INTO sessions (id, name, created_at, last_updated_at, pdfs_uploaded) VALUES (?, ?, ?, ?, ?)",
                   (session_id, session_name, current_time, current_time, 0))
    conn.commit(); conn.close(); return session_id, session_name

def get_sessions_db():
    conn = sqlite3.connect(DATABASE_PATH); cursor = conn.cursor()
    cursor.execute("SELECT id, name, last_updated_at, pdfs_uploaded FROM sessions ORDER BY last_updated_at DESC")
    sessions = [{"id": r[0], "name": r[1], "last_updated_at": r[2], "pdfs_uploaded": r[3]} for r in cursor.fetchall()]
    conn.close(); return sessions

def load_messages_db(session_id):
    conn = sqlite3.connect(DATABASE_PATH); cursor = conn.cursor()
    cursor.execute("SELECT role, content, gemini_grounding_metadata_json FROM messages WHERE session_id = ? ORDER BY timestamp ASC", (session_id,))
    messages = []
    for row in cursor.fetchall():
        msg = {"role": row[0], "content": row[1]}
        if row[2]: # gemini_grounding_metadata_json
            try: msg["gemini_grounding_metadata"] = json.loads(row[2]) 
            except json.JSONDecodeError: msg["gemini_grounding_metadata_error"] = "Lỗi parse metadata"
        messages.append(msg)
    conn.close(); return messages

def save_message_db(session_id, role, content, grounding_metadata_obj=None):
    message_id = str(uuid.uuid4()); current_time = int(time.time())
    conn = sqlite3.connect(DATABASE_PATH); cursor = conn.cursor()
    grounding_metadata_json_str = None
    if grounding_metadata_obj:
        try: grounding_metadata_json_str = json.dumps(grounding_metadata_obj)
        except TypeError: st.warning("Không thể serialize grounding metadata.")
    cursor.execute("INSERT INTO messages (id, session_id, role, content, timestamp, gemini_grounding_metadata_json) VALUES (?, ?, ?, ?, ?, ?)",
                   (message_id, session_id, role, content, current_time, grounding_metadata_json_str))
    cursor.execute("UPDATE sessions SET last_updated_at = ? WHERE id = ?", (current_time, session_id))
    conn.commit(); conn.close()

def set_pdfs_uploaded_for_session_db(session_id):
    conn = sqlite3.connect(DATABASE_PATH); cursor = conn.cursor()
    cursor.execute("UPDATE sessions SET pdfs_uploaded = 1, last_updated_at = ? WHERE id = ?", (int(time.time()), session_id))
    conn.commit(); conn.close()

def rename_session_db(session_id, new_name):
    conn=sqlite3.connect(DATABASE_PATH);cursor=conn.cursor()
    try: cursor.execute("UPDATE sessions SET name = ?, last_updated_at = ? WHERE id = ?", (new_name, int(time.time()), session_id)); conn.commit(); return True
    except sqlite3.Error as e: st.error(f"Lỗi DB rename: {e}"); return False
    finally: conn.close()

def delete_session_db(session_id):
    conn=sqlite3.connect(DATABASE_PATH);cursor=conn.cursor()
    try: cursor.execute("DELETE FROM sessions WHERE id = ?", (session_id,)); conn.commit(); return True
    except sqlite3.Error as e: st.error(f"Lỗi DB delete: {e}"); return False
    finally: conn.close()

init_db()

def load_api_key():
    if GEMINI_API_KEY_FILE.exists():
        with open(GEMINI_API_KEY_FILE, 'r') as f: data = json.load(f); return data.get("GEMINI_API_KEY")
    return os.environ.get("GEMINI_API_KEY")

def save_api_key(api_key_value):
    with open(GEMINI_API_KEY_FILE, 'w') as f: json.dump({"GEMINI_API_KEY": api_key_value}, f)

@st.cache_resource
def get_gemini_client(api_key_value):
    try:
        client = google_genai_sdk.Client(api_key=api_key_value)
        client.models.list() 
        st.success("Gemini Client đã khởi tạo thành công!")
        return client
    except Exception as e:
        st.error(f"Lỗi khởi tạo Gemini Client: {e}. Kiểm tra API Key.")
        return None

def upload_files_to_gemini(client, pdf_filenames_list, current_session_id):
    if current_session_id in UPLOADED_FILES_CACHE and UPLOADED_FILES_CACHE[current_session_id]:
        st.info(f"Sử dụng file đã upload cho session {current_session_id} từ cache.")
        return UPLOADED_FILES_CACHE[current_session_id]

    uploaded_file_objects = []
    st.write("Đang upload tài liệu PDF lên Gemini...")
    for filename in pdf_filenames_list:
        file_path_obj = DOC_DIR / filename
        if file_path_obj.exists():
            try:
                with st.spinner(f"Uploading {filename}..."):
                    st.write(f"Đang upload: {file_path_obj.name}")
                    gemini_file_obj = client.files.upload(file=file_path_obj) 
                    uploaded_file_objects.append(gemini_file_obj)
                    st.success(f"Đã upload: {filename} (ID: {gemini_file_obj.name})")
            except Exception as e:
                st.error(f"Lỗi upload file {filename}: {e}")
                st.error(f"Chi tiết lỗi: {type(e).__name__} - {e}")
        else:
            st.error(f"Không tìm thấy file: {file_path_obj}")
    
    if uploaded_file_objects:
        UPLOADED_FILES_CACHE[current_session_id] = uploaded_file_objects
        set_pdfs_uploaded_for_session_db(current_session_id)
    else:
        st.warning("Không có file PDF nào được upload thành công.")
    return uploaded_file_objects

def generate_gemini_response_stream(client, user_prompt_text, current_session_id, existing_chat_history):
    global UPLOADED_FILES_CACHE
    model_to_use = GEMINI_MODEL_ID 
    
    system_instruction_string = """bạn là một trợ lý về giao thông công cộng khu vực nội thành thành phố hồ chí minh. Nhiệm vụ của bạn là trả lời các thông tin về giao thông công cộng một cách chi tiết, nếu thông tin liên quan cho câu hỏi không có thì hãy thực hiện google search, đừng tự tạo ra thông tin. Nếu câu hỏi lạc đề, hãy nhấn mạnh lại vai trò của bạn và dẫn dắt người dùng hỏi những câu hỏi liên quan"""
    
    system_parts_for_config = [google_genai_types.Part.from_text(text=system_instruction_string)]

    gemini_contents = []
    for msg in existing_chat_history:
        role = "user" if msg["role"] == "user" else "model"
        msg_content_str = str(msg.get("content", "")) 
        gemini_contents.append(google_genai_types.Content(role=role, parts=[google_genai_types.Part.from_text(text=msg_content_str)]))

    current_user_parts = [google_genai_types.Part.from_text(text=user_prompt_text)]

    session_info = next((s for s in st.session_state.get("sessions_list", []) if s["id"] == current_session_id), None)
    pdfs_already_uploaded_for_session = False
    if session_info: pdfs_already_uploaded_for_session = session_info.get("pdfs_uploaded", 0) == 1
    else:
        conn = sqlite3.connect(DATABASE_PATH); cursor = conn.cursor()
        cursor.execute("SELECT pdfs_uploaded FROM sessions WHERE id = ?", (current_session_id,))
        db_row = cursor.fetchone(); conn.close()
        if db_row: pdfs_already_uploaded_for_session = db_row[0] == 1
    
    needs_pdf_upload_this_turn = not pdfs_already_uploaded_for_session

    if needs_pdf_upload_this_turn:
        st.info("Tin nhắn đầu/file chưa up cho phiên này. Đính kèm PDFs...")
        pdf_file_objects_for_this_turn = [] 
        if current_session_id not in UPLOADED_FILES_CACHE or not UPLOADED_FILES_CACHE[current_session_id]:
            pdf_file_objects_for_this_turn = upload_files_to_gemini(client, PDF_FILENAMES, current_session_id)
        else:
            pdf_file_objects_for_this_turn = UPLOADED_FILES_CACHE[current_session_id]; st.info("Dùng PDF cache cho Gemini.")
        
        if pdf_file_objects_for_this_turn:
            for file_obj in pdf_file_objects_for_this_turn:
                file_part = google_genai_types.Part(
                    file_data=google_genai_types.FileData(
                        mime_type=file_obj.mime_type, file_uri=file_obj.uri
                    ))
                current_user_parts.append(file_part)
            st.success(f"Đã chuẩn bị {len(pdf_file_objects_for_this_turn)} PDF parts để đính kèm.")
        else: st.warning("Không PDF nào được chuẩn bị để đính kèm.")
            
    elif current_session_id in UPLOADED_FILES_CACHE and UPLOADED_FILES_CACHE[current_session_id]:
        st.info("Đính kèm lại các file PDF đã upload vào prompt (từ cache).")
        pdf_file_objects_from_cache = UPLOADED_FILES_CACHE[current_session_id]
        for file_obj in pdf_file_objects_from_cache:
            file_part = google_genai_types.Part(
                file_data=google_genai_types.FileData(
                    mime_type=file_obj.mime_type, file_uri=file_obj.uri
                ))
            current_user_parts.append(file_part)
        if pdf_file_objects_from_cache : st.success(f"Đã chuẩn bị {len(pdf_file_objects_from_cache)} PDF parts từ cache.")

    gemini_contents.append(google_genai_types.Content(role="user", parts=current_user_parts))
    tools_for_gemini = [google_genai_types.Tool(google_search=google_genai_types.GoogleSearch())]
    
    generation_config_for_stream = google_genai_types.GenerateContentConfig(
        tools=tools_for_gemini,
        response_mime_type="text/plain",
        system_instruction=system_parts_for_config 
    )
    
    full_response_text = ""; captured_grounding_metadata_dict = None; raw_tool_calls_from_stream = []
    try:
        st.info(f"Gọi Gemini API ({model_to_use}) với stream...")
        response_stream = client.models.generate_content_stream(
            model=model_to_use, contents=gemini_contents, config=generation_config_for_stream,
        )
        placeholder = st.empty()
        for chunk in response_stream: 
            if hasattr(chunk, 'text') and chunk.text: 
                full_response_text += chunk.text
                placeholder.markdown(full_response_text + "▌")
            
            # Correctly check for function calls
            if hasattr(chunk, 'candidates') and chunk.candidates:
                for candidate in chunk.candidates:
                    if hasattr(candidate, 'content') and candidate.content and \
                       hasattr(candidate.content, 'parts') and candidate.content.parts:
                        for part in candidate.content.parts:
                            if hasattr(part, 'function_call') and part.function_call:
                                fc = part.function_call
                                args_dict = {}
                                if hasattr(fc, 'args') and fc.args:
                                    try: args_dict = dict(fc.args)
                                    except TypeError: 
                                        args_dict = {"error": "Could not parse fc.args to dict"}
                                        st.warning(f"Không thể convert fc.args sang dict: {type(fc.args)}")
                                raw_tool_calls_from_stream.append({"name": fc.name, "args": args_dict})
                                st.caption(f"Gemini đề xuất dùng tool: {fc.name} với args: {args_dict}")
        placeholder.markdown(full_response_text)

        if any(tc['name'].lower() in ['googlesearch', 'google_search'] for tc in raw_tool_calls_from_stream):
            st.info("Google Search được Gemini sử dụng (chi tiết metadata đầy đủ cần non-streaming call).")
            search_queries = []
            for tc in raw_tool_calls_from_stream:
                if tc['name'].lower() in ['googlesearch', 'google_search'] and tc.get('args'):
                    query_arg = tc['args'].get('query', tc['args'].get('q', 'Không rõ query'))
                    search_queries.append(str(query_arg))
            captured_grounding_metadata_dict = {"search_performed": True, "queries_used_by_gemini": search_queries if search_queries else ["Không rõ query cụ thể."]}
        
        return full_response_text, captured_grounding_metadata_dict
    except GoogleAPIError as e:
        st.error(f"Lỗi API từ Gemini: {getattr(e, 'message', str(e))} (Code: {getattr(e, 'code', 'N/A')})")
        if hasattr(e, 'summary'): st.error(f"Tóm tắt lỗi: {getattr(e, 'summary', '')}")
        return f"[Lỗi Gemini API: {getattr(e, 'message', str(e))}]", None
    except Exception as e: 
        st.error(f"Lỗi không xác định khi gọi Gemini API: {e}")
        return f"[Lỗi Gemini: {e}]", None

# --- Streamlit UI ---
st.set_page_config(page_title="Chatbot GTCC HCM (Gemini)", layout="wide")
if "current_session_id" not in st.session_state: st.session_state.current_session_id = None
if "chat_history" not in st.session_state: st.session_state.chat_history = []
if "sessions_list" not in st.session_state: st.session_state.sessions_list = get_sessions_db()
if "gemini_api_key" not in st.session_state: st.session_state.gemini_api_key = load_api_key()

if st.session_state.gemini_api_key and GEMINI_CLIENT is None:
    GEMINI_CLIENT = get_gemini_client(st.session_state.gemini_api_key)

with st.sidebar:
    st.header("Phiên trò chuyện")
    if st.button("➕ Trò chuyện mới", use_container_width=True):
        new_id, _ = create_new_session_db(); st.session_state.current_session_id = new_id
        st.session_state.chat_history = []; 
        if new_id in UPLOADED_FILES_CACHE: del UPLOADED_FILES_CACHE[new_id] 
        st.session_state.sessions_list = get_sessions_db(); st.rerun()
    
    st.session_state.sessions_list = get_sessions_db() # Refresh list
    if not st.session_state.current_session_id and st.session_state.sessions_list:
        st.session_state.current_session_id = st.session_state.sessions_list[0]["id"]
        st.session_state.chat_history = load_messages_db(st.session_state.current_session_id)
    
    for session_item in st.session_state.sessions_list:
        cols = st.columns([0.7, 0.15, 0.15]); 
        is_curr = st.session_state.current_session_id == session_item['id']
        btn_label = f"{'➡️ ' if is_curr else ''}{session_item['name']}"
        if cols[0].button(btn_label, key=f"session_{session_item['id']}", use_container_width=True):
            if not is_curr: 
                st.session_state.current_session_id = session_item['id']; 
                st.session_state.chat_history = load_messages_db(session_item['id']); 
                st.rerun()
        if cols[1].button("✏️", key=f"rename_{session_item['id']}", help="Đổi tên"): 
            st.session_state.renaming_session_id = session_item['id']; st.rerun()
        if cols[2].button("🗑️", key=f"delete_{session_item['id']}", help="Xoá"):
            if delete_session_db(session_item['id']):
                if st.session_state.current_session_id == session_item['id']: 
                    st.session_state.current_session_id = None; st.session_state.chat_history = []
                if session_item['id'] in UPLOADED_FILES_CACHE: del UPLOADED_FILES_CACHE[session_item['id']]
                st.session_state.sessions_list = get_sessions_db(); st.rerun()
                
    if st.session_state.get('renaming_session_id'):
        with st.form(key="rename_form"):
            st.subheader("Đổi tên trò chuyện")
            current_name_for_rename = next((s['name'] for s in st.session_state.sessions_list if s['id'] == st.session_state.renaming_session_id), "")
            new_session_name = st.text_input("Tên mới:", value=current_name_for_rename)
            if st.form_submit_button("Lưu"):
                if new_session_name.strip():
                    if rename_session_db(st.session_state.renaming_session_id, new_session_name.strip()):
                        del st.session_state.renaming_session_id; 
                        st.session_state.sessions_list = get_sessions_db(); st.rerun()
                else: 
                    st.warning("Tên không được để trống.")
    st.divider()
    st.header("Cài đặt API Gemini")
    if st.session_state.gemini_api_key:
        st.success("Đã có Gemini API Key.")
        if st.button("Thay đổi/Xóa API Key"): 
            st.session_state.gemini_api_key = None; save_api_key(None); 
            GEMINI_CLIENT = None; st.rerun()
    else:
        new_key = st.text_input("Nhập Gemini API Key:", type="password", key="new_gem_key_input")
        if st.button("Lưu API Key", key="save_gem_key_btn"):
            if new_key: 
                client_test = get_gemini_client(new_key) # Test key
                if client_test: 
                    st.session_state.gemini_api_key = new_key; save_api_key(new_key); 
                    GEMINI_CLIENT = client_test; st.success("Đã lưu!"); st.rerun()
            else: 
                st.warning("Vui lòng nhập API Key.")

st.title("Chatbot GTCC TP.HCM (Gemini API)")
current_session_name = "Chưa chọn phiên"
if st.session_state.current_session_id:
    cs_info = next((s for s in st.session_state.sessions_list if s["id"] == st.session_state.current_session_id), None)
    if cs_info: current_session_name = cs_info["name"]
st.subheader(f"Phiên: {current_session_name}")

if st.session_state.current_session_id:
    for msg in st.session_state.chat_history:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg.get("gemini_grounding_metadata"):
                meta = msg["gemini_grounding_metadata"]
                with st.expander("Thông tin tìm kiếm Google (từ Gemini)", expanded=False):
                    if meta.get("search_performed"): st.caption("Gemini đã sử dụng Google Search.")
                    if meta.get("queries_used_by_gemini"): st.write("Truy vấn có thể đã dùng:", meta.get("queries_used_by_gemini"))
                    if not meta.get("queries_used_by_gemini") and meta.get("search_performed"): st.write("Không có chi tiết truy vấn từ stream.")
                    elif not meta.get("search_performed"): st.write("Không có tìm kiếm nào được thực hiện.")


user_prompt = st.chat_input("Câu hỏi về giao thông công cộng TP.HCM:")
if user_prompt and st.session_state.current_session_id:
    if not GEMINI_CLIENT: st.error("Client Gemini chưa sẵn sàng. Kiểm tra API Key.")
    else:
        st.session_state.chat_history.append({"role": "user", "content": user_prompt})
        save_message_db(st.session_state.current_session_id, "user", user_prompt)
        with st.chat_message("user"): st.markdown(user_prompt)
        with st.chat_message("assistant"):
            full_response, grounding_meta_dict = generate_gemini_response_stream(
                GEMINI_CLIENT, user_prompt, st.session_state.current_session_id,
                st.session_state.chat_history[:-1] 
            )
            assistant_msg_obj = {"role": "assistant", "content": full_response}
            if grounding_meta_dict: assistant_msg_obj["gemini_grounding_metadata"] = grounding_meta_dict
            st.session_state.chat_history.append(assistant_msg_obj)
            save_message_db(st.session_state.current_session_id, "assistant", full_response, grounding_metadata_obj=grounding_meta_dict)
elif user_prompt and not st.session_state.current_session_id:
    st.warning("Vui lòng chọn hoặc tạo phiên trò chuyện mới.")
