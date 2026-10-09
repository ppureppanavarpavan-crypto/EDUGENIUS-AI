from app.extensions import db
from app.models import MasteryEvent, TopicMastery, TopicPrerequisite


def record_result(user_id, topic_id, result, event_type="quiz"):
    """Update an exponentially weighted topic score and persist its source event."""
    if not 0 <= result <= 1:
        raise ValueError("Result must be between 0 and 1.")

    mastery = TopicMastery.query.filter_by(user_id=user_id, topic_id=topic_id).first()
    if mastery is None:
        mastery = TopicMastery(user_id=user_id, topic_id=topic_id, score=result, attempts=1)
        db.session.add(mastery)
    else:
        alpha = 0.35
        mastery.score = alpha * result + (1 - alpha) * mastery.score
        mastery.attempts += 1

    db.session.add(
        MasteryEvent(user_id=user_id, topic_id=topic_id, event_type=event_type, result=result)
    )
    db.session.flush()
    return mastery


def prerequisite_suggestions(user_id, topic_id):
    mastery = TopicMastery.query.filter_by(user_id=user_id, topic_id=topic_id).first()
    if mastery is None or mastery.score >= 0.6:
        return []

    links = TopicPrerequisite.query.filter_by(topic_id=topic_id).all()
    suggestions = []
    for link in links:
        prerequisite = TopicMastery.query.filter_by(
            user_id=user_id, topic_id=link.prerequisite_topic_id
        ).first()
        if prerequisite is None or prerequisite.score < 0.7:
            suggestions.append(link.prerequisite_topic)
    return suggestions
