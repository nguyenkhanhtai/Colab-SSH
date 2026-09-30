# Colab Session

Một script độc lập: tạo session Colab → tùy chọn clone GitHub → mount Google Drive.
Chạy từ máy local, trong thư mục project, với `uv` và Python 3.12 trở lên:

```bash
uv tool install -e .
colab-ssh
colab-ssh https://github.com/OWNER/REPO
colab-ssh https://github.com/OWNER/REPO --gpu L4 --branch main --drive-dir data
```

## Quản lý nhiều session và dashboard

Mỗi runtime có SSH alias riêng (`colab-SESSION`) nên nhiều Colab session có thể
chạy song song mà không ghi đè cấu hình của nhau. Liệt kê hoặc dừng một runtime
trực tiếp từ tool:

```bash
colab-ssh --list
colab-ssh --stop SESSION
```

Lệnh stop gọi Colab CLI rồi thu hồi file SSH config và known-host riêng của
session, kể cả khi Colab CLI báo lỗi. Để chạy control-plane local:

```bash
colab-ssh --serve
# hoặc: colab-ssh-server --host 127.0.0.1 --port 6767
```

Mở `http://127.0.0.1:6767` để tạo, theo dõi, mở notebook và dừng nhiều session.
Form chính chỉ chọn compute session. Khi tạo, dashboard hỏi riêng có cần khởi tạo
workspace từ GitHub hay không; nếu có mới hiện repository, branch và credentials.
Có thể dùng PAT mapping đã lưu hoặc nhập PAT mới. PAT mới chỉ đi qua stdin của
process tạo session, không xuất hiện trong command line, log hay API response, và
được lưu vào mapping tương ứng sau khi clone thành công.
Dashboard refresh mỗi 15 giây; server reconcile state mỗi 30 giây và tự xóa SSH
state của runtime không còn trong `~/.config/colab-cli/sessions.json`. Log của
các tác vụ tạo session nền nằm trong `~/.config/colab-ssh/logs/`.
Server mặc định chỉ nghe localhost vì API có quyền tạo và dừng runtime; không
bind ra mạng công cộng nếu chưa đặt reverse proxy có authentication.

Dependencies được khai báo trong `pyproject.toml` và khóa phiên bản trong `uv.lock`.
`uv tool install -e .` cài `google-colab-cli` và `jupyter-kernel-client` vào `.venv` của project.
Kết nối SSH cần OpenSSH trên máy local; VS Code cần extension Remote-SSH nếu sử dụng.
Đăng nhập Google theo hướng dẫn
của CLI; bước mount Drive có thể yêu cầu xác nhận trong trình duyệt.
Tool dùng [Google Colab CLI](https://github.com/googlecolab/google-colab-cli);
cần tài khoản Colab đủ điều kiện sử dụng CLI và runtime đã chọn.

## Môi trường lập trình tự động

Mỗi session mới tự cài Codex CLI và Antigravity CLI bằng installer chính thức,
áp dụng settings editor/file phù hợp với remote và đăng ký extensions tự cài khi
VS Code kết nối. Profile lấy từ VS Code local lần đầu và lưu tại
`~/.config/colab-ssh/environment.json` (không đưa vào Git). Theme và phím tắt tiếp tục dùng
trực tiếp từ VS Code local. Profile không chứa token hay lịch sử đăng nhập.

Tool cũng đồng bộ context chủ động qua SSH: `~/.codex/AGENTS.md`, Codex user
skills, `~/.gemini/GEMINI.md` và Antigravity CLI user skills. Danh sách này là
allowlist và bao gồm lịch sử hội thoại trong Codex `sessions`/`archived_sessions`
cùng Antigravity CLI/IDE `conversations`. Tool không copy `auth.json`, `*.pat`,
`.env`, MCP OAuth tokens, Codex rules/config/system skills, memories, brain,
knowledge, logs hoặc cache. Nội dung người dùng từng dán trực tiếp vào hội thoại
không thể tự động phân biệt với context thông thường và cũng sẽ được đồng bộ.
Codex và Antigravity vẫn phải đăng nhập riêng trên Colab.
`--skip-environment` bỏ qua cả cài CLI, profile VS Code và đồng bộ context.

Installer: [Codex](https://developers.openai.com/codex/cli/) và
[Antigravity](https://antigravity.google/docs/cli/install/).
Các binary đã có sẵn sẽ được dùng lại. Phiên bản CLI được in khi setup.
Extensions dùng `remote.SSH.defaultExtensions`; chúng được cài khi kết nối lần đầu
hoặc ngay lúc setup nếu VS Code Server đã có trên VM. Danh sách áp dụng cho các
host Remote-SSH của VS Code. Settings local được sao lưu tại
`~/.config/Code/User/settings.colab-session.backup.jsonc` trước khi cập nhật.

Làm mới profile từ máy local hoặc áp dụng lên session đã có:

```bash
uv run setup_environment.py --capture --register
uv run setup_environment.py --session SESSION
```

Sau khi kết nối, đăng nhập lần đầu bằng `codex login --device-auth` và `agy`.
Để tạo session chỉ clone/mount Drive, thêm `--skip-environment`.
Tool hiện lấy settings từ VS Code Stable mặc định trên Linux; có thể chỉnh
`~/.config/colab-ssh/environment.json` để chọn tools, extensions và remote settings.

Nếu truyền GitHub URL, code nằm tại `/content/REPO` và Drive nằm tại `/content/REPO/drive/MyDrive`.
Nếu không truyền URL, workspace là `/content` và Drive nằm tại `/content/drive/MyDrive`.
`--drive-dir` đổi tên điểm mount, không chọn thư mục con của Drive.
Nếu tên này đã tồn tại trong workspace, script dừng để tránh che hoặc ghi đè dữ liệu.
Khi dùng GitHub, điểm mount được loại khỏi Git bằng `.git/info/exclude` chỉ trên VM.

Mỗi lần chạy tạo session mới. `--session NAME` đặt tên cho session mới, không resume.
Script in lệnh SSH, lấy URL trình duyệt và dừng session. Nếu có SSH key `~/.ssh/id_ed25519`, tool tạo một file `.conf` riêng trong
`~/.config/colab-ssh/ssh/` và thêm wildcard `Include` vào `~/.ssh/config` để
VS Code thấy tất cả runtime. Trong VS Code chọn **Remote-SSH: Connect to Host…**
rồi chọn alias được tool in ra, sau đó mở `/content/REPO` hoặc `/content`.

Để thiết lập lại SSH cho session đã có, chạy:

```bash
uv run setup_ssh.py --session SESSION
```

Lệnh tự đăng ký host vào SSH config. Có thể chạy ngay sau khi VM được tạo,
kể cả khi bước mount Drive chưa hoàn tất. Với key khác, thêm
`--identity /path/to/private_key`. Mỗi session có alias, file config và host key riêng để tránh nhầm runtime.
`~/.config/colab-ssh/ssh/` của tool được loại khỏi Git. Thêm `--no-install` nếu
chỉ muốn tạo config riêng mà chưa đăng ký vào `~/.ssh/config`.

Tool kiểm tra GPU thực tế bằng `nvidia-smi` trước khi clone.
Tool cũng đăng ký `/usr/lib64-nvidia` với Linux loader và shell environment để
terminal SSH, VS Code và Python tìm được thư viện NVIDIA. Với VM đã có, sửa riêng bằng:

```bash
uv run setup_gpu.py --session SESSION --gpu T4
```

Proxy SSH kiểm tra
session còn trong local state và là GPU runtime trước khi kết nối; session đã dừng
hoặc là CPU sẽ báo lỗi. Điều này tránh hành vi Colab CLI tự tạo CPU runtime khi
kết nối SSH vào tên session đã bị xóa. Sau khi dừng VM, tạo session mới bằng tool
thay vì kết nối lại tên cũ. Chọn Python trên VM có PyTorch hỗ trợ CUDA để chạy GPU.

Repo public dùng ngay. Với repo private, thêm `--pat` để nhập GitHub Personal Access
Token trong terminal (ký tự được ẩn):

```bash
colab-ssh https://github.com/OWNER/PRIVATE_REPO --pat
```

Nếu biến môi trường `GH_TOKEN` đã có sẵn, tool tự dùng token đó; `--pat` ưu tiên
token nhập trực tiếp. Token rỗng khi nhập sẽ dừng trước khi tạo VM.
Dùng PAT có quyền đọc repo đích. Không đặt token vào URL hoặc đối số dòng lệnh.
Sau khi clone thành công bằng `--pat`, tool tự lưu token vào file riêng trong
`~/.config/colab-ssh/` và cập nhật mapping của repo trong `auth.json`. Lần chạy
sau với cùng repo sẽ tự dùng PAT đã lưu. Clone thất bại không lưu token;
`--pat-file` và `GH_TOKEN` không tự thay đổi mapping.

### Đọc PAT từ file

Lưu PAT trong `~/.config/colab-ssh/github.pat`, chỉ một token trên một dòng, rồi chạy:

```bash
colab-ssh https://github.com/OWNER/PRIVATE_REPO --pat-file ~/.config/colab-ssh/github.pat
```

Để tự chọn PAT tương ứng với từng project, tạo `~/.config/colab-ssh/auth.json` theo mẫu:

```json
{
  "github_repositories": {
    "https://github.com/OWNER/PROJECT_A": "project-a.pat",
    "https://github.com/OWNER/PROJECT_B": "project-b.pat"
  }
}
```

Có thể copy `auth.example.json` vào `~/.config/colab-ssh/auth.json`. Đường dẫn PAT tương đối
được tính từ thư mục chứa config; hỗ trợ đường dẫn tuyệt đối và `~`.
URL được so khớp không phân biệt chữ hoa/thường và chấp nhận cả dạng có `.git`.
Project không có trong mapping sẽ không đọc PAT của project khác.

Schema một project cũ vẫn được hỗ trợ:

```json
{
  "github_pat_file": "github.pat",
  "github_repository": "https://github.com/OWNER/REPO.git"
}
```

Với config mặc định, project không khớp mapping có thể dùng `GH_TOKEN`.
Khi dùng `--auth-file` rõ ràng mà project không khớp, tool báo lỗi trước khi tạo VM.

Sau đó chạy tool bình thường, không cần `--pat`. `--auth-file /path/auth.json`
chọn config khác. `--pat`, `--pat-file`, `--auth-file` chỉ dùng một tùy chọn mỗi lần.
Tùy chọn nhập/file chỉ định trực tiếp được ưu tiên; sau đó tới `~/.config/colab-ssh/auth.json`,
rồi `GH_TOKEN`. File thiếu, rỗng hoặc sai định dạng sẽ dừng trước khi tạo VM.

`~/.config/colab-ssh/`, `*.pat` và `auth.json` được loại khỏi Git. Giới hạn quyền đọc bằng
`chmod 600 ~/.config/colab-ssh/*.pat ~/.config/colab-ssh/auth.json`. Token được đọc ở local, truyền qua
stdin SSH và không in ra log. Chỉ GitHub PAT được cấu hình từ file này.

Clone bằng PAT cần OpenSSH và SSH key local đã được Colab CLI hỗ trợ (ví dụ
`~/.ssh/id_ed25519`; tạo bằng `ssh-keygen -t ed25519` nếu chưa có key).
Token được gửi qua stdin của SSH, dùng tạm cho Git qua `GIT_ASKPASS`, không ghi vào
URL remote, cấu hình Git hay lịch sử code của Colab CLI. Helper tạm được dọn sau
lần clone kể cả khi Git báo lỗi. Token chỉ dùng để clone; các lần pull/push sau
trong session cần xác thực riêng.

Dependencies và các lệnh chạy của repo đích do bạn chuẩn bị sau khi kết nối.
Code ở ổ tạm: commit/push để lưu thay đổi. Chỉ dữ liệu ghi vào Drive
mới tồn tại trên Drive sau khi dừng VM. Nếu setup lỗi, session được giữ lại để kiểm tra;
dùng lệnh `stop` được in ra khi không cần nữa.

Kiểm tra local (không tạo VM): `uv run python -m unittest discover -s tests -v`.
