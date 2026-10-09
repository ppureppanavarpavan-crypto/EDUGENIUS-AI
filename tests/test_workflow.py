from datetime import date, timedelta

from app.extensions import db
from app.models import (
    Course,
    Flashcard,
    HintSession,
    Note,
    StudyTask,
    Topic,
    TopicMastery,
    TopicPrerequisite,
    Unit,
    User,
)
from app.services.flashcard_service import schedule_next_review
from app.services.ai_service import AIServiceError
from app.services.planner_service import build_exam_plan
from app.services.planner_service import build_exam_plan


def test_registration_and_password_hashing(app, client):
    response = client.post(
        "/register",
        data={
            "name": "Ari Student",
            "email": "ARI@example.edu",
            "academic_level": "Computer Science",
            "password": "correct-horse-battery",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Semester command center" in response.data
    with app.app_context():
        user = User.query.filter_by(email="ari@example.edu").one()
        assert user.password_hash != "correct-horse-battery"
        assert user.check_password("correct-horse-battery")


def test_registration_rejects_short_password(app, client):
    response = client.post(
        "/register",
        data={"name": "Ari", "email": "ari@example.edu", "password": "short"},
    )
    assert b"at least 10 characters" in response.data
    with app.app_context():
        assert User.query.count() == 0


def test_syllabus_quiz_updates_mastery_and_suggests_prerequisite(app, client, register_user):
    register_user(client, "Ari", "ari@example.edu")
    with app.app_context():
        user = User.query.filter_by(email="ari@example.edu").one()
        course = Course(user_id=user.id, name="Engineering Mathematics", branch="Engineering")
        db.session.add(course)
        db.session.flush()
        unit = Unit(course_id=course.id, title="Transforms")
        foundation_unit = Unit(course_id=course.id, title="Foundations")
        db.session.add_all([unit, foundation_unit])
        db.session.flush()
        advanced = Topic(unit_id=unit.id, title="Inverse Laplace transforms", weightage=14)
        foundation = Topic(unit_id=foundation_unit.id, title="Partial fractions", weightage=4)
        db.session.add_all([advanced, foundation])
        db.session.commit()
        advanced_id, foundation_id = advanced.id, foundation.id

    response = client.post(
        f"/topics/{advanced_id}/prerequisites",
        data={"prerequisite_topic_id": foundation_id},
        follow_redirects=True,
    )
    assert response.status_code == 200
    with app.app_context():
        assert TopicPrerequisite.query.filter_by(
            topic_id=advanced_id, prerequisite_topic_id=foundation_id
        ).count() == 1

    response = client.post(
        f"/topics/{advanced_id}/quiz",
        data={
            "prompt[]": ["What is the first step?", "Which property applies?"],
            "option_a[]": ["Identify the pole", "Linearity"],
            "option_b[]": ["Guess", "Randomness"],
            "option_c[]": ["Skip", "None"],
            "option_d[]": ["Copy", "All"],
            "correct[]": ["0", "0"],
        },
    )
    assert response.status_code == 302
    quiz_path = response.headers["Location"]

    quiz_page = client.get(quiz_path)
    assert quiz_page.status_code == 200
    assert b"Correct answer:" not in quiz_page.data

    from app.models import Quiz
    with app.app_context():
        quiz_id = int(quiz_path.rsplit("/", 1)[1])
        quiz = db.session.get(Quiz, quiz_id)
        answers = {f"answer_{question.id}": "1" for question in quiz.questions}
    result = client.post(quiz_path, data=answers)
    assert result.status_code == 302
    result_page = client.get(result.headers["Location"])
    assert result_page.status_code == 200
    assert b"Prerequisite detective" in result_page.data
    assert b"Partial fractions" in result_page.data

    with app.app_context():
        mastery = TopicMastery.query.filter_by(topic_id=advanced_id).one()
        assert mastery.score == 0
        assert mastery.attempts == 1
    assert b"Correct answer:" not in quiz_page.data


def test_cross_user_course_access_returns_404(app, client, register_user):
    register_user(client, "Ari", "ari@example.edu")
    with app.app_context():
        owner = User.query.filter_by(email="ari@example.edu").one()
        course = Course(user_id=owner.id, name="Private course")
        db.session.add(course)
        db.session.commit()
        course_id = course.id

    other_client = app.test_client()
    register_user(other_client, "Sam", "sam@example.edu")
    response = other_client.get(f"/courses/{course_id}")
    assert response.status_code == 404


def test_exam_plan_ranks_low_mastery_topics_and_rejects_past_date(app):
    with app.app_context():
        user = User(name="Ari", email="ari@example.edu")
        user.set_password("correct-horse-battery")
        course = Course(user=user, name="Engineering Math", exam_date=date.today() + timedelta(days=5))
        unit = Unit(course=course, title="Transforms")
        weak = Topic(unit=unit, title="Inverse transforms", weightage=14)
        strong = Topic(unit=unit, title="Laplace basics", weightage=4)
        db.session.add_all([user, course, unit, weak, strong])
        db.session.flush()
        db.session.add(
            TopicMastery(user_id=user.id, topic_id=strong.id, score=0.9, attempts=4)
        )
        db.session.commit()

        plan = build_exam_plan(user.id, course)
        assert plan["days_left"] == 5
        assert plan["sessions"][0]["topic"].title == "Inverse transforms"
        assert plan["sessions"][0]["mastery"] is None

        course.exam_date = date.today() - timedelta(days=1)
        try:
            build_exam_plan(user.id, course)
        except ValueError as error:
            assert "future" in str(error)
        else:
            raise AssertionError("Past exam date should be rejected.")


def test_hint_ladder_is_demo_labeled_and_logs_solution(app, client, register_user, monkeypatch):
    monkeypatch.delenv("AI_API_KEY", raising=False)
    register_user(client, "Ari", "ari@example.edu")
    problem = "Explain how binary search narrows a sorted array."

    first = client.post("/tutor", data={"problem": problem, "rung": "1"})
    assert first.status_code == 200
    assert b"[DEMO MODE]" in first.data
    assert b"REST" not in first.data

    with app.app_context():
        hint_session = HintSession.query.filter_by(user_id=1).one()
        session_id = hint_session.id
        assert hint_session.highest_rung == 1
        assert hint_session.solution_viewed is False

    for rung in range(2, 6):
        response = client.post(
            "/tutor",
            data={
                "problem": problem,
                "rung": str(rung),
                "hint_session_id": str(session_id),
            },
        )
        assert response.status_code == 200
        assert b"[DEMO MODE]" in response.data

    with app.app_context():
        hint_session = db.session.get(HintSession, session_id)
        assert hint_session.highest_rung == 5
        assert hint_session.solution_viewed is True


def test_code_explainer_never_executes_or_claims_analysis(client, register_user, monkeypatch):
    monkeypatch.delenv("AI_API_KEY", raising=False)
    register_user(client, "Ari", "ari@example.edu")
    response = client.post(
        "/code-explainer",
        data={"code": "raise RuntimeError('must not run')", "sample_input": ""},
    )
    assert response.status_code == 200
    assert b"no code analysis was produced" in response.data.lower()
    assert b"never executed" in response.data.lower()


def test_syllabus_import_rejects_unsupported_files(app, client, register_user):
    from io import BytesIO

    register_user(client, "Ari", "ari@example.edu")
    response = client.post(
        "/syllabus/import",
        data={"syllabus": (BytesIO(b"Course | Unit | Topic"), "syllabus.exe")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 302
    with app.app_context():
        assert Course.query.count() == 0


def test_exam_plan_page_requires_owner_login(app, client, register_user):
    register_user(client, "Ari", "ari@example.edu")
    with app.app_context():
        user = User.query.filter_by(email="ari@example.edu").one()
        course = Course(user_id=user.id, name="Private course")
        db.session.add(course)
        db.session.commit()
        course_id = course.id

    anonymous = app.test_client()
    response = anonymous.get(f"/courses/{course_id}/exam-plan")
    assert response.status_code == 302
    assert response.headers["Location"].startswith("/login")


def test_exam_plan_preserves_unknown_mastery_and_respects_capacity(app, client, register_user):
    register_user(client, "Ari", "ari@example.edu")
    with app.app_context():
        user = User.query.filter_by(email="ari@example.edu").one()
        course = Course(
            user_id=user.id,
            name="Algorithms",
            exam_date=date.today() + timedelta(days=3),
            available_hours_per_day=0.25,
        )
        unit = Unit(course=course, title="Searching")
        unknown = Topic(unit=unit, title="Binary search", weightage=10)
        assessed = Topic(unit=unit, title="Linear search", weightage=5)
        db.session.add_all([course, unit, unknown, assessed])
        db.session.flush()
        db.session.add(
            TopicMastery(user_id=user.id, topic_id=assessed.id, score=0.9, attempts=1)
        )
        db.session.commit()

        plan = build_exam_plan(user.id, course, today=date.today())

        assert plan["sessions"][0]["topic"].title == "Binary search"
        assert plan["sessions"][0]["mastery"] is None
        assert plan["sessions"][0]["basis"] == "coverage"
        assert all(session["minutes"] <= 15 for session in plan["sessions"])
        assert all(session["date"] < plan["revision_date"] for session in plan["sessions"])
        assert plan["revision_date"] == date.today() + timedelta(days=2)


def test_tutor_provider_failure_is_not_saved_as_a_success(app, client, register_user, monkeypatch):
    register_user(client, "Ari", "ari@example.edu")
    monkeypatch.setattr("app.routes.main.is_available", lambda: True)

    def fail_provider(problem, rung, topic_title=None):
        assert problem == "Explain recursion."
        assert rung == 1
        assert topic_title is None
        raise AIServiceError("provider unavailable")

    monkeypatch.setattr("app.routes.main.hint_response", fail_provider)
    response = client.post(
        "/tutor",
        data={"problem": "Explain recursion.", "rung": "1"},
    )

    assert response.status_code == 503
    assert b"provider unavailable" in response.data
    with app.app_context():
        assert HintSession.query.count() == 0


def _add_course_topic(user, title="Transforms"):
    course = Course(user_id=user.id, name="Engineering Mathematics")
    unit = Unit(course=course, title="Unit 1")
    topic = Topic(unit=unit, title=title, weightage=4)
    db.session.add(course)
    db.session.commit()
    return course, topic


def test_notes_are_editable_and_private(app, client, register_user):
    register_user(client, "Ari", "ari@example.edu")
    with app.app_context():
        user = User.query.filter_by(email="ari@example.edu").one()
        _, topic = _add_course_topic(user)
        topic_id = topic.id

    response = client.post(
        "/notes",
        data={"title": "Laplace pairs", "content": "Check the initial conditions.", "topic_id": str(topic_id)},
    )
    assert response.status_code == 302
    assert client.get("/notes").status_code == 200
    with app.app_context():
        note = Note.query.filter_by(user_id=1, title="Laplace pairs").one()
        note_id = note.id

    stranger = app.test_client()
    register_user(stranger, "Sam", "sam@example.edu")
    assert stranger.get(f"/notes/{note_id}/edit").status_code == 404
    assert stranger.post(f"/notes/{note_id}/delete").status_code == 404
    assert client.get(f"/notes/{note_id}/edit").status_code == 200
    client.post(
        f"/notes/{note_id}/edit",
        data={"title": "Updated pairs", "content": "Recheck conditions.", "topic_id": ""},
    )
    with app.app_context():
        note = db.session.get(Note, note_id)
        assert note.title == "Updated pairs"
        assert note.topic_id is None


def test_flashcard_intervals_and_early_review_guard(app, client, register_user):
    register_user(client, "Ari", "ari@example.edu")
    with app.app_context():
        user = User.query.filter_by(email="ari@example.edu").one()
        _, topic = _add_course_topic(user)
        topic_id = topic.id

    response = client.post(
        "/flashcards",
        data={
            "topic_id": str(topic_id),
            "question": "What is the Laplace transform of 1?",
            "answer": "1/s, for s > 0.",
        },
    )
    assert response.status_code == 302
    assert client.get("/flashcards").status_code == 200
    with app.app_context():
        card = Flashcard.query.filter_by(user_id=1).one()
        card_id = card.id

    assert client.post(
        f"/flashcards/{card_id}/review", data={"quality": "5"}
    ).status_code == 302
    with app.app_context():
        card = db.session.get(Flashcard, card_id)
        assert card.review_count == 1
        assert card.review_interval == 1
    assert client.get("/flashcards").status_code == 200
    client.post(f"/flashcards/{card_id}/review", data={"quality": "5"})
    with app.app_context():
        card = db.session.get(Flashcard, card_id)
        assert card.review_count == 1
        assert card.review_interval == 1


def test_flashcard_low_recall_resets_interval():
    from types import SimpleNamespace
    from datetime import datetime, timezone

    card = SimpleNamespace(review_count=3, review_interval=14, next_review_at=None)
    schedule_next_review(card, quality=2, now=datetime(2025, 1, 1, tzinfo=timezone.utc))
    assert card.review_count == 0
    assert card.review_interval == 1
    assert card.next_review_at == datetime(2025, 1, 2, tzinfo=timezone.utc)


def test_tasks_are_course_scoped_and_completion_is_persisted(app, client, register_user):
    register_user(client, "Ari", "ari@example.edu")
    with app.app_context():
        user = User.query.filter_by(email="ari@example.edu").one()
        course, _ = _add_course_topic(user)
        course_id = course.id

    response = client.post(
        "/tasks",
        data={
            "title": "Finish problem set",
            "course_id": str(course_id),
            "due_date": (date.today() + timedelta(days=2)).isoformat(),
            "estimated_minutes": "45",
        },
    )
    assert response.status_code == 302
    assert client.get("/tasks").status_code == 200
    with app.app_context():
        task = StudyTask.query.filter_by(user_id=1).one()
        task_id = task.id

    client.post(f"/tasks/{task_id}/toggle")
    assert client.get("/analytics").status_code == 200
    with app.app_context():
        assert db.session.get(StudyTask, task_id).completed is True
