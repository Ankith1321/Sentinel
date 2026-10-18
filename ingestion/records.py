from dataclasses import asdict, dataclass


@dataclass
class SourceRecord:
    source_id: str
    source_type: str
    path: str
    language: str
    title: str | None
    content: str
    content_hash: str = ""

    def to_dict(self) -> dict:
        return asdict(self)