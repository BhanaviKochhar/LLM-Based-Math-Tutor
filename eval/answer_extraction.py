"""eval/answer_extraction.py -- find the final answer a tutor response
COMMITS to, and check it against an item's ground truth.

Replaces score_transcripts.py's old fallback, which counted an item correct
if the expected answer appeared ANYWHERE in the response text. That rescued
plenty of genuinely right answers (baseline bolds its result instead of
writing an "Answer:" line, which final_number_str can't read), but it also
scored wrong answers as right whenever the expected value happened to appear
somewhere else -- a single-digit answer matches almost any explanation
(cb-908: "4" in an LCM/HCF essay).

The rule here: find the short statement(s) of the response's final answer,
and compare only those against the ground truth. Statements are looked for
in confidence order:
  1. an "Answer:" line or "Answer" heading (the last one) -- authoritative,
     except a bare yes/no (a misconception question answered "Answer: no"
     states its corrected value in the sentence before),
  2. concluding sentences ("So, ...", "Therefore, ...", "The answer is ..."),
  3. the last bold phrase outside trailing pleasantries.
Within a statement, the result is the number that is NOT one of the
question's own numbers (the inputs), falling back to the first number when
every number in it comes from the question ("So, 7 is greater than 3").
If nothing of the right kind is stated, the response is UNDECIDED (None) --
never guessed. An LLM extraction step settles those later; correctness is
still decided here, in code, against ground truth.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from scripts.llm import response_parser, verifier

_ANSWER_LINE_RE = re.compile(r"(?im)^[ \t>*_#-]*(?:final\s+)?answer[ \t*_]*[:\-][ \t*_]*(.*)$")
_ANSWER_HEADING_RE = re.compile(
    r"(?i)^[ \t>*_#-]*(?:\d{1,2}\.\s*)?(?:\W{1,3}\s*)?(?:final\s+)?(?:answer|result)[ \t*_:]*$")
_CONCLUSION_START_RE = re.compile(
    r"^(?:so|therefore|thus|hence|that means|this means|that's why|this is why|"
    r"the answer is|the final answer is|final answer|final time|result|bottom line|in total)\b",
    re.IGNORECASE)
_ANSWER_IS_RE = re.compile(r"\b(?:the|final|correct)\s+answer\s+is\b", re.IGNORECASE)
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*|__(.+?)__", re.DOTALL)
# Trailing lines that are never the answer: invitations, praise, practice.
_PLEASANTRY_RE = re.compile(
    r"let me know|any (?:more|other) questions|keep (?:practi[cs]ing|it up|up the|trying|asking)|"
    r"great (?:job|work|question|effort|thinking)|well done|you(?:'|\u2019)re doing|you are doing|"
    r"happy (?:learning|studying|counting|calculating)|if you (?:ever |have |want |would |'d |like)|"
    r"would you like|want to try|try (?:this|another|it)|practice(?: question)?\s*:|"
    r"your turn|challenge\s*:|next question|good luck|feel free",
    re.IGNORECASE)
_EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF\uFE0F\u200d\u2705]")
_TIME_RE = re.compile(r"\b(\d{1,2})\s*:\s*(\d{2})\b")
_NUM_RE = re.compile(response_parser._NUMBER_TOKEN)
_END_OK_RE = re.compile(r"[.!?)\]*:\"\u201d\u2019'`]$|[\U0001F300-\U0001FAFF\u2600-\u27BF\uFE0F]$")
_YES_NO_RE = re.compile(r"^(?:yes|no|true|false|correct|not correct|wrong)[.!]?$", re.IGNORECASE)
_YES_NO_WORD_RE = re.compile(r"\b(?:yes|no)\b", re.IGNORECASE)
_NUMBER_WORDS = {w: str(i) for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen "
    "fourteen fifteen sixteen seventeen eighteen nineteen twenty".split())}
_NUMBER_WORDS.update({"thirty": "30", "forty": "40", "fifty": "50", "sixty": "60",
                      "seventy": "70", "eighty": "80", "ninety": "90", "hundred": "100"})
_NUMBER_WORD_RE = re.compile(r"\b(" + "|".join(_NUMBER_WORDS) + r")\b(?![-‑])", re.IGNORECASE)
_UNICODE_FRACTIONS = {"¼": " 1/4", "½": " 1/2", "¾": " 3/4", "⅓": " 1/3", "⅔": " 2/3"}
_LEFTOVER_RE = re.compile(r"remainder|left\s*over|left|remain|\bR\b", re.IGNORECASE)


@dataclass
class Commit:
    segments: list[str]   # statements of the final answer, best first
    source: str           # answer_line | conclusion | last_bold | none
    truncated: bool       # reply ends mid-sentence (hit the token cap)
    tail: str = ""        # last few non-pleasantry lines, for listed / q-r answers
    authoritative: bool = field(default=False)  # an explicit, non-yes/no Answer line
    yes_no: bool = False  # the Answer line is a bare yes/no

    @property
    def segment(self) -> str | None:
        return self.segments[0] if self.segments else None


def reply_text(turn: dict) -> str:
    """The text to read a turn's answer from: the model's own output where the
    runner kept it (baseline turns store it as raw_response), else the stored
    response. The stored baseline response went through the app's LaTeX
    clean-up, which flattens \\dfrac{25}{100} to "25100"."""
    return (turn or {}).get("raw_response") or (turn or {}).get("response") or ""


_FRAC_VARIANT_RE = re.compile(r"\\[dt]frac\b")
_FRAC_DIGITS_RE = re.compile(r"\\frac\s*(\d)\s*(\d)")          # \frac13 -> \frac{1}{3}
_WRAPPER_RE = re.compile(r"\\(?:boxed|text|textbf|mathrm|mathbf|operatorname)\s*\{([^{}]*)\}")


def _normalize(text: str) -> str:
    t = text or ""
    t = _FRAC_VARIANT_RE.sub(r"\\frac", t)
    t = _FRAC_DIGITS_RE.sub(r"\\frac{\1}{\2}", t)
    for _ in range(3):                                   # \boxed{\frac{2}{3}\text{ cup}}
        t = _WRAPPER_RE.sub(r"\1", t)
    t = re.sub(r"(?<=\d)\\[,;: ](?=\d)", "", t)          # 72\,000 -> 72000
    t = t.replace("\\ ", " ")
    t = response_parser.strip_latex(t)
    t = re.sub(r"\\[()\[\]]", " ", t)                   # \( \) \[ \] delimiters
    t = re.sub(r"\\[,;:!]", "", t)                      # LaTeX spacing commands
    # A thin/no-break space between digit groups is a thousands separator
    # ("2 000 grams", "98 531"), not a gap between two numbers.
    t = re.sub(r"(?<=\d)[\u00a0\u2009\u202f\u2007](?=\d{3}\b)", "", t)
    t = re.sub(r"[\u00a0\u2009\u202f\u2007]", " ", t)    # narrow/no-break spaces
    t = t.replace("\u2011", "-").replace("\u2013", "-").replace("\u2212", "-")
    t = t.replace("\u2044", "/").replace("\u20b9", "Rs ")
    t = re.sub(r"\bRs\.", "Rs", t)                     # "Rs." must not end a sentence
    for ch, frac in _UNICODE_FRACTIONS.items():
        t = t.replace(ch, frac)
    t = re.sub(r"([.!?])(\*\*|__)", r"\2\1", t)        # "**So, 7.**" -> "**So, 7**."
    return t


def is_truncated(text: str) -> bool:
    s = (text or "").rstrip()
    if not s:
        return False
    if _ANSWER_LINE_RE.match(s.splitlines()[-1]):
        return False
    return not _END_OK_RE.search(s)


def _strip_marks(s: str) -> str:
    s = _EMOJI_RE.sub("", s)
    return re.sub(r"[*_`#>]", "", s).strip(" \t-")


def _is_skippable(sentence: str) -> bool:
    plain = _strip_marks(sentence)
    return not plain or bool(_PLEASANTRY_RE.search(plain)) or plain.endswith("?")


def _lines(text: str) -> list[str]:
    out = []
    for l in text.splitlines():
        l = l.strip()
        if l and not set(l) <= set("-*_=|`") and not l.startswith("```"):
            out.append(l)
    return out


def _sentences(lines: list[str]) -> list[str]:
    """Sentences, with a lead-in that carries no value of its own ("So,",
    "**So, the correct order is:**", "### Final answer", "... is") joined to
    the line that follows it, where the value actually is."""
    def lead_in(line: str) -> bool:
        raw_end = line.rstrip(" *_")
        plain = _strip_marks(line)
        return bool(raw_end.endswith((":", ",", "=")) or re.search(r"\b(?:is|are|be)$", raw_end)
                    or (not re.search(r"\d", plain) and (line.lstrip().startswith("#") or len(plain.split()) <= 3)))

    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        # Join to the next line only when that line carries the value, not
        # when it is itself a lead-in ("Multiply:" then "So," then the value).
        if lead_in(line) and i + 1 < len(lines) and not lead_in(lines[i + 1]):
            line = f"{line} {lines[i + 1]}"
            i += 1
        out += [p.strip() for p in re.split(r"(?<=[.!?])\s+(?=[A-Z*\d])", line) if p.strip()]
        i += 1
    return out


def committed_answer(text: str) -> Commit:
    t = _normalize(text)
    truncated = is_truncated(t)
    lines = _lines(t)
    sents = _sentences(lines)
    kept = [s for s in sents[-10:] if not _is_skippable(s)]
    tail = " ".join(kept[-4:])
    conclusions = [s for s in reversed(kept)
                   if _CONCLUSION_START_RE.match(_strip_marks(s)) or _ANSWER_IS_RE.search(_strip_marks(s))]
    bolds = [s for s in reversed(kept[-6:])
             if [1 for b, u in _BOLD_RE.findall(s)
                 if not re.match(r"(?i)^\s*(step|answer|check|result|example|remember)\b", b or u)]]

    # 1. "Answer:" line or "Answer" heading -- the last one with a value.
    for i in range(len(lines) - 1, -1, -1):
        m = _ANSWER_LINE_RE.match(lines[i])
        if m:
            value = m.group(1).strip()
        elif _ANSWER_HEADING_RE.match(lines[i]):
            value = ""
        else:
            continue
        block = [value] if _strip_marks(value) else []
        block += [l for l in lines[i + 1:i + 4] if not _is_skippable(l)]
        if not block:
            continue
        if _YES_NO_RE.match(_strip_marks(block[0])):
            return Commit([block[0]] + conclusions, "answer_line", truncated, tail, yes_no=True)
        # The first line states the answer; a multi-line block ("Each gets 4 /
        # 3 left over", a factor list) is kept as the tail for those kinds.
        return Commit([block[0]], "answer_line", truncated, " ".join(block[:3]), authoritative=True)

    if conclusions:
        return Commit(conclusions + bolds[:1], "conclusion", truncated, tail)
    if bolds:
        return Commit(bolds[:1], "last_bold", truncated, tail)
    return Commit([], "none", truncated, tail)


# --------------------------------------------------------------------------- matching
def _num_value(tok: str):
    return verifier._safe_eval(response_parser._normalize_token(tok))


def _plain_numeric(segment: str, words: bool = False) -> str:
    """Segment text ready for number reading: marks stripped, clock times
    removed (never read "4:00" as 4 and 0), "a / b" with spaces read as a
    division sign (only "4/5" is a fraction), lakh/crore expanded, and
    optionally number words as digits."""
    plain = _TIME_RE.sub(" ", _strip_marks(_normalize(segment)))
    plain = re.sub(r"\^\s*\d", " ", plain)           # cm^3: the 3 is a unit, not a value
    plain = re.sub(r"(\d)\s+/\s*(\d)|(\d)\s*/\s+(\d)",
                   lambda m: f"{m.group(1) or m.group(3)} ÷ {m.group(2) or m.group(4)}", plain)
    plain = re.sub(r"(\d+(?:\.\d+)?)\s*(lakh|crore)s?\b",
                   lambda m: str(int(float(m.group(1)) * (10**5 if m.group(2).lower() == "lakh" else 10**7))),
                   plain, flags=re.IGNORECASE)
    if words:
        plain = _NUMBER_WORD_RE.sub(lambda m: _NUMBER_WORDS[m.group(1).lower()], plain)
    return plain


_STATES_RE = re.compile(r"\b(?:is|are|was|makes?|gives?|get|equals|total of|left with)\b\s*(?:Rs\s*)?([-+]?\d[\d,./]*)",
                        re.IGNORECASE)


def _result_number(segment: str, question: str) -> str | None:
    """The one number the segment states as its result, or None. Candidates
    in priority order -- the right-hand side of "=", a short bold span, a
    number after "is"/"makes"/..., the remaining digits, then number words --
    and the first that is not one of the question's own (input) numbers wins;
    if all of them are inputs ("So, 7 is greater than 3"), the top one."""
    # The question's numbers as written ("15 lakh" -> 15): expanding them
    # would make a conversion question's answer look like one of its inputs.
    q_plain = _TIME_RE.sub(" ", _strip_marks(_normalize(question or "")))
    q_vals = {str(_num_value(n)) for n in _NUM_RE.findall(q_plain)}
    # "Use 20 / 4 = 5": a division written with spaces is two inputs, not the fraction 20/4.
    q_vals |= {str(_num_value(n)) for pair in re.findall(r"(\d+)\s+/\s+(\d+)", q_plain) for n in pair}
    # A parenthetical is an aside ("4/5 metre (which is 80 cm)"), not the result.
    segment = re.sub(r"\([^()]*\)", " ", segment)
    ordered: list[str] = []
    plain = _plain_numeric(segment)
    if "=" in plain:
        ordered += _NUM_RE.findall(plain.rsplit("=", 1)[1])
    spans = [b or u for b, u in _BOLD_RE.findall(_normalize(segment)) if len((b or u).split()) <= 6]
    for span in reversed(spans):
        ordered += _NUM_RE.findall(_plain_numeric(span))
    ordered += [m.group(1).rstrip(".,") for m in reversed(list(_STATES_RE.finditer(_plain_numeric(segment, words=True))))]
    ordered += _NUM_RE.findall(plain)
    ordered += _NUM_RE.findall(_plain_numeric(segment, words=True))
    ordered = [t for t in ordered if t]
    if not ordered:
        return None
    for tok in ordered:
        if str(_num_value(tok)) not in q_vals:
            return tok
    return ordered[0]


def _norm_text(s: str) -> str:
    s = _strip_marks(_normalize(s)).lower()
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s:/,.-]", " ", s)).strip()


def _time_key(h: str, m: str) -> str:
    return f"{int(h) % 12 or 12}:{m}"


def candidate_kind(candidate: str) -> str:
    cand = str(candidate).strip()
    if _TIME_RE.fullmatch(cand.replace(" ", "")):
        return "time"
    if _YES_NO_RE.match(cand):
        return "yes_no"
    nums = _NUM_RE.findall(cand)
    words = re.sub(r"[\d,./:\s-]+", " ", cand).strip()
    if nums and re.search(r"remainder", cand, re.IGNORECASE):
        return "quotient_remainder"
    if nums and not words:
        return "list" if len(nums) > 1 else "number"
    return "text"


_OCLOCK_RE = re.compile(r"\b(\d{1,2})\s*o\s*['’]?\s*clock\b", re.IGNORECASE)
_PAST_TO_RE = re.compile(r"\b(half|quarter)\s+(past|to)\s+(\d{1,2})\b", re.IGNORECASE)


def _spoken_times(plain: str) -> set[str]:
    """ "half past 4" -> 4:30, "quarter to 5" -> 4:45, "5 o'clock" -> 5:00."""
    keys = {_time_key(h, "00") for h in _OCLOCK_RE.findall(plain)}
    for amount, rel, h in _PAST_TO_RE.findall(plain):
        mins = 30 if amount.lower() == "half" else 15
        if rel.lower() == "past":
            keys.add(_time_key(h, f"{mins:02d}"))
        else:
            keys.add(_time_key(str(int(h) - 1), f"{60 - mins:02d}"))
    return keys


def _has_value(segment: str, kind: str) -> bool:
    if kind == "time":
        plain = _strip_marks(_normalize(segment))
        return bool(_TIME_RE.search(plain) or _spoken_times(plain))
    if kind in ("number", "list", "quotient_remainder"):
        if re.search(r"\b(?:answer|it)\s+is\s+(?:yes|no)\b", _strip_marks(segment), re.IGNORECASE):
            return False   # "the answer is no" -- a yes/no commitment, not a value
        return bool(_NUM_RE.search(_plain_numeric(segment)))
    if kind == "yes_no":   # "composite" / "is prime" answer a yes/no prime question (see match)
        return bool(_YES_NO_WORD_RE.search(_strip_marks(segment))
                    or re.search(r"\b(?:composite|prime)\b", segment, re.IGNORECASE))
    return True


def match(segment: str, candidate: str, question: str = "") -> bool:
    """Does this one committed statement state this ground-truth candidate?"""
    cand = str(candidate).strip()
    if not cand or not segment:
        return False
    kind = candidate_kind(cand)
    if kind == "time":
        plain = _strip_marks(_normalize(segment))
        keys = {_time_key(h, m) for h, m in _TIME_RE.findall(plain)}
        keys |= _spoken_times(plain)
        return _time_key(*_TIME_RE.fullmatch(cand.replace(" ", "")).groups()) in keys
    if kind == "list":   # "2, 4, 7, 9": a comma-separated run of the same numbers, any order
        want = sorted({str(_num_value(n)) for n in _NUM_RE.findall(cand)})
        runs = re.findall(r"\d+(?:\s*,\s*(?:and\s+)?\d+)+", _plain_numeric(segment))
        return any(sorted({str(_num_value(n)) for n in re.findall(r"\d+", run)}) == want for run in runs)
    if kind == "number":
        tok = _result_number(segment, question)
        cv, sv = _num_value(_NUM_RE.findall(cand)[0]), _num_value(tok) if tok else None
        return cv is not None and sv is not None and bool(verifier._close(cv, sv))
    if kind == "quotient_remainder":
        plain = _plain_numeric(segment)
        seg_vals = [_num_value(n) for n in _NUM_RE.findall(plain)]
        q, r = (_num_value(n) for n in _NUM_RE.findall(cand)[:2])
        return bool(_LEFTOVER_RE.search(plain)) and q in seg_vals and r in seg_vals
    if kind == "yes_no":
        plain = _strip_marks(segment)
        said = {w.lower() for w in _YES_NO_WORD_RE.findall(plain)}
        if not said and re.search(r"\bprime\b", question, re.IGNORECASE):
            # "Is 51 a prime number?" answered "51 is a composite number".
            if re.search(r"\b(?:composite|not\s+(?:a\s+)?prime)\b", plain, re.IGNORECASE):
                said = {"no"}
            elif re.search(r"\bis\s+(?:a\s+)?prime\b", plain, re.IGNORECASE):
                said = {"yes"}
        return said == {cand.lower().rstrip(".!")}
    # Categorical / worded answer: every part present as whole words.
    nseg = _norm_text(segment)
    parts = [p.strip() for p in re.split(r"[,;]| and ", cand.lower()) if p.strip()]
    return all(re.search(r"(?<!\w)" + re.escape(_norm_text(p)) + r"(?!\w)", nseg) for p in parts)


def judge(commit: Commit, candidates: list[str], question: str = "") -> bool | None:
    """True/False once the response commits to an answer of the right kind;
    None (undecided -- for the LLM extraction step) when it doesn't."""
    decided = False
    for cand in candidates:
        kind = candidate_kind(cand)
        if commit.yes_no and kind != "yes_no":
            # "Answer: no" to a misconception question whose ground truth is
            # the corrected value: which value it commits to is a judgment
            # call, left to the LLM extraction step.
            continue
        if kind in ("list", "quotient_remainder"):
            pool = list(commit.segments) + ([commit.tail] if commit.tail else [])
        elif commit.authoritative:
            pool = commit.segments[:1]
        else:
            pool = list(commit.segments)
        seg = next((s for s in pool if _has_value(s, kind)), None)
        if seg is None and kind == "time" and cand.replace(" ", "").endswith(":00") and pool:
            # "Answer: 5" to a what-time question whose answer is 5:00 -- the
            # hour alone is a complete answer for an o'clock time.
            hour = _result_number(pool[0], question)
            if hour is not None and _num_value(hour) == int(cand.split(":")[0]):
                return True
        if seg is None:
            if commit.authoritative and kind in ("time", "number") and _NUM_RE.search(_plain_numeric(pool[0])):
                # An explicit "Answer: 550" to a what-time question commits to
                # the wrong kind of answer (minutes, not a clock time): wrong.
                decided = True
            continue
        if match(seg, cand, question):
            return True
        if kind in ("list", "quotient_remainder") and any(
                match(s, cand, question) for s in pool if _has_value(s, kind)):
            return True   # a two-line answer: "Each gets 4" / "3 left over"
        if kind != "text":
            # A worded answer that doesn't match may still be a synonym
            # ("kg" for "kilograms") -- undecided, not wrong.
            decided = True
    return False if decided else None
