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

## Môi trường lập trình tự động

Mỗi session mới tự cài Codex CLI và Antigravity CLI bằng installer chính thức,
áp dụng settings editor/file phù hợp với remote và đăng ký extensions tự cài khi
VS Code kết nối. Profile lấy từ VS Code local lần đầu và lưu tại
`.local/environment.json` (không đưa vào Git). Theme và phím tắt tiếp tục dùng
trực tiếp từ VS Code local. Profile không chứa token hay lịch sử đăng nhập.

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
`.local/environment.json` để chọn tools, extensions và remote settings.

Code nằm tại `/content/REPO`; Drive nằm tại `/content/REPO/drive/MyDrive`.
`--drive-dir` đổi tên điểm mount, không chọn thư mục con của Drive.
Nếu tên này đã tồn tại trong repo, script dừng để tránh che hoặc ghi đè dữ liệu.
Điểm mount được loại khỏi Git bằng `.git/info/exclude` chỉ trên VM.

Mỗi lần chạy tạo session mới. `--session NAME` đặt tên cho session mới, không resume.
Script in lệnh SSH, lấy URL trình duyệt và dừng session. Nếu có SSH key
`~/.ssh/id_ed25519`, tool tự cập nhật host `colab-session` trong `.ssh/config` của tool
và thêm `Include` vào `~/.ssh/config` để VS Code thấy host ngay.
Trong VS Code chọn **Remote-SSH: Connect to Host…** → `colab-session`,
rồi mở `/content/REPO`.

Để thiết lập lại SSH cho session đã có, chạy:

```bash
uv run setup_ssh.py --session SESSION
```

Lệnh tự đăng ký host vào SSH config. Có thể chạy ngay sau khi VM được tạo,
kể cả khi bước mount Drive chưa hoàn tất. Với key khác, thêm
`--identity /path/to/private_key`. Host `colab-session` trỏ tới VM vừa setup, thay thế VM trước trong danh sách SSH.
Mỗi session có file host key riêng để tránh
nhầm với VM trước. `.ssh/` của tool được loại khỏi Git. Thêm `--no-install` nếu
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
uv run start_colab.py https://github.com/OWNER/PRIVATE_REPO --pat
```

Nếu biến môi trường `GH_TOKEN` đã có sẵn, tool tự dùng token đó; `--pat` ưu tiên
token nhập trực tiếp. Token rỗng khi nhập sẽ dừng trước khi tạo VM.
Dùng PAT có quyền đọc repo đích. Không đặt token vào URL hoặc đối số dòng lệnh.

### Đọc PAT từ file

Lưu PAT trong `.local/github.pat`, chỉ một token trên một dòng, rồi chạy:

```bash
uv run start_colab.py https://github.com/OWNER/PRIVATE_REPO --pat-file .local/github.pat
```

Để tự đọc file mỗi lần chạy, tạo `.local/auth.json` theo mẫu:

```json
{
  "github_pat_file": "github.pat"
}
```

Có thể copy `auth.example.json` vào `.local/auth.json`. Đường dẫn PAT tương đối
được tính từ thư mục chứa config; hỗ trợ đường dẫn tuyệt đối và `~`.
Có thể giới hạn PAT cho một repo bằng trường `github_repository`:

```json
{
  "github_pat_file": "github.pat",
  "github_repository": "https://github.com/OWNER/REPO.git"
}
```

Config có trường này chỉ được tự dùng khi URL repo khớp. Repo khác không đọc
PAT từ config đó; vẫn có thể dùng credential riêng qua tùy chọn trực tiếp hoặc
`GH_TOKEN`. Khi dùng `--auth-file` với repo không khớp, tool báo lỗi trước khi tạo VM.

Sau đó chạy tool bình thường, không cần `--pat`. `--auth-file /path/auth.json`
chọn config khác. `--pat`, `--pat-file`, `--auth-file` chỉ dùng một tùy chọn mỗi lần.
Tùy chọn nhập/file chỉ định trực tiếp được ưu tiên; sau đó tới `.local/auth.json`,
rồi `GH_TOKEN`. File thiếu, rỗng hoặc sai định dạng sẽ dừng trước khi tạo VM.

`.local/`, `*.pat` và `auth.json` được loại khỏi Git. Giới hạn quyền đọc bằng
`chmod 600 .local/github.pat .local/auth.json`. Token được đọc ở local, truyền qua
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
