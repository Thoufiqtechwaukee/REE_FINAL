from app.agents.responsibility_classifier import classify_bullet, classify_role


def test_task_execution_bullet():
    rank, label = classify_bullet("Developed and implemented new REST endpoints")
    assert label == "TASK_EXECUTION"


def test_ownership_bullet():
    rank, label = classify_bullet("Owned the delivery of the payments migration end to end")
    assert label == "OWNERSHIP"


def test_architecture_bullet():
    rank, label = classify_bullet("Architected a microservices-based event-driven system")
    assert label == "ARCHITECTURE"


def test_mentoring_leadership_bullet():
    rank, label = classify_bullet("Mentored junior engineers and led the team through the migration")
    assert label == "MENTORING_LEADERSHIP"


def test_classify_role_takes_highest_bucket():
    label, leadership, ownership = classify_role([
        "Implemented assigned features",
        "Owned backend services",
        "Designed service architecture and mentored junior developers",
    ])
    assert label == "MENTORING_LEADERSHIP"
    assert len(leadership) == 1
    assert len(ownership) == 2  # the "owned" bullet and the "mentored...architecture" bullet


def test_classify_role_flat_task_execution_only():
    label, leadership, ownership = classify_role([
        "Developed features",
        "Implemented bug fixes",
        "Wrote unit tests",
    ])
    assert label == "TASK_EXECUTION"
    assert leadership == []
    assert ownership == []


def test_classify_role_empty_defaults_safely():
    label, leadership, ownership = classify_role([])
    assert label == "TASK_EXECUTION"
    assert leadership == []
    assert ownership == []
