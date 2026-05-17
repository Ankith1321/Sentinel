from dataclasses import dataclass, asdict
from typing import Optional


@dataclass
class SourceRecord:
    source_id: str
    source_type: str
    path: str
    language: str
    title: Optional[str]
    content: str

    def to_dict(self) -> dict:
        return asdict(self)