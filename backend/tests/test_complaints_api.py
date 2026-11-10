from collections.abc import Generator
from datetime import date, datetime, timedelta, timezone
import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import ActionLog, Authority, CallbackRequest, Complaint, IvrSession, Notification
from app.seed import seed_database
from app.followups import run_followup_job
from app import config


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient, None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)
    with TestingSession() as session:
        seed_database(session)

    def override_get_db():
        with TestingSession() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setenv("OFFICER_API_KEY", "test-officer-key")
    monkeypatch.setenv("ADMIN_API_KEY", "test-admin-key")
    monkeypatch.delenv("SARVAM_API_KEY", raising=False)
    app.state.testing_session_factory = TestingSession
    test_client = TestClient(app)
    yield test_client
    test_client.close()
    app.dependency_overrides.clear()
    del app.state.testing_session_factory
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def register(client: TestClient, **overrides) -> dict:
    payload = {
        "description": "Doctor unavailable in outpatient department",
        "language": "en",
        "hospital_id": 1,
        "channel": "assisted",
        **overrides,
    }
    response = client.post("/api/complaints", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_normal_registration_assigns_and_logs(client: TestClient):
    result = register(client)
    assert re.fullmatch(rf"SD-{date.today().year}-\d{{5}}", result["complaint_id"])
    assert result["category"] == "Doctor/Staff Unavailable"
    assert result["assigned_role"] == "Medical Superintendent"
    assert result["due_at"]
    assert "registered" in result["message"].lower()


def test_emergency_is_redirected_and_flagged(client: TestClient):
    response = client.post("/api/complaints", json={
        "description": "Accident with bleeding",
        "language": "en",
        "hospital_id": 1,
        "channel": "voice",
    })
    assert response.status_code == 201
    assert response.json()["emergency"] is True
    assert "108" in response.json()["message"]
    assert response.json()["complaint_id"] is None
    with client.app.state.testing_session_factory() as session:
        flagged = session.scalar(select(Complaint).where(Complaint.is_emergency_flagged.is_(True)))
        assert flagged is not None
        assert flagged.complaint_id.startswith("EMG-")
        assert session.scalar(select(ActionLog).where(ActionLog.complaint_id == flagged.id)).action_type == "emergency_flagged"
    # Emergency records are deliberately not returned as routine public complaints.
    assert client.get("/api/complaints/EMG-invalid").status_code == 404


def test_invalid_status_transition_rejected(client: TestClient):
    result = register(client)
    response = client.patch(
        f"/api/complaints/{result['complaint_id']}",
        headers={"X-API-Key": "test-officer-key"},
        json={"status": "Closed", "action_note": "done"},
    )
    assert response.status_code == 409


def test_resolved_requires_action_note(client: TestClient):
    result = register(client)
    url = f"/api/complaints/{result['complaint_id']}"
    headers = {"X-API-Key": "test-officer-key"}
    assert client.patch(url, headers=headers, json={"status": "In Progress"}).status_code == 200
    response = client.patch(url, headers=headers, json={"status": "Resolved", "action_note": "  "})
    assert response.status_code == 422


def test_public_status_does_not_expose_private_fields(client: TestClient):
    result = register(client, complainant_phone="9999999999")
    response = client.get(f"/api/complaints/{result['complaint_id']}")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "Assigned"
    assert data["category"] == "Doctor/Staff Unavailable"
    assert "complainant_phone" not in data
    assert "assigned_authority_id" not in data
    assert "phone" not in data
    assert "description" not in data


def test_hospital_selector_uses_consistent_fields(client: TestClient):
    response = client.get("/api/hospitals")
    assert response.status_code == 200
    hospital = response.json()[0]
    assert set(hospital) == {"id", "name", "district", "taluk"}


def test_reminder_is_idempotent_and_notifications_are_queued(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    result = register(client, complainant_phone="9999999999")
    monkeypatch.setattr(config, "REMINDER_BEFORE_DUE_HOURS", 4)
    now = datetime.now(timezone.utc)
    with client.app.state.testing_session_factory() as session:
        complaint = session.scalar(select(Complaint).where(Complaint.complaint_id == result["complaint_id"]))
        authority = session.get(Authority, complaint.assigned_authority_id)
        authority.phone = "9000000001"
        complaint.due_at = now + timedelta(hours=2)
        session.commit()
        notifications_before = session.query(Notification).filter(Notification.complaint_id == complaint.id).count()
        first = run_followup_job(session, now)
        notifications_after_first = session.query(Notification).filter(Notification.complaint_id == complaint.id).count()
        second = run_followup_job(session, now)
        notifications_after_second = session.query(Notification).filter(Notification.complaint_id == complaint.id).count()
        assert first["due_soon"] == 1  # one complaint received the reminder
        assert second["due_soon"] == 0
        assert notifications_after_first - notifications_before == 2  # authority in-app + SMS rows
        assert notifications_after_second == notifications_after_first  # retry created no rows
        deliveries = session.scalars(select(Notification).where(
            Notification.complaint_id == complaint.id,
            Notification.recipient_role == authority.role,
        )).all()
        assert {item.channel for item in deliveries} == {"inapp", "sms"}
        assert all(item.recipient_phone == "9000000001" for item in deliveries if item.channel == "sms")
        assert session.query(ActionLog).filter(ActionLog.complaint_id == complaint.id, ActionLog.action_type == "reminder_sent").count() == 1


def test_reminder_without_authority_phone_queues_only_inapp(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    result = register(client)
    monkeypatch.setattr(config, "REMINDER_BEFORE_DUE_HOURS", 4)
    now = datetime.now(timezone.utc)
    with client.app.state.testing_session_factory() as session:
        complaint = session.scalar(select(Complaint).where(Complaint.complaint_id == result["complaint_id"]))
        authority = session.get(Authority, complaint.assigned_authority_id)
        assert authority.phone is None  # seeded authorities have no phone by default
        complaint.due_at = now + timedelta(hours=2)
        session.commit()
        before = session.query(Notification).filter(Notification.complaint_id == complaint.id).count()
        first = run_followup_job(session, now)
        after_first = session.query(Notification).filter(Notification.complaint_id == complaint.id).count()
        second = run_followup_job(session, now)
        after_second = session.query(Notification).filter(Notification.complaint_id == complaint.id).count()
        assert first["due_soon"] == 1
        assert after_first - before == 1
        delivery = session.scalar(select(Notification).where(Notification.complaint_id == complaint.id))
        assert delivery.recipient_role == authority.role
        assert delivery.channel == "inapp"
        assert second["due_soon"] == 0
        assert after_second == after_first


def test_escalation_chain_reaches_superintendent_then_dho(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(config, "ESCALATE_AFTER_OVERDUE_HOURS", 1)
    monkeypatch.setattr(config, "ESCALATION_REPEAT_HOURS", 1)
    result = register(client, description="Medicine unavailable", hospital_id=1)
    base = datetime.now(timezone.utc)
    with client.app.state.testing_session_factory() as session:
        complaint = session.scalar(select(Complaint).where(Complaint.complaint_id == result["complaint_id"]))
        complaint.due_at = base - timedelta(hours=3)
        session.commit()
        run_followup_job(session, base)
        session.refresh(complaint)
        first_target = session.get(Authority, complaint.assigned_authority_id)
        assert first_target.role == "Medical Superintendent"
        assert complaint.escalation_level == 1
        run_followup_job(session, base + timedelta(hours=2))
        session.refresh(complaint)
        second_target = session.get(Authority, complaint.assigned_authority_id)
        assert second_target.role == "District Health Officer"
        assert complaint.escalation_level == 2


def test_backdate_endpoint_disabled_when_demo_mode_off(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(config, "DEMO_MODE", False)
    result = register(client)
    response = client.post(f"/api/demo/backdate/{result['complaint_id']}?hours=48", headers={"X-API-Key": "test-officer-key"})
    assert response.status_code == 404


def test_phone_inbox_and_demo_status_gated_when_demo_mode_off(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(config, "DEMO_MODE", False)
    assert client.get("/api/demo/status").json() == {"demo_mode": False}
    assert client.get("/sms").status_code == 404
    response = client.post("/api/sms/inbox", json={"phone": "12025550101"})
    assert response.status_code == 404
    monkeypatch.setattr(config, "DEMO_MODE", True)
    assert client.get("/sms").status_code == 200


def test_status_change_queues_complainant_notifications(client: TestClient):
    result = register(client, complainant_phone="9999999999")
    url = f"/api/complaints/{result['complaint_id']}"
    headers = {"X-API-Key": "test-officer-key"}
    response = client.patch(url, headers=headers, json={"status": "In Progress", "action_note": "Work started"})
    assert response.status_code == 200
    response = client.get("/api/notifications", headers=headers)
    assert response.status_code == 200
    items = response.json()["items"]
    assert any(item["recipient_role"] == "Complainant" and "started" in item["message"] for item in items)


def test_stats_counts_sla_and_recurring_issue_threshold(client: TestClient):
    from app.models import Hospital

    now = datetime.now(timezone.utc)
    with client.app.state.testing_session_factory() as session:
        hospital1 = session.get(Hospital, 1)
        hospital2 = session.get(Hospital, 2)
        samples = [
            Complaint(complaint_id="SD-STATS-00001", hospital_id=hospital1.id, category="Medicine Unavailable",
                      description="[TEST] Pharmacy service delay", language="en", channel="assisted", status="Assigned",
                      priority="medium", created_at=now-timedelta(days=1), due_at=now-timedelta(hours=1), escalation_level=1),
            Complaint(complaint_id="SD-STATS-00002", hospital_id=hospital1.id, category="Medicine Unavailable",
                      description="[TEST] Pharmacy queue delay", language="en", channel="assisted", status="Resolved",
                      priority="low", created_at=now-timedelta(days=2), due_at=now-timedelta(days=1)+timedelta(hours=13),
                      resolved_at=now-timedelta(days=1)+timedelta(hours=12)),
            Complaint(complaint_id="SD-STATS-00003", hospital_id=hospital1.id, category="Medicine Unavailable",
                      description="[TEST] Pharmacy counter service delay", language="en", channel="assisted", status="Closed",
                      priority="low", created_at=now-timedelta(days=3), due_at=now-timedelta(days=2)-timedelta(hours=1),
                      resolved_at=now-timedelta(days=2)),
            Complaint(complaint_id="SD-STATS-00004", hospital_id=hospital2.id, category="Medicine Unavailable",
                      description="[TEST] Pharmacy service delay", language="en", channel="assisted", status="Assigned",
                      priority="medium", created_at=now-timedelta(days=1), due_at=now+timedelta(days=1)),
            Complaint(complaint_id="SD-STATS-00005", hospital_id=hospital2.id, category="Medicine Unavailable",
                      description="[TEST] Pharmacy counter delay", language="en", channel="assisted", status="Assigned",
                      priority="medium", created_at=now-timedelta(days=2), due_at=now+timedelta(days=1)),
        ]
        session.add_all(samples)
        session.commit()

    response = client.get(
        f"/api/stats?start_date={(now.date()-timedelta(days=4)).isoformat()}&end_date={now.date().isoformat()}",
        headers={"X-API-Key": "test-officer-key"},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["total"] == 5
    assert data["totals_by_status"]["Assigned"] == 3
    assert data["totals_by_status"]["Resolved"] == 1
    assert data["totals_by_status"]["Closed"] == 1
    assert data["overdue_count"] == 1
    assert data["escalated_count"] == 1
    assert data["average_resolution_hours"] == 30
    assert data["resolved_within_sla_percent"] == 50
    assert len(data["complaints_per_day"]) == 14
    assert data["recurring_issues"] == [{
        "hospital_id": 1, "hospital": "District Hospital Kalaburagi",
        "category": "Medicine Unavailable", "count": 3,
    }]


def test_dashboard_is_served_locally_without_external_assets(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(config, "DEMO_MODE", True)
    response = client.get("/dashboard")
    assert response.status_code == 200
    assert "dashboard.html" not in response.text
    assert "https://" not in response.text
    assert "cdn." not in response.text
    assert "api/stats" in response.text
    for path, marker in (("/assisted", "/api/complaints/assisted"), ("/ivr", "/api/ivr/session"), ("/sms", "/api/sms/inbox")):
        page = client.get(path)
        assert page.status_code == 200
        assert marker in page.text
    monkeypatch.setattr(config, "DEMO_MODE", False)
    assert client.get("/sms").status_code == 404


def _ivr_input(client: TestClient, session_id: str, **payload) -> dict:
    response = client.post(f"/api/ivr/session/{session_id}/input", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def test_ivr_register_flow_creates_ivr_complaint(client: TestClient):
    start = client.post("/api/ivr/session")
    assert start.status_code == 200
    data = start.json()
    assert data["expects"] == "digit"
    assert "1" in data["prompt_text"] and "2" in data["prompt_text"] and "9" in data["prompt_text"]
    sid = data["session_id"]
    language_prompt = _ivr_input(client, sid, digit="1")
    assert language_prompt["expects"] == "digit"
    hospital_prompt = _ivr_input(client, sid, digit="1")
    assert hospital_prompt["expects"] == "digit" and "ಆಸ್ಪತ್ರೆ" in hospital_prompt["prompt_text"]
    step = _ivr_input(client, sid, digit="1")
    assert step["expects"] == "voice"
    confirm = _ivr_input(client, sid, speech="There is no drinking water at the public water point.")
    assert confirm["expects"] == "digit"
    created = _ivr_input(client, sid, digit="1")
    assert created["expects"] == "digit"
    assert created["complaint_id"].startswith("SD-")
    assert "2 0 2 6" in created["prompt_text"]
    finished = _ivr_input(client, sid, digit="2")
    assert finished["expects"] == "end"
    with client.app.state.testing_session_factory() as session:
        complaint = session.scalar(select(Complaint).where(Complaint.complaint_id == created["complaint_id"]))
        assert complaint is not None and complaint.channel == "ivr"
        assert complaint.status == "Assigned"
        assert complaint.complainant_phone is None


def test_ivr_status_flow_emergency_and_invalid_keypress(client: TestClient):
    registered = register(client, description="Water supply is unavailable", language="en")
    start = client.post("/api/ivr/session").json()
    sid = start["session_id"]
    _ivr_input(client, sid, digit="7")
    invalid = _ivr_input(client, sid, digit="7")
    assert invalid["expects"] == "digit"
    assert "ಸರಿಯಲ್ಲ" in invalid["prompt_text"]
    _ivr_input(client, sid, digit="2")
    _ivr_input(client, sid, digit="2")  # English
    complaint_digits = registered["complaint_id"].replace("SD-", "").replace("-", "")
    for digit in complaint_digits:
        result = _ivr_input(client, sid, digit=digit)
    assert result["expects"] == "digit"
    status_result = _ivr_input(client, sid, digit="#")
    assert status_result["expects"] == "end"
    assert status_result["status"] == "Assigned"
    assert registered["complaint_id"] in status_result["prompt_text"]

    emergency_session = client.post("/api/ivr/session").json()
    emergency = _ivr_input(client, emergency_session["session_id"], digit="9")
    assert emergency["expects"] == "end"
    assert emergency["emergency"] is True
    assert "108" in emergency["prompt_text"]


def test_ivr_emergency_keyword_ends_without_normal_complaint(client: TestClient):
    start = client.post("/api/ivr/session").json()
    sid = start["session_id"]
    _ivr_input(client, sid, digit="1")
    _ivr_input(client, sid, digit="1")
    _ivr_input(client, sid, digit="1")
    result = _ivr_input(client, sid, speech="There has been an accident and bleeding.")
    assert result["expects"] == "end"
    assert result["emergency"] is True
    with client.app.state.testing_session_factory() as session:
        assert session.scalar(select(Complaint).where(Complaint.is_emergency_flagged.is_(False))) is None


def test_missed_call_callback_masks_phone_and_can_be_completed(client: TestClient):
    response = client.post("/api/ivr/missed-call", json={"phone": "9876543210", "hospital_id": 1})
    assert response.status_code == 201, response.text
    item = response.json()
    assert item["phone_masked"] == "98XXXXXX10"
    assert "9876543210" not in str(item)
    with client.app.state.testing_session_factory() as session:
        stored = session.get(CallbackRequest, item["id"])
        assert stored.phone_masked == "98XXXXXX10"
        assert not hasattr(stored, "phone")
    headers = {"X-API-Key": "test-officer-key"}
    callbacks = client.get("/api/callbacks", headers=headers)
    assert callbacks.status_code == 200
    assert callbacks.json()[0]["phone_masked"] == "98XXXXXX10"
    called = client.patch(f"/api/callbacks/{item['id']}", headers=headers)
    assert called.status_code == 200
    assert called.json()["status"] == "Called back"


def test_assisted_registration_requires_and_logs_operator_reference(client: TestClient):
    payload = {
        "description": "The public water point has no drinking water.",
        "language": "en", "hospital_id": 1, "channel": "assisted",
        "registered_by": "ASHA-07",
    }
    response = client.post("/api/complaints/assisted", json=payload)
    assert response.status_code == 201, response.text
    with client.app.state.testing_session_factory() as session:
        complaint = session.scalar(select(Complaint).where(Complaint.complaint_id == response.json()["complaint_id"]))
        assert complaint.channel == "assisted"
        log = session.scalar(select(ActionLog).where(ActionLog.complaint_id == complaint.id, ActionLog.action_type == "registered"))
        assert "ASHA-07" in log.note
    missing = client.post("/api/complaints/assisted", json={key: value for key, value in payload.items() if key != "registered_by"})
    assert missing.status_code == 422


def test_ivr_sms_offer_queues_number_and_phone_inbox_reads_it(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(config, "DEMO_MODE", True)
    start = client.post("/api/ivr/session").json()
    sid = start["session_id"]
    _ivr_input(client, sid, digit="1")
    _ivr_input(client, sid, digit="2")  # English
    hospital_prompt = _ivr_input(client, sid, digit="1")
    assert hospital_prompt["expects"] == "voice"
    _ivr_input(client, sid, speech="The drinking water supply is unavailable.")
    created = _ivr_input(client, sid, digit="1")
    _ivr_input(client, sid, digit="1")  # opt into SMS
    sms = _ivr_input(client, sid, digits="9876543210")
    assert sms["expects"] == "end" and sms["sms_queued"] is True
    inbox = client.post("/api/sms/inbox", json={"phone": "9876543210"})
    assert inbox.status_code == 200
    assert any(item["complaint_id"] == created["complaint_id"] and created["complaint_id"] in item["message"]
               for item in inbox.json()["messages"])
    monkeypatch.setattr(config, "DEMO_MODE", False)
    assert client.get("/sms").status_code == 404
    assert client.post("/api/sms/inbox", json={"phone": "9876543210"}).status_code == 404


def test_speak_error_returns_machine_readable_reason(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.routers import voice
    from app.services.sarvam import SarvamUnavailable

    async def fail_speech(text, language):
        raise SarvamUnavailable("Sarvam TTS returned HTTP 422: invalid speaker")

    monkeypatch.setattr(voice, "synthesize_speech", fail_speech)
    client = TestClient(app)
    response = client.post("/api/voice/speak", json={"text": "test", "language": "kn"})
    client.close()
    assert response.status_code == 503
    assert response.json()["detail"] == {
        "error": "sarvam_tts_failed",
        "reason": "Sarvam TTS returned HTTP 422: invalid speaker",
    }
