from schema import PERMANENT_TYPES, SINGLETON_TYPES, Memory, SessionEvent


def test_memory_defaults():
    m = Memory(
        project_id="p1",
        session_id="s1",
        type="progress",
        content="did a thing",
        agent="claude-code",
    )
    assert m.id
    assert 0.0 <= m.importance <= 1.0
    assert m.superseded_by is None


def test_permanent_types_pin_importance_to_one():
    m = Memory(
        project_id="p1",
        session_id="s1",
        type="failed_attempt",
        content="tried X, failed",
        agent="codex",
        importance=0.2,
    )
    assert m.importance == 1.0

    m2 = Memory(
        project_id="p1",
        session_id="s1",
        type="decision",
        content="chose FastAPI",
        agent="codex",
        importance=0.3,
    )
    assert m2.importance == 1.0


def test_non_permanent_type_keeps_given_importance():
    m = Memory(
        project_id="p1",
        session_id="s1",
        type="progress",
        content="phase 1 done",
        agent="claude-code",
        importance=0.6,
    )
    assert m.importance == 0.6


def test_singleton_and_permanent_type_sets_are_disjoint_and_cover_expected_types():
    assert SINGLETON_TYPES == {"current_state", "next_step"}
    assert PERMANENT_TYPES == {"decision", "failed_attempt"}
    assert not (SINGLETON_TYPES & PERMANENT_TYPES)


def test_session_event_defaults():
    event = SessionEvent(
        project_id="p1",
        session_id="s1",
        agent="codex",
        tool="checkpoint",
        memories_affected=["m1", "m2"],
    )
    assert event.id
    assert event.memories_affected == ["m1", "m2"]
