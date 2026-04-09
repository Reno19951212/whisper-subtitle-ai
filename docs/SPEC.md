# 廣播字幕製作系統 — 技術規格文件 (Technical Specification)

**版本：** 2.1
**日期：** 2026-04-09
**對應 PRD：** docs/PRD.md

---

## 1. 技術架構

### 1.1 系統架構圖

```
┌───────────────────────────────────────────────────────────┐
│                     用戶瀏覽器                              │
│                                                            │
│  index.html (主控台)          proofread.html (校對編輯器)    │
│  ┌─────────────────┐         ┌──────────────────┐         │
│  │ 上傳 / 轉錄預覽  │         │ 影片 + 字幕校對   │         │
│  │ 翻譯 / 設定面板  │────────▶│ 批核 + 渲染輸出   │         │
│  └────────┬────────┘         └────────┬─────────┘         │
└───────────┼────────────────────────────┼──────────────────┘
            │ HTTP + WebSocket           │ HTTP
            ▼                            ▼
┌───────────────────────────────────────────────────────────┐
│              Flask + Flask-SocketIO (Port 5001)            │
│                                                            │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐    │
│  │ profiles │ │ glossary │ │ language │ │ renderer │    │
│  │   .py    │ │   .py    │ │config.py │ │   .py    │    │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘    │
│                                                            │
│  ┌────────────────────────────────────────────────┐       │
│  │                  app.py (路由 + 協調)             │       │
│  └──────┬────────────────┬────────────────┬───────┘       │
│         │                │                │                │
│         ▼                ▼                ▼                │
│  ┌────────────┐  ┌─────────────┐  ┌────────────┐         │
│  │  asr/      │  │ translation/│  │  FFmpeg    │         │
│  │ (引擎抽象) │  │ (引擎抽象)  │  │ (音頻/渲染) │         │
│  └──────┬─────┘  └──────┬──────┘  └────────────┘         │
│         │               │                                  │
│         ▼               ▼                                  │
│  ┌────────────┐  ┌─────────────┐                          │
│  │ Whisper    │  │ Ollama HTTP │                          │
│  │ (本地模型) │  │ :11434      │                          │
│  └────────────┘  └─────────────┘                          │
│                                                            │
│  config/                                                   │
│  ├── settings.json    (active profile 指標)                │
│  ├── profiles/*.json  (ASR + 翻譯 + 字體配置)             │
│  ├── glossaries/*.json(術語表)                             │
│  └── languages/*.json (語言參數)                           │
└───────────────────────────────────────────────────────────┘
```

### 1.2 技術棧

| 層級 | 技術 | 版本 |
|------|------|------|
| **前端** | HTML5 / CSS3 / JavaScript (ES6+) | — |
| **前端通訊** | Socket.IO Client | 4.7.2 |
| **後端框架** | Flask + Flask-SocketIO | 3.0+ / 5.3+ |
| **ASR** | faster-whisper / openai-whisper | 1.0+ / 20231117+ |
| **翻譯** | Ollama HTTP API + Qwen2.5 | — |
| **音頻/渲染** | FFmpeg (系統依賴) | — |
| **語言** | Python | 3.8+ |
| **運行環境** | 本地部署（無雲端依賴） | — |

### 1.3 設計原則

| 原則 | 實踐 |
|------|------|
| **引擎抽象** | ASR 及翻譯均透過 ABC + Factory 模式，新增引擎只需實現介面 |
| **Profile 驅動** | 所有 AI 模型選擇由 Profile JSON 決定，運行時可切換 |
| **前後端分離** | 前端純靜態 HTML，透過 REST API + WebSocket 與後端通訊 |
| **本地優先** | 所有 AI 推理在本地完成，無外部 API 調用 |
| **JSON 文件存儲** | Profile、術語表、語言配置均用 JSON 文件，無需數據庫 |

---

## 2. 後端模塊規格

### 2.1 app.py — 主服務器

**職責：** REST API 路由、WebSocket 事件處理、Pipeline 協調、文件管理

**REST API 端點（共 35 個）：**

#### 文件管理 (7)
| 方法 | 路徑 | 說明 | 回應 |
|------|------|------|------|
| POST | `/api/transcribe` | 上傳影片 + 啟動轉錄 | `{file_id, status}` |
| POST | `/api/transcribe/sync` | 同步轉錄（等待完成） | `{file_id, segments}` |
| GET | `/api/files` | 列出所有文件 | `{files: [{id, name, status, translation_status}]}` |
| GET | `/api/files/<id>/media` | 串流媒體文件 | 二進制串流 |
| GET | `/api/files/<id>/subtitle.<fmt>` | 下載字幕 (srt/vtt/txt) | 文字文件 |
| GET | `/api/files/<id>/segments` | 取得轉錄段落 | `{segments: [{id, start, end, text}]}` |
| DELETE | `/api/files/<id>` | 刪除文件 | `{deleted: true}` |

#### Profile 管理 (6)
| 方法 | 路徑 | 說明 | 回應 |
|------|------|------|------|
| GET | `/api/profiles` | 列出所有 | `{profiles: [...]}` |
| POST | `/api/profiles` | 建立 | `{profile}` 201 |
| GET | `/api/profiles/active` | 取得當前 | `{profile}` |
| GET | `/api/profiles/<id>` | 取得指定 | `{profile}` |
| PATCH | `/api/profiles/<id>` | 更新 | `{profile}` |
| POST | `/api/profiles/<id>/activate` | 切換當前 | `{profile}` |

#### 翻譯與校對 (7)
| 方法 | 路徑 | 說明 | 回應 |
|------|------|------|------|
| POST | `/api/translate` | 翻譯文件字幕 | `{file_id, translations}` |
| GET | `/api/files/<id>/translations` | 取得翻譯 | `{translations: [{en_text, zh_text, status}]}` |
| PATCH | `/api/files/<id>/translations/<idx>` | 修改翻譯 | `{translation}` |
| POST | `/api/files/<id>/translations/<idx>/approve` | 批核單句 | `{approved: true}` |
| POST | `/api/files/<id>/translations/approve-all` | 批量批核 | `{approved_count}` |
| GET | `/api/files/<id>/translations/status` | 批核進度 | `{total, approved, pending}` |

#### 術語表 (8)
| 方法 | 路徑 | 說明 | 回應 |
|------|------|------|------|
| GET | `/api/glossaries` | 列出所有 | `{glossaries: [{id, name, entry_count}]}` |
| POST | `/api/glossaries` | 建立 | `{glossary}` 201 |
| GET | `/api/glossaries/<id>` | 取得（含 entries） | `{id, name, entries: [{id, en, zh}]}` |
| PATCH | `/api/glossaries/<id>` | 更新名稱/描述 | `{glossary}` |
| DELETE | `/api/glossaries/<id>` | 刪除 | `{deleted: true}` |
| POST | `/api/glossaries/<id>/entries` | 新增術語 | `{glossary}` 201 |
| DELETE | `/api/glossaries/<id>/entries/<eid>` | 刪除術語 | `{glossary}` |
| POST | `/api/glossaries/<id>/import` | 匯入 CSV | `{glossary}` |

#### 語言配置 (3)
| 方法 | 路徑 | 說明 | 回應 |
|------|------|------|------|
| GET | `/api/languages` | 列出所有 | `{languages: [{id, name, asr, translation}]}` |
| GET | `/api/languages/<id>` | 取得指定 | `{language: {id, asr, translation}}` |
| PATCH | `/api/languages/<id>` | 更新參數 | `{language}` |

#### 渲染 (3)
| 方法 | 路徑 | 說明 | 回應 |
|------|------|------|------|
| POST | `/api/render` | 開始渲染 | `{render_id}` |
| GET | `/api/renders/<id>` | 查詢狀態 | `{status, progress}` |
| GET | `/api/renders/<id>/download` | 下載成品 | 二進制串流 |

#### 系統 (3)
| 方法 | 路徑 | 說明 | 回應 |
|------|------|------|------|
| GET | `/api/health` | 系統狀態 | `{status, models_loaded}` |
| GET | `/api/models` | 可用模型列表 | `{models: [...]}` |
| POST | `/api/restart` | 重啟服務 | `{status}` |

**WebSocket 事件：**

| 方向 | 事件 | 載荷 | 觸發時機 |
|------|------|------|----------|
| S→C | `connected` | `{sid}` | 連接建立 |
| S→C | `model_loading` | `{model, status}` | 模型加載中 |
| S→C | `model_ready` | `{model}` | 模型加載完成 |
| S→C | `transcription_status` | `{status, message}` | 轉錄階段變化 |
| S→C | `subtitle_segment` | `{id, start, end, text, progress}` | 每段轉錄完成 |
| S→C | `transcription_complete` | `{text, segment_count}` | 轉錄全部完成 |
| S→C | `transcription_error` | `{error}` | 轉錄失敗 |
| S→C | `file_added` | `{id, name, ...}` | 新文件上傳 |
| S→C | `file_updated` | `{id, status, translation_status}` | 文件狀態變化 |
| C→S | `load_model` | `{model}` | 客戶端請求加載模型 |

### 2.2 profiles.py — Profile 管理

**職責：** Profile CRUD、驗證、active profile 切換

**Profile 結構：**
```json
{
  "id": "prod-default",
  "name": "Broadcast Production",
  "asr": {
    "engine": "whisper",
    "model_size": "small",
    "language": "en",
    "language_config_id": "en",
    "device": "auto"
  },
  "translation": {
    "engine": "qwen2.5-3b",
    "style": "formal",
    "glossary_id": "broadcast-news",
    "temperature": 0.1
  },
  "font": {
    "family": "Noto Sans TC",
    "size": 48,
    "color": "#FFFFFF",
    "outline_color": "#000000",
    "outline_width": 2,
    "position": "bottom",
    "margin_bottom": 40
  }
}
```

### 2.3 asr/ — ASR 引擎抽象

**介面：**
```python
class ASREngine(ABC):
    def transcribe(self, audio_path: str, language: str = "en") -> list[Segment]
    def get_info(self) -> dict
```

**Segment 結構：** `{start: float, end: float, text: str}`

**引擎實現：**

| 文件 | 引擎 | 說明 |
|------|------|------|
| `whisper_engine.py` | Whisper | 雙後端（faster-whisper 優先，openai-whisper 備用）；線程安全模型快取 |
| `qwen3_engine.py` | Qwen3-ASR | Stub — `raise NotImplementedError` |
| `flg_engine.py` | FLG-ASR | Stub — `raise NotImplementedError` |
| `segment_utils.py` | — | `split_segments()` 後處理：按 max_words / max_duration 分割過長段落 |

**工廠函數：** `create_asr_engine(config) → ASREngine`
- `engine: "whisper"` → WhisperEngine
- `engine: "qwen3-asr"` → Qwen3ASREngine
- `engine: "flg-asr"` → FLGASREngine

### 2.4 translation/ — 翻譯引擎抽象

**介面：**
```python
class TranslationEngine(ABC):
    def translate(self, segments, glossary=None, style="formal",
                  batch_size=None, temperature=None) -> list[TranslatedSegment]
    def get_info(self) -> dict
```

**TranslatedSegment 結構：** `{start: float, end: float, en_text: str, zh_text: str}`

**引擎實現：**

| 文件 | 引擎 | 說明 |
|------|------|------|
| `ollama_engine.py` | Ollama | 調用 `localhost:11434/api/chat`；批次翻譯；numbered 格式解析；術語表注入 |
| `mock_engine.py` | Mock | 返回 `[EN→ZH] {text}` 格式 |

**Ollama 翻譯流程：**
1. 組裝 system prompt（書面語/粵語 + 術語表）
2. 組裝 user message（numbered 英文段落）
3. POST 到 Ollama `/api/chat`（stream: false）
4. 解析回應（優先 numbered 格式，fallback line-by-line）

**工廠函數：** `create_translation_engine(config) → TranslationEngine`
- `engine: "mock"` → MockTranslationEngine
- `engine: "qwen2.5-3b"` / `"qwen2.5-7b"` / `"qwen2.5-72b"` / `"qwen3-235b"` → OllamaTranslationEngine

### 2.5 glossary.py — 術語表管理

**職責：** 術語表 CRUD、CSV 匯入/匯出、術語驗證

**存儲格式：** `config/glossaries/<id>.json`
```json
{
  "id": "broadcast-news",
  "name": "Broadcast News",
  "entries": [
    {"id": "uuid", "en": "Legislative Council", "zh": "立法會"},
    {"id": "uuid", "en": "Chief Executive", "zh": "行政長官"}
  ]
}
```

### 2.6 language_config.py — 語言參數

**職責：** 每語言 ASR + 翻譯參數管理、驗證

**存儲格式：** `config/languages/<id>.json`
```json
{
  "id": "en",
  "name": "English",
  "asr": {
    "max_words_per_segment": 40,
    "max_segment_duration": 10.0
  },
  "translation": {
    "batch_size": 10,
    "temperature": 0.1
  }
}
```

**驗證範圍：**

| 參數 | 最小值 | 最大值 |
|------|--------|--------|
| max_words_per_segment | 5 | 200 |
| max_segment_duration | 1.0 | 60.0 |
| batch_size | 1 | 50 |
| temperature | 0.0 | 2.0 |

### 2.7 renderer.py — 字幕渲染

**職責：** ASS 字幕生成、FFmpeg 燒入

**渲染流程：**
1. `generate_ass()` — 從已批核翻譯 + 字體配置生成 ASS 字幕文件
2. `render()` — 調用 FFmpeg 將 ASS 字幕燒入影片

**輸出格式：**

| 格式 | 編碼 | 用途 |
|------|------|------|
| MP4 | H.264 (libx264) | 一般發布 |
| MXF | ProRes 422 HQ (prores_ks profile 3) | 廣播級後期製作 |

---

## 3. 前端規格

### 3.1 index.html — 主控台

**佈局：** 兩欄 Grid（左：影片+上傳+文件列表；右：設定+轉錄面板）

**右側設定面板結構：**
1. Pipeline Profile 選擇器
2. 模型預加載按鈕
3. 字幕延遲控制（0-5 秒，預設 0）
4. 字幕大小控制（14-48px，預設 18px）
5. 🌐 語言配置（可收合）— 4 個參數輸入 + 儲存按鈕
6. 📖 術語表管理（可收合）— 選擇/新增/刪除/CSV 匯入
7. 📄 轉錄文字面板

**文件卡片狀態：**

| 狀態 | 徽章 | 按鈕 |
|------|------|------|
| 已上傳 | 「已上傳」灰色 | — |
| 轉錄中 | 「轉錄中」動畫 | 進度條 |
| 轉錄完成 + 待翻譯 | 「待翻譯」灰色 | 「▶ 翻譯」 |
| 翻譯中 | 「翻譯中...」黃色 | — |
| 翻譯完成 | 「翻譯完成」綠色 | 「🔄 重新翻譯」+「校對」 |

**通訊方式：**
- REST API：文件上傳、翻譯觸發、設定管理
- WebSocket：轉錄進度、文件狀態更新（即時推送）

### 3.2 proofread.html — 校對編輯器

**佈局：** 三區 Grid（左：影片面板；右：字幕表格；底部：操作列）

**字幕表格欄位：** 英文原文 | 中文翻譯 | 狀態圖標

**操作流程：**
1. 點擊段落 → 影片跳轉至對應時間點
2. 點擊中文欄 → 進入編輯模式（textarea）
3. Enter → 儲存 + 自動批核
4. Esc → 取消編輯
5. 「批核所有未改動」→ 一鍵批核
6. 選擇格式 → 「匯出燒入字幕」→ 渲染 + 下載

---

## 4. 數據流規格

### 4.1 轉錄 + 翻譯流程（時序）

```
前端                     後端                      AI 引擎
  │                        │                          │
  │── POST /api/transcribe ──▶│                       │
  │◀── {file_id, status} ──│                          │
  │                        │── FFmpeg 提取音頻 ──▶     │
  │                        │◀── 16kHz WAV ──          │
  │                        │                          │
  │                        │── ASR 轉錄 ──▶           │
  │◀── WS: subtitle_segment ──│  (逐段)              │
  │◀── WS: subtitle_segment ──│                       │
  │◀── WS: subtitle_segment ──│                       │
  │                        │◀── segments[] ──          │
  │                        │                          │
  │                        │── split_segments() ──    │
  │                        │                          │
  │                        │── 自動翻譯 ──▶            │
  │                        │    (Ollama /api/chat)     │
  │                        │◀── translations[] ──      │
  │◀── WS: file_updated ────│                          │
  │   (translation_status:  │                          │
  │    'done')              │                          │
```

### 4.2 渲染流程

```
前端                     後端                      FFmpeg
  │                        │                          │
  │── POST /api/render ────▶│                         │
  │◀── {render_id} ────────│                          │
  │                        │── generate_ass() ──      │
  │                        │── FFmpeg 燒入 ──▶         │
  │── GET /renders/<id> ──▶│                          │
  │◀── {status: running} ──│                          │
  │── GET /renders/<id> ──▶│                          │
  │◀── {status: done} ─────│◀── 完成 ──               │
  │── GET /renders/<id>/download ──▶│                  │
  │◀── 二進制文件 ──────────│                          │
```

---

## 5. 配置文件規格

### 5.1 settings.json

```json
{
  "active_profile": "dev-default"
}
```

### 5.2 Profile JSON

見 2.2 節。

### 5.3 Glossary JSON

見 2.5 節。

### 5.4 Language Config JSON

見 2.6 節。

---

## 6. 測試規格

### 6.1 測試套件

| 測試文件 | 測試數 | 覆蓋模塊 |
|----------|--------|----------|
| `test_profiles.py` | 25 | Profile CRUD、驗證、active 切換 |
| `test_asr.py` | 10 | ASR 引擎工廠、可用性檢查 |
| `test_translation.py` | 15 | 翻譯引擎工廠、Mock、Ollama prompt 組裝、回應解析 |
| `test_glossary.py` | 28 | 術語表 CRUD、CSV 匯入/匯出、驗證 |
| `test_proofreading.py` | 8 | 翻譯取得、修改、批核 |
| `test_render_api.py` | 9 | 渲染 API、狀態查詢、下載 |
| `test_renderer.py` | 14 | ASS 生成、顏色轉換、時間格式 |
| `test_language_config.py` | 14 | 語言參數 CRUD、驗證 |
| `test_segment_utils.py` | 8 | 段落分割、句子邊界、時間分配 |
| `test_sentence_pipeline.py` | 14 | 句子合併、重分配、驗證（實驗性） |
| **合計** | **145** | |

### 6.2 運行測試

```bash
cd backend && ../backend/venv/bin/python -m pytest tests/ -v
```

---

## 7. 部署規格

### 7.1 依賴

**系統依賴：**
- Python 3.8+
- FFmpeg
- Ollama（翻譯引擎）

**Python 依賴（requirements.txt）：**
- openai-whisper / faster-whisper（ASR）
- flask / flask-socketio / flask-cors（Web 框架）
- eventlet / gevent（WebSocket 支援）
- torch / torchaudio（Whisper 模型）
- numpy（數值計算）
- pysbd（句子邊界偵測）

### 7.2 安裝及啟動

```bash
# 安裝
./setup.sh

# 安裝 Ollama + 翻譯模型
ollama pull qwen2.5:3b

# 啟動
./start.sh
# → 後端: http://localhost:5001
# → 前端: http://localhost:8080（或瀏覽器自動打開）
```

### 7.3 目錄結構（運行時）

```
backend/data/          （gitignore）
├── uploads/           上傳嘅媒體文件
├── results/           渲染輸出文件
└── registry.json      文件 registry（持久化）
```
