# Colab SSH & Control Plane

> **"Turn Colab into your own GPU server"**
>
> Giải pháp toàn diện quản lý runtime Google Colab, kết nối VS Code Remote-SSH, đồng bộ môi trường AI (Codex, Antigravity), sao lưu tự động lên Google Drive và điều khiển qua Web Dashboard / Docker.

---

## 📌 Tính năng nổi bật

- ⚡ **VS Code Remote-SSH mượt mà**: Mỗi Colab session sở hữu SSH alias riêng (`colab-SESSION`), cấu hình độc lập, không ghi đè, hỗ trợ nhiều runtime song song.
- 🚀 **Remote Job Execution & Declarative Config**: Dễ dàng gửi script, thư mục code hoặc lệnh huấn luyện từ máy local lên Colab GPU server. Hỗ trợ file cấu hình `colab-job.json` tự động kiểm tra và tái sử dụng session GPU đang chạy hoặc tự động tạo mới khi chưa có.
- 🤖 **Model Context Protocol (MCP) Server**: Tích hợp sẵn MCP stdio server (`colab-mcp`) cho phép các AI Assistant (Claude, Cursor, Antigravity) tự động quản lý GPU runtime, dispatch job, theo dõi log và backup hoàn toàn tự động.
- 🖥️ **Web Dashboard trực quan**: Giao diện điều khiển local (port `6767`) giúp tạo runtime, theo dõi tiến trình provisioning theo thời gian thực, mở notebook, gửi job trực tiếp và quản lý session chỉ với 1 click.
- 💾 **Backup & Restore qua Google Drive**: Sao lưu toàn bộ workspace với mã định danh ngẫu nhiên (`bk-xxxxxxxx`) lưu tại `MyDrive/Colab-Backups`, dễ dàng khôi phục code vào bất kỳ runtime mới nào.
- 🐳 **Đóng gói Docker & Docker Compose**: Thiết lập trọn vẹn môi trường (Python 3.12, Colab CLI, SSH keys) chỉ với một lệnh `docker compose up -d`.
- 🤖 **Môi trường AI & Development tự động**: Tự động cài đặt Codex CLI, Antigravity CLI, áp dụng profile VS Code và đồng bộ ngữ cảnh (agents, skills, context allowlist).
- 🔒 **Bảo mật cao cấp**: GitHub PAT được truyền bảo mật qua SSH stdin (không lộ trong command line/log), token được lưu phân quyền an toàn, hỗ trợ CSRF Origin check và lọc bỏ toàn bộ secrets khi đồng bộ hay backup.
- 📐 **Kiến trúc Modular & SOLID**: Phân chia codebase thành các package theo từng tính năng chức năng (`auth`, `ssh`, `hardware`, `env`, `storage`, `session`, `jobs`, `server`, `cli`), dễ bảo trì và mở rộng.

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
3. **Thao tác quản lý & quan sát**:
   - **Files 📁**: Quan sát & duyệt cây thư mục từ xa trên máy Colab trực tiếp trên trình duyệt (giới hạn 10 mục/nhánh, điều hướng thư mục, hiển thị dung lượng file).
   - **Backup**: Sao lưu ngay workspace hiện tại lên Drive và trả về mã key để copy.
   - **Stop**: Dọn dẹp máy ảo và gỡ cấu hình SSH an toàn.
   *(Lưu ý: Web Dashboard chỉ phục vụ quan sát, quản lý file và vòng đời session. Việc thực thi job được chạy chuyên trách qua CLI hoặc AI Agent thông qua MCP tools).*

---

## ⚡ Gửi & Chạy Job từ xa (Remote Job Execution)

Bên cạnh việc dùng VS Code kết nối tương tác, bạn có thể gửi lệnh hoặc script trực tiếp từ máy tính cá nhân lên Colab GPU server để thực thi qua CLI hoặc AI MCP tools.

### 📋 Khai báo Minh bạch & Kiểm tra Tiên quyết (Execution Manifest & Pre-flight Checks)
Trước khi thực thi bất kỳ job nào, hệ thống tự động kiểm tra các điều kiện bắt buộc và in bảng khai báo chi tiết (**Execution Manifest**):
```text
╔════════════════════════════════════════════════════════════════════════════╗
║                     COLAB JOB EXECUTION MANIFEST                           ║
╚════════════════════════════════════════════════════════════════════════════╝
[Target & Session]
  • Session Name  : colab-20261028-202224-b12aac (GPU: T4)
  • Execution Mode: Background (Detached)
  • Remote CWD    : /content

[Execution Target]
  • Local Script  : train.py (Uploaded to /content/train.py)
  • Local Sync Dir: ./src -> /content
  • Command       : python3 train.py --epochs 20

[Outputs & Logging]
  • Terminal Log  : logs/colab-20261028-202224-b12aac/2026-10-29/job-1a2b.log
  • Pull Artifacts: checkpoints/model.pt, results.csv -> ./downloads

[Telemetry & Experiment Tracking]
  • Platform      : WANDB (Project: 'solar-filament', Run: 'exp-baseline')
  • Tracked Metrics: loss, accuracy
══════════════════════════════════════════════════════════════════════════════
```
Nếu thiếu mục tiêu thực thi (không có `command`, `--script`, hay `--config`) hoặc đường dẫn file/thư mục local không tồn tại, hệ thống sẽ báo lỗi cụ thể ngay lập tức mà không gửi request sai lên server.

### 1. Gửi lệnh chạy trực tiếp (Foreground Streaming):
```bash
# Chạy lệnh kiểm tra GPU hoặc script trực tiếp, stream output về máy bạn:
colab-ssh job run --session <tên-session> "nvidia-smi"
colab-ssh --run "python3 train.py --epochs 20" --session <tên-session>
```

### 2. Gửi job chạy ngầm (Detached Background Job):
Không lo mất việc nếu máy bạn ngắt mạng hay tắt máy:
```bash
# Gửi lệnh chạy ngầm:
colab-ssh job submit --session <tên-session> "python3 -u train.py --epochs 50"

# Gửi kèm script từ máy local lên server rồi chạy:
colab-ssh job submit --session <tên-session> --script ./train.py

# Đồng bộ cả thư mục code từ máy local lên server trước khi chạy:
colab-ssh job submit --session <tên-session> --sync-dir ./src "python3 -u src/main.py"
```
Lệnh sẽ trả về mã định danh job, ví dụ: `job-a1b2c3d4`.

### 3. Quản lý trạng thái và Log của Job:
```bash
# Xem danh sách tất cả các job trên session:
colab-ssh job list --session <tên-session>

# Xem trạng thái (running / completed / failed / stopped) và exit code:
colab-ssh job status job-a1b2c3d4 --session <tên-session>

# Xem log output thời gian thực:
colab-ssh job logs job-a1b2c3d4 --session <tên-session> --tail 100

# Dừng khẩn cấp một job đang chạy:
colab-ssh job stop job-a1b2c3d4 --session <tên-session>
```

### 4. Quản lý & Chạy Job bằng File cấu hình (`colab-job.json` / `colab-job.yaml`):

Thay vì phải gõ thủ công từng câu lệnh dài và cờ tham số, bạn có thể định nghĩa toàn bộ workflow huấn luyện vào một file cấu hình declarative (hỗ trợ cả **JSON** lẫn **YAML**).

Quy trình gửi job tự động giải quyết bài toán kiểm tra & tái sử dụng tài nguyên:
1. **Kiểm tra**: Quét xem có session nào đang chạy với GPU tương ứng (ví dụ: `T4`, `L4`, `A100`) hay chưa.
2. **Tái sử dụng hoặc Tạo mới**: Nếu có sẵn thì dùng luôn; nếu chưa có thì tự động tạo một server Colab mới với GPU tương ứng.
3. **Thực thi**: Đồng bộ code, chạy lệnh hoặc script, lưu log ngầm và trả về trạng thái.

#### Khởi tạo file mẫu cấu hình:
```bash
# Tạo file JSON mẫu:
colab-ssh job init-config
# Hoặc tạo file YAML mẫu:
colab-ssh job init-config my-train-job.yaml
```

Cấu trúc file `colab-job.json` (hoặc `colab-job.yaml`):
```json
{
  "name": "train-mnist",
  "gpu": "T4",
  "session": null,
  "auto_create": true,
  "command": "python3 -u train.py --epochs 10",
  "script": "train.py",
  "sync_dir": null,
  "cwd": "/content",
  "detached": true,
  "mount_drive": false,
  "download_files": [
    "checkpoints/model.pt",
    "results.csv"
  ],
  "download_dir": "./outputs",
  "log_file": "./logs/train.log"
}
```

#### Các cách thực thi qua file cấu hình từ CLI:

1. **Truyền trực tiếp tên file cấu hình (Tự động nhận diện)**:
   ```bash
   colab-ssh colab-job.json
   colab-ssh my-train-job.yaml
   ```

2. **Dùng cờ viết tắt `-c` hoặc `--config`**:
   ```bash
   # Tự động tìm colab-job.json hoặc colab-job.yaml trong thư mục hiện tại:
   colab-ssh -c

   # Hoặc chỉ định file cụ thể:
   colab-ssh -c custom-job.json
   ```

3. **Qua subcommand `job config` hoặc `job run-config`**:
   ```bash
   colab-ssh job config
   colab-ssh job config my-train-job.yaml
   ```

4. **Tích hợp với `job run` (chạy foreground) và `job submit` (chạy background)**:
   ```bash
   # Chạy foreground và stream log trực tiếp:
   colab-ssh job run -c colab-job.json

   # Gửi chạy ngầm trong background:
   colab-ssh job submit -c colab-job.json
   ```

5. **Ghi đè (override) linh hoạt các tham số cấu hình ngay trên CLI**:
   ```bash
   # Đổi GPU thành A100 và chạy ở chế độ foreground:
   colab-ssh -c colab-job.json --gpu A100 --foreground

   # Chỉ định session cụ thể và đổi đường dẫn log:
   colab-ssh -c colab-job.json -s my-custom-session --log-file ./new.log
   ```

---

### 5. Chỉ định rõ & Tải File/Kết quả về Máy Local (Download & Pull Artifacts)

Hệ thống cho phép bạn chỉ định rõ những file, thư mục hoặc glob pattern (`*.pt`, `results/*.png`, v.v.) cần tải từ server Colab về máy local:

#### Cách 1: Tự động tải qua file cấu hình `colab-job.json`
- Khi chạy job ở chế độ foreground (`detached: false`), các file khai báo trong `download_files` sẽ được **tự động tải về ngay sau khi job hoàn thành** vào thư mục `download_dir` (mặc định: `./outputs`).
- Khi chạy job ở chế độ background (`detached: true`), thông tin `download_files` được lưu theo metadata của job để kéo về bất kỳ lúc nào bằng lệnh `pull`:
  ```bash
  colab-ssh job pull <job_id> --session <tên-session>
  # Hoặc lưu sang thư mục khác:
  colab-ssh job pull <job_id> --session <tên-session> --dest ./my_results
  ```

#### Cách 2: Tải file bất kỳ theo danh sách chỉ định qua CLI
```bash
# Tải các file cụ thể từ session Colab về thư mục ./downloads:
colab-ssh job download model.pt results.csv "runs/*.png" --session <tên-session> --dest ./downloads

# Hoặc dùng shorthand trực tiếp ở lệnh root colab-ssh:
colab-ssh --session <tên-session> --download model.pt results.csv --dest ./downloads
```

#### Cách 3: Tải khi gửi lệnh trực tiếp
```bash
colab-ssh job run "python3 train.py" --session <tên-session> --download model.pt --download-dir ./outputs
```

---

### 6. Theo dõi Thí nghiệm ML (Weights & Biases Tracking Framework)

Hệ thống tích hợp sẵn framework ghi nhận dữ liệu huấn luyện, siêu tham số và chỉ số đánh giá lên nền tảng **Weights & Biases (W&B)**:

#### Khai báo trong file cấu hình (`colab-job.json` hoặc `colab-job.yaml`):
```json
{
  "name": "train-solar",
  "gpu": "T4",
  "command": "python3 train.py",
  "tracking": {
    "enabled": true,
    "provider": "wandb",
    "project": "solar-filament-detection",
    "run_name": "run-epoch20",
    "tags": ["colab", "resnet50"],
    "config": {
      "lr": 0.001,
      "batch_size": 32,
      "epochs": 20
    },
    "metrics": ["loss", "val_loss", "accuracy"]
  }
}
```
*Hệ thống tự động cài đặt `wandb` trên máy ảo Colab nếu chưa có và truyền toàn bộ biến môi trường cấu hình.*

#### Cách 3: Ghi nhận trong code Python của bạn
Trong code huấn luyện (`train.py`), bạn có thể dùng trực tiếp `wandb` chuẩn hoặc dùng helper chống crash offline:
```python
from colab_session.tracking import get_tracker

# Tự động đọc project, run_name và config từ job setup:
tracker = get_tracker()

for epoch in range(1, 21):
    # Huấn luyện...
    tracker.log({"epoch": epoch, "loss": train_loss, "val_loss": val_loss})

tracker.finish()
```

---

### 7. Lưu trữ Toàn bộ Terminal Output của Job (Log Files)

Tất cả output terminal (stdout và stderr) của các job đều được tự động lưu trữ theo cấu trúc thư mục quy chuẩn:
$$\text{logs} / \langle\text{tên-máy}\rangle / \langle\text{date}\rangle / \dots$$
Ví dụ: `logs/colab-gpu-1/2026-10-28/train.log` hoặc `logs/colab-gpu-1/2026-10-28/job_233000.log`.

- **Chế độ trực tiếp (Foreground)**: Vừa stream realtime ra terminal vừa tự động tee vào thư mục log của máy theo ngày:
  ```bash
  # Mặc định tự động ghi vào logs/<session>/<date>/job_<timestamp>.log:
  colab-ssh job run --session <tên-session> "python3 train.py"

  # Hoặc chỉ định tên file cụ thể (sẽ được đặt trong logs/<session>/<date>/train.log):
  colab-ssh job run --session <tên-session> --log-file train.log "python3 train.py"
  ```
- **Chế độ ngầm (Background / Detached)**: Output được lưu trên server tại `/root/.colab-jobs/<job_id>.log`. Khi gọi `colab-ssh job pull <job_id> --session <tên-session>`, file log sẽ được tự động tải về thư mục `logs/<session>/<date>/` cùng với các artifacts.
- **Khai báo trong file cấu hình**: Trường `"log_file": "train.log"` trong `colab-job.json` sẽ tự động được định tuyến vào thư mục ngày tương ứng của máy.

---

### 8. Quan sát Đường dẫn & Cây Thư mục Từ xa (Directory Tree Inspection)

Hệ thống cung cấp cơ chế trực quan hóa cây thư mục từ xa trên máy Colab qua SSH, **giới hạn hiển thị tối đa 10 mục trong mỗi nhánh cây thư mục** để giữ cho context gọn gàng và tránh quá tải:

#### 1. Trực tiếp trên Web Browser (Dashboard UI):
Khởi chạy dashboard bằng lệnh `colab-ssh --serve` rồi mở `http://localhost:6767`:
- Trên card của từng session đang chạy, bấm nút **Files 📁**.
- Giao diện cung cấp:
  - **Điều hướng thư mục linh hoạt**: Nhập đường dẫn bất kỳ (ví dụ `/content/drive` hoặc `/root`), nút **⬆ Up** để lên thư mục cha, hoặc bấm trực tiếp vào tên thư mục con để đi sâu vào bên trong.
  - **Giới hạn 10 mục/nhánh**: Hiển thị rõ `... (+X more items)` nếu nhánh có nhiều hơn 10 phần tử.
  - **Tùy chỉnh linh hoạt**: Điều chỉnh độ sâu cây (`Depth: 1, 2, 3`), bật/tắt file ẩn `Hidden`.
  - **Chế độ xem kép**: Chuyển đổi giữa chế độ tương tác (Interactive View) và dạng cây văn bản thuần túy (Raw ASCII), có nút 1-click để Copy Tree.

#### 2. Qua CLI:
```bash
# Xem cây thư mục mặc định tại /content (tối đa 10 mục/nhánh, độ sâu 2):
colab-ssh job tree --session <tên-session>
# Hoặc alias ls:
colab-ssh job ls --session <tên-session>

# Xem đường dẫn cụ thể với độ sâu tùy chọn:
colab-ssh job tree /content/checkpoints --session <tên-session> --depth 3

# Xem bằng shorthand trên root CLI:
colab-ssh --session <tên-session> --tree /content
```
*Kết quả hiển thị trực quan dạng cây kèm dung lượng file:*
```text
/content/
├── checkpoints/
│   ├── best_model.pt (42.5 MB)
│   ├── epoch_1.pt (42.5 MB)
│   └── ... (+18 more items)
├── data/
│   ├── train/
│   └── val/
├── train.py (5.2 KB)
└── requirements.txt (210 B)
```

---

## 🤖 Tích hợp AI qua MCP (Model Context Protocol)

Dự án tích hợp sẵn MCP stdio server tuân thủ chuẩn JSON-RPC 2.0, giúp AI Assistant (Claude Desktop, Cursor, Antigravity/Gemini) trực tiếp điều khiển Colab runtime và thực thi jobs.

### Cấu hình MCP Client

Thêm cấu hình sau vào file thiết lập MCP của bạn (ví dụ: `claude_desktop_config.json` hoặc Cursor MCP settings):

```json
{
  "mcpServers": {
    "colab-ssh": {
      "command": "uv",
      "args": ["run", "--directory", "/đường/dẫn/Colab-SSH", "colab-mcp"]
    }
  }
}
```

*(Hoặc nếu đã cài đặt toàn cục: `"command": "colab-mcp"`)*.

### Các MCP Tools có sẵn:

| Tool MCP | Chức năng |
| :--- | :--- |
| `colab_list_sessions` | Liệt kê tất cả các Colab session đang hoạt động cùng trạng thái và SSH command. |
| `colab_resolve_session` | Tự động tìm session có GPU tương ứng đang chạy hoặc tự động tạo mới runtime nếu chưa có. |
| `colab_tree_directory` | Khám phá cây thư mục và quan sát đường dẫn trên máy Colab qua SSH (tối đa 10 mục/nhánh). |
| `colab_run_job` | Gửi và chạy job (foreground hoặc background detached) trên runtime đã chọn. |
| `colab_run_from_config` | Đọc file cấu hình (`colab-job.json`), tự động resolve session GPU và chạy job trọn gói. |
| `colab_get_job_status` | Lấy trạng thái, exit code, thời gian bắt đầu/kết thúc của job. |
| `colab_get_job_logs` | Xem stdout/stderr logs thời gian thực của job với tùy chọn tail dòng. |
| `colab_stop_job` | Dừng tiến trình job đang chạy trên server Colab. |
| `colab_backup_session` | Sao lưu toàn bộ workspace lên Google Drive và nhận lại backup key. |
| `colab_stop_session` | Tắt VM Colab và dọn dẹp cấu hình SSH. |
| `colab_download_files` | Tải các file, folder hoặc pattern chỉ định từ session Colab về máy local. |
| `colab_pull_job_artifacts` | Tự động kéo các file kết quả (artifacts) được cấu hình trong `download_files` của job về máy. |

---

## 🏗️ Cấu trúc thư mục theo Functionality (Package Structure)

Dự án được phân chia thành các module chức năng chuyên biệt trong package `colab_session/`:

```text
Colab-SSH/
├── colab_session/             # Core package chính
│   ├── auth/                  # Quản lý GitHub PAT, auth mapping, token
│   │   └── credentials.py
│   ├── ssh/                   # Cấu hình SSH host, known_hosts, proxy command
│   │   ├── config.py
│   │   └── proxy.py
│   ├── hardware/              # Cấu hình NVIDIA LD_LIBRARY_PATH, check GPU
│   │   └── gpu.py
│   ├── env/                   # VS Code profile, default extensions, AI context sync
│   │   └── environment.py
│   ├── storage/               # Google Drive backup & restore logic
│   │   └── backup.py
│   ├── session/               # Vòng đời runtime, sessions.json, Colab CLI, resolution & provisioning
│   │   ├── manager.py
│   │   ├── resolver.py
│   │   └── provisioner.py
│   ├── jobs/                  # Quản lý & điều phối Remote Job (models, runner, manager, config)
│   │   ├── models.py
│   │   ├── runner.py
│   │   ├── manager.py
│   │   └── config.py
│   ├── server/                # Web Dashboard control plane & REST API
│   │   └── app.py
│   ├── cli/                   # Giao diện dòng lệnh (CLI subcommands & parser)
│   │   ├── main.py
│   │   └── server.py
│   └── mcp/                   # Model Context Protocol stdio server cho AI
│       └── server.py
├── tests/                     # Test suite toàn diện (111 tests)
├── Dockerfile & docker-compose.yml
├── pyproject.toml
└── [facade modules: colab_ssh.py, colab_server.py, ...]
```
├── Dockerfile & docker-compose.yml
├── pyproject.toml
└── [facade modules: colab_ssh.py, colab_server.py, ...]
```

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

Dự án đi kèm bộ unit tests toàn diện (111 tests) kiểm tra toàn bộ luồng provisioning, SSH proxy, GPU setup, CSRF origin check, backup/restore logic, remote job dispatching và MCP server:

```bash
# Chạy kiểm thử trên máy local:
python3 -m unittest discover -s tests -v

# Hoặc chạy kiểm thử bên trong Docker container:
docker run --rm colab-ssh:latest python3 -m unittest discover -s tests -v
```
