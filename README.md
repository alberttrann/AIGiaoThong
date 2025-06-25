# Chatbot Giao Thông Công Cộng TP.HCM (Hỗ trợ bởi Gemini 2.0 Flash thông qua API)

Chào mừng bạn đến với Chatbot Giao Thông Công Cộng TP.HCM! Đây là một trợ lý AI thông minh được thiết kế để cung cấp thông tin nhanh chóng và chính xác về hệ thống giao thông công cộng tại Thành phố Hồ Chí Minh, bao gồm:

1.  **Tuyến đường sắt đô thị (Metro)**
2.  **Xe đạp công cộng, xe điện 4 bánh và xe buýt đường sông**
3.  **Xe buýt truyền thống**
4.  **Bến phà, Bến Đò**
5.  **Các kênh phương tiện chính thức để người dân tham khảo về phương tiện công cộng**

Đây là sản phẩm công nghệ dự thi cuộc thi "Thiết kế sản phẩm tuyên truyền về An toàn giao thông" theo nội dung: "Ứng dụng chuyển đổi số và tăng cường trí tuệ nhân tạo trong việc tuyên truyền về xây dựng văn hoá giao thông an toàn; tuyên truyền về sử dụng năng lượng xanh trong tham gia giao thông". 

Chatbot sử dụng sức mạnh của Google Gemini API để hiểu câu hỏi của bạn và cung cấp câu trả lời dựa trên nội dung từ các tài liệu chuyên đề về giao thông công cộng, cũng như khả năng tìm kiếm thông tin cập nhật trên Google khi cần thiết. Để trải nghiệm, vui lòng truy cập vào web Streamlit này: https://chatbotgtcchcm.streamlit.app/

Ứng dụng được triển khai qua Streamlit Cloud Community. Rate limit hiện tại của Gemini Flash 2.0 là 15 requests mỗi phút, 1 triệu token mỗi phút, và 1500 requests mỗi ngày, khá thoải mái để người dùng cá nhân hỏi đáp với riêng API key cá nhân được lấy từ https://aistudio.google.com/app/apikey

Thỉnh thoảng sẽ có thông báo lỗi 503 như thế này, nhưng đây là vấn đề từ phía server của Google và rất hiếm khi diễn ra nên chỉ cần đợi một lát quay lại mọi thứ sẽ bình thường:
![image](https://github.com/user-attachments/assets/a6a45e3e-c163-4409-83e7-8cabc636405c)


## Mục lục

*   [Tính năng nổi bật](#tính-năng-nổi-bật)
*   [Hướng dẫn sử dụng cho Người dùng](#hướng-dẫn-sử-dụng-cho-người-dùng)
    *   [Bắt đầu](#bắt-đầu)
    *   [Nhập API Key của Google Gemini (Quan trọng!)](#nhập-api-key-của-google-gemini-quan-trọng)
    *   [Tạo và Quản lý Phiên trò chuyện](#tạo-và-quản-lý-phiên-trò-chuyện)
    *   [Đặt câu hỏi cho Chatbot](#đặt-câu-hỏi-cho-chatbot)
    *   [Sử dụng Thông tin Tìm kiếm (Google Search)](#sử-dụng-thông-tin-tìm-kiếm-google-search)
*   [Dành cho Nhà phát triển (Chạy ứng dụng cục bộ)](#dành-cho-nhà-phát-triển-chạy-ứng-dụng-cục-bộ)
    *   [Yêu cầu](#yêu-cầu)
    *   [Cài đặt](#cài-đặt)
    *   [Thiết lập API Key](#thiết-lập-api-key)
    *   [Chạy ứng dụng](#chạy-ứng-dụng)
*   [Cấu trúc thư mục](#cấu-trúc-thư-mục)
*   [Đóng góp](#đóng-góp)
*   [Giấy phép](#giấy-phép)

## Tính năng nổi bật

*   **Tra cứu thông tin đa dạng:** Cung cấp thông tin về nhiều loại hình GTCC tại TP.HCM.
*   **Giao diện trò chuyện trực quan:** Dễ dàng đặt câu hỏi và nhận câu trả lời.
*   **Sử dụng Gemini API mạnh mẽ:** Hiểu ngôn ngữ tự nhiên (tiếng Việt) và có khả năng xử lý thông tin từ tài liệu PDF được cung cấp.
*   **Tích hợp Google Search:** Tự động tìm kiếm thông tin cập nhật hoặc thông tin không có sẵn trong tài liệu.
*   **Quản lý phiên trò chuyện:**
    *   Tạo nhiều phiên trò chuyện riêng biệt.
    *   Lưu trữ lịch sử hội thoại cho từng phiên.
    *   Đổi tên và xóa các phiên trò chuyện.
    *   Lịch sử được lưu trữ bền vững ngay cả khi bạn đóng trình duyệt hoặc khởi động lại ứng dụng.
*   **Đính kèm tài liệu tự động:** Tự động đính kèm các tài liệu nền tảng về GTCC TP.HCM cho Gemini xử lý ở đầu mỗi phiên trò chuyện mới. Đây là cách tiếp cận sử dụng CAG(Cached Augemented Generation) thay vì RAG (Retrieval Augmented Generation)
*   **Thông báo trạng thái:** Hiển thị các thông báo về quá trình xử lý, upload file, v.v.
*   **Google OAuth**: Chatbot có hỗ trợ đăng nhập để sử dụng với tài khoản Google

![image](https://github.com/user-attachments/assets/21b5459d-d5cd-474b-8e34-2e275d120405)


![image](https://github.com/user-attachments/assets/7c9c6760-72c9-45cd-b970-cfd67eef0171)

## Hướng dẫn sử dụng cho Người dùng

### Bắt đầu

Bạn có thể truy cập trực tiếp vào ứng dụng chatbot qua đường link được cung cấp (nếu đã triển khai) hoặc chạy ứng dụng theo hướng dẫn ở phần "Dành cho Nhà phát triển".

### Nhập API Key của Google Gemini (Quan trọng!)

Để chatbot có thể hoạt động và trả lời các câu hỏi của bạn, nó cần sử dụng dịch vụ của Google Gemini. Điều này yêu cầu bạn cung cấp một "API Key" (Khóa truy cập API) của riêng bạn.

**API Key là gì?**
Nó giống như một chiếc chìa khóa riêng mà Google cung cấp cho bạn để sử dụng các dịch vụ AI của họ. Chatbot này **không lưu trữ API Key của bạn trên máy chủ nào cả**, mà chỉ lưu trữ tạm thời trên trình duyệt của bạn hoặc trong một file cài đặt nếu bạn chạy cục bộ, để có thể giao tiếp với Google Gemini.

**Làm thế nào để có API Key?**
1.  Bạn cần có một tài khoản Google.
2.  Truy cập Google AI Studio tại [https://aistudio.google.com/](https://aistudio.google.com/).
3.  Đăng nhập bằng tài khoản Google của bạn.
4.  Nhấp vào nút "Get API key" (hoặc "Tạo Khóa API").
5.  Tạo một dự án mới (nếu chưa có) và sau đó tạo một API key mới.
6.  **Sao chép (Copy) API key này.** Nó sẽ là một chuỗi ký tự dài.

**Cách nhập API Key vào Chatbot:**
1.  Ở thanh bên trái (sidebar) của ứng dụng chatbot, bạn sẽ thấy mục **"Cài đặt API Gemini"**.
2.  Nếu bạn chưa nhập API Key, sẽ có một ô để bạn **"Nhập Gemini API Key"**.
3.  **Dán (Paste) API key** bạn đã sao chép từ Google AI Studio vào ô này.
4.  Nhấn nút **"Lưu API Key"**.
5.  Nếu API Key hợp lệ, bạn sẽ thấy thông báo "Đã có Gemini API Key." và chatbot đã sẵn sàng để sử dụng!

**Lưu ý quan trọng:**
*   **Bảo mật API Key:** Hãy giữ API Key của bạn cẩn thận, không chia sẻ công khai. Việc sử dụng API có thể phát sinh chi phí tùy theo chính sách của Google.
*   **Chỉ cần nhập một lần:** Sau khi lưu thành công, API Key sẽ được nhớ cho các lần sử dụng sau trên cùng trình duyệt/máy tính đó (thông qua file `gemini_api_key.json` được tạo trong thư mục của ứng dụng).

![image](https://github.com/user-attachments/assets/f5473cfa-e4f3-4891-afbd-6fbca10dad60)


### Tạo và Quản lý Phiên trò chuyện

Chatbot cho phép bạn có nhiều cuộc trò chuyện riêng biệt, giúp bạn dễ dàng theo dõi các chủ đề khác nhau.

*   **Bắt đầu trò chuyện mới:** Nhấn nút **"➕ Trò chuyện mới"** ở sidebar. Một phiên trò chuyện mới sẽ được tạo và tự động được chọn.
*   **Chọn phiên trò chuyện:** Danh sách các phiên trò chuyện đã có sẽ hiển thị ở sidebar. Nhấn vào tên một phiên để mở lại và tiếp tục cuộc trò chuyện đó. Phiên hiện tại sẽ có dấu "➡️" phía trước.
*   **Đổi tên phiên:** Nhấn vào biểu tượng **"✏️"** bên cạnh tên phiên bạn muốn đổi. Một ô nhập liệu sẽ xuất hiện để bạn nhập tên mới và nhấn "Lưu".
*   **Xóa phiên:** Nhấn vào biểu tượng **"🗑️"** bên cạnh tên phiên bạn muốn xóa. **Lưu ý:** Hành động này sẽ xóa toàn bộ lịch sử của phiên đó và không thể hoàn tác.

![image](https://github.com/user-attachments/assets/6427a970-a4df-40b6-8daa-af83feae1f61)


### Đặt câu hỏi cho Chatbot

1.  Đảm bảo bạn đã chọn hoặc tạo một phiên trò chuyện.
2.  Nhập câu hỏi của bạn vào ô **"Câu hỏi về giao thông công cộng TP.HCM:"** ở cuối trang.
3.  Nhấn Enter hoặc nút gửi hình mũi tên.
4.  Chatbot sẽ xử lý câu hỏi của bạn:
    *   Nếu đây là tin nhắn đầu tiên trong phiên, chatbot sẽ tự động upload 3 tài liệu PDF nền tảng về GTCC TP.HCM lên Gemini. Quá trình này có thể mất vài giây.
    *   Sau đó, Gemini sẽ phân tích câu hỏi và các tài liệu (nếu có) để đưa ra câu trả lời.
    *   Câu trả lời sẽ được hiển thị theo từng phần (streaming) trong khung chat.

**Gợi ý khi đặt câu hỏi:**
*   Hỏi cụ thể, rõ ràng.
*   Sử dụng tiếng Việt có dấu để chatbot hiểu chính xác hơn.
*   Ví dụ:
    *   "Từ quận 7 đi đến Đại học Bách Khoa bằng xe buýt số mấy?"
    *   "Giá vé tháng của tuyến Metro số 1 là bao nhiêu?"
    *   "Xe đạp công cộng TNGO có trạm nào gần công viên Lê Văn Tám không?"
    *   "Làm thế nào để đăng ký thẻ UniPass?"

Như trong những hình dưới đây là người dùng đã thành công thêm api key, tạo phiên trò chuyện mới và tương tác với mô hình trong phiên trò chuyện:
![image](https://github.com/user-attachments/assets/8267c015-4823-45c9-8e22-78956929b68d)

![image](https://github.com/user-attachments/assets/275ee54e-a8aa-4ca8-b84e-e3a4effd74a5)

![image](https://github.com/user-attachments/assets/18183ef5-f148-4c2e-be14-0c4571808c6a)


### Sử dụng Thông tin Tìm kiếm (Google Search)

Chatbot được cấu hình để tự động sử dụng Google Search (thông qua Gemini) nếu thông tin cần thiết không có trong các tài liệu được cung cấp hoặc khi câu hỏi mang tính chất cần thông tin cập nhật theo thời gian thực.

*   Bạn không cần làm gì đặc biệt để kích hoạt tính năng này.
*   Nếu Gemini sử dụng Google Search, bạn có thể thấy thông báo trong quá trình xử lý.
*   Sau khi có câu trả lời, nếu có thông tin từ Google Search, một mục **"Thông tin tìm kiếm Google (từ Gemini)"** có thể xuất hiện dưới câu trả lời của chatbot, cho bạn biết các truy vấn mà Gemini đã sử dụng.

Gemini sẽ tự động tra cứu Google đối với các câu hỏi yêu cầu thông tin mới từ phía người dùng:
![image](https://github.com/user-attachments/assets/35bca240-ccfc-4b3b-a3b1-4da427f15e67)

![image](https://github.com/user-attachments/assets/6e57a843-c335-492b-864d-45cee721b2ba)

![image](https://github.com/user-attachments/assets/263b1334-78d8-4a27-a7e4-5ec6622e77f3)


## Dành cho Nhà phát triển (Chạy ứng dụng cục bộ)

Nếu bạn muốn chạy ứng dụng này trên máy tính của mình:

### Yêu cầu

*   Python 3.8 trở lên.
*   `pip` (trình quản lý gói của Python).
*   Git (để clone repository).

### Cài đặt

1.  **Clone repository (Nếu bạn tải từ GitHub):**
    ```bash
    git clone https://github.com/alberttrann/AIGiaoThong
    cd AiGiaoThong
    ```

2.  **Tạo môi trường ảo (Khuyến khích):**
    ```bash
    python -m venv .venv
    source .venv/bin/activate  # Trên Linux/macOS
    # .venv\Scripts\activate    # Trên Windows
    ```

3.  **Cài đặt các thư viện cần thiết:**
    Đảm bảo bạn có file `requirements.txt` trong thư mục gốc của dự án với nội dung tối thiểu như sau:
    ```txt
    streamlit
    google-genai
    # Các thư viện khác nếu có
    ```
    Sau đó chạy lệnh:
    ```bash
    pip install -r requirements.txt
    ```

4.  **Chuẩn bị tài liệu PDF:**
   Sẵn ở trong folder của dự án đã có các tài liệu liên quan đến thông tin của các loại hình giao thông công cộng trong nội thành, được tạo ra từ tính năng Deep Research(Nghiên cứu sâu) với Gemini 2.5 Pro(Preview) và từ các tài liệu chính thức từ phía các ban quản lý các loại hình giao thông công cộng. Việc tự bổ sung các tài liệu tự tạo sẽ cần có thay đổi đối với logic của code script

### Thiết lập API Key

Bạn có hai cách để cung cấp Gemini API Key cho ứng dụng khi chạy cục bộ:

*   **Cách 1: Qua giao diện ứng dụng (Như hướng dẫn cho người dùng ở trên):** Chạy ứng dụng và nhập API key vào sidebar. Key sẽ được lưu vào file `gemini_api_key.json`.
*   **Cách 2: Biến môi trường (Ưu tiên nếu bạn không muốn tạo file):**
    Đặt biến môi trường `GEMINI_API_KEY` với giá trị API Key của bạn.
    ```bash
    # Linux/macOS
    export GEMINI_API_KEY="YOUR_API_KEY_HERE"
    # Windows (Command Prompt)
    set GEMINI_API_KEY="YOUR_API_KEY_HERE"
    # Windows (PowerShell)
    $env:GEMINI_API_KEY="YOUR_API_KEY_HERE"
    ```
    Ứng dụng sẽ tự động đọc biến môi trường này nếu không tìm thấy file `gemini_api_key.json`.

### Chạy ứng dụng

Sau khi cài đặt xong, chạy lệnh sau từ thư mục gốc của dự án:
```bash
streamlit run app.py

Hoặc để tránh các vấn đề tiềm ẩn với file watcher của Streamlit:
```bash
streamlit run app.py --server.fileWatcherType none
```
Mở trình duyệt và truy cập vào địa chỉ `http://localhost:8501`.

## Cấu trúc thư mục (Ví dụ)

```
your-chatbot-project/
├── app.py                     # File mã nguồn chính của ứng dụng Streamlit
├── documents/                 # Thư mục chứa các file PDF làm cơ sở kiến thức
│   ├── tuyen_duong_sat_do_thi_hcm.pdf
│   ├── xe_dap_cong_cong_xe_dien_4_banh_va_xe_buyt_duong_song.pdf
│   └── xe_buyt.pdf
├── chat_sessions.db           # File database SQLite lưu trữ lịch sử trò chuyện (tự động tạo khi dự án được khởi chạy)
├── requirements.txt           # File liệt kê các thư viện Python cần thiết
└── README.md                  # File hướng dẫn này
```

## Một số hình ảnh của dự án:

![Screenshot 2025-05-26 115814](https://github.com/user-attachments/assets/dd5f4a21-baaa-4ce9-a0a8-9a64ba59ac6b)


![Screenshot 2025-05-26 115828](https://github.com/user-attachments/assets/a7310335-db43-47de-84c3-c2f71619dd16)


![Screenshot 2025-05-26 115844](https://github.com/user-attachments/assets/48da8490-35ea-4ebf-b917-03170e2bd0a8)


![image](https://github.com/user-attachments/assets/81baaf92-095a-4e29-b9b0-a4e688ea4cb9)



