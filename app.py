from __future__ import annotations

import hmac
import json
import time
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st

from src.assessment_models import AssessmentResult
from src.cases import EXPERIENCE_TOPICS, PRACTICE_CASES, case_options, get_case
from src.constants import AGENT_TYPE, MODE_LABELS, STAGE_LABELS, STAGES
from src.continuity import build_memory_record
from src.email_otp import (
    email_allowed,
    generate_otp,
    mask_email,
    new_otp_nonce,
    normalize_email,
    otp_digest,
    otp_matches,
    participant_id_for_email,
    send_otp_email,
)
from src.gemini_gateway import GatewayError, GeminiGateway
from src.prompts import (
    dialogue_system_prompt,
    dialogue_turn_input,
    evaluator_input,
    evaluator_system_prompt,
    format_transcript,
)
from src.safety import crisis_response, detect_immediate_crisis
from src.settings import Settings, load_settings
from src.sheets_store import NullStore, SheetsStore, SheetsStoreError
from src.usage_time import COUNSELOR_TARGET_MINUTES, SEMESTER_TARGET_MINUTES

TAIPEI = ZoneInfo("Asia/Taipei")
OWNER_TEST_EMAIL = "ryanhsiao89@gmail.com"

st.set_page_config(
    page_title="助人技巧訓練 Agent",
    page_icon="💬",
    layout="centered",
)


def now() -> datetime:
    return datetime.now(TAIPEI)


def now_iso() -> str:
    return now().isoformat(timespec="seconds")


def init_state() -> None:
    defaults = {
        "active_session": None,
        "messages": [],
        "turn_index": 0,
        "assessment": None,
        "assessment_error": "",
        "logging_error": "",
        "admin_ok": False,
        # Gemini Key 僅存在目前瀏覽器的 Streamlit session；不寫入 Google Sheets。
        "student_api_key": "",
        "start_mode": "experience",
        # 學校 Email OTP 登入狀態。
        "auth_verified": False,
        "verified_email": "",
        "verified_participant_id": "",
        "otp_sent": False,
        "pending_email": "",
        "otp_code_digest": "",
        "otp_nonce": "",
        "otp_expires_at": 0.0,
        "otp_last_sent_at": 0.0,
        "otp_attempts": 0,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


@st.cache_resource(show_spinner=False)
def cached_store(service_account_json: str, spreadsheet_id: str):
    if not service_account_json or not spreadsheet_id:
        return NullStore()
    service_account_info = json.loads(service_account_json)
    store = SheetsStore(service_account_info, spreadsheet_id)
    store.ensure_schema()
    return store


def load_runtime() -> tuple[Settings, object, str]:
    """載入教師端系統設定與 Google Sheets；Gemini Key 不從教師端 Secrets 取用。"""
    settings = load_settings(st.secrets)
    store_error = ""
    try:
        store = cached_store(settings.service_account_json, settings.spreadsheet_id)
    except (SheetsStoreError, ValueError, json.JSONDecodeError) as exc:
        store = NullStore()
        store_error = str(exc)
    return settings, store, store_error


def build_student_gateway(settings: Settings) -> tuple[GeminiGateway | None, str]:
    """以目前學生輸入的 API Key 建立 Gateway；Key 僅存在 st.session_state。"""
    api_key = st.session_state.get("student_api_key", "").strip()
    if not api_key:
        return None, ""
    try:
        return GeminiGateway(api_keys=(api_key,), model_name=settings.model_name), ""
    except ValueError as exc:
        return None, str(exc)


def clear_otp_challenge(*, keep_last_sent: bool = False) -> None:
    for key, value in {
        "otp_sent": False,
        "pending_email": "",
        "otp_code_digest": "",
        "otp_nonce": "",
        "otp_expires_at": 0.0,
        "otp_attempts": 0,
    }.items():
        st.session_state[key] = value
    if not keep_last_sent:
        st.session_state.otp_last_sent_at = 0.0


def issue_login_otp(settings: Settings, school_email: str) -> None:
    email = normalize_email(school_email)
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
    st.session_state.pending_email = email
    st.session_state.otp_nonce = nonce
    st.session_state.otp_code_digest = otp_digest(email, code, nonce)
    st.session_state.otp_expires_at = sent_at + settings.otp_ttl_seconds
    st.session_state.otp_last_sent_at = sent_at
    st.session_state.otp_attempts = 0
    st.session_state.otp_sent = True


def complete_email_login(store, school_email: str) -> None:
    email = normalize_email(school_email)
    participant_id = participant_id_for_email(email)
    row = store.ensure_student(
        school_email=email,
        participant_id=participant_id,
        verified_at=now_iso(),
    )
    st.session_state.auth_verified = True
    st.session_state.verified_email = email
    st.session_state.verified_participant_id = str(
        row.get("participant_id", participant_id) or participant_id
    ).strip()
    clear_otp_challenge(keep_last_sent=True)


def logout_student() -> None:
    for key in (
        "active_session",
        "messages",
        "turn_index",
        "assessment",
        "assessment_error",
        "logging_error",
        "student_api_key",
        "verified_email",
        "verified_participant_id",
    ):
        if key in st.session_state:
            del st.session_state[key]
    st.session_state.auth_verified = False
    clear_otp_challenge()
    init_state()


def log_message(
    *,
    store,
    content: str,
    speaker_role: str,
    ui_role: str,
    latency_ms: int | str = "",
    error_flag: str = "",
) -> None:
    session = st.session_state.active_session
    if not session:
        return

    timestamp = now_iso()
    turn_index = st.session_state.turn_index
    message = {
        "ui_role": ui_role,
        "speaker_role": speaker_role,
        "content": content,
        "timestamp": timestamp,
        "stage": session["current_stage"],
    }
    st.session_state.messages.append(message)
    st.session_state.turn_index += 1

    try:
        store.append_record(
            "ChatLogs",
            {
                "turn_id": str(uuid.uuid4()),
                "session_id": session["session_id"],
                "turn_index": turn_index,
                "speaker_role": speaker_role,
                "speaker_id": "",
                "content_raw": content,
                "timestamp": timestamp,
                "stage_at_turn": session["current_stage"],
                "skill_labels": "",
                "selected_skill_match": "",
                "latency_ms": latency_ms,
                "error_flag": error_flag,
                "model_name": session["model_name"],
                "prompt_version": session["prompt_version"],
            },
        )
    except SheetsStoreError as exc:
        st.session_state.logging_error = str(exc)


def initial_message(session: dict) -> tuple[str, str, str]:
    if session["mode"] == "experience":
        prior = session.get("continuity_memory")
        if prior:
            opening = str(prior.get("next_opening", "") or "").strip()
            if not opening:
                opening = (
                    "上次我們談過一段近況。今天你想從上次談到的地方繼續，"
                    "還是先說說這幾天有什麼變化？"
                )
            return opening, "ai_counselor", "assistant"

        topic = EXPERIENCE_TOPICS[session["experience_topic_id"]]
        content = (
            f"你好，這裡是助人技巧的教學體驗。我會先陪你談一小段「{topic}」相關的低至中度壓力經驗。"
            "你可以只說願意用於課堂練習的內容，也請不要輸入任何可識別的個人或真實個案資料。你想先從哪一件事談起？"
        )
        return content, "ai_counselor", "assistant"

    case = get_case(session["case_id"])
    return case["opening"], "ai_client", "assistant"


def build_session_record(session: dict, *, status: str, ended_at: str = "") -> dict:
    duration_seconds: int | str = ""
    if ended_at:
        start = datetime.fromisoformat(session["started_at"])
        end = datetime.fromisoformat(ended_at)
        duration_seconds = max(0, int((end - start).total_seconds()))

    return {
        "session_id": session["session_id"],
        "participant_id": session["participant_id"],
        "agent_type": AGENT_TYPE,
        "mode": session["mode"],
        "started_at": session["started_at"],
        "ended_at": ended_at,
        "duration_seconds": duration_seconds,
        "duration_target_min": session["duration_target_min"],
        "case_id": session["case_id"],
        "stage_start": session["stage_start"],
        "stage_end": session["current_stage"],
        "model_name": session["model_name"],
        "prompt_version": session["prompt_version"],
        "completion_status": status,
        "message_count": len(st.session_state.messages),
        "crisis_flag": session.get("crisis_flag", False),
    }


def start_session(
    *,
    settings: Settings,
    store,
    participant_id: str,
    mode: str,
    duration_target_min: int,
    experience_topic_id: str,
    case_id: str,
    training_path: str,
    conversation_action: str = "new",
    retain_for_continuity: bool = False,
    prior_memory: dict | None = None,
) -> None:
    usage = store.usage_summary(participant_id)
    audited_before = store.audited_usage_summary(participant_id)
    if mode == "experience":
        stage_start = "full_demo"
        current_stage = "full_demo"
        case_id = f"experience_{experience_topic_id}"
    elif training_path == "full":
        stage_start = "exploration"
        current_stage = "exploration"
    else:
        stage_start = training_path
        current_stage = training_path

    if mode == "experience" and conversation_action == "continue" and prior_memory:
        conversation_id = str(prior_memory.get("conversation_id", "") or str(uuid.uuid4()))
        parent_session_id = str(prior_memory.get("session_id", "") or "")
        try:
            conversation_session_number = int(prior_memory.get("session_number", 1) or 1) + 1
        except (TypeError, ValueError):
            conversation_session_number = 2
    else:
        conversation_id = str(uuid.uuid4())
        parent_session_id = ""
        conversation_session_number = 1

    session = {
        "session_id": str(uuid.uuid4()),
        "participant_id": participant_id,
        "mode": mode,
        "started_at": now_iso(),
        "duration_target_min": duration_target_min,
        "experience_topic_id": experience_topic_id,
        "experience_topic_label": EXPERIENCE_TOPICS.get(experience_topic_id, ""),
        "case_id": case_id,
        "training_path": training_path,
        "stage_start": stage_start,
        "current_stage": current_stage,
        "model_name": settings.model_name,
        "prompt_version": settings.prompt_version,
        "crisis_flag": False,
        "ended_at": "",
        "completion_status": "in_progress",
        "usage_number": usage.started + 1,
        "usage_total_minutes_before": audited_before.total_minutes,
        "usage_counselor_minutes_before": audited_before.counselor_minutes,
        "conversation_action": conversation_action if mode == "experience" else "new",
        "conversation_id": conversation_id,
        "parent_session_id": parent_session_id,
        "conversation_session_number": conversation_session_number,
        "retain_for_continuity": bool(retain_for_continuity) if mode == "experience" else False,
        # 只存在本次 Streamlit session；傳給模型時 prompts.py 只會帶入去識別的續談摘要。
        "continuity_memory": prior_memory if mode == "experience" and conversation_action == "continue" else None,
        "continuity_saved": False,
    }

    store.append_record("Sessions", build_session_record(session, status="in_progress"))
    st.session_state.active_session = session
    st.session_state.messages = []
    st.session_state.turn_index = 0
    st.session_state.assessment = None
    st.session_state.assessment_error = ""
    st.session_state.logging_error = ""
    content, speaker_role, ui_role = initial_message(session)
    log_message(store=store, content=content, speaker_role=speaker_role, ui_role=ui_role)


def save_continuity_memory(
    *,
    store,
    session: dict,
    continuity: dict | None,
    updated_at: str,
    status: str,
) -> None:
    if session.get("mode") != "experience" or not session.get("retain_for_continuity"):
        return
    record = build_memory_record(
        session=session,
        messages=st.session_state.messages,
        updated_at=updated_at,
        continuity=continuity,
        status=status,
    )
    store.append_record("ContinuityMemory", record)
    session["continuity_saved"] = True


def finish_session(settings: Settings, store, gateway: GeminiGateway | None) -> None:
    session = st.session_state.active_session
    if not session or session.get("ended_at"):
        return

    assessment_status = "completed"
    assessment_id = str(uuid.uuid4())
    created_at = now_iso()
    continuity_for_memory: dict | None = None
    memory_status = "fallback"

    if gateway is None:
        assessment_status = "completed_evaluation_error"
        st.session_state.assessment_error = "尚未設定 Gemini API，無法產生晤談後回饋。"
    else:
        try:
            result = gateway.generate_structured(
                prompt=evaluator_input(mode=session["mode"], messages=st.session_state.messages),
                system_instruction=evaluator_system_prompt(),
                temperature=settings.evaluator_temperature,
                schema=AssessmentResult,
                model_name=settings.evaluator_model_name,
            )
            parsed = result.parsed.model_dump()
            st.session_state.assessment = parsed
            continuity_for_memory = parsed.get("continuity") or None
            memory_status = "ready"

            quoted_examples = [
                {
                    "evidence_quote": point["evidence_quote"],
                    "alternative_response": point.get("alternative_response", ""),
                }
                for point in parsed["strengths"] + parsed["improvement_points"]
            ]
            store.append_record(
                "Assessments",
                {
                    "assessment_id": assessment_id,
                    "session_id": session["session_id"],
                    "rubric_version": settings.rubric_version,
                    "created_at": created_at,
                    "dimension_scores_json": {},
                    "stage_judgment": parsed["stage_judgment"],
                    "strengths_json": parsed["strengths"],
                    "improvement_points_json": parsed["improvement_points"],
                    "quoted_examples_json": quoted_examples,
                    "next_tasks_json": parsed["next_practice_tasks"],
                    "raw_model_output": result.raw_text,
                    "parsed_json": parsed,
                    "evaluator_model": settings.evaluator_model_name,
                    "evaluator_temperature": settings.evaluator_temperature,
                    "status": "success",
                },
            )
            for event in parsed["technique_events"]:
                store.append_record(
                    "SkillEvents",
                    {
                        "skill_event_id": str(uuid.uuid4()),
                        "session_id": session["session_id"],
                        "assessment_id": assessment_id,
                        "technique": event["technique"],
                        "category": event["category"],
                        "evidence_quote": event["evidence_quote"],
                        "quality": event["quality"],
                        "rationale": event["rationale"],
                        "effect": event["effect"],
                        "alternative_response": event.get("alternative_response", ""),
                        "created_at": created_at,
                        "evaluator_model": settings.evaluator_model_name,
                        "rubric_version": settings.rubric_version,
                    },
                )
        except (GatewayError, SheetsStoreError) as exc:
            assessment_status = "completed_evaluation_error"
            st.session_state.assessment_error = str(exc)
            try:
                store.append_record(
                    "Assessments",
                    {
                        "assessment_id": assessment_id,
                        "session_id": session["session_id"],
                        "rubric_version": settings.rubric_version,
                        "created_at": created_at,
                        "dimension_scores_json": {},
                        "stage_judgment": "",
                        "strengths_json": [],
                        "improvement_points_json": [],
                        "quoted_examples_json": [],
                        "next_tasks_json": [],
                        "raw_model_output": "",
                        "parsed_json": {"error": str(exc)},
                        "evaluator_model": settings.evaluator_model_name,
                        "evaluator_temperature": settings.evaluator_temperature,
                        "status": "error",
                    },
                )
            except SheetsStoreError:
                pass

    # 只有學生主動選擇保留／續談時才保存跨日記憶。
    if session.get("mode") == "experience" and session.get("retain_for_continuity"):
        try:
            save_continuity_memory(
                store=store,
                session=session,
                continuity=continuity_for_memory,
                updated_at=created_at,
                status=memory_status,
            )
        except SheetsStoreError as exc:
            st.session_state.logging_error = str(exc)

    ended_at = now_iso()
    session["ended_at"] = ended_at
    session["completion_status"] = assessment_status
    try:
        store.update_session(
            session["session_id"],
            build_session_record(session, status=assessment_status, ended_at=ended_at),
        )
    except SheetsStoreError as exc:
        st.session_state.logging_error = str(exc)


def safety_end(store) -> None:
    session = st.session_state.active_session
    session["crisis_flag"] = True
    content = crisis_response()
    log_message(
        store=store,
        content=content,
        speaker_role="system",
        ui_role="assistant",
        error_flag="immediate_crisis_rule",
    )
    ended_at = now_iso()
    session["ended_at"] = ended_at
    session["completion_status"] = "safety_ended"
    try:
        store.update_session(
            session["session_id"],
            build_session_record(session, status="safety_ended", ended_at=ended_at),
        )
    except SheetsStoreError as exc:
        st.session_state.logging_error = str(exc)


def advance_stage(store) -> None:
    session = st.session_state.active_session
    current = session["current_stage"]
    index = STAGES.index(current)
    if index >= len(STAGES) - 1:
        return
    session["current_stage"] = STAGES[index + 1]
    log_message(
        store=store,
        content=f"教學階段由「{STAGE_LABELS[current]}」切換為「{STAGE_LABELS[session['current_stage']]}」。",
        speaker_role="system",
        ui_role="system",
    )


def handle_user_turn(
    *,
    user_text: str,
    settings: Settings,
    store,
    gateway: GeminiGateway,
) -> None:
    session = st.session_state.active_session
    user_role = "student_client" if session["mode"] == "experience" else "student_counselor"
    log_message(store=store, content=user_text, speaker_role=user_role, ui_role="user")
    if st.session_state.logging_error and settings.require_sheets:
        return

    if session["mode"] == "experience" and detect_immediate_crisis(user_text).is_crisis:
        safety_end(store)
        return

    case = get_case(session["case_id"]) if session["mode"] == "practice" else None
    topic = (
        EXPERIENCE_TOPICS.get(session["experience_topic_id"], "")
        if session["mode"] == "experience"
        else ""
    )
    system_prompt = dialogue_system_prompt(
        mode=session["mode"],
        stage=session["current_stage"],
        case=case,
        experience_topic=topic,
    )
    prompt = dialogue_turn_input(
        st.session_state.messages,
        max_chars=settings.max_history_chars,
        continuity_memory=session.get("continuity_memory"),
    )
    try:
        result = gateway.generate_text(
            prompt=prompt,
            system_instruction=system_prompt,
            temperature=settings.dialogue_temperature,
        )
        speaker_role = "ai_counselor" if session["mode"] == "experience" else "ai_client"
        log_message(
            store=store,
            content=result.text,
            speaker_role=speaker_role,
            ui_role="assistant",
            latency_ms=result.latency_ms,
        )
    except GatewayError as exc:
        log_message(
            store=store,
            content=str(exc),
            speaker_role="system",
            ui_role="assistant",
            error_flag="model_error",
        )


def reset_for_new_session() -> None:
    # 清除上一段練習資料，但保留已驗證學校 Email 與學生 API Key。
    for key in (
        "active_session",
        "messages",
        "turn_index",
        "assessment",
        "assessment_error",
        "logging_error",
    ):
        if key in st.session_state:
            del st.session_state[key]
    init_state()


def render_assessment(assessment: dict) -> None:
    st.subheader("晤談後形成性回饋")
    st.write(assessment["overall_summary"])
    st.caption(f"歷程判斷：{assessment['stage_judgment']}")

    st.markdown("#### 做得好的地方")
    for point in assessment["strengths"]:
        st.markdown(f"**{point['title']}**")
        st.write(f"逐字稿證據：「{point['evidence_quote']}」")
        st.write(point["explanation"])

    st.markdown("#### 最值得調整的地方")
    for point in assessment["improvement_points"]:
        st.markdown(f"**{point['title']}**")
        st.write(f"逐字稿證據：「{point['evidence_quote']}」")
        st.write(point["explanation"])
        if point.get("alternative_response"):
            st.write(f"可嘗試：{point['alternative_response']}")

    with st.expander("查看技巧辨識與次數"):
        for item in assessment["skill_statistics"]:
            st.write(f"- {item['technique']}：{item['count']} 次。{item.get('note', '')}")
        st.caption("技巧次數不等於技巧品質。")

    st.markdown("#### 下一次練習任務")
    for task in assessment["next_practice_tasks"]:
        st.write(f"- {task}")
    if assessment.get("evidence_limitations"):
        st.caption(f"證據限制：{assessment['evidence_limitations']}")


def render_usage_progress(store, participant_id: str) -> None:
    """顯示 Sessions × ChatLogs 交叉稽核後的學期分鐘進度。"""
    if not getattr(store, "enabled", False):
        st.info("目前為本機預覽模式，無法計算學期累積分鐘。")
        return
    try:
        usage = store.audited_usage_summary(participant_id)
    except SheetsStoreError as exc:
        st.warning(f"目前無法讀取累積上機分鐘：{exc}")
        return

    st.markdown("#### 本學期上機進度")
    total_col, counselor_col = st.columns(2)
    total_col.metric(
        "累積上機分鐘",
        f"{usage.total_minutes:.1f} / {SEMESTER_TARGET_MINUTES}",
    )
    counselor_col.metric(
        "其中擔任諮商師",
        f"{usage.counselor_minutes:.1f} / {COUNSELOR_TARGET_MINUTES}",
    )
    st.progress(usage.progress_ratio)
    st.caption(
        f"尚需累積 {usage.remaining_minutes:.1f} 分鐘；"
        f"其中諮商師角色尚需 {usage.remaining_counselor_minutes:.1f} 分鐘。"
    )
    if usage.semester_requirement_met:
        st.success("已達成本學期上機要求：總累積至少 120 分鐘，且諮商師角色至少 60 分鐘。")
    else:
        st.caption(
            "分鐘數以 Sessions 與 ChatLogs 交叉核對；本次練習需完成互動並正式按「結束並查看回饋」後才會更新。"
        )


init_state()
settings, store, store_error = load_runtime()
gateway, gateway_error = build_student_gateway(settings)

st.title("助人技巧訓練 Agent")
st.caption("教學模擬、技能演練、跨次續談、歷程紀錄與形成性回饋")
st.warning(
    "本系統僅供教學演練，不提供心理治療、診斷或緊急危機服務。請勿輸入真實個案姓名、電話、地址、學校或機構等可識別資訊。",
    icon="⚠️",
)

with st.sidebar:
    st.header("系統狀態")
    if st.session_state.auth_verified:
        st.success(f"身分：已驗證 {mask_email(st.session_state.verified_email)}")
    else:
        st.info("身分：請以學校 Email 驗證")

    if gateway is not None:
        st.success(f"Gemini：已使用學生 API Key（{settings.model_name}）")
    elif gateway_error:
        st.error(f"Gemini API Key 設定錯誤：{gateway_error}")
    else:
        st.info("Gemini：請由學生輸入自己的 API Key")

    if store.enabled:
        st.success("Google Sheets：已連線")
        st.caption("續談記憶：以已驗證學校 Email 對應的學習者代碼讀取")
    elif settings.require_sheets:
        st.error("Google Sheets：尚未連線")
    else:
        st.info("Google Sheets：本機預覽模式")
    if store_error:
        st.caption(store_error)

    if st.session_state.auth_verified and not st.session_state.get("active_session"):
        if st.button("切換學校帳號", use_container_width=True):
            logout_student()
            st.rerun()

    st.divider()
    st.caption(f"Prompt：{settings.prompt_version}")
    st.caption(f"Rubric：{settings.rubric_version}")

# ---------------------------------------------------------
# 學校 Email OTP 驗證：所有練習皆先驗證，OTP 不落地保存。
# ---------------------------------------------------------
if not st.session_state.auth_verified:
    st.subheader("學校 Email 身分驗證")

    if not settings.otp_configured:
        st.error(
            "尚未完成 Email OTP 設定。請教師在 Streamlit Secrets 設定 [email] sender、password，"
            "以及 SCHOOL_EMAIL_DOMAINS。"
        )
        st.stop()

    if settings.require_sheets and not store.enabled:
        st.error("研究模式要求 Google Sheets 正常連線後才能進行身分驗證。")
        st.stop()

    allowed_text = "、".join(f"@{domain}" for domain in settings.school_email_domains)

    if not st.session_state.otp_sent:
        st.write(f"請輸入你的學校 Email。系統只接受：{allowed_text}")
        school_email = st.text_input(
            "學校 Email",
            placeholder="例如 student@school.edu.tw",
        ).strip()
        if st.button("寄送 6 位數驗證碼", type="primary", use_container_width=True):
            normalized = normalize_email(school_email)
            if not email_allowed(
                normalized,
                settings.school_email_domains,
                allowed_emails=(OWNER_TEST_EMAIL,),
            ):
                st.error(f"請使用指定的學校 Email（{allowed_text}）。")
            else:
                try:
                    with st.spinner("正在寄送驗證碼……"):
                        issue_login_otp(settings, normalized)
                    st.rerun()
                except RuntimeError as exc:
                    st.error(str(exc))
    else:
        email = st.session_state.pending_email
        st.success(f"驗證碼已寄至：{mask_email(email)}")
        st.caption(
            f"驗證碼 {max(1, settings.otp_ttl_seconds // 60)} 分鐘內有效；"
            f"最多可輸錯 {settings.otp_max_attempts} 次。"
        )
        otp_value = st.text_input("6 位數驗證碼", max_chars=6, type="password").strip()
        verify_col, resend_col, change_col = st.columns(3)

        if verify_col.button("確認登入", type="primary", use_container_width=True):
            current_time = time.time()
            if current_time > float(st.session_state.otp_expires_at or 0):
                clear_otp_challenge(keep_last_sent=True)
                st.error("驗證碼已過期，請重新寄送。")
            elif st.session_state.otp_attempts >= settings.otp_max_attempts:
                clear_otp_challenge(keep_last_sent=True)
                st.error("驗證碼錯誤次數已達上限，請重新寄送。")
            elif otp_matches(
                email,
                otp_value,
                st.session_state.otp_nonce,
                st.session_state.otp_code_digest,
            ):
                try:
                    complete_email_login(store, email)
                    st.rerun()
                except SheetsStoreError as exc:
                    st.error(str(exc))
            else:
                st.session_state.otp_attempts += 1
                remaining = max(0, settings.otp_max_attempts - st.session_state.otp_attempts)
                st.error(f"驗證碼不正確，還可嘗試 {remaining} 次。")

        cooldown_remaining = max(
            0,
            int(
                settings.otp_resend_seconds
                - (time.time() - float(st.session_state.otp_last_sent_at or 0))
            ),
        )
        if resend_col.button(
            "重新寄送",
            use_container_width=True,
            disabled=cooldown_remaining > 0,
        ):
            try:
                with st.spinner("正在重新寄送驗證碼……"):
                    issue_login_otp(settings, email)
                st.rerun()
            except RuntimeError as exc:
                st.error(str(exc))
        if cooldown_remaining > 0:
            resend_col.caption(f"{cooldown_remaining} 秒後可重送")

        if change_col.button("更換 Email", use_container_width=True):
            clear_otp_challenge()
            st.rerun()

    st.stop()

session = st.session_state.active_session

if not session:
    st.subheader("開始一段練習")
    st.success(
        f"已驗證：{mask_email(st.session_state.verified_email)}｜"
        f"學習者代碼：{st.session_state.verified_participant_id}"
    )
    render_usage_progress(store, st.session_state.verified_participant_id)

    # 放在 form 外，使切換模式／續談選項時能立即更新相應欄位。
    mode = st.radio(
        "訓練模式",
        options=list(MODE_LABELS),
        format_func=lambda value: MODE_LABELS[value],
        key="start_mode",
        horizontal=True,
    )

    conversation_action = "new"
    retain_for_continuity = False
    if mode == "experience":
        st.markdown("#### 跨日續談")
        conversation_action = st.radio(
            "這次要怎麼談？",
            options=["new", "continue"],
            format_func=lambda value: (
                "開始新的談話" if value == "new" else "繼續上次談話"
            ),
            key="conversation_action",
            horizontal=True,
        )
        if conversation_action == "new":
            retain_for_continuity = st.checkbox(
                "我希望保留本次談話供下次續談",
                value=False,
                key="retain_for_continuity",
            )
        else:
            retain_for_continuity = True

    with st.form("start_session_form"):
        student_api_key = st.text_input(
            "Gemini API Key",
            type="password",
            value=st.session_state.get("student_api_key", ""),
            placeholder="請貼上你自己的 Gemini API Key",
            help=(
                "此 Key 只暫存在你目前的 Streamlit 瀏覽器 session，"
                "不會寫入 Google Sheets、逐字稿或評量紀錄。"
            ),
        ).strip()

        access_code = ""
        if settings.course_access_code:
            access_code = st.text_input("課程通行碼", type="password")

        duration_target_min = st.select_slider(
            "建議練習時間（不會強制中斷）",
            options=[5, 8, 10, 12, 15, 20],
            value=10,
        )

        experience_topic_id = "interpersonal"
        case_id = "college_peer_01"
        training_path = "full"

        if mode == "experience":
            experience_topic_id = st.selectbox(
                "這次想體驗的主題",
                options=list(EXPERIENCE_TOPICS),
                format_func=lambda value: EXPERIENCE_TOPICS[value],
                disabled=conversation_action == "continue",
            )
            if conversation_action == "continue":
                st.info("系統會依你已驗證的學校 Email 身分找到最近一次已保留的談話摘要與最後幾輪，自動承接。")
            elif retain_for_continuity:
                st.info("體驗模式中，AI 擔任示範助人者；本次結束後會建立供下次續談的去識別摘要。")
            else:
                st.info("體驗模式中，AI 擔任示範助人者；本次不建立跨日續談記憶。")
        else:
            options = case_options()
            case_id = st.selectbox(
                "選擇虛構標準化案例",
                options=list(options),
                format_func=lambda value: options[value],
            )
            st.caption(PRACTICE_CASES[case_id]["public_brief"])
            path_labels = {
                "full": "完整三階段：探索 → 洞察 → 行動",
                "exploration": "單一階段：探索",
                "insight": "單一階段：洞察",
                "action": "單一階段：行動",
            }
            training_path = st.selectbox(
                "練習路徑",
                options=list(path_labels),
                format_func=lambda value: path_labels[value],
            )

        agreed = st.checkbox("我了解這是教學模擬，並同意不輸入可識別的真實個案資料。")
        submitted = st.form_submit_button("開始練習", type="primary", use_container_width=True)

    if submitted:
        errors: list[str] = []
        prior_memory: dict | None = None
        participant_id = st.session_state.verified_participant_id

        if settings.course_access_code and not hmac.compare_digest(
            access_code, settings.course_access_code
        ):
            errors.append("課程通行碼不正確。")
        if not agreed:
            errors.append("請先勾選教學模擬與資料去識別提醒。")
        if not student_api_key:
            errors.append("請輸入你自己的 Gemini API Key。")
        if settings.require_sheets and not store.enabled:
            errors.append("研究模式要求 Google Sheets 正常連線後才能開始。")

        if mode == "experience" and conversation_action == "continue" and store.enabled:
            try:
                prior_memory = store.latest_continuity(participant_id)
            except SheetsStoreError as exc:
                prior_memory = None
                errors.append(str(exc))

            if prior_memory:
                reverse_topics = {label: key for key, label in EXPERIENCE_TOPICS.items()}
                experience_topic_id = reverse_topics.get(
                    str(prior_memory.get("topic_label", "")), experience_topic_id
                )
            else:
                errors.append("目前找不到你的已保留續談紀錄；請先選擇「開始新的談話」，並勾選保留供下次續談。")

        if not errors:
            st.session_state.student_api_key = student_api_key
            gateway, gateway_error = build_student_gateway(settings)
            if gateway is None:
                errors.append(
                    f"Gemini API Key 無法使用：{gateway_error or '請確認 API Key 是否正確。'}"
                )

        if errors:
            if gateway is None:
                st.session_state.student_api_key = ""
            for error in errors:
                st.error(error)
        else:
            try:
                start_session(
                    settings=settings,
                    store=store,
                    participant_id=participant_id,
                    mode=mode,
                    duration_target_min=duration_target_min,
                    experience_topic_id=experience_topic_id,
                    case_id=case_id,
                    training_path=training_path,
                    conversation_action=conversation_action,
                    retain_for_continuity=retain_for_continuity,
                    prior_memory=prior_memory,
                )
                st.rerun()
            except SheetsStoreError as exc:
                st.error(str(exc))

else:
    ended = bool(session.get("ended_at"))
    elapsed = now() - datetime.fromisoformat(session["started_at"])
    elapsed_seconds = max(0, int(elapsed.total_seconds()))
    minutes, seconds = divmod(elapsed_seconds, 60)

    top_left, top_middle, top_right, top_fourth = st.columns(4)
    top_left.metric("模式", "體驗" if session["mode"] == "experience" else "實作")
    top_middle.metric("目前階段", STAGE_LABELS[session["current_stage"]])
    top_right.metric("已進行", f"{minutes}:{seconds:02d}")
    if session["mode"] == "experience":
        top_fourth.metric("同一談話第", f"{session.get('conversation_session_number', 1)} 次")
    else:
        top_fourth.metric("本學期第", f"{session.get('usage_number', 1)} 次")

    if not ended:
        st.caption(
            f"本次開始前：累積 {session.get('usage_total_minutes_before', 0):.1f}/{SEMESTER_TARGET_MINUTES} 分鐘｜"
            f"其中擔任諮商師 {session.get('usage_counselor_minutes_before', 0):.1f}/{COUNSELOR_TARGET_MINUTES} 分鐘。"
            "本次需正式結束後才會計入。"
        )

    caption = f"學習者代碼：{session['participant_id']}｜Session：{session['session_id'][:8]}"
    if session["mode"] == "experience":
        caption += f"｜Conversation：{session.get('conversation_id', '')[:8]}"
        if session.get("conversation_action") == "continue":
            caption += "｜續談"
    st.caption(caption)

    if st.session_state.logging_error:
        st.error(
            f"資料寫入發生問題：{st.session_state.logging_error}"
            " 為避免研究資料不完整，請先停止輸入並通知教師。"
        )

    for message in st.session_state.messages:
        if message["ui_role"] == "system":
            st.caption(message["content"])
            continue
        avatar = "🧑" if message["ui_role"] == "user" else "💬"
        with st.chat_message(message["ui_role"], avatar=avatar):
            st.write(message["content"])

    if not ended:
        controls = st.columns([1, 1])
        if (
            session["mode"] == "practice"
            and session["training_path"] == "full"
            and session["current_stage"] != "action"
        ):
            current_index = STAGES.index(session["current_stage"])
            next_label = STAGE_LABELS[STAGES[current_index + 1]]
            if controls[0].button(f"進入{next_label}階段", use_container_width=True):
                advance_stage(store)
                st.rerun()
        else:
            controls[0].empty()

        if controls[1].button("結束並查看回饋", type="primary", use_container_width=True):
            spinner_text = "正在根據逐字稿產生形成性回饋……"
            if session.get("mode") == "experience" and session.get("retain_for_continuity"):
                spinner_text = "正在根據逐字稿產生形成性回饋並建立續談摘要……"
            with st.spinner(spinner_text):
                finish_session(settings, store, gateway)
            st.rerun()

        st.caption(
            "💡 非語言訊息也可以輸入：請用半形 ( ) 或全形（ ）表示，例如「(眼神渙散)」、"
            "「(避免眼神接觸)」、「(握緊拳頭)」、「(面帶微笑)」或「(身體僵硬)」。"
            "括號內會被視為非語言行為／歷程提示，不是說出口的話。"
        )
        input_disabled = bool(st.session_state.logging_error and settings.require_sheets)
        user_text = st.chat_input(
            "輸入這一輪想說的話……",
            max_chars=settings.max_user_input_chars,
            disabled=input_disabled,
        )
        if user_text:
            if gateway is None:
                st.error("目前沒有可用的學生 Gemini API Key，請重新開始並輸入自己的 API Key。")
            else:
                with st.spinner("AI 正在回應……"):
                    handle_user_turn(
                        user_text=user_text,
                        settings=settings,
                        store=store,
                        gateway=gateway,
                    )
                st.rerun()
    else:
        render_usage_progress(store, session["participant_id"])

        if st.session_state.assessment:
            render_assessment(st.session_state.assessment)
        elif st.session_state.assessment_error:
            st.error(st.session_state.assessment_error)
        elif session.get("completion_status") == "safety_ended":
            st.info("本次教學模擬已依安全規則停止，不進行技巧評量。")

        if session.get("mode") == "experience" and session.get("continuity_saved"):
            st.success("已建立下次續談記憶。下次用相同學校 Email 完成 OTP 驗證後，即可選擇「繼續上次談話」。")

        # 保留學生自主下載逐字稿，供課後重新閱讀、自我反思與學習；續談本身不需要重新上傳。
        transcript = format_transcript(st.session_state.messages, max_chars=100000)
        st.download_button(
            "下載本次逐字稿（選用；可供課後自我反思）",
            data=transcript.encode("utf-8-sig"),
            file_name=f"helping_transcript_{session['session_id'][:8]}.txt",
            mime="text/plain",
            use_container_width=True,
        )
        if st.button("開始另一段練習", use_container_width=True):
            reset_for_new_session()
            st.rerun()
