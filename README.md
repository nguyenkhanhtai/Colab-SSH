# Colab SSH & Control Plane

> **"Turn Colab into your own GPU server"**
>
> Giải pháp toàn diện quản lý runtime Google Colab, kết nối VS Code Remote-SSH, đồng bộ môi trường AI (Codex, Antigravity), sao lưu tự động lên Google Drive và điều khiển qua Web Dashboard / Docker.

---

## 📌 Tính năng nổi bật

- ⚡ **VS Code Remote-SSH mượt mà**: Mỗi Colab session sở hữu SSH alias riêng (`colab-SESSION`), cấu hình độc lập, không ghi đè, hỗ trợ nhiều runtime song song.
- 🖥️ **Web Dashboard trực quan**: Giao diện điều khiển local (port `6767`) giúp tạo runtime, theo dõi tiến trình provisioning theo thời gian thực, mở notebook và quản lý session chỉ với 1 click.
- 💾 **Backup & Restore qua Google Drive**: Sao lưu toàn bộ workspace với mã định danh ngẫu nhiên (`bk-xxxxxxxx`) lưu tại `MyDrive/Colab-Backups`, dễ dàng khôi phục code vào bất kỳ runtime mới nào.
- 🐳 **Đóng gói Docker & Docker Compose**: Thiết lập trọn vẹn môi trường (Python 3.12, Colab CLI, SSH keys) chỉ với một lệnh `docker compose up -d`.
- 🤖 **Môi trường AI & Development tự động**: Tự động cài đặt Codex CLI, Antigravity CLI, áp dụng profile VS Code và đồng bộ ngữ cảnh (agents, skills, context allowlist).
- 🔒 **Bảo mật cao cấp**: GitHub PAT được truyền bảo mật qua SSH stdin (không lộ trong command line/log), token được lưu phân quyền an toàn, hỗ trợ CSRF Origin check và lọc bỏ toàn bộ secrets khi đồng bộ hay backup.

---

## 🚀 Khởi động nhanh (Quickstart)

### Cách 1: Sử dụng Docker & Docker Compose (Khuyên dùng)

Không cần cài đặt Python, `uv` hay dependencies trên máy host:

```bash
# 1. Đăng nhập Google Colab CLI (chỉ cần làm lần đầu)
docker compose run --rm -it cli colab login

# 2. Khởi chạy Web Dashboard ở chế độ chạy ngầm
docker compose up -d

# 3. Mở trình duyệt truy cập: http://localhost:6767
```

Chạy các lệnh CLI qua Docker:
```bash
# Xem danh sách session
docker compose run --rm cli colab-ssh --list

# Tạo session mới
docker compose run --rm cli colab-ssh https://github.com/OWNER/REPO --gpu T4

# Backup session
docker compose run --rm cli colab-ssh --backup <tên-session>

# Khôi phục session từ backup key
docker compose run --rm cli colab-ssh --restore bk-xxxxxxxx
```

---

### Cách 2: Sử dụng `uv` trên máy local

Yêu cầu: Python 3.12+ và [uv](https://github.com/astral-sh/uv).

```bash
# Cài đặt tool toàn cục ở chế độ editable:
uv tool install -e .

# Đăng nhập Colab CLI (nếu chưa đăng nhập):
colab login

# Khởi chạy session cơ bản:
colab-ssh

# Khởi chạy với GitHub repo và GPU:
colab-ssh https://github.com/OWNER/REPO --gpu L4 --branch main
```

---

## 🖥️ Web Dashboard (Local Control Plane)

Khởi động server dashboard tại máy local:
```bash
colab-ssh --serve
# hoặc: colab-ssh-server --host 127.0.0.1 --port 6767
```
Mở trình duyệt tại **`http://localhost:6767`**.

### Điểm nổi bật trên Dashboard:
1. **Tạo runtime mới (+ New session)**:
   - Chọn loại GPU: `T4`, `L4`, `G4`, `A100`, `H100`.
   - Tùy chọn **Mount Google Drive**: Hỗ trợ flow xác thực OAuth trực tiếp.
   - Tùy chọn **Restore from backup**: Dán mã key (`bk-xxxxxxxx`) để phục hồi ngay workspace cũ.
   - Tùy chọn **Initialize from GitHub**: Hỗ trợ clone repo public hoặc nhập PAT (truyền an toàn qua stdin).
2. **Theo dõi tiến trình**: Progress bar cập nhật chi tiết từng giai đoạn: Khởi tạo VM $\rightarrow$ Cấu hình SSH/GPU $\rightarrow$ Cài đặt AI tools $\rightarrow$ Sync context $\rightarrow$ Mount Drive $\rightarrow$ Sẵn sàng.
3. **Thao tác 1-click**:
   - **Open notebook ↗**: Mở thẳng Colab notebook trên trình duyệt.
   - **Backup**: Sao lưu ngay workspace hiện tại lên Drive và trả về mã key để copy.
   - **Stop**: Dọn dẹp máy ảo và gỡ cấu hình SSH an toàn.

---

## 💾 Cơ chế Backup & Restore (Google Drive)

Toàn bộ code và file làm việc trên Colab có thể được sao lưu lên Google Drive để phòng ngừa trường hợp runtime bị ngắt kết nối:

```bash
# 1. Sao lưu workspace của một session đang chạy:
colab-ssh --backup <tên-session>
# Output: Backup Key: bk-a1b2c3d4, Path: MyDrive/Colab-Backups/bk-a1b2c3d4.tar.gz

# 2. Xem danh sách các bản backup đã lưu trên Drive:
colab-ssh --list-backups

# 3. Tạo một session mới và khôi phục nguyên vẹn code từ mã key:
colab-ssh --restore bk-a1b2c3d4 --gpu L4
```

### Chi tiết kỹ thuật:
- **Vị trí lưu trữ**: Thư mục `MyDrive/Colab-Backups` trên Google Drive cá nhân của bạn.
- **Dữ liệu lưu**: Gồm file nén `bk-xxxxxxxx.tar.gz` (workspace) và file `bk-xxxxxxxx.json` (metadata: thời gian tạo, git commit, kích thước).
- **An toàn bảo mật**: Tự động loại trừ các file bí mật (`.env`, `*.pat`, `auth.json`, token, SSH keys) khi tạo file nén; giải nén an toàn với cờ `--no-same-owner` để tránh xung đột quyền file.

---

## 💻 Hướng dẫn dòng lệnh (CLI Reference)

```text
usage: colab-ssh [-h] [--gpu {T4,L4,G4,A100,H100}] [--session SESSION]
                 [--branch BRANCH] [--drive-dir DRIVE_DIR] [--skip-drive]
                 [--pat | --pat-file PAT_FILE | --auth-file AUTH_FILE]
                 [--skip-environment]
                 [--list | --stop SESSION | --serve | --backup SESSION | --list-backups]
                 [--restore KEY] [repo]
```

### Các tùy chọn chính:

| Tham số | Ý nghĩa |
| :--- | :--- |
| `repo` | URL GitHub HTTPS repository (tùy chọn) |
| `--gpu` | Loại accelerator: `T4` (mặc định), `L4`, `G4`, `A100`, `H100` |
| `--session NAME` | Đặt tên cụ thể cho session mới (mặc định tự sinh) |
| `--branch BRANCH` | Nhánh hoặc tag git cần clone |
| `--drive-dir DIR` | Thư mục mount Drive bên trong workspace (mặc định: `drive`) |
| `--skip-drive` | Bỏ qua bước mount Google Drive |
| `--pat` | Nhập GitHub PAT ẩn trên terminal |
| `--pat-file FILE` | Đọc GitHub PAT từ file local |
| `--auth-file FILE` | File cấu hình mapping PAT cho từng repository |
| `--skip-environment` | Bỏ qua cài đặt Codex/Antigravity CLI và đồng bộ context |
| `--list` | Xem danh sách các session đang hoạt động |
| `--stop SESSION` | Dừng runtime và dọn dẹp cấu hình SSH |
| `--serve` | Khởi chạy Web Dashboard local |
| `--backup SESSION` | Sao lưu workspace của session lên Google Drive |
| `--list-backups` | Xem danh sách các bản backup trên Drive |
| `--restore KEY` | Khôi phục code từ backup key trong session mới |

---

## 🔌 Kết nối VS Code Remote-SSH

Khi một session được tạo thành công:
1. Tool tự sinh cấu hình SSH tại `~/.config/colab-ssh/ssh/<session>.conf` và đăng ký vào `~/.ssh/config`.
2. Mở **VS Code**, nhấn `F1` (hoặc `Ctrl+Shift+P` / `Cmd+Shift+P`).
3. Chọn **Remote-SSH: Connect to Host...** $\rightarrow$ chọn `colab-<session>`.
4. Mở thư mục làm việc: `/content/<repo>` (nếu clone repo) hoặc `/content`.
5. Điểm mount Drive sẽ nằm tại `/content/<repo>/drive/MyDrive` hoặc `/content/drive/MyDrive`.

---

## 🔒 Quản lý GitHub PAT & Bảo mật

- **Public Repository**: Không cần cấu hình thêm, clone trực tiếp.
- **Private Repository**:
  ```bash
  # Nhập trực tiếp qua terminal (ký tự được ẩn an toàn):
  colab-ssh https://github.com/OWNER/PRIVATE_REPO --pat
  ```
  Sau khi clone thành công, PAT sẽ được tự động lưu vào `~/.config/colab-ssh/auth.json` cho các lần sử dụng sau.
- **Mapping file `auth.json`**:
  ```json
  {
    "github_repositories": {
      "https://github.com/OWNER/PROJECT_A": "project-a.pat",
      "https://github.com/OWNER/PROJECT_B": "project-b.pat"
    }
  }
  ```
- **Bảo mật**: PAT không bao giờ xuất hiện trong log, command line arguments hay URL. Quá trình clone sử dụng script `GIT_ASKPASS` tạm thời và tự hủy ngay sau khi hoàn tất.

---

## 🤖 Môi trường AI & Đồng bộ Context

Mỗi session mới sẽ tự động:
1. Cài đặt phiên bản chính thức của **Codex CLI** và **Antigravity CLI**.
2. Đăng ký extensions VS Code cần thiết (`remote.SSH.defaultExtensions`).
3. Tối ưu cấu hình GPU loader (`/usr/lib64-nvidia`) để PyTorch, CUDA và Python nhận diện chính xác card đồ họa.
4. Đồng bộ context lập trình của bạn từ máy local sang remote:
   - Allowlist an toàn: `~/.codex/AGENTS.md`, Codex user skills, `~/.gemini/GEMINI.md`, Antigravity skills và lịch sử hội thoại.
   - Loại trừ tuyệt đối: Tokens, SSH keys, credentials, file `.env`, memories, cache và logs.

---

## 🧪 Kiểm thử (Testing)

Dự án đi kèm bộ unit tests toàn diện (61 tests) kiểm tra toàn bộ luồng provisioning, SSH proxy, GPU setup, CSRF origin check, backup/restore logic:

```bash
# Chạy kiểm thử trên máy local:
python3 -m unittest discover -s tests -v

# Hoặc chạy kiểm thử bên trong Docker container:
docker run --rm colab-ssh:latest python3 -m unittest discover -s tests -v
```
