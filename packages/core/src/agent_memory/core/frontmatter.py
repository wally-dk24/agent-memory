"""A deliberately small frontmatter dialect.

The core carries no YAML dependency: the schema is closed, so a strict reader over the
subset we emit is both sufficient and a guardrail — anything richer is rejected rather
than silently reinterpreted.
"""

from __future__ import annotations

DELIMITER = "---"
_TRUE = "true"
_FALSE = "false"
_NULLS = ("", "null", "~")


def split_document(text: str) -> tuple[str | None, str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != DELIMITER:
        return None, text
    try:
        end = lines.index(DELIMITER, 1)
    except ValueError:
        return None, text
    body = "\n".join(lines[end + 1 :]).lstrip("\n")
    return "\n".join(lines[1:end]), body


def parse(text: str) -> tuple[dict[str, object], str]:
    header, body = split_document(text)
    if header is None:
        return {}, body
    return _parse_mapping(header.splitlines()), body


def render(fields: dict[str, object], body: str) -> str:
    lines = [DELIMITER]
    for key, value in fields.items():
        lines.append(f"{key}: {_render_scalar(value)}")
    lines.append(DELIMITER)
    return "\n".join(lines) + "\n\n" + body.strip() + "\n"


def _parse_mapping(lines: list[str]) -> dict[str, object]:
    fields: dict[str, object] = {}
    pending_key: str | None = None
    for raw in lines:
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if raw.lstrip().startswith("- ") and pending_key is not None:
            bucket = fields.setdefault(pending_key, [])
            if isinstance(bucket, list):
                bucket.append(_parse_scalar(raw.lstrip()[len("- ") :]))
            continue
        key, separator, value = raw.partition(":")
        if not separator:
            continue
        key = key.strip()
        value = value.strip()
        if value == "":
            fields[key] = []
            pending_key = key
            continue
        pending_key = None
        fields[key] = _parse_scalar(value)
    return {key: value for key, value in fields.items()}


def _parse_scalar(value: str) -> object:
    value = value.strip()
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [_parse_scalar(item) for item in _split_items(inner)]
    if len(value) > 1 and value[0] == value[-1] and value[0] in ("'", '"'):
        return _unescape_quoted(value[1:-1], value[0])
    lowered = value.lower()
    if lowered == _TRUE:
        return True
    if lowered == _FALSE:
        return False
    if lowered in _NULLS:
        return None
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value


def _unescape_quoted(inner: str, quote: str) -> str:
    """Undo the escaping _render_scalar applies inside a quoted value.

    Only the quote character itself and the backslash are escape-significant;
    anything else keeps its literal backslash (e.g. "\\n" stays backslash-n).
    """
    out: list[str] = []
    i = 0
    n = len(inner)
    while i < n:
        char = inner[i]
        if char == "\\" and i + 1 < n and inner[i + 1] in (quote, "\\"):
            out.append(inner[i + 1])
            i += 2
        else:
            out.append(char)
            i += 1
    return "".join(out)


def _split_items(inner: str) -> list[str]:
    items: list[str] = []
    current: list[str] = []
    quote: str | None = None
    at_value_start = True
    i = 0
    n = len(inner)
    while i < n:
        char = inner[i]
        if quote:
            if char == "\\" and i + 1 < n and inner[i + 1] in (quote, "\\"):
                # Escaped quote or backslash: literal, must not toggle quote mode.
                current.append(char)
                current.append(inner[i + 1])
                i += 2
                at_value_start = False
                continue
            if char == quote:
                quote = None
            current.append(char)
            at_value_start = False
        elif char in ("'", '"') and at_value_start:
            quote = char
            current.append(char)
            at_value_start = False
        elif char == ",":
            items.append("".join(current))
            current = []
            at_value_start = True
        elif char in (" ", "\t"):
            if current:
                current.append(char)
                at_value_start = False
        else:
            current.append(char)
            at_value_start = False
        i += 1
    if quote is not None:
        # Unbalanced quote: treat every quote as a literal character and
        # fall back to a plain comma split rather than swallowing the list.
        return [item for item in (item.strip() for item in inner.split(",")) if item]
    items.append("".join(current))
    return [item for item in (item.strip() for item in items) if item]


def _looks_like_non_string(text: str) -> bool:
    """True when the reader would not hand this unquoted text back as a string."""
    probe = _parse_scalar(text)
    return not isinstance(probe, str) or probe != text


def _render_scalar(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return _TRUE if value else _FALSE
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_render_scalar(item) for item in value) + "]"
    if isinstance(value, (int, float)):
        return repr(value)
    text = str(value)
    if (
        text == ""
        or text != text.strip()
        or text[:1] in ("'", '"')  # a leading quote would open quote mode in lists
        or any(char in text for char in ":#[]{},")
        or _looks_like_non_string(text)
    ):
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return text
