import re
from dataclasses import dataclass

BLOCKED_ANSWER = (
    "This question asks Sentinel to ignore or reveal its instructions, so it was not answered. "
    "Ask about the codebase instead."
)
GATED_ANSWER = (
    "The retrieved passages do not contain the answer: nothing in the indexed codebase is close enough to "
    "this question, so Sentinel did not generate one."
)

INJECTION_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\b(ignore|disregard|forget|override|bypass)\b[^.?!]{0,30}\b(previous|prior|above|earlier|all|any|your|these|those)\b"
        r"[^.?!]{0,20}\b(instructions?|rules|prompts?|guidelines|directions|constraints)\b",
        r"\b(reveal|show|print|repeat|output|leak|dump|tell me)\b[^.?!]{0,20}\b(your|the)\b[^.?!]{0,15}"
        r"\b(system|hidden|initial|original|secret)\s+(prompt|instructions?|message|rules)\b",
        r"\byou are (now|no longer)\b",
        r"\b(developer|god|jailbreak|unrestricted|unfiltered) mode\b",
        r"\bdo anything now\b",
        r"\bpretend (you are|to be|that you)\b",
        r"\b(answer|respond|reply)\b[^.?!]{0,15}\bwithout\b[^.?!]{0,15}\b(citations?|citing|sources|restrictions|rules)\b",
        r"\b(use|rely on|answer from)\b[^.?!]{0,10}\b(your|outside|general|prior)\s+(own\s+)?knowledge\b",
    )
]

SECRET_PATTERNS = [
    (
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL),
        "[REDACTED PRIVATE KEY]",
    ),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[REDACTED AWS KEY]"),
    (re.compile(r"\bsk-(?:ant-)?[A-Za-z0-9_\-]{20,}"), "[REDACTED API KEY]"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"), "[REDACTED TOKEN]"),
    (re.compile(r"\bsnt_[A-Za-z0-9_\-]{20,}"), "[REDACTED API KEY]"),
    (
        re.compile(
            r"(?i)\b((?:secret|password|passwd|pwd|api[_-]?key|access[_-]?token|auth[_-]?token|private[_-]?key)\w*"
            r"\s*[:=]\s*)(['\"])([^'\"\s]{8,})\2"
        ),
        r"\1\2[REDACTED]\2",
    ),
]

WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]{3,}")
SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
CITATION = re.compile(r"\[S\d+(?:\s*[,;]\s*S?\d+)*\]")
MIN_SENTENCE_WORDS = 3
SUPPORTED_COVERAGE = 0.5
STOPWORDS = frozenset(
    """
    about above after again also another because been before being below between both cannot could does doing down
    during each either else every from further have having here into itself just more most much must never only other
    otherwise over same should since some such than that their them then there these they this those through under
    until upon very want were what when where whether which while whom whose will with within without would your
    answer passage passages source sources provided retrieved file files class function method code used uses using
    based specific defined defines define following include includes including relevant called handles handled
    """.split()
)


def injection_reason(question: str) -> str | None:
    for pattern in INJECTION_PATTERNS:
        if pattern.search(question):
            return "prompt_injection"
    return None


def redact(text: str) -> tuple[str, int]:
    count = 0
    for pattern, replacement in SECRET_PATTERNS:
        text, n = pattern.subn(replacement, text)
        count += n
    return text, count


@dataclass(frozen=True)
class Support:
    ratio: float
    checked: int
    unsupported: list[str]


def sentence_support(answer: str, passages: list[str]) -> Support:
    vocabulary = {w.lower() for passage in passages for w in WORD.findall(passage)}
    checked = 0
    unsupported: list[str] = []

    for sentence in SENTENCE_SPLIT.split(CITATION.sub(" ", answer)):
        words = [w.lower() for w in WORD.findall(sentence) if w.lower() not in STOPWORDS]
        if len(words) < MIN_SENTENCE_WORDS:
            continue
        checked += 1
        coverage = sum(w in vocabulary for w in words) / len(words)
        if coverage < SUPPORTED_COVERAGE:
            unsupported.append(sentence.strip())

    ratio = 1.0 if checked == 0 else round(1 - len(unsupported) / checked, 3)
    return Support(ratio=ratio, checked=checked, unsupported=unsupported)
