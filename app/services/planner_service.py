from datetime import date, timedelta

from app.models import Topic, TopicMastery, Unit


def build_exam_plan(user_id, course, today=None):
    """Build focus blocks that fit the user's daily capacity and reserve final revision."""
    today = today or date.today()
    if not course.exam_date:
        raise ValueError("Add an exam date before generating a plan.")
    days_left = (course.exam_date - today).days
    if days_left < 1:
        raise ValueError("Choose an exam date at least one day in the future.")

    topics = (
        Topic.query.join(Topic.unit)
        .filter(Unit.course_id == course.id)
        .all()
    )
    assessed = []
    unassessed = []
    urgency = 1 + 1 / days_left
    for topic in topics:
        mastery = TopicMastery.query.filter_by(user_id=user_id, topic_id=topic.id).first()
        if mastery is None:
            unassessed.append((topic.weightage * urgency, topic, None, "coverage"))
        else:
            priority = topic.weightage * (1 - mastery.score) * urgency
            assessed.append((priority, topic, mastery, "mastery"))
    unassessed.sort(key=lambda entry: entry[0], reverse=True)
    assessed.sort(key=lambda entry: entry[0], reverse=True)
    ranked = unassessed + assessed

    study_days = days_left - 1
    available_minutes = int(course.available_hours_per_day * 60)
    session_minutes = min(25, available_minutes)
    sessions_per_day = max(1, available_minutes // session_minutes)
    session_capacity = study_days * sessions_per_day
    revision_date = today + timedelta(days=study_days)
    sessions = []
    for index, (_, topic, mastery, basis) in enumerate(ranked[:session_capacity]):
        session_day = today + timedelta(days=index // sessions_per_day)
        sessions.append(
            {
                "date": session_day,
                "topic": topic,
                "mastery": mastery,
                "minutes": session_minutes,
                "priority": index + 1,
                "basis": basis,
            }
        )
    return {
        "days_left": days_left,
        "sessions": sessions,
        "unscheduled_topics": [topic for _, topic, _, _ in ranked[session_capacity:]],
        "revision_date": revision_date,
        "sessions_per_day": sessions_per_day,
    }
