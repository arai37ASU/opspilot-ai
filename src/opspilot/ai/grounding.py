"""The number guard: text may only state numbers that appear in its facts.

The check is deliberately simple and strict. Every quantity in the text must
match one of the same kind in the facts, allowing for the rounding a writer
would do: "18.0%" supports "18%", but not "18" or "18 hours", and the time
"19:30" does not support "19%". It checks numbers, not meaning: it cannot tell
whether a sentence reads a number correctly, or which fact a matching number
came from. That is why the risk, the flag and each reason's direction are
filled in by code rather than written by the model.
"""

import json
import re

QUANTITY = re.compile(
    r"(?<![\w.:,])(?:(?P<time>\d{1,2}:\d{2})\b"
    r"|(?P<number>\d+(?:,\d{3})*(?:\.\d+)?)(?P<percent>\s*(?:%|percent\b))?)",
    re.IGNORECASE,
)

# Spelled-out quantities would slip past a digit check. One to three are left
# alone because they are mostly ordinary words ("one of the reasons").
NUMBER_WORDS = re.compile(
    r"\b(four|five|six|seven|eight|nine|ten|eleven|twelve|\w+teen|twenty|thirty|forty|fifty|sixty|seventy|eighty"
    r"|ninety|hundred|thousand|dozen|half|quarter|third|twice|double|triple)\b",
    re.IGNORECASE,
)


def _quantities(text: str) -> list[tuple[str, tuple]]:
    """Each quantity in `text` as (what was written, (kind, value))."""
    found = []
    for match in QUANTITY.finditer(text):
        if match["time"]:
            hours, minutes = match["time"].split(":")
            key = ("time", (int(hours), int(minutes)))
        else:
            key = ("percent" if match["percent"] else "number", float(match["number"].replace(",", "")))
        found.append((match.group(0), key))
    return found


def allowed_quantities(facts: dict) -> set[tuple]:
    """Every quantity in the facts, plus numbers rounded to a whole and to one decimal."""
    allowed = set()
    for _, (kind, value) in _quantities(json.dumps(facts, ensure_ascii=False)):
        allowed.add((kind, value))
        if kind != "time":
            allowed.update({(kind, float(int(value + 0.5))), (kind, round(value, 1))})
    return allowed


def unsupported_numbers(text: str, facts: dict) -> list[str]:
    """The quantities and number words in `text` that the facts do not support."""
    allowed = allowed_quantities(facts)
    digits = [written for written, key in _quantities(text) if key not in allowed]
    return digits + [match.group(0) for match in NUMBER_WORDS.finditer(text)]
