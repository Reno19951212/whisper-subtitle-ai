# 🎙 廣播字幕製作系統

基於 [OpenAI Whisper](https://github.com/openai/whisper) 及本地 AI 翻譯模型嘅專業字幕製作工具。將英文影片自動轉錄、翻譯為**繁體中文（粵語/書面語）**字幕，經人工校對後燒入影片輸出。

---

## 功能特點

| 功能 | 說明 |
|------|------|
| 📁 **文件上傳與管理** | 拖放或選擇影片/音頻，支援 MP4、MOV、AVI、MKV、WebM、MXF 等格式 |
| 🤖 **英文語音轉錄** | Whisper ASR 自動將英文語音轉為英文文字（支援 faster-whisper 加速） |
| 🌐 **中文翻譯** | 本地 Ollama + Qwen2.5 模型，將英文字幕翻譯為繁體中文（粵語或書面語） |
| 📖 **術語表管理** | 自訂英中術語對照表，確保專業名詞翻譯一致（支援 CSV 匯入/匯出） |
| ⚙️ **Profile 配置** | 可切換不同 ASR + 翻譯引擎組合，適應開發/生產環境 |
| 🌐 **語言參數配置** | 每種語言獨立設定 ASR 分段參數（每句最大字數/時長）及翻譯參數（batch size/temperature） |
| ✏️ **字幕校對編輯器** | 獨立校對頁面，左右並排影片與字幕表格，逐句審核、編輯、批核 |
| 🎬 **燒入字幕輸出** | 配置字體後，將已批核字幕燒入影片，輸出 MP4 或 MXF (ProRes 422 HQ) |
| 📊 **轉錄進度條** | 轉錄時顯示進度百分比、已處理/總時長、預計剩餘時間 |
| ⚡ **雙引擎支援** | 自動選用 faster-whisper（快 4–8 倍）或 openai-whisper |
| 💾 **字幕導出** | 每個文件獨立提供 SRT、VTT、TXT 下載 |

---

## 系統需求

- **Python** 3.8 或以上
- **FFmpeg**（用於從影片提取音頻及燒入字幕）
- **Ollama**（本地 LLM 翻譯引擎）— [下載](https://ollama.com/download)
- **pip**（Python 套件管理工具）
- 現代瀏覽器（Chrome / Firefox / Safari / Edge）

---

## 快速開始

### 第一步：安裝

```bash
./setup.sh
```

安裝腳本會自動：
- 檢查 Python 3 及 FFmpeg 是否已安裝
- 建立 Python 虛擬環境（`backend/venv/`）
- 安裝所有 Python 依賴套件

### 第二步：安裝 Ollama 及翻譯模型

```bash
# 安裝 Ollama（macOS）
# 從 https://ollama.com/download 下載安裝

# 下載翻譯模型
ollama pull qwen2.5:3b
```

### 第三步：啟動

```bash
./start.sh
```

啟動腳本會：
1. 啟動後端服務器（`http://localhost:5001`）
2. 預加載 Whisper small 模型
3. 自動在瀏覽器打開前端頁面

按 `Ctrl+C` 停止服務器。

---

## 使用流程

### 1. 選擇 Profile

在右側「設置」面板嘅「Pipeline Profile」下拉選單中選擇配置：
- **Development** — Whisper tiny + Mock 翻譯（開發測試用）
- **Broadcast Production** — Whisper + Qwen2.5 翻譯（正式使用）

可直接喺側邊欄 Profile 管理介面**建立、編輯、刪除** Profile，或按下「＋ New Profile」按鈕建立新配置。點擊任何 Profile 列表行可立即激活該 Profile（綠點指示）。

- **引擎選擇**：編輯 Profile 時，ASR 和翻譯引擎選單會從後端動態載入，顯示每個引擎的可用狀態（綠點 = 可用、灰點 = 不可用）。切換引擎後，對應的參數欄位會自動更新。

### 2. 上傳英文影片

- 拖放影片至上傳區域，或點擊選擇文件
- 支援格式：MP4、MOV、AVI、MKV、WebM、MXF、MP3、WAV 等
- 點擊「🚀 上傳並轉錄」

### 3. 自動轉錄 + 翻譯

- 系統自動進行英文語音轉錄
- 轉錄完成後自動觸發中文翻譯
- 右側轉錄面板會顯示翻譯後嘅中文字幕
- 播放影片時字幕會同步顯示

### 4. 校對字幕

- 文件卡片上會出現紫色「**校對**」按鈕
- 點擊進入校對編輯器（`proofread.html`）
- 左邊播放影片，右邊逐句審核翻譯
- 可直接編輯中文翻譯，按 Enter 儲存並批核
- 「批核所有未改動」可一次批核所有未修改嘅句子

**鍵盤快捷鍵：**
| 按鍵 | 功能 |
|------|------|
| ↑↓ | 切換段落 |
| Enter | 批核當前段落 |
| E | 編輯翻譯 |
| Esc | 取消編輯 |
| Space | 播放/暫停影片 |

### 5. 燒入字幕輸出

- 所有段落批核完成後，「匯出燒入字幕」按鈕啟用
- 選擇輸出格式：**MP4** 或 **MXF (ProRes)**
- 點擊開始渲染，完成後自動下載

---

## 系統架構

### 整體 Pipeline 流程

```
┌─────────────────────────────────────────────────────────────────┐
│                        前端 (Frontend)                           │
│                                                                  │
│  index.html                              proofread.html          │
│  ┌──────────────────────┐                ┌────────────────────┐  │
│  │ 📁 上傳影片           │                │ ✏️ 校對編輯器       │  │
│  │ ⚙️ Profile / 語言配置 │                │ 📹 影片 + 字幕表格  │  │
│  │ 📖 術語表管理         │                │ ✅ 逐句批核         │  │
│  │ 📄 轉錄 + 翻譯預覽   │──── 校對 ────▶│ 🎬 燒入字幕輸出     │  │
│  └──────────┬───────────┘                └─────────┬──────────┘  │
│             │ REST API + WebSocket                  │ REST API    │
└─────────────┼───────────────────────────────────────┼────────────┘
              │                                       │
              ▼                                       ▼
┌─────────────────────────────────────────────────────────────────┐
│                     後端 (Flask + SocketIO)                       │
│                                                                  │
│  ┌─────────┐    ┌──────────┐    ┌──────────┐    ┌───────────┐  │
│  │ Profile  │    │ Glossary │    │ Language  │    │   File    │  │
│  │ Manager  │    │ Manager  │    │  Config   │    │ Registry  │  │
│  └────┬─────┘    └────┬─────┘    └────┬─────┘    └─────┬─────┘  │
│       │               │               │                │         │
│       ▼               ▼               ▼                ▼         │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                    轉錄 + 翻譯 Pipeline                    │   │
│  │                                                           │   │
│  │  1. FFmpeg 音頻提取 (MP4/MXF → 16kHz WAV)                │   │
│  │              │                                            │   │
│  │              ▼                                            │   │
│  │  2. ASR 引擎 (英文語音 → 英文文字段落)                     │   │
│  │     ┌─────────────┬──────────────┬──────────────┐        │   │
│  │     │ Whisper     │ Qwen3-ASR   │ FLG-ASR      │        │   │
│  │     │ (完整實現)   │ (stub)      │ (stub)       │        │   │
│  │     │ tiny/base/  │ 生產環境     │ 生產環境      │        │   │
│  │     │ small/medium│ 大型模型     │ 快速引擎      │        │   │
│  │     │ /large/turbo│              │              │        │   │
│  │     └─────────────┴──────────────┴──────────────┘        │   │
│  │              │                                            │   │
│  │              ▼                                            │   │
│  │  3. 段落後處理 (split_segments)                            │   │
│  │     按 max_words / max_duration 分割過長段落               │   │
│  │              │                                            │   │
│  │              ▼                                            │   │
│  │  4. 翻譯引擎 (英文文字 → 繁體中文)                         │   │
│  │     ┌──────────────────────┬──────────────┐              │   │
│  │     │ Ollama + Qwen2.5    │ Mock Engine   │              │   │
│  │     │ (本地 LLM 翻譯)      │ (開發測試)    │              │   │
│  │     │ 3B / 7B / 72B       │ [EN→ZH] 格式  │              │   │
│  │     │ 書面語 / 粵語口語    │              │              │   │
│  │     │ + 術語表注入         │              │              │   │
│  │     └──────────────────────┴──────────────┘              │   │
│  │              │                                            │   │
│  │              ▼                                            │   │
│  │  5. 翻譯結果儲存 → WebSocket 通知前端                      │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                    字幕渲染 Pipeline                        │   │
│  │                                                           │   │
│  │  已批核翻譯 → ASS 字幕生成 → FFmpeg 燒入                  │   │
│  │  輸出格式：MP4 (H.264) 或 MXF (ProRes 422 HQ)            │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

### AI 模型配置

系統透過 **Profile** 統一管理 AI 模型組合。每個 Profile 指定 ASR 引擎 + 翻譯引擎 + 字體配置：

| Profile | ASR 引擎 | 翻譯引擎 | 用途 |
|---------|----------|----------|------|
| **Development** | Whisper tiny | Mock | 開發測試，無需 GPU |
| **Broadcast Production** | Whisper / Qwen3-ASR | Ollama Qwen2.5 | 正式製作 |

#### ASR 引擎

| 引擎 | 狀態 | 模型 | 說明 |
|------|------|------|------|
| **Whisper** | ✅ 完整實現 | tiny / base / small / medium / large / turbo | OpenAI 開源語音辨識，支援 faster-whisper 加速 |
| **Qwen3-ASR** | 🔧 Stub | — | 生產環境大型模型（待實現） |
| **FLG-ASR** | 🔧 Stub | — | 生產環境快速引擎（待實現） |

#### 翻譯引擎

| 引擎 | 狀態 | 模型 | 說明 |
|------|------|------|------|
| **Ollama** | ✅ 完整實現 | qwen2.5:3b / 7b / 72b | 本地 LLM，支援書面語及粵語風格 |
| **Mock** | ✅ 測試用 | — | 返回 `[EN→ZH]` 格式，用於開發測試 |

#### 語言參數

每種語言可獨立設定：

| 參數 | 說明 | 預設值 (EN) |
|------|------|------------|
| `max_words_per_segment` | ASR 每段最大字數 | 40 |
| `max_segment_duration` | ASR 每段最大時長（秒） | 10.0 |
| `batch_size` | 翻譯批次大小 | 10 |
| `temperature` | 翻譯隨機度 | 0.1 |

### 前端頁面

| 頁面 | 功能 | 與後端通訊 |
|------|------|-----------|
| **index.html** | 主控台 — 上傳、轉錄、翻譯、設定 | REST API + WebSocket（即時進度） |
| **proofread.html** | 校對編輯器 — 審核、編輯、批核、渲染 | REST API（輪詢渲染狀態） |

**index.html 右側面板：**
- ⚙️ Profile 選擇器
- 📦 模型預加載
- 🎬 字幕延遲 / 大小控制
- 🌐 語言配置（可展開收合）
- 📖 術語表管理（可展開收合）

### 資料流（完整流程）

```
1. 用戶上傳影片 (index.html)
   │
   ├─ POST /api/transcribe → 上傳文件 + 開始轉錄
   │
2. 後端處理
   │
   ├─ FFmpeg 提取音頻 (16kHz WAV)
   ├─ ASR 引擎轉錄 (WebSocket 逐段推送進度)
   ├─ split_segments 後處理（按語言參數分割過長段落）
   ├─ 自動觸發翻譯 (Ollama Qwen2.5 + 術語表)
   └─ WebSocket 通知前端「翻譯完成」
   │
3. 前端預覽
   │
   ├─ 轉錄面板顯示中文字幕
   ├─ 播放影片時字幕同步顯示
   └─ 可點擊「🔄 重新翻譯」重做
   │
4. 校對 (proofread.html)
   │
   ├─ 左：影片播放 / 右：英中對照表格
   ├─ 逐句編輯中文翻譯 (Enter 儲存 + 自動批核)
   └─ 「批核所有未改動」一鍵完成
   │
5. 燒入字幕輸出
   │
   ├─ 選擇格式：MP4 (H.264) 或 MXF (ProRes 422 HQ)
   ├─ 後端生成 ASS 字幕 → FFmpeg 燒入
   └─ 完成後自動下載
```

---

## 項目結構

```
whisper-subtitle-ai/
├── backend/
│   ├── app.py              # Flask 後端服務器（REST API + WebSocket）
│   ├── profiles.py         # Profile 管理模組（ASR + 翻譯 + 字體配置）
│   ├── glossary.py         # 術語表管理模組（CRUD + CSV 匯入/匯出）
│   ├── language_config.py  # 語言參數配置模組（ASR + 翻譯參數）
│   ├── renderer.py         # 字幕渲染模組（ASS 生成 + FFmpeg 燒入）
│   ├── asr/                # ASR 引擎抽象層
│   │   ├── __init__.py     #   ASREngine ABC + 工廠函數
│   │   ├── whisper_engine.py #   Whisper 實現（faster-whisper / openai-whisper）
│   │   ├── segment_utils.py  #   段落後處理（分割過長段落）
│   │   ├── qwen3_engine.py #   Qwen3-ASR stub
│   │   └── flg_engine.py   #   FLG-ASR stub
│   ├── translation/        # 翻譯引擎抽象層
│   │   ├── __init__.py     #   TranslationEngine ABC + 工廠函數
│   │   ├── ollama_engine.py #   Ollama/Qwen 翻譯（本地 LLM）
│   │   └── mock_engine.py  #   Mock 翻譯（開發測試）
│   ├── config/             # 配置文件
│   │   ├── settings.json   #   當前 Profile 指標
│   │   ├── profiles/       #   Profile JSON 文件
│   │   ├── glossaries/     #   術語表 JSON 文件
│   │   └── languages/      #   語言參數 JSON 文件 (en.json, zh.json)
│   ├── tests/              # 測試套件（145 個測試）
│   └── data/               # 上傳文件及渲染輸出（自動生成，gitignore）
├── frontend/
│   ├── index.html          # 主控台 — 上傳、轉錄、翻譯、設定
│   └── proofread.html      # 校對編輯器 — 審核、編輯、批核、渲染
├── docs/superpowers/       # 設計文檔及實作計劃
├── setup.sh                # 一鍵安裝腳本
├── start.sh                # 一鍵啟動腳本
└── README.md               # 本文件
```

---

## 術語表管理

系統內建「Broadcast News」術語表，包含常用香港廣播新聞術語：

| 英文 | 中文 |
|------|------|
| Legislative Council | 立法會 |
| Chief Executive | 行政長官 |
| Hong Kong | 香港 |
| government | 政府 |
| police | 警方 |
| ... | ... |

可通過 API 新增、編輯、匯入 CSV 術語表。術語會自動注入翻譯 prompt，確保專業名詞翻譯一致。

---

## Whisper 模型對照表

| 模型 | 參數量 | 速度 | 精準度 | 建議用途 |
|------|--------|------|--------|---------|
| tiny | 39M | 最快 | 基礎 | 開發測試 |
| base | 74M | 快 | 良好 | 快速轉錄 |
| small | 244M | 中等 | 優良 | 一般使用（推薦） |
| medium | 769M | 慢 | 出色 | 高精準度需求 |
| large | 1550M | 最慢 | 最佳 | 最高精準度 |
| turbo | 809M | 快 | 優良 | 速度與精準度平衡 |

> **提示**：安裝 `faster-whisper` 後，所有模型速度可提升 4–8 倍。

---

## API 參考

後端提供以下 REST 端點（基礎 URL：`http://localhost:5001`）：

### 文件管理
| 方法 | 路徑 | 說明 |
|------|------|------|
| POST | `/api/transcribe` | 上傳並轉錄（自動觸發翻譯） |
| GET | `/api/files` | 列出所有文件 |
| GET | `/api/files/<id>/media` | 取得媒體文件 |
| GET | `/api/files/<id>/subtitle.<fmt>` | 下載字幕（srt/vtt/txt） |
| DELETE | `/api/files/<id>` | 刪除文件 |

### Profile 管理
| 方法 | 路徑 | 說明 |
|------|------|------|
| GET | `/api/profiles` | 列出所有 Profile |
| POST | `/api/profiles` | 建立 Profile |
| GET | `/api/profiles/active` | 取得當前 Profile |
| POST | `/api/profiles/<id>/activate` | 切換 Profile |

### 翻譯與校對
| 方法 | 路徑 | 說明 |
|------|------|------|
| POST | `/api/translate` | 翻譯文件字幕 |
| GET | `/api/files/<id>/translations` | 取得翻譯結果 |
| PATCH | `/api/files/<id>/translations/<idx>` | 修改翻譯（自動批核） |
| POST | `/api/files/<id>/translations/approve-all` | 批量批核 |

### 術語表
| 方法 | 路徑 | 說明 |
|------|------|------|
| GET | `/api/glossaries` | 列出術語表 |
| POST | `/api/glossaries/<id>/entries` | 新增術語 |
| DELETE | `/api/glossaries/<id>/entries/<eid>` | 刪除術語 |
| POST | `/api/glossaries/<id>/import` | 匯入 CSV |
| GET | `/api/glossaries/<id>/export` | 匯出 CSV |

### 語言配置
| 方法 | 路徑 | 說明 |
|------|------|------|
| GET | `/api/languages` | 列出所有語言配置 |
| GET | `/api/languages/<id>` | 取得語言配置 |
| PATCH | `/api/languages/<id>` | 更新語言參數 |

### 渲染
| 方法 | 路徑 | 說明 |
|------|------|------|
| POST | `/api/render` | 開始燒入字幕渲染 |
| GET | `/api/renders/<id>` | 查詢渲染狀態 |
| GET | `/api/renders/<id>/download` | 下載渲染結果 |

---

## 更新記錄

### v2.1 — 語言配置、前端 UI 整合、Bug 修復
- 語言參數配置：每種語言獨立設定 ASR 分段參數及翻譯參數
- ASR 後處理：自動分割過長段落（按句子邊界）
- 前端語言配置面板：可展開收合，直接編輯語言參數
- 前端術語表面板：可展開收合，新增/刪除術語、CSV 匯入
- 翻譯狀態徽章：待翻譯/翻譯中/翻譯完成，支援手動觸發翻譯
- 多項 Bug 修復：術語表顯示、拖放上傳、驗證錯誤提示等
- 145 個自動化測試（+36 個新測試）

### v2.0 — 廣播字幕製作系統
- 全新 pipeline：英文影片 → ASR 轉錄 → 中文翻譯 → 校對 → 燒入字幕輸出
- Profile 系統：可切換 ASR + 翻譯引擎組合
- 多引擎 ASR：統一介面支援 Whisper、Qwen3-ASR（stub）、FLG-ASR（stub）
- 翻譯 pipeline：本地 Ollama + Qwen2.5，支援粵語及書面語風格
- 術語表管理：英中對照，CSV 匯入/匯出
- 校對編輯器：獨立頁面，左右並排，逐句審核
- 字幕渲染：ASS 字幕 + FFmpeg 燒入，支援 MP4 及 MXF (ProRes) 輸出
- 自動翻譯：轉錄完成自動觸發翻譯
- 移除實時錄製模式：專注文件式廣播字幕製作流程
- 109 個自動化測試

### v1.0–v1.5 — 原始版本
- 文件上傳轉錄，支援多種格式
- Whisper ASR + faster-whisper 加速
- 轉錄進度條及預計剩餘時間
- 字幕內容編輯
- SRT/VTT/TXT 導出
