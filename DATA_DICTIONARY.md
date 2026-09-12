# 助人技巧 Agent 資料字典

## Sessions

每一列代表一次練習。Session 開始時先寫入 `in_progress`，按下結束後更新同一列。

| 欄位 | 意義 |
| --- | --- |
| session_id | UUID，四張表的主要串接鍵 |
| participant_id | 教師分配的匿名學習者代碼 |
| agent_type | 固定為 helping |
| mode | experience 或 practice |
| started_at、ended_at | Asia/Taipei ISO 8601 時戳 |
| duration_seconds | 實際起訖秒數 |
| duration_target_min | 學生選擇的建議練習分鐘數 |
| case_id | 標準化案例或體驗主題代碼 |
| stage_start、stage_end | 起始與結束階段 |
| model_name | 對話模型版本 |
| prompt_version | 對話 Prompt 版本 |
| completion_status | in_progress、completed、completed_evaluation_error 或 safety_ended |
| message_count | 本次保存的訊息總數 |
| crisis_flag | 是否觸發最低限度危機攔截 |

## ChatLogs

每一列是一則原始訊息；`content_raw` 不因日後重新評量而改寫。

| 欄位 | 意義 |
| --- | --- |
| turn_id | 每輪 UUID |
| session_id | 對應 Sessions |
| turn_index | 從 0 開始的對話順序 |
| speaker_role | student_client、student_counselor、ai_client、ai_counselor 或 system |
| content_raw | 原始文字 |
| timestamp | 該輪時間 |
| stage_at_turn | 該輪所處階段 |
| latency_ms | AI 回應耗時；學生與系統訊息通常空白 |
| error_flag | model_error、immediate_crisis_rule 等異常標記 |
| model_name、prompt_version | 產生該輪時的技術版本 |

## SkillEvents

晤談後評量辨識到的每一項技巧證據各占一列。相同一句可有多個技巧標籤。

| 欄位 | 意義 |
| --- | --- |
| skill_event_id | 技巧事件 UUID |
| assessment_id | 對應 Assessments |
| technique、category | 技巧名稱與探索／洞察／行動分類 |
| evidence_quote | 逐字稿證據 |
| quality | 機械套用、基本恰當、自然且有助益或無法判定 |
| rationale、effect | 判定理由與下一輪可觀察效果 |
| alternative_response | 必要時提供的替代回應 |
| evaluator_model、rubric_version | 評量技術版本 |

## Assessments

每次評量新增一列，保留原始輸出與解析結果。未來重跑評量時應使用新的 `assessment_id`，不可覆寫。

| 欄位 | 意義 |
| --- | --- |
| assessment_id | 評量 UUID |
| session_id | 對應 Sessions |
| rubric_version | 評量規準版本 |
| strengths_json、improvement_points_json | 具逐字稿證據的優點與調整處 |
| quoted_examples_json | 原句及替代句 |
| next_tasks_json | 下一次 1–2 個練習任務 |
| raw_model_output | Gemini 原始 JSON 字串 |
| parsed_json | 通過 Schema 後的結構化資料 |
| evaluator_model、evaluator_temperature | 評量模型與溫度 |
| status | success 或 error |
