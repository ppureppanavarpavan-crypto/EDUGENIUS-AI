from datetime import datetime, timedelta, timezone


def schedule_next_review(card, quality, now=None):
    """Use a simple recall-quality spaced interval; low recall restarts the sequence."""
    if not 0 <= quality <= 5:
        raise ValueError("Recall quality must be between 0 and 5.")
    now = now or datetime.now(timezone.utc)
    if quality < 3:
        card.review_count = 0
        card.review_interval = 1
    else:
        card.review_count += 1
        if card.review_count == 1:
            card.review_interval = 1
        elif card.review_count == 2:
            card.review_interval = 3
        else:
            card.review_interval = min(card.review_interval * 2, 60)
    card.next_review_at = now + timedelta(days=card.review_interval)
    return card
