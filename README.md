# Colab Session

Một script độc lập: tạo session Colab → clone GitHub → mount Google Drive trong repo.
Chạy từ máy local, trong thư mục project, với `uv` và Python 3.12 trở lên:

```bash
uv sync
uv run start_colab.py https://github.com/OWNER/REPO
uv run start_colab.py https://github.com/OWNER/REPO --gpu L4 --branch main --drive-dir data
```

Dependencies được khai báo trong `pyproject.toml` và khóa phiên bản trong `uv.lock`.
`uv sync` cài `google-colab-cli` và `jupyter-kernel-client` vào `.venv` của project.
Kết nối SSH cần OpenSSH trên máy local; VS Code cần extension Remote-SSH nếu sử dụng.
Đăng nhập Google theo hướng dẫn
của CLI; bước mount Drive có thể yêu cầu xác nhận trong trình duyệt.
Tool dùng [Google Colab CLI](https://github.com/googlecolab/google-colab-cli);
cần tài khoản Colab đủ điều kiện sử dụng CLI và runtime đã chọn.

Code nằm tại `/content/REPO`; Drive nằm tại `/content/REPO/drive/MyDrive`.
`--drive-dir` đổi tên điểm mount, không chọn thư mục con của Drive.
Nếu tên này đã tồn tại trong repo, script dừng để tránh che hoặc ghi đè dữ liệu.
Điểm mount được loại khỏi Git bằng `.git/info/exclude` chỉ trên VM.

Mỗi lần chạy tạo session mới. `--session NAME` đặt tên cho session mới, không resume.
Script in lệnh SSH, lấy URL trình duyệt và dừng session. Để dùng VS Code Remote-SSH,
cấu hình host với `User root`, `HostName SESSION`, và
`ProxyCommand /absolute/path/to/colab ssh --proxy-mode -s SESSION`;
dùng đường dẫn CLI được in trong lệnh kết nối và SSH key của bạn.

Repo public dùng ngay. Repo private cần thông tin xác thực Git được chuẩn bị trên VM;
script hiện không chuyển token/SSH key từ local, không nhận token trong URL.
Dependencies và các lệnh chạy của repo đích do bạn chuẩn bị sau khi kết nối.
Code ở ổ tạm: commit/push để lưu thay đổi. Chỉ dữ liệu ghi vào Drive
mới tồn tại trên Drive sau khi dừng VM. Nếu setup lỗi, session được giữ lại để kiểm tra;
dùng lệnh `stop` được in ra khi không cần nữa.

Kiểm tra local (không tạo VM): `uv run python -m unittest discover -s tests -v`.
