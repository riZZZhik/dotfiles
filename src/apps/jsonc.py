"""Project JSONC entries without reformatting the retained source text."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import json5

_TOKENS = re.compile(
    r""""(?:\\[\s\S]|[^"\\])*"|'(?:\\[\s\S]|[^'\\])*'|(?P<comment>//[^\r\n]*|/\*[\s\S]*?\*/)"""
)
_TRIVIA = re.compile(r"(?:[\s\ufeff]+|//[^\r\n]*|/\*[\s\S]*?\*/)*")
_KEY = re.compile(r""""(?:\\[\s\S]|[^"\\])*"|'(?:\\[\s\S]|[^'\\])*'|[^\s:/]+""")
_REGION = re.compile(r"//\s*#(end)?region\b[^\r\n]*")
_REGION_LINE = re.compile(r"^[ \t]*//[ \t]*#(?:end)?region\b[^\r\n]*(?:\r?\n|$)", re.MULTILINE)


def _skip(text: str, position: int) -> int:
    match = _TRIVIA.match(text, position)
    assert match is not None
    return match.end()


def _inline_end(text: str, position: int) -> int:
    """Comments on the comma's line belong to the preceding entry."""
    while position < len(text):
        if text[position] in " \t":
            position += 1
        elif text.startswith("//", position):
            match = re.search(r"\r|\n|$", text[position:])
            assert match is not None
            return match.start() + position
        elif text.startswith("/*", position):
            position = text.index("*/", position + 2) + 2
        else:
            break
    return position


@dataclass(eq=False)
class _Region:
    opening: str
    closing: str = "// #endregion"


def _regions(source: str, stack: list[_Region]) -> None:
    for token in _TOKENS.finditer(source):
        directive = _REGION.fullmatch(token.group("comment") or "")
        if directive is None:
            continue
        if directive.group(1):
            if stack:
                stack.pop().closing = directive.group()
        else:
            stack.append(_Region(directive.group()))


@dataclass
class _Entry:
    key: str | int
    value: Any
    leading: str
    head: str
    source: str
    tail: str
    comma: int | None
    regions: tuple[_Region, ...]


class Document:
    """Use JSON5 for values and keep source spans for top-level entries."""

    def __init__(self, text: str):
        self.text = text
        try:
            self.value = json5.loads(text, allow_duplicate_keys=False)
            if not isinstance(self.value, (dict, list)):
                raise TypeError
            self.start = _skip(text, 0)
            newline = re.search(r"\r\n|\r|\n", text)
            self.newline = newline.group() if newline else "\n"
            self.opening = text[self.start]
            self.closing = "}" if isinstance(self.value, dict) else "]"
            self.entries: list[_Entry] = []
            regions: list[_Region] = []
            cursor = self.start + 1
            while True:
                position = _skip(text, cursor)
                if text[position] == self.closing:
                    self.footer = text[cursor:position]
                    _regions(self.footer, regions)
                    self.end = position + 1
                    break
                head_start = position
                _regions(text[cursor:head_start], regions)
                if isinstance(self.value, dict):
                    match = _KEY.match(text, position)
                    if match is None:
                        raise ValueError
                    key_text = match.group()
                    key = next(iter(json5.loads("{" + key_text + ":null}")))
                    colon = _skip(text, match.end())
                    if text[colon] != ":":
                        raise ValueError
                    position = _skip(text, colon + 1)
                else:
                    key = len(self.entries)
                value, error, end = json5.parse(text, start=position, consume_trailing=False)
                if error:
                    raise ValueError
                separator = _skip(text, end)
                comma = separator - end if text[separator] == "," else None
                tail_end = _inline_end(text, separator + 1 if comma is not None else end)
                self.entries.append(
                    _Entry(
                        key,
                        value,
                        text[cursor:head_start],
                        text[head_start:position],
                        text[position:end],
                        text[end:tail_end],
                        comma,
                        tuple(regions),
                    )
                )
                _regions(text[end:tail_end], regions)
                cursor = tail_end
            self.trailing_comma = bool(self.entries and self.entries[-1].comma is not None)
        except (ValueError, TypeError, IndexError, StopIteration):
            raise ValueError(
                "Invalid JSONC document; existing exports were not replaced."
            ) from None

    def project(
        self, selected: dict | list, safe_comment: Callable[[str], bool] | None = None
    ) -> str:
        """Keep an ordered subset; excluded entries take their comments with them."""
        if type(selected) is not type(self.value):
            raise ValueError("JSONC projection must retain the container type.")
        kept = []
        index = 0
        for entry in self.entries:
            if isinstance(selected, dict):
                if entry.key not in selected:
                    continue
                value = selected[entry.key]
            else:
                if index == len(selected) or entry.value != selected[index]:
                    continue
                value = selected[index]
                index += 1
            kept.append((entry, value))
        if len(kept) != len(selected):
            raise ValueError("JSONC projection must be a subset in source order.")

        def clean(source: str, *, orphan: bool = False, regions: bool = False) -> str:
            if regions:
                source = _REGION_LINE.sub("", source)
            allowed_regions: list[bool] = []

            def replace(match: re.Match) -> str:
                comment = match.group("comment")
                if comment is None:
                    return match.group()
                if regions and _REGION.fullmatch(comment):
                    return ""
                if safe_comment is None:
                    return comment
                directive = _REGION.fullmatch(comment)
                if directive is not None:
                    if not directive.group(1):
                        allowed_regions.append(not orphan and safe_comment(comment))
                        allowed = allowed_regions[-1]
                    else:
                        allowed = allowed_regions.pop() if allowed_regions else not orphan
                    if allowed:
                        return comment if safe_comment(comment) else "// #endregion"
                    return ""
                if not orphan and safe_comment(comment):
                    return comment
                # Keep line structure and token separation when removing a comment.
                return " " + "".join(re.findall(r"\r\n|\r|\n", comment))

            return _TOKENS.sub(replace, source)

        if selected == self.value and (
            safe_comment is None
            or all(
                safe_comment(m.group()) for m in _TOKENS.finditer(self.text) if m.group("comment")
            )
        ):
            return self.text
        split = len(kept) != len(self.entries)
        parts = [clean(self.text[: self.start], orphan=split), self.opening]
        active: tuple[_Region, ...] = ()

        def closing(region: _Region) -> str:
            if safe_comment is None or safe_comment(region.closing):
                return region.closing
            return "// #endregion"

        for index, (entry, value) in enumerate(kept):
            scopes = tuple(
                region
                for region in entry.regions
                if safe_comment is None or safe_comment(region.opening)
            )
            shared = 0
            while shared < min(len(active), len(scopes)) and active[shared] is scopes[shared]:
                shared += 1
            indentation = re.search(r"[ \t]*$", entry.leading)
            assert indentation is not None
            indent = indentation.group()
            for region in reversed(active[shared:]):
                parts.append(self.newline + indent + closing(region))
            leading = clean(entry.leading, regions=True)
            gap = re.match(r"\s*", leading)
            assert gap is not None
            parts.append(leading[: gap.end()])
            for region in scopes[shared:]:
                parts.append(region.opening + self.newline + indent)
            parts.append(leading[gap.end() :])
            active = scopes
            if value == entry.value:
                body = clean(entry.source)
            elif isinstance(value, (dict, list)):
                body = Document(entry.source).project(value, safe_comment)
            else:
                body = json.dumps(value, ensure_ascii=False)
            tail = entry.tail
            if index == len(kept) - 1 and not self.trailing_comma and entry.comma is not None:
                tail = tail[: entry.comma] + tail[entry.comma + 1 :]
            parts.extend((clean(entry.head), body, clean(tail, regions=True)))
        for region in reversed(active):
            parts.append(self.newline + indent + closing(region))
        footer = clean(self.footer, orphan=split, regions=True)
        if not re.search(r"\r|\n", footer) and re.search(r"\r|\n", self.text):
            footer = self.newline + footer
        parts.extend(
            (
                footer,
                self.closing,
                clean(self.text[self.end :], orphan=split),
            )
        )
        result = "".join(parts)
        try:
            valid = json5.loads(result, allow_duplicate_keys=False) == selected
        except ValueError:
            valid = False
        if not valid:
            raise ValueError("JSONC projection changed values; existing exports were not replaced.")
        return result
