"""Medium-specific markdown formatting.

DESIGN.md §9 has the Editor call ``medium_format`` on the polished markdown
before posting it to Telegram for human approval. Medium's importer/paste
flow accepts standard markdown but has a few quirks worth normalizing
before the human sees the article:

- **Multiple H1s confuse the importer** — Medium treats the first ``#`` as
  the article title and may strip subsequent ones. We demote H1s after the
  first to H2.
- **Code blocks need a language identifier** for syntax highlighting. We
  default unmarked fences to ``python`` (the dominant runtime in this
  pipeline's quickstart articles).
- **GIF and image embeds work via plain markdown** ``![alt](url)`` —
  Medium auto-detects ``.gif``/``.png``/``.jpg`` URLs and renders inline.
  No transformation needed.
- **MP4 links don't auto-embed** — they render as plain links, which is
  what DESIGN.md §9 step 5 expects (`[download MP4](mp4_url)`).
- **Excessive blank lines** get collapsed to a single empty line so the
  article renders compactly.
"""

import re

CODE_FENCE_PREFIX = "```"
DEFAULT_CODE_LANGUAGE = "python"


def medium_format(markdown: str) -> str:
    """Format markdown for Medium's importer.

    Args:
        markdown: The polished article markdown.

    Returns:
        Medium-friendly markdown. Returns an empty string for empty input.
    """
    if not markdown:
        return ""

    lines = markdown.splitlines()
    lines = _demote_extra_h1s(lines)
    lines = _label_unmarked_code_blocks(lines)
    text = "\n".join(lines)
    text = _collapse_blank_lines(text)
    return text.rstrip() + "\n"


def _demote_extra_h1s(lines: list[str]) -> list[str]:
    """Promote the first ``#`` heading to the title; demote subsequent H1s to H2."""
    seen_first = False
    out = []
    for line in lines:
        if _is_h1(line):
            if seen_first:
                out.append("#" + line)  # H1 → H2
            else:
                seen_first = True
                out.append(line)
        else:
            out.append(line)
    return out


def _is_h1(line: str) -> bool:
    return line.startswith("# ") and not line.startswith("##")


def _label_unmarked_code_blocks(lines: list[str]) -> list[str]:
    """Add a default language identifier to code fences that lack one."""
    out = []
    in_code = False
    for line in lines:
        stripped = line.rstrip()
        if not in_code and stripped == CODE_FENCE_PREFIX:
            out.append(f"{CODE_FENCE_PREFIX}{DEFAULT_CODE_LANGUAGE}")
            in_code = True
        elif stripped.startswith(CODE_FENCE_PREFIX):
            out.append(line)
            in_code = not in_code
        else:
            out.append(line)
    return out


def _collapse_blank_lines(text: str) -> str:
    """Collapse runs of 3+ newlines to exactly two (one blank line)."""
    return re.sub(r"\n{3,}", "\n\n", text)
