from datetime import date, datetime, timezone

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models import (
    Course,
    Flashcard,
    HintSession,
    MasteryEvent,
    Note,
    Question,
    Quiz,
    QuizAttempt,
    StudyTask,
    Topic,
    TopicMastery,
    TopicPrerequisite,
    Unit,
)
from app.services.ai_service import (
    AIServiceError,
    RUNG_GUIDANCE,
    RUNG_LABELS,
    generate_response,
    hint_response,
    is_available,
)
from app.services.mastery_service import prerequisite_suggestions, record_result
from app.services.flashcard_service import schedule_next_review
from app.services.planner_service import build_exam_plan

main_bp = Blueprint("main", __name__)


def owned_course(course_id):
    course = Course.query.filter_by(id=course_id, user_id=current_user.id).first()
    if course is None:
        abort(404)
    return course


def owned_topic(topic_id):
    topic = (
        Topic.query.join(Topic.unit)
        .join(Unit.course)
        .filter(Topic.id == topic_id, Course.user_id == current_user.id)
        .first()
    )
    if topic is None:
        abort(404)
    return topic


@main_bp.route("/")
def index():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    return render_template("index.html")


@main_bp.route("/health")
def health():
    return {"status": "ok"}, 200


@main_bp.route("/dashboard")
@login_required
def dashboard():
    courses = Course.query.filter_by(user_id=current_user.id).order_by(Course.name).all()
    course_topics = []
    for course in courses:
        topics = Topic.query.join(Topic.unit).filter(Unit.course_id == course.id).all()
        assessed = [
            TopicMastery.query.filter_by(user_id=current_user.id, topic_id=topic.id).first()
            for topic in topics
        ]
        scored = [record for record in assessed if record]
        course_topics.append(
            {
                "course": course,
                "topics": topics,
                "assessed": len(scored),
                "average": round(sum(item.score for item in scored) / len(scored) * 100)
                if scored else None,
                "next_topics": sorted(
                    (
                        topic for topic in topics
                        if not TopicMastery.query.filter_by(
                            user_id=current_user.id, topic_id=topic.id
                        ).first()
                    ),
                    key=lambda topic: topic.weightage,
                    reverse=True,
                )[:3],
            }
        )
    recent_events = (
        MasteryEvent.query.filter_by(user_id=current_user.id)
        .order_by(MasteryEvent.created_at.desc())
        .limit(6)
        .all()
    )
    return render_template("dashboard.html", course_topics=course_topics, recent_events=recent_events)


@main_bp.route("/courses", methods=["GET", "POST"])
@login_required
def courses():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        branch = request.form.get("branch", "").strip()
        semester = request.form.get("semester", "").strip()
        if not name or len(name) > 120:
            flash("Enter a course name of 1 to 120 characters.", "error")
        else:
            db.session.add(
                Course(user_id=current_user.id, name=name, branch=branch[:100], semester=semester[:30])
            )
            db.session.commit()
            flash("Course added. You can now organize it into units and topics.", "success")
            return redirect(url_for("main.courses"))
    courses_list = Course.query.filter_by(user_id=current_user.id).order_by(Course.name).all()
    return render_template("courses.html", courses=courses_list)


@main_bp.route("/courses/<int:course_id>", methods=["GET", "POST"])
@login_required
def course_detail(course_id):
    course = owned_course(course_id)
    if request.method == "POST":
        unit_title = request.form.get("unit_title", "").strip()
        if unit_title and len(unit_title) <= 120:
            db.session.add(
                Unit(course_id=course.id, title=unit_title, position=len(course.units) + 1)
            )
            db.session.commit()
            flash("Unit added.", "success")
        else:
            flash("Enter a unit title of 1 to 120 characters.", "error")
        return redirect(url_for("main.course_detail", course_id=course.id))
    return render_template("course_detail.html", course=course)


@main_bp.post("/units/<int:unit_id>/topics")
@login_required
def add_topic(unit_id):
    unit = Unit.query.join(Unit.course).filter(
        Unit.id == unit_id, Course.user_id == current_user.id
    ).first_or_404()
    title = request.form.get("title", "").strip()
    raw_weightage = request.form.get("weightage", "1")
    try:
        weightage = float(raw_weightage)
    except ValueError:
        weightage = 0
    if not title or len(title) > 160 or not 0.1 <= weightage <= 100:
        flash("Enter a topic name and a weight between 0.1 and 100.", "error")
    else:
        db.session.add(
            Topic(unit_id=unit.id, title=title, weightage=weightage, position=len(unit.topics) + 1)
        )
        db.session.commit()
        flash("Topic added to your syllabus.", "success")
    return redirect(url_for("main.course_detail", course_id=unit.course_id))


@main_bp.post("/topics/<int:topic_id>/prerequisites")
@login_required
def add_prerequisite(topic_id):
    topic = owned_topic(topic_id)
    try:
        prerequisite_id = int(request.form.get("prerequisite_topic_id", ""))
    except ValueError:
        abort(400)
    prerequisite = owned_topic(prerequisite_id)
    if prerequisite.id == topic.id or prerequisite.unit.course_id != topic.unit.course_id:
        flash("Choose a different prerequisite topic in the same course.", "error")
    elif TopicPrerequisite.query.filter_by(
        topic_id=topic.id, prerequisite_topic_id=prerequisite.id
    ).first():
        flash("That prerequisite is already linked.", "info")
    else:
        db.session.add(TopicPrerequisite(topic_id=topic.id, prerequisite_topic_id=prerequisite.id))
        db.session.commit()
        flash("Prerequisite linked.", "success")
    return redirect(url_for("main.course_detail", course_id=topic.unit.course_id))


@main_bp.route("/topics/<int:topic_id>/quiz", methods=["GET", "POST"])
@login_required
def topic_quiz(topic_id):
    topic = owned_topic(topic_id)
    if request.method == "POST":
        prompts = request.form.getlist("prompt[]")
        option_a = request.form.getlist("option_a[]")
        option_b = request.form.getlist("option_b[]")
        option_c = request.form.getlist("option_c[]")
        option_d = request.form.getlist("option_d[]")
        correct = request.form.getlist("correct[]")
        usable = []
        for values in zip(prompts, option_a, option_b, option_c, option_d, correct):
            prompt, *rest = [value.strip() for value in values]
            *options, answer = rest
            if prompt and all(options) and answer in {"0", "1", "2", "3"}:
                usable.append((prompt, options, int(answer)))
        if not 1 <= len(usable) <= 10:
            flash("Add between 1 and 10 complete multiple-choice questions.", "error")
        else:
            quiz = Quiz(
                user_id=current_user.id,
                topic_id=topic.id,
                title=f"Practice: {topic.title}",
            )
            for prompt, options, answer in usable:
                quiz.questions.append(
                    Question(prompt=prompt, options=options, correct_option=answer)
                )
            db.session.add(quiz)
            db.session.commit()
            return redirect(url_for("main.take_quiz", quiz_id=quiz.id))
    mastery = TopicMastery.query.filter_by(user_id=current_user.id, topic_id=topic.id).first()
    weak_prerequisites = prerequisite_suggestions(current_user.id, topic.id)
    return render_template(
        "quiz_build.html",
        topic=topic,
        mastery=mastery,
        prerequisites=weak_prerequisites,
    )


@main_bp.route("/quizzes/<int:quiz_id>", methods=["GET", "POST"])
@login_required
def take_quiz(quiz_id):
    quiz = Quiz.query.filter_by(id=quiz_id, user_id=current_user.id).first_or_404()
    if request.method == "POST":
        correct_count = 0
        for question in quiz.questions:
            try:
                selected = int(request.form.get(f"answer_{question.id}", "-1"))
            except ValueError:
                selected = -1
            correct_count += selected == question.correct_option
        total = len(quiz.questions)
        score = correct_count / total if total else 0
        db.session.add(
            QuizAttempt(
                user_id=current_user.id,
                quiz_id=quiz.id,
                score=score,
                correct_count=correct_count,
                total_questions=total,
            )
        )
        record_result(current_user.id, quiz.topic_id, score, "quiz")
        db.session.commit()
        return redirect(url_for("main.quiz_result", quiz_id=quiz.id))
    return render_template("take_quiz.html", quiz=quiz)


@main_bp.route("/quizzes/<int:quiz_id>/result")
@login_required
def quiz_result(quiz_id):
    quiz = Quiz.query.filter_by(id=quiz_id, user_id=current_user.id).first_or_404()
    attempt = QuizAttempt.query.filter_by(user_id=current_user.id, quiz_id=quiz.id).order_by(
        QuizAttempt.created_at.desc()
    ).first_or_404()
    mastery = TopicMastery.query.filter_by(
        user_id=current_user.id, topic_id=quiz.topic_id
    ).first_or_404()
    suggestions = prerequisite_suggestions(current_user.id, quiz.topic_id)
    return render_template(
        "quiz_result.html",
        quiz=quiz,
        attempt=attempt,
        mastery=mastery,
        suggestions=suggestions,
    )


@main_bp.route("/courses/<int:course_id>/exam-plan", methods=["GET", "POST"])
@login_required
def exam_plan(course_id):
    course = owned_course(course_id)
    if request.method == "POST":
        exam_date_value = request.form.get("exam_date", "")
        try:
            course.exam_date = date.fromisoformat(exam_date_value)
            hours = float(request.form.get("available_hours", "2"))
            if not 0.25 <= hours <= 16:
                raise ValueError
            course.available_hours_per_day = hours
            db.session.commit()
        except ValueError:
            db.session.rollback()
            flash("Enter a valid future exam date and daily availability (0.25–16 hours).", "error")
            return redirect(url_for("main.exam_plan", course_id=course.id))
    plan = None
    if course.exam_date:
        try:
            plan = build_exam_plan(current_user.id, course)
        except ValueError as error:
            flash(str(error), "info")
    return render_template("exam_plan.html", course=course, plan=plan)


@main_bp.route("/tutor", methods=["GET", "POST"])
@login_required
def tutor():
    output = None
    hint_session = None
    selected_topic = None
    rung = 0
    problem = ""
    mode = "AI" if is_available() else "DEMO"
    if request.method == "POST":
        if request.form.get("new_problem"):
            return redirect(url_for("main.tutor"))
        problem = request.form.get("problem", "").strip()
        if not problem or len(problem) > 3000:
            flash("Enter a study problem of 1 to 3,000 characters.", "error")
            return render_template(
                "tutor.html", output=None, mode=mode, rung=0, problem=problem,
                ladder=RUNG_GUIDANCE, topics=[],
            )
        try:
            rung = int(request.form.get("rung", "1"))
            topic_id = int(request.form["topic_id"]) if request.form.get("topic_id") else None
            session_id = int(request.form["hint_session_id"]) if request.form.get("hint_session_id") else None
        except ValueError:
            abort(400)
        if not 1 <= rung <= 5:
            abort(400)
        if topic_id is not None:
            selected_topic = owned_topic(topic_id)

        if session_id is not None:
            hint_session = HintSession.query.filter_by(
                id=session_id, user_id=current_user.id
            ).first_or_404()
            if hint_session.problem != problem or hint_session.topic_id != topic_id:
                abort(400)
            if rung != hint_session.highest_rung + 1:
                flash("Climb the hint ladder one rung at a time.", "error")
                return render_template(
                    "tutor.html", output=None, mode=mode, rung=hint_session.highest_rung,
                    problem=problem, hint_session=hint_session, selected_topic=selected_topic,
                    ladder=RUNG_GUIDANCE, labels=RUNG_LABELS, topics=[],
                )
        elif rung != 1:
            abort(400)

        try:
            if is_available():
                output = hint_response(problem, rung, selected_topic.title if selected_topic else None)
            else:
                output = demo_hint(rung, selected_topic.title if selected_topic else None)
        except AIServiceError as error:
            flash(str(error), "error")
            return render_template(
                "tutor.html", output=None, mode=mode, rung=rung, problem=problem,
                hint_session=hint_session, selected_topic=selected_topic,
                ladder=RUNG_GUIDANCE, labels=RUNG_LABELS, topics=[],
            ), 503

        if hint_session is None:
            hint_session = HintSession(
                user_id=current_user.id,
                topic_id=topic_id,
                problem=problem,
                highest_rung=0,
            )
            db.session.add(hint_session)
        hint_session.highest_rung = rung
        hint_session.solution_viewed = rung == 5
        db.session.commit()
    topics = (
        Topic.query.join(Topic.unit).join(Unit.course)
        .filter(Course.user_id == current_user.id)
        .order_by(Course.name, Unit.position, Topic.position)
        .all()
    )
    return render_template(
        "tutor.html", output=output, mode=mode, rung=rung, problem=problem,
        hint_session=hint_session, selected_topic=selected_topic, topics=topics,
        ladder=RUNG_GUIDANCE, labels=RUNG_LABELS,
    )


def demo_hint(rung, topic_title=None):
    """Return clearly bounded study prompts rather than fabricated AI responses."""
    topic_line = f" Topic: {topic_title}." if topic_title else ""
    replies = {
        1: f"[DEMO MODE] Start by rewriting what the problem asks and listing the information it gives.{topic_line} No AI provider is configured, so I cannot interpret the specific problem.",
        2: f"[DEMO MODE] Recall the definition or theorem for this topic, then identify which quantities are known and unknown.{topic_line} This is a general study prompt, not a problem-specific answer.",
        3: "[DEMO MODE] Write the governing equation or algorithm first, then substitute the known values one step at a time. Check dimensions or invariants after each step.",
        4: "[DEMO MODE] A worked similar example requires a configured AI provider. Try writing a smaller example from your course notes and compare the reasoning.",
        5: "[DEMO MODE] Full worked solutions are unavailable without a configured AI provider. Use your instructor's material to verify the result.",
    }
    return replies[rung]


@main_bp.route("/code-explainer", methods=["GET", "POST"])
@login_required
def code_explainer():
    explanation = None
    code = ""
    mode = "AI" if is_available() else "DEMO"
    if request.method == "POST":
        code = request.form.get("code", "")
        sample_input = request.form.get("sample_input", "").strip()
        if not code.strip() or len(code) > 4000 or len(sample_input) > 1000:
            flash("Enter code (up to 4,000 characters) and a sample input (up to 1,000 characters).", "error")
        elif not is_available():
            explanation = (
                "[DEMO MODE] No AI provider is configured, so no code analysis was produced. "
                "The pasted code is treated as text only and is never executed by this server."
            )
        else:
            prompt = (
                "Analyze this code as text only. Never claim that you executed it. Explain the "
                "main flow, trace variable values for the sample input if possible, estimate time "
                "and space complexity, and identify possible bugs. Mark uncertain conclusions.\n\n"
                f"Sample input:\n{sample_input or '(not provided)'}\n\nCode:\n{code}"
            )
            try:
                explanation = generate_response(
                    prompt,
                    "You are a programming tutor. Analyze pasted code statically. Never execute it or claim you did.",
                    max_characters=5000,
                )
            except AIServiceError as error:
                flash(str(error), "error")
                return render_template(
                    "code_explainer.html", explanation=None, code=code,
                    sample_input=sample_input, mode=mode,
                ), 503
    return render_template(
        "code_explainer.html", explanation=explanation, code=code,
        sample_input=request.form.get("sample_input", ""), mode=mode,
    )


@main_bp.route("/syllabus/import", methods=["POST"])
@login_required
def import_syllabus():
    """Import plain-text lines formatted as Course | Unit | Topic."""
    uploaded = request.files.get("syllabus")
    if uploaded is None or not uploaded.filename or not uploaded.filename.lower().endswith((".txt", ".md")):
        flash("Choose a .txt or .md syllabus file.", "error")
        return redirect(url_for("main.courses"))
    raw = uploaded.stream.read(2 * 1024 * 1024 + 1)
    if len(raw) > 2 * 1024 * 1024:
        flash("Syllabus files must be no larger than 2 MB.", "error")
        return redirect(url_for("main.courses"))
    try:
        lines = raw.decode("utf-8-sig").splitlines()
    except UnicodeDecodeError:
        flash("The syllabus file must be UTF-8 encoded text.", "error")
        return redirect(url_for("main.courses"))

    rows = []
    for line in lines:
        if not line.strip():
            continue
        parts = [part.strip() for part in line.split("|")]
        if (
            len(parts) != 3
            or any(not part for part in parts)
            or len(parts[0]) > 120
            or len(parts[1]) > 120
            or len(parts[2]) > 160
        ):
            flash("Use one Course | Unit | Topic entry per line.", "error")
            return redirect(url_for("main.courses"))
        rows.append(parts)
    if not rows or len(rows) > 500:
        flash("Include between 1 and 500 syllabus topic lines.", "error")
        return redirect(url_for("main.courses"))

    courses_by_name = {course.name: course for course in Course.query.filter_by(user_id=current_user.id).all()}
    units_by_course_title = {}
    for course_name, unit_name, topic_name in rows:
        course = courses_by_name.get(course_name)
        if course is None:
            course = Course(user_id=current_user.id, name=course_name)
            db.session.add(course)
            db.session.flush()
            courses_by_name[course_name] = course
        unit_key = (course.id, unit_name)
        unit = units_by_course_title.get(unit_key)
        if unit is None:
            unit = Unit(course_id=course.id, title=unit_name, position=len(course.units) + 1)
            db.session.add(unit)
            db.session.flush()
            units_by_course_title[unit_key] = unit
        db.session.add(
            Topic(unit_id=unit.id, title=topic_name, position=len(unit.topics) + 1)
        )
    db.session.commit()
    flash(f"Imported {len(rows)} topics across your syllabus.", "success")
    return redirect(url_for("main.courses"))


@main_bp.get("/study-tools")
@login_required
def study_tools():
    return render_template("study_tools.html")


@main_bp.route("/notes", methods=["GET", "POST"])
@login_required
def notes():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        content = request.form.get("content", "").strip()
        topic_id = request.form.get("topic_id", "").strip()
        if topic_id and not topic_id.isdigit():
            abort(400)
        topic = owned_topic(int(topic_id)) if topic_id else None
        if not title or len(title) > 160 or len(content) > 20000:
            flash("Add a title (up to 160 characters) and note text (up to 20,000 characters).", "error")
        else:
            db.session.add(
                Note(
                    user_id=current_user.id,
                    topic_id=topic.id if topic else None,
                    title=title,
                    content=content,
                )
            )
            db.session.commit()
            flash("Note saved.", "success")
            return redirect(url_for("main.notes"))
    notes_list = Note.query.filter_by(user_id=current_user.id).order_by(Note.created_at.desc()).all()
    topics = (
        Topic.query.join(Topic.unit).join(Unit.course)
        .filter(Course.user_id == current_user.id)
        .order_by(Course.name, Unit.position, Topic.position)
        .all()
    )
    return render_template("notes.html", notes=notes_list, topics=topics)


@main_bp.route("/notes/<int:note_id>/edit", methods=["GET", "POST"])
@login_required
def edit_note(note_id):
    note = Note.query.filter_by(id=note_id, user_id=current_user.id).first_or_404()
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        content = request.form.get("content", "").strip()
        topic_id = request.form.get("topic_id", "").strip()
        if topic_id and not topic_id.isdigit():
            abort(400)
        topic = owned_topic(int(topic_id)) if topic_id else None
        if not title or len(title) > 160 or len(content) > 20000:
            flash("Add a title (up to 160 characters) and note text (up to 20,000 characters).", "error")
        else:
            note.title = title
            note.content = content
            note.topic_id = topic.id if topic else None
            db.session.commit()
            flash("Note updated.", "success")
            return redirect(url_for("main.notes"))
    topics = (
        Topic.query.join(Topic.unit).join(Unit.course)
        .filter(Course.user_id == current_user.id)
        .order_by(Course.name, Unit.position, Topic.position)
        .all()
    )
    return render_template("note_edit.html", note=note, topics=topics)


@main_bp.post("/notes/<int:note_id>/delete")
@login_required
def delete_note(note_id):
    note = Note.query.filter_by(id=note_id, user_id=current_user.id).first_or_404()
    db.session.delete(note)
    db.session.commit()
    flash("Note deleted.", "success")
    return redirect(url_for("main.notes"))


@main_bp.route("/flashcards", methods=["GET", "POST"])
@login_required
def flashcards():
    if request.method == "POST":
        question = request.form.get("question", "").strip()
        answer = request.form.get("answer", "").strip()
        topic_id = request.form.get("topic_id", "").strip()
        if not topic_id.isdigit():
            flash("Choose a syllabus topic for this flashcard.", "error")
        else:
            topic = owned_topic(int(topic_id))
            if not question or len(question) > 2000 or not answer or len(answer) > 5000:
                flash("Enter a question (up to 2,000 characters) and answer (up to 5,000 characters).", "error")
            else:
                db.session.add(
                    Flashcard(
                        user_id=current_user.id,
                        topic_id=topic.id,
                        question=question,
                        answer=answer,
                    )
                )
                db.session.commit()
                flash("Flashcard added to your review queue.", "success")
                return redirect(url_for("main.flashcards"))
    cards = Flashcard.query.filter_by(user_id=current_user.id).order_by(
        Flashcard.next_review_at, Flashcard.id
    ).all()
    due_card_ids = set(
        db.session.execute(
            db.select(Flashcard.id).where(
                Flashcard.user_id == current_user.id,
                Flashcard.next_review_at <= datetime.now(timezone.utc),
            )
        ).scalars().all()
    )
    topics = (
        Topic.query.join(Topic.unit).join(Unit.course)
        .filter(Course.user_id == current_user.id)
        .order_by(Course.name, Unit.position, Topic.position)
        .all()
    )
    return render_template(
        "flashcards.html", cards=cards, topics=topics, due_card_ids=due_card_ids
    )


@main_bp.post("/flashcards/<int:card_id>/review")
@login_required
def review_flashcard(card_id):
    card = Flashcard.query.filter_by(id=card_id, user_id=current_user.id).first_or_404()
    try:
        quality = int(request.form.get("quality", "-1"))
    except ValueError:
        abort(400)
    if not 0 <= quality <= 5:
        abort(400)
    next_review = card.next_review_at
    if next_review.tzinfo is None:
        next_review = next_review.replace(tzinfo=timezone.utc)
    if next_review > datetime.now(timezone.utc):
        flash("That card is scheduled for a later review.", "info")
        return redirect(url_for("main.flashcards"))
    schedule_next_review(card, quality)
    db.session.commit()
    flash("Review recorded.", "success")
    return redirect(url_for("main.flashcards"))


@main_bp.route("/tasks", methods=["GET", "POST"])
@login_required
def tasks():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        course_id = request.form.get("course_id", "").strip()
        due_date_value = request.form.get("due_date", "").strip()
        try:
            minutes = int(request.form.get("estimated_minutes", "30"))
            due_date = date.fromisoformat(due_date_value) if due_date_value else None
        except ValueError:
            flash("Enter a valid due date and estimated duration.", "error")
            return redirect(url_for("main.tasks"))
        if not title or len(title) > 160 or not 5 <= minutes <= 480 or not course_id.isdigit():
            flash("Enter a task title, choose a course, and set 5–480 estimated minutes.", "error")
        else:
            course = owned_course(int(course_id))
            db.session.add(
                StudyTask(
                    user_id=current_user.id,
                    course_id=course.id,
                    title=title,
                    due_date=due_date,
                    estimated_minutes=minutes,
                )
            )
            db.session.commit()
            flash("Study task added.", "success")
            return redirect(url_for("main.tasks"))
    courses_list = Course.query.filter_by(user_id=current_user.id).order_by(Course.name).all()
    tasks_list = StudyTask.query.filter_by(user_id=current_user.id).order_by(
        StudyTask.completed, StudyTask.due_date.is_(None), StudyTask.due_date, StudyTask.id
    ).all()
    return render_template("tasks.html", courses=courses_list, tasks=tasks_list)


@main_bp.post("/tasks/<int:task_id>/toggle")
@login_required
def toggle_task(task_id):
    task = StudyTask.query.filter_by(id=task_id, user_id=current_user.id).first_or_404()
    task.completed = not task.completed
    db.session.commit()
    return redirect(url_for("main.tasks"))


@main_bp.post("/tasks/<int:task_id>/delete")
@login_required
def delete_task(task_id):
    task = StudyTask.query.filter_by(id=task_id, user_id=current_user.id).first_or_404()
    db.session.delete(task)
    db.session.commit()
    flash("Study task deleted.", "success")
    return redirect(url_for("main.tasks"))


@main_bp.get("/analytics")
@login_required
def analytics():
    courses_list = Course.query.filter_by(user_id=current_user.id).order_by(Course.name).all()
    topic_count = (
        Topic.query.join(Topic.unit).join(Unit.course)
        .filter(Course.user_id == current_user.id)
        .count()
    )
    mastery_records = TopicMastery.query.filter_by(user_id=current_user.id).all()
    events = MasteryEvent.query.filter_by(user_id=current_user.id).order_by(
        MasteryEvent.created_at.desc()
    ).limit(20).all()
    return render_template(
        "analytics.html",
        courses=courses_list,
        topic_count=topic_count,
        assessed_count=len(mastery_records),
        average_mastery=(
            round(sum(record.score for record in mastery_records) / len(mastery_records) * 100)
            if mastery_records else None
        ),
        events=events,
    )
