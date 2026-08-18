"""
Deterministic text repair (spec §7: "repair obvious extraction artifacts,
never destroy original text"). Ported/adapted from the prior Python port's
`resume_text_normalizer.py` (itself a port of the C# ResumeTextNormalizer),
which found real bugs worth preserving: a dangling hyphen only gets joined to
a following lowercase continuation (a genuine PDF line-wrap break), never to
an uppercase continuation (which would merge two real sentences/headings).
"""
import re

_WHITESPACE_RUN = re.compile(r"[ \t]+")
_BLANK_LINE_RUN = re.compile(r"\n{3,}")


def normalize_whitespace(text: str) -> str:
    if not text:
        return ""
    lines = [_WHITESPACE_RUN.sub(" ", line).strip() for line in text.split("\n")]
    joined = "\n".join(lines)
    return _BLANK_LINE_RUN.sub("\n\n", joined).strip()


def repair_line_wrap_hyphenation(text: str) -> str:
    """Joins a line ending in a dangling hyphen with no preceding space to a
    following line that starts lowercase with no leading whitespace -- a PDF
    line-wrap break, e.g. "Mi-" + "croservices" -> "Mi-croservices". The
    hyphen is preserved (not guessed away) since a real hyphenated compound
    wraps at the same visual point and can't be distinguished here;
    reconciliation happens downstream via vocabulary/catalog matching."""
    if not text:
        return ""

    lines = text.split("\n")
    result: list[str] = []
    i = 0
    while i < len(lines):
        current = lines[i]
        while (
            current
            and current.endswith("-")
            and not current.endswith("--")
            and i + 1 < len(lines)
            and lines[i + 1]
            and lines[i + 1][0].islower()
        ):
            i += 1
            current = current + lines[i]
        result.append(current)
        i += 1
    return "\n".join(result)
