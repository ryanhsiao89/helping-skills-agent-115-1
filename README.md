# 助人技巧訓練 Agent

本專案是一套以 Streamlit 與 Gemini 建置的助人技巧教學模擬系統。學生可先以個案角色體驗 AI 示範，也可擔任助人者，依探索、洞察、行動三階段與虛構標準化個案演練。系統會把使用時間、次數、完整逐輪對話與晤談後形成性回饋寫入 Google Sheets。

新版加入「學校 Email＋一次性驗證碼（OTP）」登入。教師可藉由學校 Email 辨識學生身分；研究與逐字資料則以系統產生的 `participant_id` 串接。體驗模式另支援跨日續談：學生不必重新上傳逐字稿，系統會在同一已驗證學生身分下，自動載入最近一次有保留的去識別摘要與最後數輪脈絡。

學生完成練習後仍可自由下載本次逐字稿，帶回家重新閱讀、自我反思與持續學習。

本系統只供教學演練，不提供心理治療、診斷或緊急危機服務。

## 已完成的功能

- 學校 Email OTP 身分驗證：6 位數驗證碼、10 分鐘有效、60 秒重送冷卻、最多 5 次錯誤嘗試。
- 僅接受教師在 Secrets 指定的學校 Email 網域。
- `StudentRoster` 保存 `school_email ↔ participant_id` 對照，方便教師辨識學生與追蹤平時練習。
- OTP 不寫入 Google Sheets、逐字稿或 log。
- 體驗模式：學生當個案，AI 示範助人者；過程不顯示技巧標籤。
- 體驗模式跨日續談：完成相同學校 Email 的 OTP 驗證後，可接續最近一次有保留的談話。
- 新談話預設不建立續談記憶；只有勾選「我希望保留本次談話供下次續談」才保存。
- 續談每次仍建立新的 `session_id`，但沿用同一 `conversation_id`，方便縱貫分析。
- 續談只把前次摘要、尚未談完重點與最後數輪送給 Gemini，不反覆塞入整份歷史逐字稿。
- 實作模式：學生當助人者，AI 扮演虛構標準化個案。
- 完整三階段或單一階段練習。
- 對話生成與晤談後評量使用獨立模型呼叫。
- 每位學生自行輸入自己的 Gemini API Key；Key 不寫入 Google Sheets、逐字稿或評量紀錄。
- 完整逐字稿下載：學生可自行保存本次 `.txt` 逐字稿供課後反思。
- 教師後台查看與下載各資料表 CSV。
- 明確第一人稱即時危機語句的最低限度安全攔截。
- GitHub Actions 自動執行語法檢查與離線測試。

## Google Sheets 資料表

程式會自動建立六張工作表：

- `Sessions`：每一次獨立練習／晤談。
- `ChatLogs`：完整逐輪原始內容。
- `SkillEvents`：形成性評量辨識到的技巧事件。
- `Assessments`：形成性回饋與原始／解析 JSON。
- `ContinuityMemory`：跨日續談所需的去識別摘要、未竟重點與最後數輪。
- `StudentRoster`：已驗證學校 Email 與系統 `participant_id` 的對照。

詳細欄位見 `DATA_DICTIONARY.md`。

## 學生使用流程

### 1. 學校 Email OTP 驗證

學生先輸入學校 Email：

```text
student@school.edu.tw
→ 寄送驗證碼
→ 收到 6 位數 OTP
→ 驗證成功
→ 系統自動辨識／建立 participant_id
```

同一瀏覽器 session 驗證成功後，開始下一段練習不需要再次收 OTP；重新開啟瀏覽器或之後再回來時，重新驗證即可。

### 2. 輸入自己的 Gemini API Key

Gemini API Key 由學生自己準備，只暫存在目前 Streamlit session，不寫入研究資料。

### 3. 新談話與續談

體驗模式開始新談話時：

```text
● 開始新的談話
□ 我希望保留本次談話供下次續談
```

不勾選：本次照常練習，但不建立跨日記憶。

勾選：按下「結束並查看回饋」後，系統建立 `ContinuityMemory`。

下次同一位學生完成學校 Email OTP 驗證後，可選：

```text
○ 繼續上次談話
```

系統會依該學生的 `participant_id` 找到最新一筆已保留續談記憶，自然承接前次內容。

### 4. 下載逐字稿

每段練習結束後都保留：

```text
下載本次逐字稿（選用；可供課後自我反思）
```

學生可下載回家重新審視自己的對話。續談本身不需要把逐字稿重新上傳給 Agent。

## Streamlit Secrets

Gemini API Key 不放在教師端 Secrets；由每位學生自行輸入。

請依 `.streamlit/secrets.toml.example` 設定：

```toml
MODEL_NAME = "gemini-3.8-flash"
EVALUATOR_MODEL_NAME = "gemini-3.8-flash"
DIALOGUE_TEMPERATURE = 0.35
EVALUATOR_TEMPERATURE = 0.0

SPREADSHEET_ID = "你的試算表ID"
REQUIRE_SHEETS = true
COURSE_ACCESS_CODE = "課程成員共用通行碼"
ADMIN_PASSWORD = "至少16字元且只有教師知道的密碼"

MAX_HISTORY_CHARS = 12000
MAX_USER_INPUT_CHARS = 800

# 改成實際允許的學校 Email 網域。
SCHOOL_EMAIL_DOMAINS = ["你的學校網域.edu.tw"]
OTP_TTL_SECONDS = 600
OTP_RESEND_SECONDS = 60
OTP_MAX_ATTEMPTS = 5

[email]
# 可沿用舊版 Agent 已使用的 Gmail SMTP 寄件帳號與 Google App Password。
sender = "你的寄件Gmail@gmail.com"
password = "你的Google App Password"
smtp_host = "smtp.gmail.com"
smtp_port = 465

GOOGLE_SERVICE_ACCOUNT_JSON = '''
把下載的服務帳戶 JSON 全部原封不動貼在這裡
'''
```

注意：

- `email.password` 應使用 Google App Password，不要把一般 Gmail 密碼寫入程式碼。
- 真實 Secrets 只放在 Streamlit Community Cloud 的 App settings，不可 commit 到 GitHub。
- `SCHOOL_EMAIL_DOMAINS` 可放一個或多個允許網域，例如 `["school.edu.tw", "student.school.edu.tw"]`。
- OTP 只存在目前 Streamlit session 的雜湊狀態，驗證成功後立即失效。
- `GOOGLE_SERVICE_ACCOUNT_JSON` 外層使用三個單引號；JSON 內的 `\n` 要保留。

## Google Cloud / Google Sheets 設定

1. 建立 Google Sheet，複製網址 `/d/` 與 `/edit` 之間的 `SPREADSHEET_ID`。
2. 在 Google Cloud 啟用 Google Sheets API 與 Google Drive API。
3. 建立 Service Account 並下載 JSON Key。
4. 把 Google Sheet 分享給該 Service Account 的 `client_email`，權限設為編輯者。
5. 將完整 JSON 貼入 Streamlit Secrets 的 `GOOGLE_SERVICE_ACCOUNT_JSON`。

首次正常啟動後，程式會自行建立缺少的工作表；不要手動修改既有工作表的第一列欄名。

## 第一次驗收

部署更新後，建議依序測試：

1. 首頁應先要求「學校 Email 身分驗證」。
2. 非允許網域的 Email 應被拒絕。
3. 正確學校 Email 可收到 6 位 OTP。
4. OTP 驗證成功後，Google Sheet 應出現 `StudentRoster`，並新增該 Email 與 `participant_id`。
5. 輸入學生自己的 Gemini API Key，跑一段體驗模式或實作模式。
6. 結束後確認 `Sessions`、`ChatLogs`、`Assessments` 等資料正常寫入。
7. 確認畫面仍有逐字稿下載按鈕。
8. 體驗模式另測一次：開始新談話並勾選保留 → 結束 → 開始另一段 → 選「繼續上次談話」，確認 Agent 能承接前次內容。
9. 確認 `ContinuityMemory.pin_hash` 在 Email OTP 版保持空白；這是舊版相容欄位。
10. 教師後台應可看到 `StudentRoster` 與其他研究資料表。

## 專案結構

```text
helping-skills-agent/
├─ app.py                         學生端主程式、OTP 登入與練習流程
├─ pages/1_教師後台.py            教師端資料檢視與匯出
├─ src/
│  ├─ email_otp.py               學校 Email、OTP、Gmail SMTP 工具
│  ├─ continuity.py              跨次記憶整理
│  ├─ sheets_store.py            Google Sheets 持久化、StudentRoster 與續談查詢
│  ├─ prompts.py                 對話、續談 context 與評量 Prompt
│  └─ ...
├─ tests/                         不需 API Key 的離線測試
├─ DATA_DICTIONARY.md             資料表欄位定義
├─ .streamlit/secrets.toml.example Secrets 範例，不能放真實密鑰
└─ .github/workflows/ci.yml       GitHub 自動測試
```

## 研究與資料治理注意事項

- `StudentRoster` 含可辨識的學校 Email，教師後台與 Google Sheet 權限應限制於研究／授課團隊。
- Email 不重複寫入每一筆 `ChatLogs`；研究與逐字資料以 `participant_id` 串接。
- Google Sheets 保存完整原始逐字稿；下載逐字稿則由學生自行決定是否保存於個人裝置。
- `raw_model_output` 與 `parsed_json` 分開保存，重新評量時新增新列，不覆蓋舊結果。
- 正式研究前應固定 `model_name`、`prompt_version`、`rubric_version` 與 temperature，並記錄改版日期。
- AI 技巧辨識與回饋屬形成性、探索性用途；若作為正式成績指標，應另建立清楚的課程評分規準與人工覆核原則。
