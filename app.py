from __future__ import annotations

import hmac
import json
import re
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st

from src.assessment_models import AssessmentResult
from src.cases import EXPERIENCE_TOPICS, PRACTICE_CASES, case_options, get_case
from src.constants import AGENT_TYPE, MODE_LABELS, STAGE_LABELS, STAGES
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

TAIPEI = ZoneInfo("Asia/Taipei")
PARTICIPANT_PATTERN = re.compile(r"^[A-Za-z0-9_-]{3,32}$")


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
        # 僅保存在目前瀏覽器的 Streamlit session；不寫入 Google Sheets。
        "student_api_key": "",
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
    """載入教師端系統設定與 Google Sheets；Gemini Key 不再從教師端 Secrets 取用。"""
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
        # 不使用 st.cache_resource，避免學生 API Key / Gateway 被跨 session 快取。
        return GeminiGateway(api_keys=(api_key,), model_name=settings.model_name), ""
    except ValueError as exc:
        return None, str(exc)


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
) -> None:
    usage = store.usage_summary(participant_id)
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

    session = {
        "session_id": str(uuid.uuid4()),
        "participant_id": participant_id,
        "mode": mode,
        "started_at": now_iso(),
        "duration_target_min": duration_target_min,
        "experience_topic_id": experience_topic_id,
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


def finish_session(settings: Settings, store, gateway: GeminiGateway | None) -> None:
    session = st.session_state.active_session
    if not session or session.get("ended_at"):
        return

    assessment_status = "completed"
    assessment_id = str(uuid.uuid4())
    created_at = now_iso()

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
    # 清除上一段練習資料，但保留學生 API Key，方便同一位學生在自己的筆電繼續下一段練習。
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


init_state()
settings, store, store_error = load_runtime()
gateway, gateway_error = build_student_gateway(settings)

st.title("助人技巧訓練 Agent")
st.caption("教學模擬、技能演練、歷程紀錄與形成性回饋")
st.warning(
    "本系統僅供教學演練，不提供心理治療、診斷或緊急危機服務。請勿輸入真實個案姓名、電話、地址、學校或機構等可識別資訊。",
    icon="⚠️",
)

with st.sidebar:
    st.header("系統狀態")
    if gateway is not None:
        st.success(f"Gemini：已使用學生 API Key（{settings.model_name}）")
    elif gateway_error:
        st.error(f"Gemini API Key 設定錯誤：{gateway_error}")
    else:
        st.info("Gemini：請由學生輸入自己的 API Key")
    if store.enabled:
        st.success("Google Sheets：已連線")
    elif settings.require_sheets:
        st.error("Google Sheets：尚未連線")
    else:
        st.info("Google Sheets：本機預覽模式")
    if store_error:
        st.caption(store_error)
    st.divider()
    st.caption(f"Prompt：{settings.prompt_version}")
    st.caption(f"Rubric：{settings.rubric_version}")

session = st.session_state.active_session

if not session:
    st.subheader("開始一段練習")
    with st.form("start_session_form"):
        participant_id = st.text_input(
            "匿名學習者代碼",
            placeholder="例如 P001",
            help="請使用教師分配的匿名代碼，不要輸入姓名或 Email。",
        ).strip()

        student_api_key = st.text_input(
            "Gemini API Key",
            type="password",
            value=st.session_state.get("student_api_key", ""),
            placeholder="請貼上你自己的 Gemini API Key",
            help=(
                "此 Key 只暫存在你目前的 Streamlit 瀏覽器 session，"
                "可供同一位學生連續進行多段練習；不會寫入 Google Sheets、逐字稿或評量紀錄。"
            ),
        ).strip()
        st.caption("請勿使用他人的 API Key。只要目前瀏覽器 session 仍在，開始另一段練習時會沿用你自己的 Key，不必重複貼上。")

        access_code = ""
        if settings.course_access_code:
            access_code = st.text_input("課程通行碼", type="password")

        mode = st.radio(
            "訓練模式",
            options=list(MODE_LABELS),
            format_func=lambda value: MODE_LABELS[value],
        )
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
            )
            st.info("體驗模式中，AI 擔任示範助人者；演練結束後才會揭露使用過的技巧。")
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
        if not PARTICIPANT_PATTERN.fullmatch(participant_id):
            errors.append("匿名代碼需為 3–32 個英文字母、數字、底線或連字號。")
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

        # 先把 Key 放進目前學生的 Streamlit session，再建立專屬 Gateway。
        # Key 不會被加入 session record，也不會傳給 Google Sheets。
        if not errors:
            st.session_state.student_api_key = student_api_key
            gateway, gateway_error = build_student_gateway(settings)
            if gateway is None:
                errors.append(
                    f"Gemini API Key 無法使用：{gateway_error or '請確認 API Key 是否正確。'}"
                )

        if errors:
            # 若連 Gateway 都無法建立，不保留這把 Key。
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
    top_fourth.metric("本學期第", f"{session.get('usage_number', 1)} 次")
    st.caption(f"匿名代碼：{session['participant_id']}｜Session：{session['session_id'][:8]}")

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
            with st.spinner("正在根據逐字稿產生形成性回饋……"):
                finish_session(settings, store, gateway)
            st.rerun()

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
        if st.session_state.assessment:
            render_assessment(st.session_state.assessment)
        elif st.session_state.assessment_error:
            st.error(st.session_state.assessment_error)
        elif session.get("completion_status") == "safety_ended":
            st.info("本次教學模擬已依安全規則停止，不進行技巧評量。")

        transcript = format_transcript(st.session_state.messages, max_chars=100000)
        st.download_button(
            "下載本次逐字稿",
            data=transcript.encode("utf-8-sig"),
            file_name=f"helping_transcript_{session['session_id'][:8]}.txt",
            mime="text/plain",
            use_container_width=True,
        )
        if st.button("開始另一段練習", use_container_width=True):
            reset_for_new_session()
            st.rerun()
