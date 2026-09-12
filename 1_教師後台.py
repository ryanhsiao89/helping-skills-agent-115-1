from __future__ import annotations

import hmac
import json

import pandas as pd
import streamlit as st

from src.constants import SHEET_HEADERS
from src.settings import load_settings
from src.sheets_store import SheetsStore, SheetsStoreError

st.set_page_config(page_title="教師後台", page_icon="📊", layout="wide")


@st.cache_resource(show_spinner=False)
def get_store(service_account_json: str, spreadsheet_id: str) -> SheetsStore:
    store = SheetsStore(json.loads(service_account_json), spreadsheet_id)
    store.ensure_schema()
    return store


def csv_bytes(frame: pd.DataFrame) -> bytes:
    return frame.to_csv(index=False).encode("utf-8-sig")


settings = load_settings(st.secrets)
st.title("助人技巧訓練 Agent 教師後台")
st.caption("查看原始紀錄與匯出研究資料；AI 回饋不等同標準化測驗成績。")

if not settings.admin_password:
    st.error("尚未在 Secrets 設定 ADMIN_PASSWORD，教師後台已停用。")
    st.stop()

if "admin_ok" not in st.session_state:
    st.session_state.admin_ok = False

if not st.session_state.admin_ok:
    with st.form("admin_login"):
        password = st.text_input("教師後台密碼", type="password")
        submitted = st.form_submit_button("登入", type="primary")
    if submitted:
        if hmac.compare_digest(password, settings.admin_password):
            st.session_state.admin_ok = True
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

toolbar_left, toolbar_right = st.columns([1, 5])
if toolbar_left.button("重新讀取資料"):
    st.rerun()
if toolbar_right.button("登出"):
    st.session_state.admin_ok = False
    st.rerun()

frames: dict[str, pd.DataFrame] = {}
try:
    for sheet_name, headers in SHEET_HEADERS.items():
        frames[sheet_name] = pd.DataFrame(store.read_all(sheet_name), columns=headers)
except SheetsStoreError as exc:
    st.error(str(exc))
    st.stop()

sessions = frames["Sessions"]
metric_columns = st.columns(4)
metric_columns[0].metric("Session 數", len(sessions))
metric_columns[1].metric(
    "完成數",
    int(sessions["completion_status"].isin(["completed", "completed_evaluation_error"]).sum())
    if not sessions.empty
    else 0,
)
metric_columns[2].metric("逐輪對話數", len(frames["ChatLogs"]))
metric_columns[3].metric("技巧事件數", len(frames["SkillEvents"]))

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
