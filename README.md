# EduGenius AI — Engineering Study Platform

EduGenius AI is a Flask study planner for engineering and computer-science students. Its implemented workflow is: organize a syllabus, assess individual topics, record mastery, and schedule revision around an exam date.

## Run locally on Windows

From the project directory, open PowerShell:

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
flask --app run.py init-db
python run.py
```

Open <http://127.0.0.1:5000/> in your browser. This address is local to your computer; it is not a public deployment link.

Before deploying, set a unique, randomly generated `SECRET_KEY`, use a production WSGI server, enable HTTPS and `SESSION_COOKIE_SECURE`, and configure a production database. Do not commit `.env` or credentials.

## Implemented features

- Registration, login, logout, password hashing, CSRF-protected forms, and account-scoped course access.
- Courses with units, topics, exam weightage, and same-course prerequisite links.
- Manual syllabus entry and UTF-8 `.txt`/`.md` import. Each non-empty line must be `Course | Unit | Topic`; imports are limited to 500 lines and 2 MB.
- Student-authored multiple-choice quizzes (1–10 questions). Correct answers are not shown before submission.
- Per-topic mastery updates using an exponentially weighted average (alpha `0.35`), with recorded quiz events and suggestions to review linked prerequisites after low scores.
- Exam planning based on assessed mastery and exam weightage. Unassessed topics remain explicitly unknown and are prioritized for baseline assessment. Sessions respect the configured daily time limit, the day before the exam is reserved for revision, and over-capacity topics are identified.
- A five-rung hint ladder and a static code explainer. Without an AI provider, both say clearly that they are in demo mode; pasted code is never executed. With a provider, requests are sent server-side to an OpenAI-compatible Chat Completions endpoint.
- Topic-linked notes with edit/delete actions and account-scoped study tasks with due dates, estimated time, and completion tracking.
- Topic flashcards with recall ratings and simple increasing review intervals. A card cannot be reviewed again before its scheduled date.
- Learning activity summaries based only on recorded assessments and actual syllabus coverage.
- Responsive landing page and student dashboard.

## Optional AI provider

The app works without AI credentials. To enable AI responses, set these values in `.env`:

```dotenv
AI_API_KEY=your-provider-key
AI_API_URL=https://api.openai.com/v1
AI_MODEL=gpt-4o-mini
```

`AI_API_URL` should be the provider's API root; the app appends `/chat/completions`. Keep the key private and configure it only on the server.

## Tests

```powershell
python -m pytest -q
```

The tests cover the account/syllabus/quiz workflow, mastery and prerequisite behavior, exam-date and planner constraints, AI demo/error behavior, and ownership checks.

## Current scope

This is a working foundation, not the complete Engineering Edition specification. Viva simulation, resource bookmarks, admin tools, account export/deletion, full syllabus editing/deletion, detailed analytics charts, and broader rate limiting are not implemented yet. Flashcards use a simple interval rule rather than the full SM-2 algorithm. The tutor and code explainer require a configured provider for problem-specific results; their demo prompts are not AI analysis.
