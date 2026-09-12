# 助人技巧訓練 Agent

本專案是一套以 Streamlit 與 Gemini 建置的助人技巧教學模擬系統。學生可先以個案角色體驗 AI 示範，也可擔任助人者，依探索、洞察、行動三階段和虛構標準化個案演練。系統會把使用時間、次數、完整逐輪對話及晤談後形成性回饋寫入 Google Sheets。

本系統只供教學演練，不提供心理治療、診斷或緊急危機服務。

## 第一版已完成的功能

- 體驗模式：學生當個案，AI 示範助人者；過程不顯示技巧標籤。
- 實作模式：學生當助人者，AI 扮演四種虛構標準化個案。
- 完整三階段或單一階段練習。
- 依介入品質漸進式揭露個案資訊。
- 對話生成與晤談後評量使用兩次獨立模型呼叫。
- 每位學生自行輸入自己的 Gemini API Key；Key 不寫入 Google Sheets、逐字稿或評量紀錄。
- Google Sheets 自動建立 Sessions、ChatLogs、SkillEvents、Assessments 四張工作表。
- 紀錄匿名代碼、使用次數、起訖時間、秒數、階段、模型、Prompt 版本與完整逐字稿。
- 教師後台查看與下載四類 CSV。
- 明確第一人稱即時危機語句的最低限度安全攔截。
- GitHub Actions 自動執行語法檢查與離線測試。

## 專案結構

```text
helping-skills-agent/
├─ app.py                         學生端主程式
├─ pages/1_教師後台.py            教師端資料檢視與匯出
├─ src/                           案例、Prompt、Gemini、Sheets 與安全模組
├─ tests/                         不需 API Key 的離線測試
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
3. 暫時不必自行建立欄位；程式首次連線時會自動新增四個工作表及第一列欄名。
4. 複製網址中 `/d/` 與 `/edit` 之間的字串，這就是 `SPREADSHEET_ID`。

範例：

```text
https://docs.google.com/spreadsheets/d/這一段就是SPREADSHEET_ID/edit
```

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

服務帳戶原本無法存取任何私人試算表；必須把指定試算表分享給服務帳戶。官方參考：[Google Cloud 建立服務帳戶](https://cloud.google.com/iam/docs/service-accounts-create)、[gspread Service Account 驗證](https://docs.gspread.org/en/latest/oauth2.html)

## 步驟四 學生各自取得 Gemini API Key

1. 每位學生使用自己的 Google 帳號進入 [Google AI Studio API Keys](https://aistudio.google.com/app/apikey)。
2. 建立或選擇自己的專案，按 `Create API key`。
3. 複製自己的 API Key；上課進入本系統時，貼入「Gemini API Key」密碼欄位。
4. API Key 只暫存在該次 Streamlit session，用來呼叫 Gemini；同一位學生在自己的筆電開始下一段練習時可沿用，不必重複輸入。系統不會把 Key 寫入 Google Sheets、Sessions、ChatLogs、Assessments 或下載逐字稿。
5. 學生不得把 API Key 傳給其他同學；若懷疑 Key 外洩，應立即到 Google AI Studio / Google Cloud 撤銷並重新建立。

模型名稱仍由教師端統一設定，以維持研究條件一致。本版預設 `gemini-3.8-flash`；若該模型不可用，可在 Streamlit Secrets 調整 `MODEL_NAME` 與 `EVALUATOR_MODEL_NAME`。官方參考：[Gemini API Getting started](https://ai.google.dev/gemini-api/docs/get-started)、[Interactions API](https://ai.google.dev/gemini-api/docs/interactions-overview)

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

1. 到 [Streamlit Community Cloud](https://share.streamlit.io/) 登入並連接 GitHub。
2. 按 `Create app`。
3. Repository 選擇 `你的GitHub帳號/helping-skills-agent`。
4. Branch 選 `main`。
5. Main file path 填 `app.py`。
6. 開啟 `Advanced settings` → `Secrets`。
7. 把步驟五完成的 TOML 貼入 Secrets，按儲存；不要加入教師共用的 `GEMINI_API_KEY` 或 `GEMINI_API_KEYS`。
8. 按 `Deploy`，等待套件安裝與網站啟動。

Streamlit 官方說明指出，部署時應在 Advanced settings 儲存 Secrets，不應把未加密密鑰提交到 Git Repository：[部署應用程式](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app)、[Secrets management](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/secrets-management)

## 步驟七 第一次驗收

1. 開啟部署後的網址。
2. 左側在尚未輸入學生 Key 前應顯示 `Gemini：請由學生輸入自己的 API Key`，且 `Google Sheets：已連線`。
3. 使用匿名代碼 `TEST001`，並輸入測試者自己的 Gemini API Key，開始一段「實作模式」。
4. 至少輸入兩輪，按 `結束並查看回饋`。
5. 回到 Google 試算表，應看到以下工作表：
   - `Sessions`：一列 Session，包含開始、結束、秒數及完成狀態。
   - `ChatLogs`：每一輪學生、AI 與系統訊息各一列。
   - `SkillEvents`：評量模型辨識到的技巧證據。
   - `Assessments`：原始 JSON、解析結果、回饋與版本。
6. 從 Streamlit 左側頁面導覽進入 `教師後台`，用 `ADMIN_PASSWORD` 登入。
7. 確認四張表均能顯示並下載 CSV。
8. 測試完成後，可在試算表刪除 `TEST001` 的測試列。

## 常見錯誤

| 畫面或錯誤 | 最常見原因 | 處理方式 |
| --- | --- | --- |
| Google Sheets 尚未連線 | 試算表 ID 或服務帳戶 JSON 錯誤 | 重新核對 Secrets，不要貼入多餘符號 |
| `SpreadsheetNotFound` | 試算表未分享給服務帳戶 | 將 JSON 的 `client_email` 加為該試算表編輯者 |
| Secrets 出現 TOML 錯誤 | JSON 外層引號或換行被改動 | 使用三個單引號包住完整 JSON |
| Gemini API 呼叫失敗 | 學生 Key 無效、模型不可用或該學生配額已滿 | 請該學生檢查自己的 AI Studio API Key 與用量；不要改用教師共用 Key |
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

- 學生需輸入教師分配的 `participant_id` 與自己的 Gemini API Key；API Key 只用於當次模型呼叫，不得寫入研究資料。姓名、Email 與對照表應另存於權限更嚴格的位置。
- Google Sheets 保存完整原始逐字稿；不應只留摘要。
- `raw_model_output` 與 `parsed_json` 分開保存，重新評量時新增新列，不覆蓋舊結果。
- 正式研究前應固定 `model_name`、`prompt_version`、`rubric_version` 與 temperature，並記錄改版日期。
- AI 技巧辨識與回饋目前屬形成性、探索性用途；未完成專家一致性與效度檢驗前，不應直接當作正式成績。
- 本版危機攔截只是最低限度規則，不是臨床風險評估。正式上課前仍需建立教師通報、緊急聯絡與資料治理流程。
- 若蒐集內容將用於研究，須依研究倫理審查、告知同意、保存期限、存取權限與資料刪除規則執行。

## 下一階段建議

1. 由授課教師實際跑完體驗與實作模式，修訂四個標準化個案與 Prompt。
2. 加入學生白名單及一次性 Email OTP。
3. 建立技巧判定的專家標註資料與 AI／專家一致性驗證。
4. 增加教師設定頁，控制開放期間、每人使用上限、可選模式與案例。
5. 若正式樣本量與使用頻率提高，評估把主要資料庫改為 Supabase、Firestore 或 PostgreSQL，Google Sheets 保留為教師查閱與匯出介面。
