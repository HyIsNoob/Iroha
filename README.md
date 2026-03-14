# Iroha Bot

Bot Discord đa năng viết bằng Python (discord.py).

## Tính năng

### Tiện ích
| Lệnh | Mô tả |
|---|---|
| `/yesno <câu hỏi>` | Trả lời ngẫu nhiên Yes hoặc No |
| `/random <a, b, c>` | Random 1 lựa chọn từ danh sách ngăn cách bởi dấu phẩy |
| `/team <danh sách> <số team>` | Chia ngẫu nhiên danh sách vào N team |
| `/help` | Hiển thị toàn bộ lệnh |

### Social / Game
| Lệnh | Mô tả |
|---|---|
| `/playgame <game> [max_players]` | Tạo room chơi game có nút tham gia (mặc định 3 người) |
| `/hangout <dịp> <địa điểm> <thời gian>` | Tạo event offline, mọi người có thể bấm tham gia / không thể tham gia |

### Cài đặt server
| Lệnh | Quyền cần | Mô tả |
|---|---|---|
| `/iroha` | Manage Server | Đặt channel hiện tại làm kênh nhận log của bot |

### Voice
| Lệnh | Quyền cần | Mô tả |
|---|---|---|
| `/connect` | — | Iroha vào voice channel của bạn |
| `/disconnect` | — | Iroha rời voice channel |
| `/autojoin <true/false>` | Manage Server | Tự động join khi có người vào voice |
| `/voiceinout <true/false>` | Manage Server | Log thông báo khi có người join/leave voice |
| `/speak <text>` | — | Iroha đọc TTS trong voice channel |

### Backup Dropbox
| Lệnh | Quyền cần | Mô tả |
|---|---|---|
| `/backupwatch_add <channel>` | Manage Server | Theo dõi channel để tự động backup ảnh/video mới |
| `/backupwatch_remove <channel>` | Manage Server | Gỡ theo dõi channel |
| `/backupwatch_list` | Manage Server | Liệt kê các channel đang được theo dõi |
| `/backup_manual <channel> <YYYY-MM-DD>` | Manage Server | Backup thủ công media theo ngày (tự bỏ qua đã backup) |
| `/backup_status` | Manage Server | Xem thống kê và trạng thái Dropbox |

> File lớn hơn `BACKUP_MAX_FILE_MB` (mặc định 50 MB) sẽ bị bỏ qua tự động.

### Moderation / Troll
| Lệnh | Quyền cần | Mô tả |
|---|---|---|
| `/muted <user> <channel> <true/false> [tin nhắn]` | Manage Messages | Tự động xóa tin nhắn user trong channel được chỉ định và gửi lại thông báo |
| `/clearbot` | Manage Messages | Xóa 50 tin nhắn gần nhất của Iroha trong channel hiện tại |

---

## Cài đặt local (test trước khi deploy)

### Yêu cầu
- Python 3.11 – 3.13
- [FFmpeg](https://ffmpeg.org/download.html) (cần cho `/speak`)

### Cài FFmpeg trên Windows

```powershell
winget install ffmpeg
```
hoặc tải binary tại https://ffmpeg.org và thêm vào PATH.

### Chạy bot

```powershell
# 1. Tạo venv
cd d:\fileluu\Tools\ShoreKibi-main\Iroha
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 2. Cài dependencies
pip install -r requirements.txt

# 3. Tạo file .env từ template
Copy-Item .env.example .env
# Mở .env và điền BOT_TOKEN + Dropbox keys

# 4. Chạy bot
python main.py
```

Bot sẽ in log ra terminal. Dùng `Ctrl+C` để dừng.

### Kiểm tra health endpoint

```powershell
Invoke-RestMethod http://localhost:10000/health
```

---

## Deploy lên Render

1. Push repo lên GitHub.
2. Vào [Render Dashboard](https://dashboard.render.com) → **New → Web Service** → chọn repo.
3. Render tự detect **Dockerfile** — chọn plan **Free**.
4. Điền các **Environment Variables** (xem `.env.example`):

| Key | |
|---|---|
| `BOT_TOKEN` | Token bot Discord |
| `DROPBOX_APP_KEY` | App key Dropbox |
| `DROPBOX_APP_SECRET` | App secret Dropbox |
| `DROPBOX_REFRESH_TOKEN` | Refresh token Dropbox |
| `DROPBOX_BACKUP_ROOT` | `/iroha-backup` |
| `BACKUP_MAX_FILE_MB` | `50` |
| `PORT` | `10000` |
| `LOG_LEVEL` | `INFO` |

5. Deploy.

### Keep-alive (tránh sleep sau 15 phút)

Đăng ký [UptimeRobot](https://uptimerobot.com) → monitor URL `https://<app>.onrender.com/health` mỗi **5 phút** (HTTP).

<<<<<<< Updated upstream
---
=======
---
>>>>>>> Stashed changes
