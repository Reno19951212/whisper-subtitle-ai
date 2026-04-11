# Profile CRUD UI — Design Spec

**Date:** 2026-04-11  
**Feature:** Frontend Profile Management (Create / Edit / Delete)  
**Scope:** `frontend/index.html` sidebar Profile panel

---

## 1. Overview

The backend fully implements profile CRUD (`POST`, `PATCH`, `DELETE /api/profiles`), but the frontend only exposes profile activation. This spec defines the UI to expose all profile management operations directly within the existing sidebar.

---

## 2. Layout & Components

The existing Profile panel (collapsible sidebar section) is extended into a full management panel.

```
[ Profiles ▼ ]                         ← collapsible panel header (unchanged)

  [+ New Profile]                       ← button at top of panel

  ● Development          [Edit] [Del]   ← active profile (green dot)
  
    Production           [Edit] [Del]
    ▼ inline edit form (expanded)
    ┌─────────────────────────────────┐
    │ 基本資訊 ▼                       │  ← expanded by default
    │   Name: ________________        │
    │   Desc: ________________        │
    ├─────────────────────────────────┤
    │ ASR 設定 ▶                       │  ← collapsed by default
    ├─────────────────────────────────┤
    │ 翻譯設定 ▶                       │  ← collapsed by default
    ├─────────────────────────────────┤
    │ 字型設定 ▶                       │  ← collapsed by default
    ├─────────────────────────────────┤
    │ [Save]              [Cancel]    │
    └─────────────────────────────────┘

  Custom Profile         [Edit] [Del]
```

### Behaviour Rules

- Only one profile can have its edit form expanded at a time. Opening another collapses the current one.
- Clicking **[+ New Profile]** inserts a blank expanded card at the top of the list.
- The active profile's **[Del]** button is disabled with a tooltip: "請先切換至其他 Profile".
- Delete triggers `confirm('確定刪除 Profile「{name}」？')` before calling the API.
- Profile activation (click on profile name row) is unchanged from current behaviour.

---

## 3. Data Flow & State

### API Calls

| Action | API Call |
|--------|----------|
| Page load | `GET /api/profiles` + `GET /api/profiles/active` |
| Click Edit | Fill form from local list data (no extra fetch) |
| Save (create) | `POST /api/profiles { name, description, asr, translation, font }` |
| Save (update) | `PATCH /api/profiles/<id> { ...changed fields }` |
| Delete (confirmed) | `DELETE /api/profiles/<id>` |
| After any mutation | Re-fetch `GET /api/profiles` to refresh list |

### JS State Variables

```js
let profiles = []           // full profiles list
let activeProfileId = null  // currently active profile id
let editingProfileId = null // profile id whose form is expanded (null = none)
let isCreating = false      // true when [+ New Profile] form is open
```

### Update Strategy

Re-fetch the full profile list after every successful mutation. No optimistic local updates. Buttons show loading state during API calls to prevent duplicate submissions.

---

## 4. Form Fields

Four collapsible sections. Only **基本資訊** is expanded by default.

### 基本資訊

| Field | Type | Validation |
|-------|------|------------|
| Name | text input | Required, non-empty |
| Description | textarea | Optional |

### ASR 設定

| Field | Type | Options |
|-------|------|---------|
| Engine | select | `whisper` / `qwen3` / `flg` |
| Model Size | select | `tiny` / `base` / `small` / `medium` / `large` |
| Language | text input | Default: `en` |
| Language Config ID | text input | Default: `en` |
| Device | select | `auto` / `cpu` / `cuda` / `mps` |

### 翻譯設定

| Field | Type | Options / Validation |
|-------|------|----------------------|
| Engine | select | `ollama` / `mock` |
| Style | select | `formal` / `colloquial` |
| Temperature | number input | 0.0–1.0, step 0.1 |
| Glossary | select | Dynamically loaded from `GET /api/glossaries`; includes "無" option |

### 字型設定

| Field | Type | Validation |
|-------|------|------------|
| Font Family | text input | Default: `Noto Sans TC` |
| Font Size | number input | Integer 12–120 |
| Color | color picker | Hex, default `#FFFFFF` |
| Outline Color | color picker | Hex, default `#000000` |
| Outline Width | number input | Integer 0–10 |
| Position | select | `bottom` / `top` |
| Margin Bottom | number input | Integer 0–200 |

---

## 5. Error Handling

| Scenario | Handling |
|----------|----------|
| Delete active profile | `[Del]` disabled; hover tooltip shown |
| Backend validation error | Toast showing error message from API response |
| Network error / 500 | Toast: "操作失敗，請重試" |
| Delete confirmation | `confirm('確定刪除 Profile「{name}」？')` |
| Duplicate submission | Button disabled + loading spinner during API call |
| Last profile deleted | Allowed (active protection is sufficient guard) |

---

## 6. Files Changed

- `frontend/index.html` — extend existing Profile sidebar panel

No new files. No backend changes required.
