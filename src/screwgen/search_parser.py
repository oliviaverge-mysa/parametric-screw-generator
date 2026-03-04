"""Plain-text query parser for screw dimensions and spec construction."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

from .spec import DriveSpec, HeadSpec, ScrewSpec, ShaftSpec, SmoothRegionSpec, ThreadRegionSpec

PromptFn = Callable[[str], str]

_SIZE_CHART = {
    0: {"head_d": 0.119, "shank_d": 0.060, "root_d": 0.040, "tpi": 32},
    1: {"head_d": 0.146, "shank_d": 0.073, "root_d": 0.046, "tpi": 28},
    2: {"head_d": 0.172, "shank_d": 0.086, "root_d": 0.054, "tpi": 26},
    3: {"head_d": 0.199, "shank_d": 0.099, "root_d": 0.065, "tpi": 24},
    4: {"head_d": 0.225, "shank_d": 0.112, "root_d": 0.075, "tpi": 22},
    5: {"head_d": 0.252, "shank_d": 0.125, "root_d": 0.085, "tpi": 20},
    6: {"head_d": 0.279, "shank_d": 0.138, "root_d": 0.094, "tpi": 18},
    7: {"head_d": 0.305, "shank_d": 0.151, "root_d": 0.102, "tpi": 16},
    8: {"head_d": 0.332, "shank_d": 0.164, "root_d": 0.112, "tpi": 15},
    9: {"head_d": 0.358, "shank_d": 0.177, "root_d": 0.122, "tpi": 14},
    10: {"head_d": 0.385, "shank_d": 0.190, "root_d": 0.130, "tpi": 13},
    11: {"head_d": 0.411, "shank_d": 0.203, "root_d": 0.139, "tpi": 12},
    12: {"head_d": 0.438, "shank_d": 0.216, "root_d": 0.148, "tpi": 11},
    14: {"head_d": 0.491, "shank_d": 0.242, "root_d": 0.165, "tpi": 10},
    16: {"head_d": 0.544, "shank_d": 0.268, "root_d": 0.184, "tpi": 9},
    18: {"head_d": 0.597, "shank_d": 0.294, "root_d": 0.204, "tpi": 8},
    20: {"head_d": 0.650, "shank_d": 0.320, "root_d": 0.233, "tpi": 8},
    24: {"head_d": 0.756, "shank_d": 0.372, "root_d": 0.260, "tpi": 7},
}

_HEAD_TO_SHANK = [row["head_d"] / row["shank_d"] for row in _SIZE_CHART.values()]
_ROOT_TO_SHANK = [row["root_d"] / row["shank_d"] for row in _SIZE_CHART.values()]
_HEAD_TO_SHANK_MEDIAN = sorted(_HEAD_TO_SHANK)[len(_HEAD_TO_SHANK) // 2]
_ROOT_TO_SHANK_MEDIAN = sorted(_ROOT_TO_SHANK)[len(_ROOT_TO_SHANK) // 2]
_HEAD_TO_SHANK_MIN = min(_HEAD_TO_SHANK)
_HEAD_TO_SHANK_MAX = max(_HEAD_TO_SHANK)
_ROOT_TO_SHANK_MIN = min(_ROOT_TO_SHANK)
_ROOT_TO_SHANK_MAX = max(_ROOT_TO_SHANK)
_HEAD_H_TO_HEAD_D_BY_TYPE = {
    "flat": 0.50,
    "pan": 0.45,
    "button": 0.38,
    "hex": 0.62,
}


@dataclass
class ParsedQuery:
    fastener_type: str | None
    head_type: str | None
    head_d: float | None
    head_h: float | None
    across_flats: float | None
    shank_d: float | None
    root_d: float | None
    length: float | None
    tip_len: float | None
    pitch: float | None
    thread_height: float | None
    thread_length: float | None
    thread_start: float | None
    thread_spans: list[tuple[float, float]]
    drive_type: str | None
    drive_size: int | None
    drive_explicit_none: bool
    size_number: int | None


def _parse_numeric(token: str) -> float:
    token = token.strip().lower()
    token = re.sub(r"(?:mm|inches|inch|in|\"|')\b", "", token).strip()
    m = re.search(r"-?\d+(?:\.\d+)?(?:/\d+(?:\.\d+)?)?", token)
    if m is None:
        raise ValueError(f"No numeric value found in {token!r}")
    value = m.group(0)
    if "/" in value:
        a, b = value.split("/", 1)
        return float(a) / float(b)
    return float(value)


def _find_size_number(text: str) -> int | None:
    m = re.search(r"(?:#|no\.?\s*)(\d{1,2})\b", text)
    if not m:
        return None
    value = int(m.group(1))
    return value if value in _SIZE_CHART else None


def _find_labeled_value(text: str, labels: list[str]) -> float | None:
    label_pat = "|".join(re.escape(label) for label in labels)
    num_pat = r"(-?\d+(?:\.\d+)?(?:/\d+(?:\.\d+)?)?)"
    patterns = [
        rf"(?:{label_pat})\s*(?:=|:|is|of)?\s*{num_pat}",
        rf"{num_pat}\s*(?:mm|in|inch|inches|\"|')?\s*(?:{label_pat})",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            try:
                return _parse_numeric(m.group(1))
            except ValueError:
                continue
    return None


def _normalize_typos(text: str) -> str:
    out = text
    replacements = {
        r"\blenght\b": "length",
        r"\blenth\b": "length",
        r"\blengh\b": "length",
        r"\bheigth\b": "height",
        r"\bhieght\b": "height",
        r"\bdiamter\b": "diameter",
        r"\bdiamater\b": "diameter",
        r"\bdiammeter\b": "diameter",
        r"\bthred\b": "thread",
        r"\bthead\b": "thread",
        r"\btorqs\b": "torx",
        r"\bphilips\b": "phillips",
        r"\bbold\b": "bolt",
        r"\bblot\b": "bolt",
        r"\bolt\b": "bolt",
        r"\bbolr\b": "bolt",
    }
    for pat, rep in replacements.items():
        out = re.sub(pat, rep, out)
    return out


def _find_overall_length(text: str) -> float | None:
    # Prefer explicit labels. Fall back to plain "length" only when not thread-specific.
    value = _find_labeled_value(text, ["overall length", "shaft length"])
    if value is not None:
        return value
    m0 = re.search(r"(-?\d+(?:\.\d+)?(?:/\d+(?:\.\d+)?)?)\s*(?:mm|in|inch|inches|\"|')?\s*long\b", text)
    if m0:
        return _parse_numeric(m0.group(1))
    m2 = re.search(
        r"(-?\d+(?:\.\d+)?(?:/\d+(?:\.\d+)?)?)\s*(?:mm|in|inch|inches|\"|')?\s*(?<!thread\s)(?<!tip\s)length\b(?!\s*\d)",
        text,
    )
    if m2:
        return _parse_numeric(m2.group(1))
    m = re.search(
        r"(?<!thread\s)(?<!tip\s)\blength\b\s*(?:=|:|is|of)?\s*(-?\d+(?:\.\d+)?(?:/\d+(?:\.\d+)?)?)",
        text,
    )
    if m:
        return _parse_numeric(m.group(1))
    return None


def _find_thread_length(text: str) -> float | None:
    value = _find_labeled_value(text, ["thread length", "threaded length"])
    if value is not None:
        return value
    # Handles shorthand like "12mm thread"
    m = re.search(r"(-?\d+(?:\.\d+)?(?:/\d+(?:\.\d+)?)?)\s*(?:mm|in|inch|inches|\"|')?\s*thread\b", text)
    if m:
        return _parse_numeric(m.group(1))
    m2 = re.search(r"(-?\d+(?:\.\d+)?(?:/\d+(?:\.\d+)?)?)\s*(?:mm|in|inch|inches|\"|')?\s*of\s*threads?\b", text)
    if m2:
        return _parse_numeric(m2.group(1))
    return None


def _find_thread_spans(text: str) -> list[tuple[float, float]]:
    if "thread" not in text:
        return []
    spans: list[tuple[float, float]] = []
    range_pat = (
        r"(-?\d+(?:\.\d+)?(?:/\d+(?:\.\d+)?)?)\s*(?:mm|in|inch|inches|\"|')?\s*"
        r"(?:-|to)\s*"
        r"(-?\d+(?:\.\d+)?(?:/\d+(?:\.\d+)?)?)\s*(?:mm|in|inch|inches|\"|')?"
    )
    for m in re.finditer(range_pat, text):
        try:
            a = _parse_numeric(m.group(1))
            b = _parse_numeric(m.group(2))
        except ValueError:
            continue
        lo, hi = (a, b) if a <= b else (b, a)
        if hi > lo:
            spans.append((lo, hi))
    # Deduplicate exact repeats while preserving order.
    out: list[tuple[float, float]] = []
    for span in spans:
        if span not in out:
            out.append(span)
    return out


def _infer_fastener_type(text: str) -> str | None:
    has_bolt = re.search(r"\bbolt(s)?\b", text) is not None
    has_screw = re.search(r"\bscrew(s)?\b", text) is not None
    # Be conservative: if "bolt" appears anywhere, honor bolt intent.
    if has_bolt:
        return "bolt"
    if has_screw:
        return "screw"
    return None


def _infer_drive(text: str) -> tuple[str | None, int | None]:
    if re.search(r"\b(torx|star drive)\b", text):
        return "torx", 6
    if re.search(r"\b(phillips|philips|cross[- ]head)\b", text):
        return "phillips", 4
    if re.search(r"\b(square drive|robertson|square recess)\b", text):
        return "square", 4
    if re.search(r"\b(hex drive|allen|hex socket|socket head)\b", text):
        return "hex", 3
    return None, None


def _has_explicit_no_drive(text: str) -> bool:
    return re.search(r"\b(no drive|without drive|plain head|no recess|no socket)\b", text) is not None


def _parse_drive_answer(raw: str) -> tuple[str | None, int | None]:
    a = raw.strip().lower()
    if not a:
        return None, None
    if re.search(r"\b(no drive|without drive|plain head|none|no)\b", a):
        return None, None
    if "torx" in a or "star" in a:
        return "torx", 6
    if "phillips" in a or "philips" in a or "cross" in a:
        return "phillips", 4
    if "square" in a or "robertson" in a:
        return "square", 4
    if "hex" in a or "allen" in a or "socket" in a:
        return "hex", 3
    return None, None


def _infer_with_chart_ratios(parsed: ParsedQuery, prompt: PromptFn | None) -> None:
    ref = _SIZE_CHART.get(parsed.size_number) if parsed.size_number is not None else None
    head_ratio = (ref["head_d"] / ref["shank_d"]) if ref is not None else _HEAD_TO_SHANK_MEDIAN
    root_ratio = (ref["root_d"] / ref["shank_d"]) if ref is not None else _ROOT_TO_SHANK_MEDIAN

    if parsed.shank_d is not None:
        if parsed.head_d is None:
            parsed.head_d = parsed.shank_d * head_ratio
        if parsed.root_d is None:
            parsed.root_d = parsed.shank_d * root_ratio
    elif parsed.head_d is not None:
        parsed.shank_d = parsed.head_d / head_ratio
        if parsed.root_d is None:
            parsed.root_d = parsed.shank_d * root_ratio
    elif parsed.root_d is not None:
        parsed.shank_d = parsed.root_d / root_ratio
        parsed.head_d = parsed.shank_d * head_ratio

    if prompt is not None and ref is not None:
        prompt(
            f"Using size #{parsed.size_number} chart proportions only (not absolute sizes): "
            f"head/shank={head_ratio:.3f}, root/shank={root_ratio:.3f}. Press Enter to continue."
        )

    if parsed.head_h is None and parsed.head_d is not None:
        # Head-height defaults by style based on standards-inspired proportions.
        ratio = _HEAD_H_TO_HEAD_D_BY_TYPE.get(parsed.head_type or "", 0.55)
        parsed.head_h = ratio * parsed.head_d
    if parsed.tip_len is None and parsed.length is not None:
        if parsed.fastener_type == "bolt":
            base = parsed.shank_d or (parsed.head_d * 0.45 if parsed.head_d is not None else 1.0)
            parsed.tip_len = max(0.08, 0.08 * base)
        else:
            parsed.tip_len = max(0.08 * parsed.length, min(0.15 * parsed.length, 0.28 * parsed.length))


def _ask_number(prompt: PromptFn, label: str) -> float:
    raw = prompt(f"Missing {label}. Enter a numeric value: ").strip()
    return _parse_numeric(raw)


def _confirm(prompt: PromptFn | None, message: str) -> bool:
    if prompt is None:
        return False
    answer = prompt(message).strip().lower()
    return answer in {"y", "yes"}


def _validate_realism(parsed: ParsedQuery, prompt: PromptFn | None) -> None:
    assert parsed.head_d is not None
    assert parsed.shank_d is not None
    assert parsed.root_d is not None
    assert parsed.length is not None
    assert parsed.tip_len is not None
    assert parsed.head_h is not None

    head_ratio = parsed.head_d / parsed.shank_d
    root_ratio = parsed.root_d / parsed.shank_d
    head_range = (_HEAD_TO_SHANK_MIN * 0.9, _HEAD_TO_SHANK_MAX * 1.1)
    root_range = (_ROOT_TO_SHANK_MIN * 0.9, _ROOT_TO_SHANK_MAX * 1.1)

    def _apply_or_raise(message: str, suggested: float, field: str) -> None:
        if prompt is None:
            raise ValueError(f"{message} Suggested {field}={suggested:.2f}.")
        keep = _confirm(prompt, f"{message} Suggested {field}: {suggested:.2f}. Keep your value?")
        if not keep:
            if field == "head diameter":
                parsed.head_d = suggested
            elif field == "root diameter":
                parsed.root_d = suggested
            elif field == "tip length":
                parsed.tip_len = suggested
            elif field == "head height":
                parsed.head_h = suggested

    if not (head_range[0] <= head_ratio <= head_range[1]):
        _apply_or_raise(
            f"Head/shank ratio {head_ratio:.2f} looks unrealistic.",
            parsed.shank_d * _HEAD_TO_SHANK_MEDIAN,
            "head diameter",
        )

    if not (root_range[0] <= root_ratio <= root_range[1]):
        _apply_or_raise(
            f"Root/shank ratio {root_ratio:.2f} looks unrealistic.",
            parsed.shank_d * _ROOT_TO_SHANK_MEDIAN,
            "root diameter",
        )

    if parsed.root_d >= parsed.shank_d:
        _apply_or_raise(
            "Root diameter must be smaller than shank diameter.",
            parsed.shank_d * _ROOT_TO_SHANK_MEDIAN,
            "root diameter",
        )

    if parsed.head_d <= parsed.shank_d:
        _apply_or_raise(
            "Head diameter should exceed shank diameter.",
            parsed.shank_d * _HEAD_TO_SHANK_MEDIAN,
            "head diameter",
        )

    shaft_len_for_tip = max(parsed.length - parsed.head_h, 0.5 * parsed.length)
    if parsed.fastener_type == "bolt":
        tip_low = 0.0
        tip_high = 0.12 * parsed.shank_d
        if not (tip_low <= parsed.tip_len <= tip_high):
            suggested = max(tip_low, min(parsed.tip_len, tip_high))
            _apply_or_raise(
                f"Bolt chamfer {parsed.tip_len:.2f} looks unusual for shank diameter {parsed.shank_d:.2f}.",
                suggested,
                "tip length",
            )
    else:
        tip_low = 0.05 * shaft_len_for_tip
        tip_high = 0.35 * shaft_len_for_tip
        if not (tip_low <= parsed.tip_len <= tip_high):
            suggested = max(tip_low, min(parsed.tip_len, tip_high))
            _apply_or_raise(
                f"Tip length {parsed.tip_len:.2f} looks unusual for length {parsed.length:.2f}.",
                suggested,
                "tip length",
            )
    if parsed.head_h is not None and parsed.head_h >= parsed.head_d:
        suggested = max(0.25 * parsed.head_d, min(parsed.head_h, 0.7 * parsed.head_d))
        _apply_or_raise(
            f"Head height {parsed.head_h:.2f} is unrealistic vs head diameter {parsed.head_d:.2f}.",
            suggested,
            "head height",
        )


def _infer_thread_defaults(parsed: ParsedQuery, thread_intent: bool, prompt: PromptFn | None) -> None:
    if not thread_intent:
        return
    if parsed.pitch is None:
        if parsed.size_number in _SIZE_CHART:
            tpi = _SIZE_CHART[parsed.size_number]["tpi"]
            parsed.pitch = 1.0 / tpi
        elif parsed.shank_d is not None:
            parsed.pitch = 0.25 * parsed.shank_d
        elif parsed.head_d is not None:
            parsed.pitch = 0.11 * parsed.head_d
        if parsed.pitch is not None and parsed.shank_d is not None:
            # Keep inferred pitch within a practical range for stability and realism.
            parsed.pitch = max(0.08 * parsed.shank_d, min(parsed.pitch, 0.45 * parsed.shank_d))
        if parsed.pitch is not None and prompt is not None:
            prompt(f"No pitch provided. Assuming pitch={parsed.pitch:.4f} from dimensions. Press Enter to continue.")

    if parsed.thread_height is None:
        if parsed.shank_d is not None and parsed.root_d is not None:
            inferred = (parsed.shank_d - parsed.root_d) / 2.0
            if inferred > 0:
                parsed.thread_height = inferred
        elif parsed.head_d is not None:
            parsed.thread_height = 0.06 * parsed.head_d
        if parsed.thread_height is not None and prompt is not None:
            prompt(
                f"No thread height provided. Assuming thread_height={parsed.thread_height:.4f} from dimensions. Press Enter to continue."
            )


def parse_query(text: str) -> ParsedQuery:
    t = _normalize_typos(text.lower().replace(",", " "))
    head_type = None
    for candidate in ("flat", "pan", "button", "hex"):
        if re.search(rf"\b{candidate}\b", t):
            head_type = candidate
            break

    unit_is_mm = "mm" in t
    tpi = _find_labeled_value(t, ["threads per inch", "thread per inch", "tpi"])
    pitch = _find_labeled_value(t, ["pitch"])
    if pitch is None and tpi is not None and tpi > 0:
        pitch = (25.4 / tpi) if unit_is_mm else (1.0 / tpi)

    drive_type, drive_size = _infer_drive(t)

    return ParsedQuery(
        fastener_type=_infer_fastener_type(t),
        head_type=head_type,
        head_d=_find_labeled_value(
            t,
            [
                "head diameter",
                "head dia",
                "head width",
                "head wide",
                "wide head",
                "max head diameter",
                "diameter of head",
            ],
        ),
        head_h=_find_labeled_value(t, ["head height", "head h", "head thickness"]),
        across_flats=_find_labeled_value(t, ["across flats", "acrossflats", "af"]),
        shank_d=_find_labeled_value(
            t,
            ["shank diameter", "shank dia", "major diameter", "major dia", "outside diameter", "shank"],
        ),
        root_d=_find_labeled_value(t, ["root diameter", "root dia", "minor diameter", "minor dia", "root"]),
        length=_find_overall_length(t),
        tip_len=_find_labeled_value(t, ["tip length", "tip len", "point length", "tip"]),
        pitch=pitch,
        thread_height=_find_labeled_value(t, ["thread height", "thread depth"]),
        thread_length=_find_thread_length(t),
        thread_start=_find_labeled_value(t, ["thread start", "start from head"]),
        thread_spans=_find_thread_spans(t),
        drive_type=drive_type,
        drive_size=drive_size,
        drive_explicit_none=_has_explicit_no_drive(t),
        size_number=_find_size_number(t),
    )


def screw_spec_from_query(text: str, prompt: PromptFn | None = None) -> ScrewSpec:
    parsed = parse_query(text)
    text_l = text.lower()
    thread_intent = ("thread" in text_l) or ("tpi" in text_l)
    _infer_with_chart_ratios(parsed, prompt)

    if prompt is not None:
        if parsed.fastener_type is None:
            ft = prompt("Is this a screw or a bolt?").strip().lower()
            if ft in {"screw", "bolt"}:
                parsed.fastener_type = ft
        if parsed.fastener_type is None:
            parsed.fastener_type = "screw"
        if parsed.fastener_type == "bolt":
            parsed.tip_len = 0.0
        if parsed.head_type is None:
            parsed.head_type = prompt("Missing head type (flat/pan/button/hex): ").strip().lower()
        if parsed.head_d is None:
            parsed.head_d = _ask_number(prompt, "head diameter")
        # Infer head height from standards unless user explicitly provided it.
        _infer_with_chart_ratios(parsed, prompt=None)
        if parsed.head_h is None:
            parsed.head_h = 0.55 * float(parsed.head_d)
            prompt(
                f"No head height provided. Assuming head_height={parsed.head_h:.4f} from screw standards. Press Enter to continue."
            )
        if parsed.shank_d is None:
            parsed.shank_d = _ask_number(prompt, "shank diameter (major)")
        if parsed.root_d is None:
            parsed.root_d = _ask_number(prompt, "root diameter (minor)")
        if parsed.length is None:
            parsed.length = _ask_number(prompt, "overall length (head top to tip)")
        if parsed.tip_len is None:
            _infer_with_chart_ratios(parsed, prompt=None)
            if parsed.tip_len is None:
                parsed.tip_len = _ask_number(prompt, "tip length")
        if parsed.drive_type is None and not parsed.drive_explicit_none:
            dt, ds = _parse_drive_answer(prompt("What kind of drive is it?"))
            parsed.drive_type = dt
            parsed.drive_size = ds
        if thread_intent and parsed.pitch is None:
            _infer_thread_defaults(parsed, thread_intent=True, prompt=prompt)
        if thread_intent and parsed.pitch is None:
            parsed.pitch = _ask_number(prompt, "thread pitch (or 1/TPI)")
    else:
        if parsed.fastener_type is None:
            parsed.fastener_type = "screw"
        if parsed.fastener_type == "bolt":
            parsed.tip_len = 0.0
        missing: list[str] = []
        for label, value in (
            ("head type", parsed.head_type),
            ("head diameter", parsed.head_d),
            ("head height", parsed.head_h),
            ("shank diameter", parsed.shank_d),
            ("root diameter", parsed.root_d),
            ("shaft length", parsed.length),
            ("tip length", parsed.tip_len),
        ):
            if value is None:
                missing.append(label)
        _infer_thread_defaults(parsed, thread_intent=thread_intent, prompt=None)
        if thread_intent and parsed.pitch is None:
            missing.append("thread pitch")
        if missing:
            raise ValueError(
                "Missing required dimensions from text query: "
                + ", ".join(missing)
                + ". Provide them or pass a prompt callback for interactive asks."
            )

    if parsed.head_type not in {"flat", "pan", "button", "hex"}:
        raise ValueError(f"Unsupported head type {parsed.head_type!r}.")
    if parsed.fastener_type not in {"screw", "bolt"}:
        raise ValueError(f"Unsupported fastener type {parsed.fastener_type!r}.")
    if parsed.head_type == "hex" and parsed.across_flats is None and parsed.head_d is not None:
        parsed.across_flats = parsed.head_d * 0.8660254

    _validate_realism(parsed, prompt)
    _infer_thread_defaults(parsed, thread_intent=thread_intent, prompt=prompt)

    shaft_length = float(parsed.length) - float(parsed.head_h)
    if shaft_length <= 0:
        raise ValueError("Overall length must be larger than head height.")

    thread_start = parsed.thread_start if parsed.thread_start is not None else 0.0
    max_threadable = shaft_length - float(parsed.tip_len)
    if max_threadable <= 0:
        raise ValueError("Tip length must be smaller than shaft length.")

    regions = []
    if parsed.pitch is None:
        regions = [SmoothRegionSpec(length=shaft_length)]
    else:
        if parsed.thread_spans:
            # Explicit thread spans override single thread_length/thread_start.
            clipped: list[tuple[float, float]] = []
            for start, end in sorted(parsed.thread_spans):
                s = max(0.0, start)
                e = min(end, max_threadable)
                if e - s > 1e-9:
                    if clipped and s <= clipped[-1][1] + 1e-9:
                        clipped[-1] = (clipped[-1][0], max(clipped[-1][1], e))
                    else:
                        clipped.append((s, e))
            if not clipped:
                raise ValueError("Thread spans are outside the threadable shaft range.")
            cursor_len = 0.0
            for s, e in clipped:
                if s > cursor_len + 1e-9:
                    regions.append(SmoothRegionSpec(length=s - cursor_len))
                regions.append(
                    ThreadRegionSpec(
                        length=e - s,
                        pitch=float(parsed.pitch),
                        major_d=float(parsed.shank_d),
                        thread_height=parsed.thread_height,
                    )
                )
                cursor_len = e
            tail = shaft_length - cursor_len
            if tail > 1e-9:
                regions.append(SmoothRegionSpec(length=tail))
        else:
            if parsed.thread_length is None:
                if prompt is None:
                    raise ValueError(
                        "Missing thread length. Add 'thread length' or thread spans (e.g. 3-8 and 12-20)."
                    )
                if _confirm(prompt, f"No thread length found. Use max threadable length ({max_threadable:.4f})?"):
                    parsed.thread_length = max_threadable - thread_start
                else:
                    parsed.thread_length = _ask_number(prompt, "thread length")
            thread_length = float(parsed.thread_length)
            thread_limit = shaft_length - thread_start
            if thread_length > thread_limit:
                thread_length = thread_limit
            if thread_length <= 0:
                raise ValueError("Thread length must be > 0 after accounting for overall length and thread start.")
            if thread_start > 0:
                regions.append(SmoothRegionSpec(length=thread_start))
            regions.append(
                ThreadRegionSpec(
                    length=thread_length,
                    pitch=float(parsed.pitch),
                    major_d=float(parsed.shank_d),
                    thread_height=parsed.thread_height,
                )
            )
            tail = shaft_length - (thread_start + thread_length)
            if tail > 1e-9:
                regions.append(SmoothRegionSpec(length=tail))

    return ScrewSpec(
        head=HeadSpec(
            type=parsed.head_type,
            d=float(parsed.head_d),
            h=float(parsed.head_h),
            acrossFlats=(None if parsed.across_flats is None else float(parsed.across_flats)),
        ),
        drive=(
            None
            if parsed.drive_type is None
            else DriveSpec(
                type=parsed.drive_type,  # type: ignore[arg-type]
                size=parsed.drive_size or 6,  # type: ignore[arg-type]
                fit="scale_to_head",
                clearance=0.02,
            )
        ),
        shaft=ShaftSpec(
            d_minor=float(parsed.root_d),
            L=shaft_length,
            tip_len=float(parsed.tip_len),
        ),
        regions=regions,
        fastener_type=parsed.fastener_type,  # type: ignore[arg-type]
    )

