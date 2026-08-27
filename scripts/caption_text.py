#!/usr/bin/env python3
"""Rewrite a caption with DeepSeek and render it as a fitted image.

Two jobs, kept out of cover_caption.py so that file stays about detection:

    rewrite_caption(text)                -> a punchier caption of similar length
    render_caption_png(text, size, path) -> that caption drawn to fit exactly

The renderer binary-searches the font size, so the text always fills the box
without overflowing, whatever length the model returns.
"""

import os
import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
KEY_FILE = BASE / "config" / "deepseek-key.txt"

DEEPSEEK_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-chat"

SYSTEM_MESSAGE = """You rewrite hook captions for short-form videos (YouTube Shorts, TikTok, Reels).

The user sends one caption. Rewrite it so it hits harder while saying the same thing.

HOUSE STYLE - match it exactly, this is how the channel writes:
- Title Case overall: capitalise the main words.
- Put ONE short burst in FULL CAPITALS - the emotional verb or intensifier that
  carries the hook. One to three words, never more, never the whole caption.
  The capitals are what catch the eye mid-scroll, so choose the word that
  actually carries the drama.
  This is the pattern:
      Ryan Garcia GOES OFF After Fans Kept Asking About His Wife
      WWE Star Tiffany Stratton Was SO EXCITED After N3ON Mentioned a Birkin
      N3ON Was HAPPY When Arman Tsarukyan Defended Him as His Friend
- Finish with one or two emoji that match the emotion.

RULES:
- Keep the same subject, people, and facts. Never invent details or add claims.
- Keep proper nouns spelled exactly as the user wrote them.
- Length: land within 10% of the original character count, and never above 115%
  of it. This text must fit a fixed box, so overshooting breaks the layout.
- Front-load the most interesting part. Make someone stop scrolling.
- No hashtags. No surrounding quotation marks. No preamble or explanation.
- Return ONLY the rewritten caption, on a single line."""


TITLE_SYSTEM_MESSAGE = """You rewrite YouTube Shorts titles for a clips channel.

The user sends one title. Rewrite it so it earns the click while saying the same thing.

HOUSE STYLE - match it exactly, this is how the channel writes:
- Title Case overall: capitalise the main words.
- Put ONE short burst in FULL CAPITALS - the emotional verb or intensifier that
  carries the hook. One to three words, never more, never the whole title.
  This is the pattern:
      Ryan Garcia GOES OFF After Fans Kept Asking About His Wife
      WWE Star Tiffany Stratton Was SO EXCITED After N3ON Mentioned a Birkin
      N3ON Was HAPPY When Arman Tsarukyan Defended Him as His Friend
- Lead with the name people search for, then the hook.
- The opening words matter most: a title is truncated in feeds, so the
  attention-grabbing part must come before it gets cut.

RULES:
- Keep the same subject, people, and facts. Never invent details, never promise
  anything the clip does not deliver. No fake shock, no bait the video cannot pay off.
- Keep proper nouns spelled exactly as the user wrote them.
- KEEP IT SHORT. Aim for the character count the user asks for and never
  exceed it by more than 15%. Short titles survive the feed truncation and
  read better. Cut filler, keywords and repetition rather than facts.
- Reword it properly. Do not hand back the original with two words swapped -
  change the sentence shape, the verb and the order.
- No hashtags. No surrounding quotation marks. No preamble or explanation.
- Emoji are optional: at most one, at the end, only if it genuinely adds.
- Return ONLY the rewritten title, on a single line."""


# --------------------------------------------------------------------------
# DeepSeek
# --------------------------------------------------------------------------

def load_api_key(explicit=None):
    """--api-key, then DEEPSEEK_API_KEY, then deepseek-key.txt.

    Deliberately not hardcoded: the key is a live credential and this file is
    the one most likely to get shared or committed.
    """
    if explicit:
        return explicit.strip()
    env = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if env:
        return env
    if KEY_FILE.exists():
        key = KEY_FILE.read_text(encoding="utf-8").strip()
        if key:
            return key
    return None


def _deepseek_client(api_key):
    """OpenAI client pointed at DeepSeek, verifying against the OS trust store.

    The SDK verifies TLS against certifi's bundle by default. TLS-inspecting
    antivirus (Avast, Kaspersky) and corporate proxies install their root into
    the Windows store, not into certifi, so the default fails with
    CERTIFICATE_VERIFY_FAILED even though the network is fine. Using the system
    store still verifies -- just against the roots this machine actually trusts.
    """
    try:
        from openai import OpenAI
    except ImportError:
        raise RuntimeError("The openai package is required.\n  pip install -U openai")

    kwargs = {"api_key": api_key, "base_url": DEEPSEEK_URL}
    try:
        import ssl

        import httpx

        kwargs["http_client"] = httpx.Client(verify=ssl.create_default_context(), timeout=60.0)
    except Exception:
        pass  # fall back to the SDK's own client
    return OpenAI(**kwargs)


def _similarity(a, b):
    """0..1 overlap between two captions, ignoring case and punctuation.

    Word overlap rather than character diff: the model likes to swap a word or
    two and call it a rewrite, and a character ratio barely moves when it does.
    """
    import re as _re
    from difflib import SequenceMatcher

    def norm(s):
        return _re.sub(r"[^a-z0-9 ]", "", s.lower())

    aw, bw = set(norm(a).split()), set(norm(b).split())
    jaccard = len(aw & bw) / max(1, len(aw | bw))
    ratio = SequenceMatcher(None, norm(a), norm(b)).ratio()
    return max(jaccard, ratio)


def rewrite_caption(text, api_key, tolerance=0.25, attempts=4, model=DEEPSEEK_MODEL,
                    max_similarity=0.62, system=None, kind="caption", target=None):
    """Ask DeepSeek for a similar-length, genuinely reworded caption.

    Two things are retried rather than trusted. Models drift long, and a caption
    that overshoots forces the renderer to shrink the type. They also echo: told
    to keep the facts, the people and the house style, the safest move is to
    hand back the original almost unchanged. Both are measured, and the prompt
    is steered on the next attempt by whichever is off.
    """
    client = _deepseek_client(api_key)
    target = target or len(text)
    best = None

    for attempt in range(1, attempts + 1):
        prompt = (
            "Original " + kind + " (" + str(len(text)) + " characters):\n" + text + "\n\n"
            "Rewrite it in about " + str(target) + " characters. Use different "
            "wording and a different sentence shape from the original."
        )
        if best is not None:
            notes = []
            if best["similarity"] > max_similarity:
                notes.append(
                    "Your last attempt reused too much of the original wording: \""
                    + best["text"] + "\". Keep the meaning and the house style, but "
                    "rebuild the sentence - different verb, different order, "
                    "different phrasing."
                )
            if abs(len(best["text"]) - target) / max(target, 1) > tolerance:
                way = "shorter" if len(best["text"]) > target else "longer"
                notes.append(
                    "It was " + str(len(best["text"])) + " characters; make it " + way + "."
                )
            if notes:
                prompt += "\n\n" + " ".join(notes)

        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system or SYSTEM_MESSAGE},
                {"role": "user", "content": prompt},
            ],
            temperature=1.1,
            stream=False,
        )
        candidate = clean_caption(response.choices[0].message.content)
        gap = abs(len(candidate) - target) / max(target, 1)
        similarity = _similarity(text, candidate)
        record = {"text": candidate, "gap": gap, "similarity": similarity}

        # Rank on both axes at once so a fluent near-copy never beats a real
        # rewrite that happens to be a few characters off.
        record["score"] = gap + max(0.0, similarity - max_similarity) * 3.0
        if best is None or record["score"] < best["score"]:
            best = record

        if gap <= tolerance and similarity <= max_similarity:
            return candidate, (
                str(len(candidate)) + " chars vs " + str(target) + " original, "
                + str(int(similarity * 100)) + "% similar (attempt " + str(attempt) + ")"
            )

    return best["text"], (
        str(len(best["text"])) + " chars vs " + str(target) + " original, "
        + str(int(best["similarity"] * 100)) + "% similar (closest of "
        + str(attempts) + ")"
    )



def clean_caption(raw):
    """Strip the wrappers models like to add."""
    text = (raw or "").strip()
    text = re.sub(r"^```[a-z]*\s*|\s*```$", "", text).strip()
    if len(text) > 1 and text[0] == text[-1] and text[0] in "\"'\u201c\u201d":
        text = text[1:-1].strip()
    # Collapse to one line: the renderer does its own wrapping.
    return " ".join(text.split())


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------

FONT_DIR = BASE / "assets" / "fonts"
MONTSERRAT = FONT_DIR / "Montserrat[wght].ttf"

# Montserrat first: it is what this caption style is actually set in. It ships
# as a variable font, and its weight axis DEFAULTS TO 100 (Thin) -- without an
# explicit instance every caption would render as hairlines.
FONT_CANDIDATES = [
    str(MONTSERRAT),
    r"C:\Windows\Fonts\segoeui.ttf",
    r"C:\Windows\Fonts\arial.ttf",
    r"C:\Windows\Fonts\calibri.ttf",
    r"C:\Windows\Fonts\verdana.ttf",
]
FONT_ALIASES = {
    "montserrat": str(MONTSERRAT),
    "segoe": r"C:\Windows\Fonts\segoeui.ttf",
    "arial": r"C:\Windows\Fonts\arial.ttf",
    "calibri": r"C:\Windows\Fonts\calibri.ttf",
    "verdana": r"C:\Windows\Fonts\verdana.ttf",
    "tahoma": r"C:\Windows\Fonts\tahoma.ttf",
    "trebuchet": r"C:\Windows\Fonts\trebuc.ttf",
    "segoebold": r"C:\Windows\Fonts\segoeuib.ttf",
    "arialbold": r"C:\Windows\Fonts\arialbd.ttf",
    "black": r"C:\Windows\Fonts\ariblk.ttf",
    "impact": r"C:\Windows\Fonts\impact.ttf",
}
DEFAULT_WEIGHT = "SemiBold"


def load_font(path, size, weight=DEFAULT_WEIGHT):
    """A font at a point size, with the weight instance applied if variable.

    Static fonts ignore the weight argument; variable ones must be told, or
    Pillow renders the axis default, which for Montserrat is Thin.
    """
    from PIL import ImageFont

    font = ImageFont.truetype(str(path), size)
    if not weight:
        return font
    try:
        names = [n.decode() if isinstance(n, bytes) else n
                 for n in font.get_variation_names()]
    except Exception:
        return font                      # not a variable font
    if weight in names:
        try:
            font.set_variation_by_name(weight)
        except Exception:
            pass
    return font

EMOJI_FONT = r"C:\Windows\Fonts\seguiemj.ttf"


def resolve_font(name=None):
    """A font path from a name, an alias, or the first installed default."""
    if name:
        key = name.lower().replace(" ", "").replace("-", "")
        if key in FONT_ALIASES and Path(FONT_ALIASES[key]).exists():
            return FONT_ALIASES[key]
        if Path(name).exists():
            return name
        guess = Path("C:/Windows/Fonts") / name
        if guess.exists():
            return str(guess)
        raise RuntimeError("Font not found: " + str(name))
    for candidate in FONT_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    raise RuntimeError("No usable font found in the Windows font folder")


def _is_emoji(ch):
    cp = ord(ch)
    return (
        0x1F300 <= cp <= 0x1FAFF
        or 0x1F000 <= cp <= 0x1F0FF
        or 0x2600 <= cp <= 0x27BF
        or 0x1F1E6 <= cp <= 0x1F1FF
        or 0x2B00 <= cp <= 0x2BFF
        or 0x2190 <= cp <= 0x21FF
        or cp in (0xFE0F, 0xFE0E, 0x200D, 0x20E3)
    )


def _runs(text):
    """Split into (segment, is_emoji) runs.

    One PIL draw call uses exactly one font, and no Windows text font carries
    colour emoji glyphs. Splitting lets each run use the right face while a
    shared baseline keeps them visually on one line.
    """
    out = []
    for ch in text:
        emoji = _is_emoji(ch)
        if out and out[-1][1] == emoji:
            out[-1][0] += ch
        else:
            out.append([ch, emoji])
    return [(seg, is_e) for seg, is_e in out]


def _line_width(text, font, emoji_font):
    return sum(
        (emoji_font if is_e else font).getlength(seg) for seg, is_e in _runs(text)
    )


def _wrap(text, font, emoji_font, max_width):
    words, lines, current = text.split(), [], ""
    for word in words:
        trial = (current + " " + word).strip()
        if _line_width(trial, font, emoji_font) <= max_width or not current:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _balanced_wrap(text, font, emoji_font, max_width):
    """Wrap without orphans.

    Greedy wrapping packs early lines full and dumps the remainder on the last
    one, stranding a trailing emoji or short word alone. Once the line count is
    known, re-wrapping at the narrowest width that still yields that many lines
    spreads the words evenly instead.
    """
    lines = _wrap(text, font, emoji_font, max_width)
    if len(lines) <= 1:
        return lines

    target = len(lines)
    best = lines
    lo, hi = 1, int(max_width)
    while lo <= hi:
        mid = (lo + hi) // 2
        candidate = _wrap(text, font, emoji_font, mid)
        if len(candidate) <= target:
            best = candidate
            hi = mid - 1
        else:
            lo = mid + 1
    return best


def _fit(text, box_w, box_h, font_path, min_leading, weight, lo=8, hi=None):
    """Largest font size whose wrapped text fits the box. Returns (size, lines).

    Both constraints are tested at every step, so the search stops at whichever
    binds first: the widest line hitting the box width, or the stacked lines
    hitting its height.
    """
    from PIL import ImageFont

    hi = hi or int(box_h)
    best = (lo, [text])
    while lo <= hi:
        mid = (lo + hi) // 2
        font = load_font(font_path, mid, weight)
        emoji_font = ImageFont.truetype(EMOJI_FONT, mid)
        lines = _balanced_wrap(text, font, emoji_font, box_w)
        ascent, descent = font.getmetrics()
        total = len(lines) * (ascent + descent) * min_leading
        widest = max((_line_width(l, font, emoji_font) for l in lines), default=0)
        if total <= box_h and widest <= box_w:
            best = (mid, lines)
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def render_caption_png(
    text,
    size,
    out_path,
    bg="white",
    fg="black",
    padding=0.02,
    spacing=1.02,
    radius=0.0,
    font_path=None,
    weight=DEFAULT_WEIGHT,
):
    """Draw text centred in a size-sized image, as large as it will go.

    The background is opaque and covers the whole rectangle: it has to erase the
    original caption underneath, and rounded corners would leave the old plate
    peeking out at the edges.

    Leftover vertical space is handed back to the line spacing rather than left
    as a margin, so the type reaches the top and bottom of the plate instead of
    floating in the middle. Line height never drops below ascent+descent, so
    lines cannot collide however much they are spread.
    """
    from PIL import Image, ImageDraw, ImageFont

    font_path = resolve_font(font_path)

    box_w, box_h = int(size[0]), int(size[1])
    pad_x, pad_y = int(box_w * padding), int(box_h * padding)
    inner_w, inner_h = box_w - 2 * pad_x, box_h - 2 * pad_y

    font_size, lines = _fit(text, inner_w, inner_h, font_path, spacing, weight)
    font = load_font(font_path, font_size, weight)
    emoji_font = ImageFont.truetype(EMOJI_FONT, font_size)
    ascent, descent = font.getmetrics()

    natural = (ascent + descent) * spacing
    line_h = max(natural, inner_h / len(lines))

    image = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    if radius > 0:
        draw.rounded_rectangle([0, 0, box_w - 1, box_h - 1],
                               radius=int(min(box_w, box_h) * radius), fill=bg)
    else:
        draw.rectangle([0, 0, box_w, box_h], fill=bg)

    block_h = len(lines) * line_h
    top = pad_y + (inner_h - block_h) / 2
    y = top + (line_h - (ascent + descent)) / 2 + ascent

    for line in lines:
        x = (box_w - _line_width(line, font, emoji_font)) / 2
        for seg, is_emoji in _runs(line):
            face = emoji_font if is_emoji else font
            try:
                draw.text((x, y), seg, font=face, fill=fg,
                          anchor="ls", embedded_color=is_emoji)
            except TypeError:
                draw.text((x, y), seg, font=face, fill=fg, anchor="ls")
            x += face.getlength(seg)
        y += line_h

    image.save(out_path)
    return out_path, font_size, len(lines)




if __name__ == "__main__":
    # Smoke test: render whatever is passed on the command line.
    sample = " ".join(sys.argv[1:]) or "Sample Caption That Should Fit Nicely 🔥"
    path, size, lines = render_caption_png(sample, (1652, 355), "caption-test.png")
    print(f"wrote {path} at {size}px in {lines} line(s)")

TITLE_MAX_CHARS = 60


def rewrite_title(text, api_key, max_chars=TITLE_MAX_CHARS, **kwargs):
    """Rewrite a video title in the channel voice, kept short.

    A separate system message because a title has a different job: it is read
    cold in a feed, truncated, with no picture yet doing the work.

    Unlike the caption, this does NOT match the original length. Source titles
    run long and tail off into keywords; a Short wants a title that survives
    the feed truncation and doubles as a sane filename, so the target is a cap
    rather than the input length.
    """
    kwargs.setdefault("system", TITLE_SYSTEM_MESSAGE)
    kwargs.setdefault("kind", "title")
    kwargs.setdefault("target", min(len(text), max_chars))
    return rewrite_caption(text, api_key, **kwargs)
