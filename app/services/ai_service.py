import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class AIServiceError(RuntimeError):
    """A configured AI provider did not return a usable response."""


RUNG_GUIDANCE = {
    1: "Restate the problem and identify the likely concept. Do not give a solution.",
    2: "Give one conceptual nudge that helps the student choose an approach. Do not solve it.",
    3: "Show the first step only and explain why it is a reasonable next move.",
    4: "Show a worked, similar example, then ask the student to apply the pattern. Do not solve their exact problem.",
    5: "Give a full worked solution with clear reasoning. State uncertainty and encourage checking course materials.",
}
RUNG_LABELS = {
    1: "Restate & identify",
    2: "Approach nudge",
    3: "First step",
    4: "Similar example",
    5: "Full solution",
}


def is_available():
    return bool(os.environ.get("AI_API_KEY"))


def generate_response(prompt, instruction, max_characters=5000):
    """Call a configured OpenAI-compatible chat completion service; never fake success."""
    api_key = os.environ.get("AI_API_KEY")
    if not api_key:
        raise AIServiceError("AI credentials are not configured.")

    base_url = os.environ.get("AI_API_URL", "https://api.openai.com/v1").rstrip("/")
    model = os.environ.get("AI_MODEL", "gpt-4o-mini")
    payload = json.dumps(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": instruction},
                {"role": "user", "content": prompt[:max_characters]},
            ],
            "temperature": 0.3,
            "max_tokens": 1200,
        }
    ).encode("utf-8")
    request = Request(
        f"{base_url}/chat/completions",
        data=payload,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=25) as response:
            result = json.loads(response.read(1_000_001))
    except HTTPError as error:
        raise AIServiceError(f"AI provider returned HTTP {error.code}.") from error
    except (URLError, TimeoutError) as error:
        raise AIServiceError("Could not reach the AI provider. Try again later.") from error
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise AIServiceError("AI provider returned an invalid response.") from error

    try:
        content = result["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as error:
        raise AIServiceError("AI provider response did not contain an answer.") from error
    if not isinstance(content, str) or not content.strip():
        raise AIServiceError("AI provider returned an empty answer.")
    return content.strip()


def hint_response(problem, rung, topic_title=None):
    if not 1 <= rung <= 5:
        raise ValueError("Hint ladder rung must be between 1 and 5.")
    topic_context = f"Topic: {topic_title}\n" if topic_title else ""
    instruction = (
        "You are an educational tutor. Support reasoning instead of encouraging copying. "
        "Be concise, acknowledge uncertainty, and do not claim verification. "
        + RUNG_GUIDANCE[rung]
    )
    prompt = f"{topic_context}Student problem:\n{problem}\n\nRequested hint rung: {rung} of 5."
    return generate_response(prompt, instruction)
