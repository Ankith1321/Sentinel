import re
from dataclasses import asdict, dataclass

CITATION_GROUP = re.compile(r"\[(S\d+(?:\s*[,;]\s*S?\d+)*)\]")
CITATION_NUMBER = re.compile(r"\d+")
BACKTICKED = re.compile(r"`([^`\n]{2,80})`")
IDENTIFIER_LIKE = re.compile(r"^[A-Za-z_][\w./-]*(?:\(\))?$")
ABSTAIN = re.compile(
    r"do(?:es)? not contain|don't contain|doesn't contain|no (?:relevant )?information|"
    r"cannot (?:find|determine)|can't (?:find|determine)|not (?:mentioned|provided|covered|enough)|"
    r"unable to find|doesn't (?:say|mention)|does not (?:say|mention)|"
    r"not directly (?:described|covered|addressed|mentioned)",
    flags=re.IGNORECASE,
)
MIN_TERM_LENGTH = 3


@dataclass(frozen=True)
class AnswerChecks:
    cited_sources: list[int]
    invalid_citations: list[int]
    unsupported_terms: list[str]
    abstained: bool
    needs_review: bool

    def to_dict(self) -> dict:
        return asdict(self)


def mentioned_terms(answer: str) -> set[str]:
    terms = set()

    for raw in BACKTICKED.findall(answer):
        term = raw.strip()
        if IDENTIFIER_LIKE.match(term):
            terms.add(term.removesuffix("()"))

    return {t for t in terms if len(t) >= MIN_TERM_LENGTH}


def check_answer(answer: str, contexts: list[dict]) -> AnswerChecks:
    cited = sorted({int(n) for group in CITATION_GROUP.findall(answer) for n in CITATION_NUMBER.findall(group)})
    valid = [n for n in cited if 1 <= n <= len(contexts)]
    invalid = [n for n in cited if n not in valid]

    passages = "\n".join(c["content"] for c in contexts)
    unsupported = sorted(t for t in mentioned_terms(answer) if t not in passages)
    abstained = bool(ABSTAIN.search(answer))

    needs_review = not abstained and (not valid or bool(invalid) or bool(unsupported))
    return AnswerChecks(valid, invalid, unsupported, abstained, needs_review)
