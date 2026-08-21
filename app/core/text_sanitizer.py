import regex


EMOJI_AND_PICTOGRAPH_RE = regex.compile(
    r"[\p{Extended_Pictographic}\p{Emoji_Presentation}]",
    flags=regex.VERSION1,
)
VARIATION_SELECTOR_RE = regex.compile(
    r"[\uFE00-\uFE0F\U000E0100-\U000E01EF]",
    flags=regex.VERSION1,
)


def strip_emoji_and_pictographs(text: str) -> str:
    """Remove emoji-style pictographs while preserving the surrounding text."""
    without_emoji = EMOJI_AND_PICTOGRAPH_RE.sub("", text)
    return VARIATION_SELECTOR_RE.sub("", without_emoji)
