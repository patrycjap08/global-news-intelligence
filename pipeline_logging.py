"""Small, consistent console logging helpers for the production pipeline."""

from __future__ import annotations


def log(component: str, message: str, *, level: str = "INFO") -> None:
    """Print one short, searchable pipeline message."""
    prefix = f"[{component}]" if level == "INFO" else f"[{component}][{level}]"
    print(f"{prefix} {message}", flush=True)


def short_text(value: object, limit: int = 100) -> str:
    """Collapse whitespace and keep a human-readable label short."""
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(1, limit - 1)].rstrip() + "…"


def quantity(value: int, singular: str, few: str, many: str) -> str:
    """Return a Polish number + noun phrase for readable progress messages."""
    amount = abs(int(value))
    if amount == 1:
        noun = singular
    elif amount % 10 in {2, 3, 4} and amount % 100 not in {12, 13, 14}:
        noun = few
    else:
        noun = many
    return f"{value} {noun}"


def seconds(value: float | int | None) -> str:
    """Format a duration for a console message."""
    if value is None:
        return "—"
    amount = float(value)
    if amount < 60:
        return f"{amount:.1f} s"
    minutes, remainder = divmod(round(amount), 60)
    return f"{minutes} min {remainder:02d} s"
