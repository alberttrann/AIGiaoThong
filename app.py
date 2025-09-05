import streamlit as st
import os
import json
import re
from pathlib import Path
import sqlite3
import uuid
import time
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request
import pickle

from google import genai as google_genai_sdk
from google.genai import types as google_genai_types
from google.api_core.exceptions import PermissionDenied, InvalidArgument, NotFound, GoogleAPIError

# --- Configuration ---
DOC_DIR = Path("documents")
# Renamed list to reflect inclusion of .md files
GROUNDING_FILENAMES = ["tuyen_duong_sat_do_thi_hcm.md", "xe_dap_cong_cong_xe_dien_4_banh_va_xe_buyt_duong_song.md", "xe_buyt.md", "xe_buyt1.md", "benpha.md"]
GEMINI_API_KEY_FILE = Path("gemini_api_key.json")
DATABASE_PATH = Path("chat_sessions.db")
GOOGLE_OAUTH_CONFIG = Path("google_oauth_config.json")

GEMINI_MODEL_ID = "gemini-2.0-flash" 
GEMINI_CLIENT = None
UPLOADED_FILES_CACHE = {}

# --- OAuth Configuration ---
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'  # Only for development

CLIENT_CONFIG = None
try:
    CLIENT_CONFIG = {
        "web": {
            "client_id": st.secrets["oauth"]["client_id"],
            "client_secret": st.secrets["oauth"]["client_secret"],
            "auth_uri": st.secrets["oauth"]["auth_uri"],
            "token_uri": st.secrets["oauth"]["token_uri"],
            "redirect_uris": [st.secrets["oauth"]["redirect_uri"]]
        }
    }
except Exception:
    
    if GOOGLE_OAUTH_CONFIG.exists():
        CLIENT_CONFIG = json.loads(GOOGLE_OAUTH_CONFIG.read_text())


# --- Database Helper Functions ---

def init_db():
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    # Add user table with api_key column
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            email TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            picture TEXT,
            created_at INTEGER NOT NULL,
            gemini_api_key TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            last_updated_at INTEGER NOT NULL,
            pdfs_uploaded INTEGER DEFAULT 0, -- Keep name for backward compatibility or rename carefully
            user_email TEXT,
            FOREIGN KEY (user_email) REFERENCES users(email)
        ) ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY, session_id TEXT NOT NULL, role TEXT NOT NULL,
            content TEXT NOT NULL, timestamp INTEGER NOT NULL,
            gemini_grounding_metadata_json TEXT,
            FOREIGN KEY (session_id) REFERENCES sessions (id) ON DELETE CASCADE ) ''')
    cursor.execute('''CREATE INDEX IF NOT EXISTS idx_messages_session_id_timestamp ON messages (session_id, timestamp);''')
    conn.commit(); conn.close()

def create_new_session_db(session_name_prefix="Trò chuyện mới"):
    if not st.session_state.user_info:
        st.error("User not authenticated")
        return None, None

    user_email = st.session_state.user_info.get("email")
    if not user_email:
        st.error("User email not found")
        return None, None

    session_id = str(uuid.uuid4()); conn = sqlite3.connect(DATABASE_PATH); cursor = conn.cursor()
    count = 0; session_name = f"{session_name_prefix}"
    while True:
        cursor.execute("SELECT COUNT(*) FROM sessions WHERE name = ? AND user_email = ?",
                      (session_name, user_email))
        if cursor.fetchone()[0] == 0: break
        count += 1; session_name = f"{session_name_prefix} ({count})"
    current_time = int(time.time())
    cursor.execute("""
        INSERT INTO sessions (id, name, created_at, last_updated_at, pdfs_uploaded, user_email)
        VALUES (?, ?, ?, ?, ?, ?)""",
        (session_id, session_name, current_time, current_time, 0, user_email)) # pdfs_uploaded default to 0
    conn.commit(); conn.close(); return session_id, session_name

def get_sessions_db():
    if not st.session_state.user_info:
        return []

    user_email = st.session_state.user_info.get("email")
    if not user_email:
        return []

    conn = sqlite3.connect(DATABASE_PATH); cursor = conn.cursor()
    cursor.execute("""
        SELECT id, name, last_updated_at, pdfs_uploaded
        FROM sessions
        WHERE user_email = ?
        ORDER BY last_updated_at DESC""",
        (user_email,))
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

# Function to mark files as uploaded for a session
def mark_files_uploaded_for_session_db(session_id):
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
    if not st.session_state.user_info:
        return None

    user_email = st.session_state.user_info.get('email')
    if not user_email:
        return None

    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT gemini_api_key FROM users WHERE email = ?", (user_email,))
    result = cursor.fetchone()
    conn.close()

    if result and result[0]:
        return result[0]
    return None

def save_api_key(api_key_value):
    if not st.session_state.user_info:
        return False

    user_email = st.session_state.user_info.get('email')
    if not user_email:
        return False

    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET gemini_api_key = ? WHERE email = ?",
                  (api_key_value, user_email))
    conn.commit()
    conn.close()
    return True

@st.cache_resource
def get_gemini_client(api_key_value):
    try:
        client = google_genai_sdk.Client(api_key=api_key_value)
        # Test client connectivity and API key validity
        client.models.list()
        st.success("Gemini Client đã khởi tạo thành công!")
        return client
    except Exception as e:
        st.error(f"Lỗi khởi tạo Gemini Client: {e}. Kiểm tra API Key.")
        return None

# Updated function to use the general GROUNDING_FILENAMES
def upload_files_to_gemini(client, filenames_list, current_session_id):
    if current_session_id in UPLOADED_FILES_CACHE and UPLOADED_FILES_CACHE[current_session_id]:
        st.info(f"Sử dụng file đã upload cho session {current_session_id} từ cache.")
        return UPLOADED_FILES_CACHE[current_session_id]

    uploaded_file_objects = []
    st.write("Đang upload tài liệu lên Gemini để hỗ trợ trả lời...")
    for filename in filenames_list:
        file_path_obj = DOC_DIR / filename
        if file_path_obj.exists():
            try:
                # Determine MIME type based on file extension
                mime_type = "application/pdf" if filename.lower().endswith(".pdf") else "text/markdown" if filename.lower().endswith(".md") else "application/octet-stream" # Default
                with st.spinner(f"Uploading {filename}..."):
                    st.write(f"Đang upload: {file_path_obj.name} (Type: {mime_type})")
                    # Pass mime_type to the upload method
                    gemini_file_obj = client.files.upload(file=file_path_obj)
                    uploaded_file_objects.append(gemini_file_obj)
                    st.success(f"Đã upload: {filename} (ID: {gemini_file_obj.name})")
            except Exception as e:
                st.error(f"Lỗi upload file {filename}: {e}")
                # Attempt to give more specific error if available
                error_details = getattr(e, 'message', str(e))
                st.error(f"Chi tiết lỗi: {type(e).__name__} - {error_details}")
        else:
            st.error(f"Không tìm thấy file: {file_path_obj}")

    if uploaded_file_objects:
        UPLOADED_FILES_CACHE[current_session_id] = uploaded_file_objects
        mark_files_uploaded_for_session_db(current_session_id)
    else:
        st.warning("Không có tài liệu nào được upload thành công.")
    return uploaded_file_objects

# (generate_gemini_response_stream function 
def generate_gemini_response_stream(client, user_prompt_text, current_session_id, existing_chat_history):
    global UPLOADED_FILES_CACHE
    model_to_use = GEMINI_MODEL_ID

    system_instruction_string = """
Bạn là Trợ lý Giao Thông Công Cộng Thành phố Hồ Chí Minh.

**Nhiệm vụ chính:**
Cung cấp thông tin chi tiết, chính xác và hữu ích về các phương tiện giao thông công cộng (xe buýt, metro, phà, đò, xe đạp công cộng, xe điện 4 bánh, xe buýt đường sông) trong khu vực nội thành TP.HCM.

**Nguồn thông tin:**
1.  Các tài liệu được cung cấp (bao gồm lộ trình, giá vé, ưu/nhược điểm của một số bến/tuyến).
2.  Công cụ Google Search để tìm kiếm thông tin bổ sung, cập nhật hoặc thông tin không có trong tài liệu.

**Ràng buộc và Quy tắc ứng xử:**
*   **KHÔNG** tự tạo ra thông tin nếu không tìm thấy trong tài liệu hoặc kết quả tìm kiếm. Thay vào đó, hãy thông báo rằng bạn không tìm thấy thông tin cụ thể đó và đề nghị tìm kiếm bằng Google nếu phù hợp.
*   Đối với các câu hỏi yêu cầu thông tin **theo thời gian thực** (ví dụ: tình trạng kẹt xe, phà có đông không, chuyến cuối cùng hôm nay), **BẮT BUỘC** phải sử dụng Google Search. **TUYỆT ĐỐI KHÔNG** trả lời rằng bạn không có thông tin theo thời gian thực hoặc thông tin cập nhật. Hãy thực hiện tìm kiếm và cố gắng đưa ra thông tin mới nhất có thể từ kết quả tìm kiếm.
*   Nếu câu hỏi của người dùng không liên quan đến giao thông công cộng TP.HCM, hãy nhẹ nhàng nhắc lại vai trò của bạn và khuyến khích người dùng hỏi về các chủ đề liên quan đến giao thông công cộng TP.HCM.
*   Khi trả lời, hãy trình bày thông tin một cách rõ ràng, có cấu trúc (ví dụ: dùng gạch đầu dòng, số thứ tự).

**Hướng dẫn xử lý các loại câu hỏi đặc thù:**

1.  **Dạng câu hỏi tìm tuyến đường (từ điểm A đến điểm B):**
    *   **Bước 1:** Xác định rõ địa chỉ hoặc địa điểm cụ thể của điểm bắt đầu (A) và điểm kết thúc (B). Nếu cần, sử dụng Google Search để làm rõ địa chỉ.
    *   **Bước 2:** Dựa vào tài liệu và/hoặc Google Search để tìm kiếm các phương tiện giao thông công cộng (xe buýt, metro, kết hợp các loại hình...) có thể di chuyển giữa hai điểm này.
    *   **Bước 3:** Đề xuất nhiều lựa chọn di chuyển khác nhau nếu có thể, kết hợp linh hoạt các loại hình.
    *   **Bước 4:** Đối với mỗi lựa chọn, mô tả rõ ràng các chặng di chuyển (ví dụ: đi tuyến X từ trạm Y đến trạm Z, sau đó chuyển sang tuyến A...).
    *   **Bước 5:** Nêu bật các so sánh quan trọng giữa các lựa chọn, ví dụ:
        *   Ưu thế về giá (tiết kiệm chi phí).
        *   Ưu thế về thời gian di chuyển (nhanh chóng).
        *   Tác động đến môi trường (giảm phát thải khi dùng phương tiện công cộng).
        *   Mức độ an toàn.
        *   Sự tiện lợi (ví dụ: ít lần chuyển tuyến, gần điểm đến).
    *   **Bước 6:** Đưa ra lời khuyên hoặc lưu ý thêm cho người dùng (ví dụ: kiểm tra giờ hoạt động, mang theo vật dụng cần thiết...).

2.  **Dạng câu hỏi liên quan đến hoạt động và phương tiện công cộng (ví dụ: đi đạp xe qua phà/đò):**
    *   Xác định hoạt động và các địa điểm liên quan.
    *   Tương tự như tìm tuyến đường, tìm kiếm thông tin về các phương tiện công cộng phù hợp với hoạt động đó (ví dụ: bến phà/đò nào cho phép xe đạp đi qua).
    *   Cung cấp thông tin chi tiết về các lựa chọn (tuyến đường, giá vé, ưu/nhược điểm) dựa trên tài liệu hoặc kết quả tìm kiếm, giống như cách xử lý dạng câu hỏi tìm tuyến đường.

---

**Few-shot Examples:**

**User:**
Tôi muốn đi từ chợ Phú Lâm quận 6 đến Đại học FPT thì có thể kết hợp những loại hình nào để đi đến nơi

**Assistant:**
Chào bạn, từ Chợ Phú Lâm (Quận 6) đến Đại học FPT ở Khu Công nghệ cao, TP. Thủ Đức, bạn có thể tham khảo một số lựa chọn di chuyển kết hợp bằng phương tiện công cộng như sau:

**Lựa chọn 1: Kết hợp nhiều tuyến xe buýt**
*   Bạn có thể đi bộ ra khu vực đường Bà Hom gần Chợ Phú Lâm để bắt **tuyến xe buýt số 81** về Bến xe Chợ Lớn.
*   Tại Bến xe Chợ Lớn, bạn chuyển sang **tuyến xe buýt số 56** đi về hướng Quận 1.
*   Xuống xe 56 tại trạm trung chuyển trên đường Hàm Nghi (Quận 1), sau đó bắt **tuyến xe buýt D4** (tuyến sử dụng xe buýt điện).
*   Đi tuyến D4 đến trạm gần trường Đại học FPT (thuộc Khu Công nghệ cao) và đi bộ một đoạn ngắn đến trường.

**Lựa chọn 2: Kết hợp xe buýt và tuyến xe buýt khác gần điểm cuối**
*   Tương tự, đi **tuyến 81** từ gần Chợ Phú Lâm lên Bến xe Chợ Lớn.
*   Tại Bến xe Chợ Lớn, bắt **tuyến xe buýt số 150** đi về hướng Khu Công nghệ cao.
*   Xuống xe 150 tại trạm gần Khu Công nghệ cao, sau đó đi bộ sang phía đối diện đường để đón **tuyến xe buýt số 165**.
*   Đi xe 165 vào trạm Đại học Công nghệ, nằm đối diện với Đại học FPT, rồi đi bộ đến trường.

**Lựa chọn 3: Kết hợp xe máy/taxi và Metro, sau đó là xe buýt**
*   Di chuyển bằng xe máy hoặc taxi đến Ga Metro Bến Thành (Quận 1).
*   Đi **tuyến Metro Bến Thành - Suối Tiên** đến Ga Metro Khu Công nghệ cao.
*   Tại Ga Metro Khu Công nghệ cao, bạn chuyển sang đi **tuyến xe buýt số 165** vào trạm Đại học Công nghệ, đối diện trường Đại học FPT.

**So sánh các lựa chọn:**
*   **Chi phí:** Lựa chọn 1 và 2 (đi hoàn toàn bằng xe buýt) thường tiết kiệm chi phí nhất với giá vé xe buýt thông thường. Lựa chọn 3 sẽ tốn kém hơn do có chi phí đi xe máy/taxi ban đầu và vé Metro.
*   **Thời gian:** Lựa chọn 3 (kết hợp Metro) có khả năng tiết kiệm thời gian di chuyển đáng kể nhất, đặc biệt trong giờ cao điểm, vì Metro không bị ảnh hưởng bởi kẹt xe. Lựa chọn 1 và 2 có thể mất nhiều thời gian hơn do phụ thuộc vào tình hình giao thông và thời gian chờ/chuyển tuyến.
*   **Môi trường & An toàn:** Các lựa chọn 1 và 2 (ưu tiên xe buýt) góp phần giảm phát thải giao thông hơn so với việc sử dụng xe máy cá nhân hoặc taxi một chặng dài. Đi bằng phương tiện công cộng nhìn chung cũng đảm bảo an toàn hơn so với tự lái xe máy trên quãng đường xa và đông đúc.

Bạn có thể cân nhắc ưu tiên của mình (chi phí, thời gian, sự tiện lợi, đóng góp cho môi trường) để chọn lựa chọn phù hợp nhất cho chuyến đi của mình. Chúc bạn có chuyến đi thuận lợi!
"""

    system_parts_for_config = [google_genai_types.Part.from_text(text=system_instruction_string)]

    gemini_contents = []
    for msg in existing_chat_history:
        role = "user" if msg["role"] == "user" else "model"
        msg_content_str = str(msg.get("content", ""))
        gemini_contents.append(google_genai_types.Content(role=role, parts=[google_genai_types.Part.from_text(text=msg_content_str)]))

    current_user_parts = [google_genai_types.Part.from_text(text=user_prompt_text)]

    session_info = next((s for s in st.session_state.get("sessions_list", []) if s["id"] == current_session_id), None)
    # Check if files were already marked as uploaded for this session
    files_already_uploaded_for_session = False
    if session_info: files_already_uploaded_for_session = session_info.get("pdfs_uploaded", 0) == 1 # Note: "pdfs_uploaded" might be a misnomer now

    needs_file_upload_this_turn = not files_already_uploaded_for_session

    if needs_file_upload_this_turn:
        st.info("Tin nhắn đầu/tài liệu chưa up cho phiên này. Đính kèm tài liệu...")
        document_file_objects_for_this_turn = []
        # Check cache first before attempting upload
        if current_session_id not in UPLOADED_FILES_CACHE or not UPLOADED_FILES_CACHE[current_session_id]:
            # Use the general GROUNDING_FILENAMES list
            document_file_objects_for_this_turn = upload_files_to_gemini(client, GROUNDING_FILENAMES, current_session_id)
        else:
            document_file_objects_for_this_turn = UPLOADED_FILES_CACHE[current_session_id]; st.info("Dùng cache tài liệu cho Gemini.")

        if document_file_objects_for_this_turn:
            for file_obj in document_file_objects_for_this_turn:
                file_part = google_genai_types.Part(
                    file_data=google_genai_types.FileData(
                        mime_type=file_obj.mime_type, file_uri=file_obj.uri
                    ))
                current_user_parts.append(file_part)
            st.success(f"Đã chuẩn bị {len(document_file_objects_for_this_turn)} parts tài liệu để đính kèm.")
        else: st.warning("Không có tài liệu nào được chuẩn bị để đính kèm.")

    # If files were already uploaded, append them from cache (if available) to the current user prompt
    elif current_session_id in UPLOADED_FILES_CACHE and UPLOADED_FILES_CACHE[current_session_id]:
         st.info("Đính kèm lại các tài liệu đã upload vào prompt (từ cache).")
         document_file_objects_from_cache = UPLOADED_FILES_CACHE[current_session_id]
         for file_obj in document_file_objects_from_cache:
             file_part = google_genai_types.Part(
                 file_data=google_genai_types.FileData(
                     mime_type=file_obj.mime_type, file_uri=file_obj.uri
                 ))
             current_user_parts.append(file_part)
         if document_file_objects_from_cache : st.success(f"Đã chuẩn bị {len(document_file_objects_from_cache)} parts tài liệu từ cache.")


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
        for chunk in response_stream: # chunk is a GenerateContentResponse
            if hasattr(chunk, 'text') and chunk.text: # Check if chunk.text exists and is not empty
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

# (Authentication functions init_google_auth, get_user_info remain the same)
def init_google_auth():
    if not CLIENT_CONFIG:
        st.error("Google OAuth configuration not found. Please set up google_oauth_config.json")
        return None

    flow = Flow.from_client_config(
        CLIENT_CONFIG,
        scopes=['openid', 'https://www.googleapis.com/auth/userinfo.profile', 'https://www.googleapis.com/auth/userinfo.email'],
        redirect_uri="https://chatbotgtcchcm.streamlit.app/" # Replace with your actual redirect URI
    )
    return flow

def get_user_info(creds_dict=None):
    import google.auth.transport.requests
    import requests

    try:
        if creds_dict:
            credentials = Credentials(
                token=creds_dict.get('token'),
                refresh_token=creds_dict.get('refresh_token'),
                token_uri=creds_dict.get('token_uri'),
                client_id=creds_dict.get('client_id'),
                client_secret=creds_dict.get('client_secret'),
                scopes=creds_dict.get('scopes')
            )
        else:
            credentials = st.session_state.user_credentials

        if not credentials or not credentials.valid:
            if credentials and credentials.expired and credentials.refresh_token:
                request = google.auth.transport.requests.Request()
                credentials.refresh(request)
                # Update stored credentials if they were refreshed
                if hasattr(st.session_state, 'user_credentials'):
                    st.session_state.user_credentials = credentials

        userinfo_endpoint = "https://www.googleapis.com/oauth2/v3/userinfo"
        response = requests.get(
            userinfo_endpoint,
            headers={'Authorization': f'Bearer {credentials.token}'}
        )
        if response.ok:
            return response.json()
        else:
            st.error("Failed to get user info")
            return None
    except Exception as e:
        st.error(f"Error getting user info: {e}")
        return None
# --- Initialization and Authentication ---
def initialize_auth_and_session():
    # Initialize basic session state
    if "user_info" not in st.session_state: st.session_state.user_info = None
    if "user_credentials" not in st.session_state: st.session_state.user_credentials = None
    if "current_session_id" not in st.session_state: st.session_state.current_session_id = None
    if "chat_history" not in st.session_state: st.session_state.chat_history = []
    if "gemini_api_key" not in st.session_state: st.session_state.gemini_api_key = load_api_key()
    # State variable to control main content view: "chat" or "library"
    if "view" not in st.session_state: st.session_state.view = "chat"
    # State variable to store the selected document in the library
    if "selected_document" not in st.session_state: st.session_state.selected_document = None


    # Try to refresh existing credentials if present
    if st.session_state.user_credentials and not st.session_state.user_info:
        user_info = get_user_info(st.session_state.user_credentials)
        if user_info:
            st.session_state.user_info = user_info

    # Handle authentication if not logged in
    if not st.session_state.user_info:
        flow = init_google_auth()
        if flow:
            if "code" not in st.query_params:
                auth_url, _ = flow.authorization_url(prompt='consent')
                st.image("images/gdgoc.png")
                st.markdown(f"""
                    ### 👋 Chào Mừng Đến Với Trợ Lý Giao Thông Công Cộng Tp.HCM
                    Bạn có thể hỏi đáp về xe buýt, đường sắt & metro, bến phà & bến đò, xe đạp công cộng, xe điện 4 bánh và xe buýt đường sông

                    Vui lòng đăng nhập để tiếp tục.

                    [![Login with Google](https://img.shields.io/badge/Login_with_Google-4285F4?style=for-the-badge&logo=google&logoColor=white)]({auth_url})
                    """)

                st.subheader("Hướng dẫn thiết lập sau khi đăng nhập")

               
                st.image("images/api_key.png", caption="Giao diện nhập API Key (minh họa)")

                st.image("images/api_key1.png", caption="Giao diện tạo API Key trên Google AI Studio (minh họa)")

                st.markdown("""
                    _(Lưu ý: Các ảnh trên chỉ mang tính minh họa giao diện cần thao tác sau khi đăng nhập.)_

                    Sau khi đăng nhập thành công, bạn sẽ cần cung cấp Gemini API Key để sử dụng chatbot.
                    Vui lòng truy cập vào [https://aistudio.google.com/apikey](https://aistudio.google.com/apikey) để tạo cho mình một API key.
                    Nhấn nút "Create API key" để lấy một khoá API mới.
                    Nếu được yêu cầu tạo một dự án để chứa khoá API, hãy nhanh chóng tạo và đặt một tên bất kỳ cho dự án (ví dụ: "Chatbot Project"), sau đó bạn sẽ có ngay khoá API.

                    Sao chép khoá API vừa tạo và dán vào ô "Nhập Gemini API Key cho tài khoản của bạn" ở cột bên trái (sidebar) sau khi đăng nhập.
                    Nhấn "Lưu API Key", tạo một phiên trò chuyện mới, và bạn đã sẵn sàng sử dụng trợ lý giao thông!
                    """)
                st.stop()
            else:
                try:
                    code = st.query_params["code"]
                    flow.fetch_token(code=code)
                    credentials = flow.credentials
                    st.session_state.user_credentials = credentials

                    user_info = get_user_info()
                    if user_info:
                        st.session_state.user_info = user_info
                        # Store user in database
                        conn = sqlite3.connect(DATABASE_PATH)
                        cursor = conn.cursor()                        # Only update user info, preserve API key
                        cursor.execute("""
                            INSERT INTO users (email, name, picture, created_at, gemini_api_key)
                            VALUES (?, ?, ?, ?, NULL)
                            ON CONFLICT(email) DO UPDATE SET
                                name = excluded.name,
                                picture = excluded.picture,
                                created_at = excluded.created_at
                                -- Intentionally not updating gemini_api_key to preserve it
                        """, (user_info['email'], user_info['name'],
                             user_info.get('picture', ''), int(time.time())))
                        conn.commit()

                        # Load the API key for this user
                        cursor.execute("SELECT gemini_api_key FROM users WHERE email = ?", (user_info['email'],))
                        api_key_row = cursor.fetchone()
                        if api_key_row and api_key_row[0]:
                            st.session_state.gemini_api_key = api_key_row[0]

                        conn.close()
                        st.rerun()
                except Exception as e:
                    st.error(f"Error during authentication: {e}")
                    st.session_state.user_credentials = None
                    st.session_state.user_info = None
                    st.stop()

    # After authentication, load sessions
    if "sessions_list" not in st.session_state:
        st.session_state.sessions_list = get_sessions_db()

# Initialize database tables
init_db()

# --- Streamlit UI ---
st.set_page_config(page_title="Trợ lý Giao Thông Công Cộng HCM", layout="wide")
initialize_auth_and_session() # Initialize auth and session state, including 'view' and 'selected_document'

if st.session_state.gemini_api_key and GEMINI_CLIENT is None:
    GEMINI_CLIENT = get_gemini_client(st.session_state.gemini_api_key)


# --- Sidebar ---
with st.sidebar:
    if st.session_state.user_info:
        col1, col2 = st.columns([0.7, 0.3])
        with col1:
            st.write(f"👤 Xin chào, {st.session_state.user_info.get('name', 'User')}")
        with col2:
            if st.button("Đăng xuất", key="logout_button"):
                # Clear query parameters first
                st.query_params.clear()
                # Clear all session state
                for key in ['user_credentials', 'user_info', 'current_session_id', 'chat_history', 'sessions_list', 'gemini_api_key', 'view', 'selected_document']: # Clear 'view' and 'selected_document' state
                    if key in st.session_state:
                        del st.session_state[key]
                st.rerun()
        if st.session_state.user_info.get('picture'):
            st.image(st.session_state.user_info['picture'], width=50)
        st.divider()

    # --- "Thư Viện" button in sidebar ---
    if st.session_state.user_info:
        if st.button("📚 Thư Viện Tài Liệu", use_container_width=True, key="library_sidebar_button"):
             st.session_state.view = "library"
             st.session_state.selected_document = None # Reset selected document when entering library view
             st.rerun()
        st.divider()


    st.header("Phiên trò chuyện")
    # Only show session management if logged in and in chat view
    if st.session_state.user_info and st.session_state.view == "chat":
        if st.button("➕ Trò chuyện mới", use_container_width=True):
            new_id, _ = create_new_session_db(); st.session_state.current_session_id = new_id
            st.session_state.chat_history = [];
            if new_id in UPLOADED_FILES_CACHE: del UPLOADED_FILES_CACHE[new_id]
            st.session_state.sessions_list = get_sessions_db(); st.rerun()

        st.session_state.sessions_list = get_sessions_db() # Refresh list
        if not st.session_state.current_session_id and st.session_state.sessions_list:
            st.session_state.current_session_id = st.session_state.sessions_list[0]["id"]
            st.session_state.chat_history = load_messages_db(st.session_state.current_session_id)

        # Display session list only in chat view
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
    if st.session_state.user_info:
        if st.session_state.gemini_api_key:
            st.success(f"API Key được cấu hình cho tài khoản {st.session_state.user_info.get('email')}")
            if st.button("Thay đổi/Xóa API Key"):
                st.session_state.gemini_api_key = None
                save_api_key(None)
                GEMINI_CLIENT = None
                st.rerun()
        else:
            new_key = st.text_input("Nhập Gemini API Key cho tài khoản của bạn:",
                                  type="password", key="new_gem_key_input")
            if st.button("Lưu API Key", key="save_gem_key_btn"):
                if new_key:
                    client_test = get_gemini_client(new_key) # Test key
                    if client_test:
                        if save_api_key(new_key):
                            st.session_state.gemini_api_key = new_key
                            GEMINI_CLIENT = client_test
                            st.success(f"Đã lưu API Key cho tài khoản {st.session_state.user_info.get('email')}!")
                            st.rerun()
                else:
                    st.warning("Vui lòng nhập API Key.")

# --- Main Content Area ---
if st.session_state.view == "chat":
    # --- Chat Interface ---
    st.title("Trợ Lý Giao Thông Công Cộng TP.HCM")
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
    if user_prompt: 
        if not st.session_state.current_session_id:
             st.warning("Vui lòng chọn hoặc tạo phiên trò chuyện mới để bắt đầu.")
        elif not GEMINI_CLIENT:
             st.error("Client Gemini chưa sẵn sàng. Vui lòng cài đặt API Key ở cột bên trái.")
        else:
            # Proceed with chat
            st.session_state.chat_history.append({"role": "user", "content": user_prompt})
            save_message_db(st.session_state.current_session_id, "user", user_prompt)
            with st.chat_message("user"): st.markdown(user_prompt)
            with st.chat_message("assistant"):
                full_response, grounding_meta_dict = generate_gemini_response_stream(
                    GEMINI_CLIENT, user_prompt, st.session_state.current_session_id,
                    st.session_state.chat_history[:-1] # Pass history *before* this user's current message
                )
                assistant_msg_obj = {"role": "assistant", "content": full_response}
                if grounding_meta_dict: assistant_msg_obj["gemini_grounding_metadata"] = grounding_meta_dict
                st.session_state.chat_history.append(assistant_msg_obj)
                save_message_db(st.session_state.current_session_id, "assistant", full_response, grounding_metadata_obj=grounding_meta_dict)


elif st.session_state.view == "library":
    # --- Library Interface ---
    st.title("Thư Viện Tài Liệu Giao Thông Công Cộng")
    if st.button("⬅️ Quay lại Trò chuyện", key="back_to_chat_button_library"):
        st.session_state.view = "chat"
        st.session_state.selected_document = None # Clear selection when leaving library
        st.rerun()

    st.markdown("---")
    st.subheader("Chọn tài liệu để xem nội dung:")

    if not GROUNDING_FILENAMES:
        st.info("Không có tài liệu nào được cấu hình để hiển thị.")
    else:
        # Display buttons for each document, e.g., in 3 columns
        num_columns = 3
        cols = st.columns(num_columns)
        for i, filename in enumerate(GROUNDING_FILENAMES):
            with cols[i % num_columns]:
                if st.button(f"📄 {filename}", key=f"doc_btn_{filename.replace('.', '_')}", use_container_width=True): # Ensure unique key
                    st.session_state.selected_document = filename

    # Display content of the selected document
    if st.session_state.selected_document:
        st.markdown("---") 
        selected_filename = st.session_state.selected_document
        file_path_obj = DOC_DIR / selected_filename
        if file_path_obj.exists():
            try:
                content = file_path_obj.read_text(encoding='utf-8')
                st.subheader(f"Nội dung tài liệu: {selected_filename}")
                st.markdown(content) 
            except FileNotFoundError:
                st.error(f"Không tìm thấy file: {selected_filename}")
            except Exception as e:
                st.error(f"Lỗi khi đọc file {selected_filename}: {e}")
        else:
            st.warning(f"File không tồn tại trong thư mục 'documents': {selected_filename}")

