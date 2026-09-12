# 助人技巧訓練 Agent

本專案是一套以 Streamlit 與 Gemini 建置的助人技巧教學模擬系統。學生可先以個案角色體驗 AI 示範，也可擔任助人者，依探索、洞察、行動三階段和虛構標準化個案演練。系統會把使用時間、次數、完整逐輪對話及晤談後形成性回饋寫入 Google Sheets。體驗模式另支援跨日續談：學生不必下載再上傳逐字稿，系統以匿名學習者代碼與續談 PIN 驗證後，自動載入前次去識別摘要與最後數輪脈絡。

本系統只供教學演練，不提供心理治療、診斷或緊急危機服務。

## 已完成的功能

- 體驗模式：學生當個案，AI 示範助人者；過程不顯示技巧標籤。
- 體驗模式跨日續談：相同匿名學習者代碼＋6 位 PIN 可接續最近一次已完成談話。
- 續談時每次仍建立新的 `session_id`，但沿用同一 `conversation_id`，方便縱貫研究。
- 系統只把前次摘要、尚未談完重點與最後數輪送給 Gemini，不把整份歷史逐字稿反覆塞入模型。
- 實作模式：學生當助人者，AI 扮演四種虛構標準化個案。
- 完整三階段或單一階段練習。
- 依介入品質漸進式揭露個案資訊。
- 對話生成與晤談後評量使用兩次獨立模型呼叫。
- 每位學生自行輸入自己的 Gemini API Key；Key 不寫入 Google Sheets、逐字稿或評量紀錄。
- Google Sheets 自動建立 `Sessions`、`ChatLogs`、`SkillEvents`、`Assessments`、`ContinuityMemory` 五張工作表。
- 紀錄匿名代碼、使用次數、起訖時間、秒數、階段、模型、Prompt 版本與完整逐字稿。
- 教師後台查看與下載五類 CSV。
- 明確第一人稱即時危機語句的最低限度安全攔截。
- GitHub Actions 自動執行語法檢查與離線測試。

## 專案結構

```text
helping-skills-agent/
├─ app.py                         學生端主程式
├─ pages/1_教師後台.py            教師端資料檢視與匯出
├─ src/
│  ├─ continuity.py              續談 PIN 雜湊與跨次記憶工具
│  ├─ sheets_store.py            Google Sheets 持久化與續談查詢
│  ├─ prompts.py                 對話、續談 context 與評量 Prompt
│  └─ ...
├─ tests/                         不需 API Key 的離線測試
├─ DATA_DICTIONARY.md             五張資料表欄位定義
├─ .streamlit/config.toml         介面設定
├─ .streamlit/secrets.toml.example Secrets 範例，不能放真實密鑰
├─ .github/workflows/ci.yml       GitHub 自動測試
└─ requirements.txt              部署所需套件
```

## 步驟一 建立 GitHub Repository

1. 登入 [GitHub](https://github.com/)。
2. 右上角按 `+`，選擇 `New repository`。
3. Repository name 建議填入 `helping-skills-agent`。
4. 第一階段測試建議選 `Private`。
5. 不要勾選新增 README、`.gitignore` 或 License，因下載的專案中已經包含。
6. 按 `Create repository`。
7. 解壓縮本專案 ZIP；進入解壓後的 `helping-skills-agent` 資料夾。
8. 在空白 Repository 頁面按 `uploading an existing file`，把資料夾內的所有檔案與子資料夾拖入。
9. Commit message 填入 `Initial helping skills agent MVP`，按 `Commit changes`。
10. 確認 GitHub 上看得到 `app.py`、`src`、`pages`、`.streamlit` 和 `requirements.txt`。

GitHub 官方步驟：[Creating a new repository](https://docs.github.com/en/repositories/creating-and-managing-repositories/creating-a-new-repository)

## 步驟二 建立 Google 試算表

1. 到 [Google Sheets](https://sheets.google.com/) 建立一份空白試算表。
2. 名稱可設為 `115-1助人技巧Agent研究資料`。
3. 暫時不必自行建立欄位；程式首次連線時會自動建立五個工作表及第一列欄名。
4. 複製網址中 `/d/` 與 `/edit` 之間的字串，這就是 `SPREADSHEET_ID`。

```text
https://docs.google.com/spreadsheets/d/這一段就是SPREADSHEET_ID/edit
```

五張表的用途：

- `Sessions`：每一次獨立練習／晤談。
- `ChatLogs`：完整逐輪原始內容。
- `SkillEvents`：形成性評量辨識到的技巧事件。
- `Assessments`：形成性回饋與原始／解析 JSON。
- `ContinuityMemory`：體驗模式跨日續談所需的去識別摘要、未竟重點、最後數輪與 PIN hash。

詳細欄位請見 `DATA_DICTIONARY.md`。

## 步驟三 建立 Google Cloud 服務帳戶

1. 進入 [Google Cloud Console](https://console.cloud.google.com/)。
2. 上方選擇專案，按 `New Project`，名稱可填 `helping-skills-agent`。
3. 左上選單進入 `APIs & Services` → `Library`。
4. 搜尋並啟用 `Google Sheets API`。
5. 再搜尋並啟用 `Google Drive API`。
6. 進入 `IAM & Admin` → `Service Accounts`。
7. 按 `Create service account`，名稱可填 `helping-skills-sheets`。
8. 這個用途不需要授予整個 Google Cloud 專案的 Editor 或 Owner；可直接按 `Done`。
9. 點進剛建立的服務帳戶，進入 `Keys`。
10. 按 `Add key` → `Create new key` → 選 `JSON` → `Create`。
11. 瀏覽器會下載一個 JSON 憑證檔。這是私密金鑰，不可上傳 GitHub、寄給學生或放在公開雲端。
12. 用記事本開啟 JSON，複製其中 `client_email` 的完整地址。
13. 回到步驟二的 Google 試算表，按 `共用`，把 `client_email` 加為 `編輯者`。

服務帳戶原本無法存取任何私人試算表；必須把指定試算表分享給服務帳戶。

## 步驟四 學生各自取得 Gemini API Key

1. 每位學生使用自己的 Google 帳號進入 Google AI Studio API Keys。
2. 建立或選擇自己的專案，按 `Create API key`。
3. 複製自己的 API Key；上課進入本系統時，貼入「Gemini API Key」密碼欄位。
4. API Key 只暫存在該次 Streamlit session，用來呼叫 Gemini；同一位學生在自己的筆電開始下一段練習時可沿用。系統不會把 Key 寫入任何 Google Sheets 工作表或下載逐字稿。
5. 學生不得把 API Key 傳給其他同學；若懷疑 Key 外洩，應立即撤銷並重新建立。

模型名稱仍由教師端統一設定，以維持研究條件一致。本版預設 `gemini-3.8-flash`。

## 體驗模式的跨日續談

第一次使用體驗模式時，學生除了匿名學習者代碼外，需自行設定一組 **6 位數續談 PIN**。請記住此 PIN；系統不保存 PIN 原文，只保存 PBKDF2 雜湊摘要。

第一次：

```text
匿名學習者代碼：P001
續談 PIN：******
→ 選「開始新的談話」
→ 完成談話
→ 按「結束並查看回饋」
→ 系統建立 ContinuityMemory
```

下次：

```text
匿名學習者代碼：P001
相同續談 PIN：******
→ 選「繼續上次談話」
→ 系統讀取 P001 最新一筆續談記憶
→ Agent 自然承接前次議題
```

注意：

- 只有按下「結束並查看回饋」後，才會建立完整的下次續談記憶。
- 學生不需要下載或重新上傳逐字稿。
- 若形成性評量 API 失敗，系統仍會以 `fallback` 狀態保存前次最後數輪，避免完全失去續談脈絡。
- 續談只支援 `experience` 體驗模式；`practice` 標準化個案模式仍以每次獨立演練為主。
- 危機規則造成 `safety_ended` 時，不建立一般續談記憶。

## 步驟五 準備 Streamlit Secrets

開啟 `.streamlit/secrets.toml.example`，依下列原則換成真實值：

```toml
# Gemini API Key 不放在教師端 Secrets；由每位學生自行輸入。
MODEL_NAME = "gemini-3.8-flash"
EVALUATOR_MODEL_NAME = "gemini-3.8-flash"
DIALOGUE_TEMPERATURE = 0.35
EVALUATOR_TEMPERATURE = 0.0

SPREADSHEET_ID = "你的試算表ID"
REQUIRE_SHEETS = true
COURSE_ACCESS_CODE = "課程成員共用通行碼"
ADMIN_PASSWORD = "至少16字元且只有教師知道的密碼"

GOOGLE_SERVICE_ACCOUNT_JSON = '''
把下載的服務帳戶 JSON 全部原封不動貼在這裡
'''
```

注意：

- `GOOGLE_SERVICE_ACCOUNT_JSON` 外層是三個單引號，不是雙引號。
- JSON 中的 `\n` 必須保留，不要手動改成真正換行。
- 不要把真實內容另存成 GitHub 裡的 `secrets.toml`。
- `.gitignore` 已排除 `.streamlit/secrets.toml` 與常見憑證 JSON，但仍要在 Commit 前人工確認。

## 步驟六 部署到 Streamlit Community Cloud

1. 到 Streamlit Community Cloud 登入並連接 GitHub。
2. 按 `Create app`。
3. Repository 選擇 `你的GitHub帳號/helping-skills-agent`。
4. Branch 選 `main`。
5. Main file path 填 `app.py`。
6. 開啟 `Advanced settings` → `Secrets`。
7. 把步驟五完成的 TOML 貼入 Secrets，按儲存；不要加入教師共用的 `GEMINI_API_KEY` 或 `GEMINI_API_KEYS`。
8. 按 `Deploy`，等待套件安裝與網站啟動。

## 步驟七 第一次驗收

先驗證一般功能：

1. 開啟部署後的網址。
2. 左側在尚未輸入學生 Key 前應顯示 `Gemini：請由學生輸入自己的 API Key`，且 `Google Sheets：已連線`。
3. 使用匿名代碼 `TEST001` 與測試者自己的 Gemini API Key。
4. 實作模式至少輸入兩輪，按 `結束並查看回饋`。
5. 確認 `Sessions`、`ChatLogs`、`SkillEvents`、`Assessments` 有資料。

再驗證續談：

1. 用 `TESTCONT001` 進入體驗模式，設定一組只有測試者知道的 6 位 PIN，選「開始新的談話」。
2. 至少談 2–3 輪後按 `結束並查看回饋`。
3. Google Sheets 應出現 `ContinuityMemory`，且新增一列；`pin_hash` 不應等於原始 6 位 PIN。
4. 按「開始另一段練習」，再次輸入 `TESTCONT001` 與相同 PIN，選「繼續上次談話」。
5. Agent 的第一句應自然承接前次內容，而不是重新要求完整介紹困擾。
6. 第二次結束後，`ContinuityMemory` 應新增第二列；兩列 `conversation_id` 相同、`session_id` 不同、`session_number` 應由 1 變 2。
7. 用錯誤 PIN 測試一次，系統應拒絕讀取前次內容。

教師後台會依 `SHEET_HEADERS` 自動顯示五個分頁並可下載 CSV。

## 常見錯誤

| 畫面或錯誤 | 最常見原因 | 處理方式 |
| --- | --- | --- |
| Google Sheets 尚未連線 | 試算表 ID 或服務帳戶 JSON 錯誤 | 重新核對 Secrets，不要貼入多餘符號 |
| `SpreadsheetNotFound` | 試算表未分享給服務帳戶 | 將 JSON 的 `client_email` 加為該試算表編輯者 |
| Secrets 出現 TOML 錯誤 | JSON 外層引號或換行被改動 | 使用三個單引號包住完整 JSON |
| Gemini API 呼叫失敗 | 學生 Key 無效、模型不可用或該學生配額已滿 | 請該學生檢查自己的 AI Studio API Key 與用量 |
| 找不到續談紀錄 | 前次未按「結束並查看回饋」，或該代碼尚無 ContinuityMemory | 先開始新的談話並正常結束一次 |
| 續談 PIN 不正確 | 輸入的 PIN 與該匿名代碼首次設定不同 | 使用原 PIN；教師不會在後台看到 PIN 原文 |
| 工作表第一列欄位不一致 | 曾人工改名、刪欄或使用舊版 Schema | 先備份資料；不要直接讓新版程式覆寫舊欄位 |
| 教師後台停用 | 未設定 `ADMIN_PASSWORD` | 在 Streamlit App settings 的 Secrets 補上密碼 |

## 本機測試 選用

電腦已安裝 Python 3.12 時，可執行：

```bash
python -m venv .venv
```

Windows PowerShell：

```powershell
.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
Copy-Item .streamlit\secrets.toml.example .streamlit\secrets.toml
streamlit run app.py
```

測試程式：

```powershell
pytest -q
```

## 研究與倫理注意事項

- 學生需輸入教師分配的 `participant_id` 與自己的 Gemini API Key；API Key 只用於模型呼叫，不得寫入研究資料。
- `ContinuityMemory` 是研究資料的一部分，雖已使用匿名代碼，仍應比照逐字稿管理存取權限與保存期限。
- 續談 PIN 原文不得寫入 Google Sheets、Log 或逐字稿；目前只保存 PBKDF2 hash。
- Google Sheets 保存完整原始逐字稿；不應只留摘要。
- `raw_model_output` 與 `parsed_json` 分開保存，重新評量時新增新列，不覆蓋舊結果。
- 正式研究前應固定 `model_name`、`prompt_version`、`rubric_version` 與模型設定，並記錄改版日期。
- AI 技巧辨識與回饋目前屬形成性、探索性用途；未完成專家一致性與效度檢驗前，不應直接當作正式成績。
- 本版危機攔截只是最低限度規則，不是臨床風險評估。正式上課前仍需建立教師通報、緊急聯絡與資料治理流程。
- 若蒐集內容將用於研究，須依研究倫理審查、告知同意、保存期限、存取權限與資料刪除規則執行。

## 下一階段建議

1. 由授課教師實際跑完「首次談話 → 結束 → 跨日續談」流程，檢查續談摘要是否自然且沒有多加未述事實。
2. 建立技巧判定的專家標註資料與 AI／專家一致性驗證。
3. 增加教師設定頁，控制開放期間、每人使用上限、可選模式與案例。
4. 若正式樣本量與使用頻率提高，評估把主要資料庫改為 Supabase、Firestore 或 PostgreSQL，Google Sheets 保留為教師查閱與匯出介面。
