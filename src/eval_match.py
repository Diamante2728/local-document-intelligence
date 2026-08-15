"""Numeric-token matching for answer grading. Single source of truth for how needles are matched.

WHY THIS EXISTS — a scoring-validity bug found during Stage 2 eval review.

Grading used naive substring membership (`needle in answer`). That silently credits wrong
answers whenever the expected figure is a substring of a longer number:

    needle "1.3"  matched inside  "1.36 percent"     <- WRONG, different value
    needle "5"    matched inside  "15.2", "45.1", "22.5", "13.3", ...

The flaw surfaced in a dependency check over the Stage 2 multi-doc eval set: 3 of 26
cross-document questions appeared answerable from a single document, purely because
`"1.3"` occurs inside FDIC's `"1.36"`. Two of the three were artifacts of the matcher, not
defects in the questions.

The consequence is worse for real grading than for that check: a model that answers **1.36**
when the truth is **1.3** would have been scored CORRECT. Any short needle turns the grader into
a coin flip biased toward passing.

RULE: a needle matches only as a COMPLETE number — the character before/after may not extend it
into a different number. Comma separators are normalised on both sides, so "12,419.3" matches
"12419.3".

SECOND BUG, found while QC-ing the Stage 2 training data (a sentence-final period read as a
decimal point). The first version of this module used the boundaries `(?<![\\d.])` and `(?![\\d.])`,
which reject ANY adjacent period — including the full stop that ends a sentence:

    matches_needle("The rate was 1.3.", "1.3")   -> False    <- WRONG, correct answer failed

That is a FALSE NEGATIVE, and it matters more than it looks. When I reported the substring bug I
said the correction could "only inflate, never deflate" a score. That was true of the substring
matcher it replaced, but NOT of the replacement: this boundary marks a correct answer wrong
whenever the figure lands at the end of a sentence — which is where answers naturally put it.

The boundary must reject only a real numeric continuation: an adjacent DIGIT, or a period that is
itself followed by a digit ("1.3" inside "1.36"). A period followed by a space or end-of-string is
punctuation and must not block the match.
"""
import re

__all__ = ["matches_needle", "missing_needles"]


def _normalise(text):
    return str(text).replace(",", "")


def matches_needle(text, needle):
    """True when `needle` appears in `text` as a complete number.

    Guards against the substring class above:
        matches_needle("1.36 percent", "1.3")  -> False
        matches_needle("rose 1.3 percent", "1.3") -> True
        matches_needle("15.2 and 45.1", "5")   -> False
        matches_needle("about 5 percent", "5") -> True
        matches_needle("The rate was 1.3.", "1.3") -> True   (sentence-final period is punctuation)
    """
    t, n = _normalise(text), _normalise(needle)
    if not n:
        return False
    # Non-numeric needles (rare, e.g. a word) fall back to plain containment.
    if not re.fullmatch(r"-?\d*\.?\d+", n):
        return n in t
    # Boundaries reject only a genuine numeric continuation:
    #   before — a digit ("15" ~ "5"), or a digit+period ("1.5" ~ "5")
    #   after  — a digit ("1.36" ~ "1.3"), or a period followed by a digit ("1.36" ~ "1")
    # A period followed by a space or end-of-string is a full stop and does NOT block the match.
    pattern = rf"(?<!\d)(?<!\d\.){re.escape(n)}(?!\d)(?!\.\d)"
    return re.search(pattern, t) is not None


def missing_needles(text, needles):
    """Needles absent from `text` under complete-number matching."""
    return [n for n in needles if not matches_needle(text, n)]
