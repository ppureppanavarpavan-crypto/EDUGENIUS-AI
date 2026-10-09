from datetime import datetime, timezone

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db


def utcnow():
    return datetime.now(timezone.utc)


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(254), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="student")
    academic_level = db.Column(db.String(80), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    courses = db.relationship("Course", back_populates="user", cascade="all, delete-orphan")
    preferences = db.relationship(
        "UserPreference", back_populates="user", uselist=False, cascade="all, delete-orphan"
    )

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class UserPreference(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), unique=True)
    theme = db.Column(db.String(20), nullable=False, default="light")
    weekly_availability = db.Column(db.Integer, nullable=False, default=14)
    user = db.relationship("User", back_populates="preferences")


class Course(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    branch = db.Column(db.String(100), nullable=False, default="")
    semester = db.Column(db.String(30), nullable=False, default="")
    exam_date = db.Column(db.Date, nullable=True)
    available_hours_per_day = db.Column(db.Float, nullable=False, default=2)
    is_demo = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    user = db.relationship("User", back_populates="courses")
    units = db.relationship("Unit", back_populates="course", cascade="all, delete-orphan", order_by="Unit.position")


class Unit(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey("course.id", ondelete="CASCADE"), nullable=False, index=True)
    title = db.Column(db.String(120), nullable=False)
    position = db.Column(db.Integer, nullable=False, default=1)
    course = db.relationship("Course", back_populates="units")
    topics = db.relationship("Topic", back_populates="unit", cascade="all, delete-orphan", order_by="Topic.position")


class Topic(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    unit_id = db.Column(db.Integer, db.ForeignKey("unit.id", ondelete="CASCADE"), nullable=False, index=True)
    title = db.Column(db.String(160), nullable=False)
    description = db.Column(db.Text, nullable=False, default="")
    weightage = db.Column(db.Float, nullable=False, default=1.0)
    position = db.Column(db.Integer, nullable=False, default=1)
    unit = db.relationship("Unit", back_populates="topics")
    mastery_records = db.relationship("TopicMastery", back_populates="topic", cascade="all, delete-orphan")
    events = db.relationship("MasteryEvent", back_populates="topic", cascade="all, delete-orphan")
    prerequisites = db.relationship(
        "TopicPrerequisite",
        foreign_keys="TopicPrerequisite.topic_id",
        back_populates="topic",
        cascade="all, delete-orphan",
    )


class TopicPrerequisite(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    topic_id = db.Column(db.Integer, db.ForeignKey("topic.id", ondelete="CASCADE"), nullable=False)
    prerequisite_topic_id = db.Column(db.Integer, db.ForeignKey("topic.id", ondelete="CASCADE"), nullable=False)
    topic = db.relationship("Topic", foreign_keys=[topic_id], back_populates="prerequisites")
    prerequisite_topic = db.relationship("Topic", foreign_keys=[prerequisite_topic_id])
    __table_args__ = (
        db.UniqueConstraint("topic_id", "prerequisite_topic_id"),
        db.CheckConstraint("topic_id != prerequisite_topic_id"),
    )


class TopicMastery(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    topic_id = db.Column(db.Integer, db.ForeignKey("topic.id", ondelete="CASCADE"), nullable=False, index=True)
    score = db.Column(db.Float, nullable=False)
    attempts = db.Column(db.Integer, nullable=False, default=0)
    last_updated = db.Column(db.DateTime, nullable=False, default=utcnow, onupdate=utcnow)
    topic = db.relationship("Topic", back_populates="mastery_records")
    __table_args__ = (db.UniqueConstraint("user_id", "topic_id"),)

    @property
    def confidence(self):
        return min(self.attempts / 5, 1.0)


class MasteryEvent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    topic_id = db.Column(db.Integer, db.ForeignKey("topic.id", ondelete="CASCADE"), nullable=False, index=True)
    event_type = db.Column(db.String(30), nullable=False)
    result = db.Column(db.Float, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow, index=True)
    topic = db.relationship("Topic", back_populates="events")


class Quiz(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    topic_id = db.Column(db.Integer, db.ForeignKey("topic.id", ondelete="CASCADE"), nullable=False)
    title = db.Column(db.String(160), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    questions = db.relationship("Question", back_populates="quiz", cascade="all, delete-orphan")
    topic = db.relationship("Topic")
    attempts = db.relationship("QuizAttempt", back_populates="quiz", cascade="all, delete-orphan")


class Question(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    quiz_id = db.Column(db.Integer, db.ForeignKey("quiz.id", ondelete="CASCADE"), nullable=False)
    prompt = db.Column(db.Text, nullable=False)
    options = db.Column(db.JSON, nullable=False)
    correct_option = db.Column(db.Integer, nullable=False)
    explanation = db.Column(db.Text, nullable=False, default="")
    quiz = db.relationship("Quiz", back_populates="questions")


class QuizAttempt(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    quiz_id = db.Column(db.Integer, db.ForeignKey("quiz.id", ondelete="CASCADE"), nullable=False)
    score = db.Column(db.Float, nullable=False)
    correct_count = db.Column(db.Integer, nullable=False)
    total_questions = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    quiz = db.relationship("Quiz", back_populates="attempts")


class StudyTask(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    course_id = db.Column(db.Integer, db.ForeignKey("course.id", ondelete="CASCADE"), nullable=False)
    title = db.Column(db.String(160), nullable=False)
    due_date = db.Column(db.Date, nullable=True)
    estimated_minutes = db.Column(db.Integer, nullable=False, default=30)
    completed = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    course = db.relationship("Course")


class Flashcard(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    topic_id = db.Column(db.Integer, db.ForeignKey("topic.id", ondelete="CASCADE"), nullable=False)
    question = db.Column(db.Text, nullable=False)
    answer = db.Column(db.Text, nullable=False)
    next_review_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    review_interval = db.Column(db.Integer, nullable=False, default=1)
    review_count = db.Column(db.Integer, nullable=False, default=0)
    topic = db.relationship("Topic")


class Note(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    topic_id = db.Column(db.Integer, db.ForeignKey("topic.id", ondelete="SET NULL"), nullable=True)
    title = db.Column(db.String(160), nullable=False)
    content = db.Column(db.Text, nullable=False, default="")
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    topic = db.relationship("Topic")


class Conversation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    title = db.Column(db.String(160), nullable=False, default="Study chat")
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)


class ChatMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey("conversation.id", ondelete="CASCADE"), nullable=False)
    role = db.Column(db.String(20), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)


class VivaSession(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    mode = db.Column(db.String(40), nullable=False)
    transcript = db.Column(db.JSON, nullable=False, default=list)
    feedback = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)


class HintSession(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    topic_id = db.Column(db.Integer, db.ForeignKey("topic.id", ondelete="SET NULL"), nullable=True)
    problem = db.Column(db.Text, nullable=False)
    highest_rung = db.Column(db.Integer, nullable=False, default=1)
    solution_viewed = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)


class LabExperiment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    course_id = db.Column(db.Integer, db.ForeignKey("course.id", ondelete="CASCADE"), nullable=False)
    title = db.Column(db.String(160), nullable=False)
    checklist_state = db.Column(db.JSON, nullable=False, default=dict)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
