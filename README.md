# 🎙 Whisper AI 字幕系統

基於 [OpenAI Whisper](https://github.com/openai/whisper) 嘅 AI 語音轉字幕 Web 應用程式。支援上傳影片/音頻檔案或直接從攝像頭/屏幕捕捉，自動將語音即時轉換為**繁體中文字幕**，並同步顯示喺影片畫面上。

---

## 功能特點

| 功能 | 說明 |
|------|------|
| 📁 **文件上傳與管理** | 拖放或選擇影片/音頻，文件上傳後持久保存，直到手動刪除 |
| 📋 **文件列表** | 所有已上傳文件以卡片形式顯示，包含狀態指示及下載選項 |
| 🎥 **實時直播** | 從攝像頭或屏幕共享捕捉，每 3 秒批次轉錄 |
| 💬 **繁體中文字幕** | 強制輸出繁體中文，字幕疊加於影片畫面 |
| ⏱ **延遲同步** | 0–5 秒可調延遲，確保字幕與語音同步 |
| ⚡ **雙引擎支援** | 自動選用 faster-whisper（快 4–8 倍）或 openai-whisper |
| 🤖 **6 種模型** | tiny → turbo，按速度/精準度自由選擇 |
| 💾 **三種導出** | 每個文件獨立提供 SRT、VTT、TXT 下載 |

---

## 系統需求

- **Python** 3.8 或以上
- **FFmpeg**（用於從影片提取音頻）
- **pip**（Python 套件管理工具）
- 現代瀏覽器（Chrome / Firefox / Safari / Edge）

---

## 快速開始

### 第一步：安裝

```bash
cd "Whisper 開發"
./setup.sh
```

安裝腳本會自動：
- 檢查 Python 3 及 FFmpeg 是否已安裝
- 建立 Python 虛擬環境（`backend/venv/`）
- 安裝所有 Python 依賴套件

> 如果系統未安裝 FFmpeg，腳本會嘗試用 Homebrew（macOS）或 apt（Linux）自動安裝。

### 第二步：啟動

```bash
./start.sh
```

啟動腳本會：
1. 啟動後端服務器（`http://localhost:5000`）
2. 預加載 Whisper small 模型
3. 自動在瀏覽器打開前端頁面

按 `Ctrl+C` 停止服務器。

### 手動啟動（可選）

```bash
# 啟動後端
cd backend
source venv/bin/activate
python app.py

# 前端：直接在瀏覽器打開
open frontend/index.html
```

---

## 項目結構

```
Whisper 開發/
├── backend/
│   ├── app.py              # Flask 後端服務器（REST API + WebSocket）
│   ├── requirements.txt    # Python 依賴清單
│   └── data/               # 已上傳文件及轉錄結果（自動生成，已 gitignore）
├── frontend/
│   └── index.html          # 完整 Web 應用（單一文件，無需構建）
├── setup.sh                # 一鍵安裝腳本
├── start.sh                # 一鍵啟動腳本
├── CLAUDE.md               # 開發者參考文件（英文）
└── README.md               # 本文件
```

### 後端（`backend/app.py`）

- **Flask + Flask-SocketIO**：HTTP REST API 及 WebSocket 雙向通訊
- **Whisper 引擎**：優先使用 `faster-whisper`（需額外安裝），自動回退至 `openai-whisper`
- **FFmpeg**：從影片文件提取 16kHz 單聲道音頻
- **背景線程**：轉錄在後台執行，每完成一個段落即時通過 WebSocket 推送至前端
- **文件持久化**：上傳的文件保存在 `data/uploads/`，元數據記錄在 `data/registry.json`，重啟不丟失

### 前端（`frontend/index.html`）

- 純 HTML/CSS/JavaScript，無需任何構建工具
- **文件上傳模式**：選擇或拖放檔案 → 上傳至後端 → 接收字幕段落 → 同步顯示於影片
- **文件列表**：已上傳文件以卡片顯示，點擊可預覽，轉錄完成後直接提供 SRT/VTT/TXT 下載
- **實時直播模式**：瀏覽器錄製音頻 → 每 3 秒傳送至後端 → 接收字幕 → 顯示覆蓋層

---

## 使用說明

### 文件上傳模式

1. 點擊「📁 文件上傳」頁籤
2. 拖放影片/音頻至上傳區域，或點擊選擇文件
3. 在右側「設置」面板選擇 Whisper 模型
4. 點擊「🚀 上傳並轉錄」
5. 文件會出現在下方的文件列表中，顯示轉錄狀態
6. 轉錄完成後，文件卡片會顯示 SRT / VTT / TXT 下載按鈕
7. 點擊文件卡片可隨時切換預覽不同文件
8. 點擊 ✕ 按鈕可刪除文件

> 上傳的文件會持久保存在服務器上，除非你手動刪除，重啟服務器後文件仍然存在。

**支援格式：** MP4、MOV、AVI、MKV、WebM、MP3、WAV、M4A、AAC、FLAC、OGG

### 實時直播模式

1. 點擊「🎥 實時錄製」頁籤
2. 選擇視頻源：攝像頭 或 屏幕共享
3. 點擊「▶ 開始直播」，授予瀏覽器錄製權限
4. 字幕會每 3 秒更新一次（依轉錄速度）
5. 點擊「⏹ 停止」結束直播

> **提示**：實時模式建議使用 `tiny` 或 `base` 模型以降低延遲。

### 字幕同步設置

| 設置 | 說明 |
|------|------|
| **字幕延遲** | 字幕相對於音頻出現的時間偏移。若字幕早於語音顯示，增加延遲值 |
| **字幕顯示時長** | 每條字幕在畫面停留的秒數（1–10 秒） |
| **字幕字號** | 字幕文字大小（14–48 px） |

### 導出字幕

轉錄完成後，有兩種導出方式：

**方式一：文件卡片下載**（推薦）
- 每個已完成轉錄的文件卡片上會直接顯示 **SRT** / **VTT** / **TXT** 下載按鈕
- 點擊即可下載對應格式的字幕文件

**方式二：右側轉錄面板導出**
- 點擊底部的 SRT / VTT / TXT 按鈕導出當前顯示的轉錄內容

**格式說明：**
- **SRT**：標準字幕格式，兼容大部分影片播放器（如 VLC、PotPlayer）
- **VTT**：WebVTT 格式，可直接用於 HTML5 `<video>` 的 `<track>` 元素
- **TXT**：純文字逐字稿，每段一行

---

## Whisper 模型對照表

| 模型 | 參數量 | 速度 | 精準度 | 建議用途 |
|------|--------|------|--------|---------|
| tiny | 39M | 最快 | 基礎 | 實時直播 |
| base | 74M | 快 | 良好 | 實時直播 |
| small | 244M | 中等 | 優良 | 文件轉錄（推薦預設） |
| medium | 769M | 慢 | 出色 | 高精準度需求 |
| large | 1550M | 最慢 | 最佳 | 最高精準度 |
| turbo | 809M | 快 | 優良 | 速度與精準度平衡 |

> **提示**：安裝 `faster-whisper` 後，所有模型速度可提升 4–8 倍，記憶體需求亦降低。
>
> ```bash
> pip install faster-whisper
> ```

---

## API 參考

後端提供以下 REST 端點（基礎 URL：`http://localhost:5001`）：

| 方法 | 路徑 | 說明 |
|------|------|------|
| GET | `/api/health` | 服務器狀態及已加載模型 |
| GET | `/api/models` | 可用模型清單 |
| POST | `/api/transcribe` | 上傳並異步轉錄（通過 WebSocket 串流結果） |
| POST | `/api/transcribe/sync` | 同步轉錄（適合小文件） |
| GET | `/api/files` | 列出所有已上傳文件及狀態 |
| GET | `/api/files/<id>/media` | 取得原始媒體文件 |
| GET | `/api/files/<id>/subtitle.srt` | 下載 SRT 字幕 |
| GET | `/api/files/<id>/subtitle.vtt` | 下載 VTT 字幕 |
| GET | `/api/files/<id>/subtitle.txt` | 下載 TXT 逐字稿 |
| DELETE | `/api/files/<id>` | 刪除文件及轉錄數據 |

---

## 更新記錄

### v1.3 — 文件持久化管理
- 上傳的文件現在會持久保存在服務器上，直到手動刪除
- 文件列表以卡片形式顯示，包含轉錄狀態指示
- 轉錄完成的文件卡片直接提供 SRT / VTT / TXT 下載按鈕
- 點擊文件卡片可切換預覽，點擊 ✕ 刪除文件
- 文件數據在服務器重啟後不會丟失
- 新增 REST API：文件列表、媒體服務、字幕下載、文件刪除
- 服務器 Port 改為 5001（避免 macOS AirPlay 衝突）

### v1.2 — 雙引擎支援與 WebVTT 導出
- 新增 `faster-whisper` 引擎支援（自動選用，快 4–8 倍）
- 新增 WebVTT（`.vtt`）字幕導出格式
- 修復實時模式音頻臨時文件副檔名錯誤

### v1.1 — 錯誤修復與穩定性提升
- 修復字幕延遲方向錯誤（之前延遲越大反而字幕越早出現）
- 修復 WebSocket 從背景線程調用 `emit()` 導致的崩潰
- 修復大音頻 Buffer 轉 Base64 時的堆疊溢出問題

### v1.0 — 初始版本
- 文件上傳轉錄（支援多種影片及音頻格式）
- 實時攝像頭/屏幕直播轉錄
- 繁體中文字幕即時顯示
- 字幕延遲同步、時長、字號調整
- SRT 及 TXT 字幕導出
