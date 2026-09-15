from __future__ import annotations

import hmac
import json
import time

import pandas as pd
import streamlit as st

from src.constants import SHEET_HEADERS
from src.email_otp import (
    generate_otp,
    mask_email,
    new_otp_nonce,
    normalize_email,
    otp_digest,
    otp_matches,
    send_otp_email,
)
from src.settings import load_settings
from src.sheets_store import SheetsStore, SheetsStoreError
from src.usage_time import (
    COUNSELOR_TARGET_MINUTES,
    SEMESTER_TARGET_MINUTES,
    audited_usage_summary,
)

st.set_page_config(page_title="教師後台", page_icon="📊", layout="wide")

# 教師後台 Email 授權採精確白名單，不因同網域而自動取得教師權限。
AUTHORIZED_TEACHER_EMAILS = ("plharn@hcu.edu.tw",)


@st.cache_resource(show_spinner=False)
def get_store(service_account_json: str, spreadsheet_id: str) -> SheetsStore:
    store = SheetsStore(json.loads(service_account_json), spreadsheet_id)
    store.ensure_schema()
    return store


def csv_bytes(frame: pd.DataFrame) -> bytes:
    return frame.to_csv(index=False).encode("utf-8-sig")


def build_student_usage_summary(
    roster: pd.DataFrame,
    sessions: pd.DataFrame,
    chat_logs: pd.DataFrame,
) -> pd.DataFrame:
    columns = [
        "school_email",
        "participant_id",
        "sessions_started",
        "sessions_completed",
        "counted_sessions",
        "total_minutes",
        "counselor_minutes",
        "experience_minutes",
        "remaining_total_minutes",
        "remaining_counselor_minutes",
        "requirement_met",
        "last_activity",
    ]
    if roster.empty:
        return pd.DataFrame(columns=columns)

    session_rows = sessions.to_dict("records") if not sessions.empty else []
    chat_rows = chat_logs.to_dict("records") if not chat_logs.empty else []
    records: list[dict] = []

    for _, roster_row in roster.iterrows():
        participant_id = str(roster_row.get("participant_id", "") or "").strip()
        summary = audited_usage_summary(participant_id, session_rows, chat_rows)
        participant_sessions = [
            row
            for row in session_rows
            if str(row.get("participant_id", "") or "").strip() == participant_id
        ]
        last_activity = max(
            (str(row.get("started_at", "") or "") for row in participant_sessions),
            default="",
        )
        records.append(
            {
                "school_email": str(roster_row.get("school_email", "") or ""),
                "participant_id": participant_id,
                "sessions_started": summary.started_sessions,
                "sessions_completed": summary.completed_sessions,
                "counted_sessions": summary.counted_sessions,
                "total_minutes": summary.total_minutes,
                "counselor_minutes": summary.counselor_minutes,
                "experience_minutes": summary.experience_minutes,
                "remaining_total_minutes": summary.remaining_minutes,
                "remaining_counselor_minutes": summary.remaining_counselor_minutes,
                "requirement_met": "是" if summary.semester_requirement_met else "否",
                "last_activity": last_activity,
            }
        )

    return pd.DataFrame(records, columns=columns).sort_values(
        ["school_email", "participant_id"]
    )


def init_teacher_auth_state() -> None:
    defaults = {
        "teacher_admin_ok": False,
        "teacher_auth_method": "",
        "teacher_email": "",
        "teacher_otp_sent": False,
        "teacher_pending_email": "",
        "teacher_otp_digest": "",
        "teacher_otp_nonce": "",
        "teacher_otp_expires_at": 0.0,
        "teacher_otp_last_sent_at": 0.0,
        "teacher_otp_attempts": 0,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def clear_teacher_otp(*, keep_last_sent: bool = False) -> None:
    for key, value in {
        "teacher_otp_sent": False,
        "teacher_pending_email": "",
        "teacher_otp_digest": "",
        "teacher_otp_nonce": "",
        "teacher_otp_expires_at": 0.0,
        "teacher_otp_attempts": 0,
    }.items():
        st.session_state[key] = value
    if not keep_last_sent:
        st.session_state.teacher_otp_last_sent_at = 0.0


def teacher_email_authorized(email: str) -> bool:
    normalized = normalize_email(email)
    return normalized in {normalize_email(item) for item in AUTHORIZED_TEACHER_EMAILS}


def issue_teacher_otp(settings, teacher_email: str) -> None:
    email = normalize_email(teacher_email)
    if not teacher_email_authorized(email):
        raise RuntimeError("此 Email 未被授權使用教師後台。")

    code = generate_otp()
    nonce = new_otp_nonce()
    send_otp_email(
        receiver_email=email,
        otp_code=code,
        sender_email=settings.email_sender,
        sender_password=settings.email_password,
        smtp_host=settings.smtp_host,
        smtp_port=settings.smtp_port,
    )
    sent_at = time.time()
    st.session_state.teacher_pending_email = email
    st.session_state.teacher_otp_nonce = nonce
    st.session_state.teacher_otp_digest = otp_digest(email, code, nonce)
    st.session_state.teacher_otp_expires_at = sent_at + settings.otp_ttl_seconds
    st.session_state.teacher_otp_last_sent_at = sent_at
    st.session_state.teacher_otp_attempts = 0
    st.session_state.teacher_otp_sent = True


def complete_teacher_email_login(email: str) -> None:
    normalized = normalize_email(email)
    if not teacher_email_authorized(normalized):
        raise RuntimeError("此 Email 未被授權使用教師後台。")
    st.session_state.teacher_admin_ok = True
    st.session_state.teacher_auth_method = "email_otp"
    st.session_state.teacher_email = normalized
    clear_teacher_otp(keep_last_sent=True)


def teacher_logout() -> None:
    st.session_state.teacher_admin_ok = False
    st.session_state.teacher_auth_method = ""
    st.session_state.teacher_email = ""
    clear_teacher_otp()


settings = load_settings(st.secrets)
init_teacher_auth_state()

st.title("助人技巧訓練 Agent 教師後台")
st.caption("查看學生身分對照、練習歷程與匯出研究資料；AI 回饋不等同標準化測驗成績。")

if not st.session_state.teacher_admin_ok:
    st.subheader("教師後台登入")
    email_tab, password_tab = st.tabs(["教師 Email 驗證", "管理密碼"])

    with email_tab:
        if not settings.otp_configured:
            st.error("Email OTP 尚未設定，請改用管理密碼登入或請管理者完成寄件設定。")
        elif not st.session_state.teacher_otp_sent:
            teacher_email = st.text_input(
                "教師 Email",
                placeholder="例如 teacher@hcu.edu.tw",
                key="teacher_email_input",
            ).strip()
            st.caption("只有事先列入教師白名單的 Email 才能取得後台權限。")
            if st.button(
                "寄送教師驗證碼",
                type="primary",
                use_container_width=True,
                key="send_teacher_otp",
            ):
                normalized = normalize_email(teacher_email)
                if not teacher_email_authorized(normalized):
                    st.error("此 Email 未被授權使用教師後台。")
                else:
                    try:
                        with st.spinner("正在寄送教師驗證碼……"):
                            issue_teacher_otp(settings, normalized)
                        st.rerun()
                    except RuntimeError as exc:
                        st.error(str(exc))
        else:
            email = st.session_state.teacher_pending_email
            st.success(f"教師驗證碼已寄至：{mask_email(email)}")
            st.caption(
                f"驗證碼 {max(1, settings.otp_ttl_seconds // 60)} 分鐘內有效；"
                f"最多可輸錯 {settings.otp_max_attempts} 次。"
            )
            otp_value = st.text_input(
                "6 位數教師驗證碼",
                max_chars=6,
                type="password",
                key="teacher_otp_value",
            ).strip()
            verify_col, resend_col, change_col = st.columns(3)

            if verify_col.button(
                "確認登入",
                type="primary",
                use_container_width=True,
                key="verify_teacher_otp",
            ):
                current_time = time.time()
                if current_time > float(st.session_state.teacher_otp_expires_at or 0):
                    clear_teacher_otp(keep_last_sent=True)
                    st.error("教師驗證碼已過期，請重新寄送。")
                elif st.session_state.teacher_otp_attempts >= settings.otp_max_attempts:
                    clear_teacher_otp(keep_last_sent=True)
                    st.error("驗證碼錯誤次數已達上限，請重新寄送。")
                elif otp_matches(
                    email,
                    otp_value,
                    st.session_state.teacher_otp_nonce,
                    st.session_state.teacher_otp_digest,
                ):
                    try:
                        complete_teacher_email_login(email)
                        st.rerun()
                    except RuntimeError as exc:
                        st.error(str(exc))
                else:
                    st.session_state.teacher_otp_attempts += 1
                    remaining = max(
                        0,
                        settings.otp_max_attempts - st.session_state.teacher_otp_attempts,
                    )
                    st.error(f"驗證碼不正確，還可嘗試 {remaining} 次。")

            cooldown_remaining = max(
                0,
                int(
                    settings.otp_resend_seconds
                    - (
                        time.time()
                        - float(st.session_state.teacher_otp_last_sent_at or 0)
                    )
                ),
            )
            if resend_col.button(
                "重新寄送",
                use_container_width=True,
                disabled=cooldown_remaining > 0,
                key="resend_teacher_otp",
            ):
                try:
                    with st.spinner("正在重新寄送教師驗證碼……"):
                        issue_teacher_otp(settings, email)
                    st.rerun()
                except RuntimeError as exc:
                    st.error(str(exc))
            if cooldown_remaining > 0:
                resend_col.caption(f"{cooldown_remaining} 秒後可重送")

            if change_col.button(
                "更換 Email",
                use_container_width=True,
                key="change_teacher_email",
            ):
                clear_teacher_otp()
                st.rerun()

    with password_tab:
        if not settings.admin_password:
            st.info("目前未設定 ADMIN_PASSWORD，請改用教師 Email 驗證登入。")
        else:
            with st.form("admin_password_login"):
                password = st.text_input("教師後台密碼", type="password")
                submitted = st.form_submit_button("以管理密碼登入", type="primary")
            if submitted:
                if hmac.compare_digest(password, settings.admin_password):
                    st.session_state.teacher_admin_ok = True
                    st.session_state.teacher_auth_method = "admin_password"
                    st.session_state.teacher_email = ""
                    st.rerun()
                else:
                    st.error("密碼不正確。")

    st.stop()

if not settings.sheets_configured:
    st.error("Google Sheets 尚未設定。")
    st.stop()

try:
    store = get_store(settings.service_account_json, settings.spreadsheet_id)
except (SheetsStoreError, ValueError, json.JSONDecodeError) as exc:
    st.error(str(exc))
    st.stop()

if st.session_state.teacher_auth_method == "email_otp":
    st.success(f"教師身分已驗證：{mask_email(st.session_state.teacher_email)}")
else:
    st.success("教師身分已以管理密碼驗證。")

toolbar_left, toolbar_middle, toolbar_right = st.columns([1, 4, 1])
if toolbar_left.button("重新讀取資料"):
    st.rerun()
if toolbar_right.button("登出"):
    teacher_logout()
    st.rerun()

frames: dict[str, pd.DataFrame] = {}
try:
    for sheet_name, headers in SHEET_HEADERS.items():
        frames[sheet_name] = pd.DataFrame(store.read_all(sheet_name), columns=headers)
except SheetsStoreError as exc:
    st.error(str(exc))
    st.stop()

sessions = frames["Sessions"]
metric_columns = st.columns(5)
metric_columns[0].metric("已驗證學生", len(frames["StudentRoster"]))
metric_columns[1].metric("Session 數", len(sessions))
metric_columns[2].metric(
    "完成數",
    int(sessions["completion_status"].isin(["completed", "completed_evaluation_error"]).sum())
    if not sessions.empty
    else 0,
)
metric_columns[3].metric("逐輪對話數", len(frames["ChatLogs"]))
metric_columns[4].metric("技巧事件數", len(frames["SkillEvents"]))

student_summary = build_student_usage_summary(
    frames["StudentRoster"],
    sessions,
    frames["ChatLogs"],
)
st.subheader("學生使用摘要")
st.caption(
    f"分鐘數以 Sessions × ChatLogs 交叉稽核計算；學期門檻為總累積至少 {SEMESTER_TARGET_MINUTES} 分鐘，"
    f"其中學生擔任諮商師至少 {COUNSELOR_TARGET_MINUTES} 分鐘。"
)
st.dataframe(student_summary, use_container_width=True, hide_index=True)
st.download_button(
    "下載學生使用摘要.csv",
    data=csv_bytes(student_summary),
    file_name="StudentUsageSummary.csv",
    mime="text/csv",
    key="download_student_usage_summary",
)

tabs = st.tabs(list(SHEET_HEADERS))
for tab, (sheet_name, frame) in zip(tabs, frames.items(), strict=True):
    with tab:
        st.dataframe(frame, use_container_width=True, hide_index=True)
        st.download_button(
            f"下載 {sheet_name}.csv",
            data=csv_bytes(frame),
            file_name=f"{sheet_name}.csv",
            mime="text/csv",
            key=f"download_{sheet_name}",
        )
