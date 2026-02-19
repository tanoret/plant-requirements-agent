from __future__ import annotations
from pathlib import Path
import yaml
import re
from dataclasses import dataclass
from typing import Iterable
import importlib.resources as pkg_resources
import logging

from ..models import PatternCard
from .card_validation import validate_card_dict

log = logging.getLogger(__name__)

def _tokenize(text: str) -> list[str]:
    text = text.lower()
    text = re.sub(r"[^a-z0-9_\-\s]", " ", text)
    return [t for t in text.split() if t]

@dataclass
class CardStore:
    cards: list[PatternCard]

    @classmethod
    def load_from_dir(cls, cards_dir: str | None) -> "CardStore":
        cards: list[PatternCard] = []
        sources: list[Path] = []

        if cards_dir:
            p = Path(cards_dir)
            if p.exists():
                sources.extend(sorted(p.glob("*.yaml")))

        if not sources:
            cards_root = pkg_resources.files("nucsys_agent").joinpath("data/cards")
            sources.extend([Path(str(x)) for x in sorted(cards_root.iterdir(), key=lambda x: str(x)) if str(x).endswith(".yaml")])

        for f in sources:
            try:
                raw = yaml.safe_load(Path(f).read_text(encoding="utf-8"))
                validated = validate_card_dict(raw)
                cards.append(PatternCard(**validated.model_dump()))
            except Exception as e:
                log.warning("Skipping invalid card %s: %s", f, e)

        return cls(cards=cards)

    def retrieve(self, query: str, tags: Iterable[str] = (), k: int = 8) -> list[PatternCard]:
        q_toks = _tokenize(query)
        tagset = set(t.lower() for t in tags if t)

        scored = []
        for c in self.cards:
            ctoks = _tokenize(" ".join([c.title, c.purpose, " ".join(c.tags)]))
            overlap = sum(1 for t in q_toks if t in ctoks)
            tag_boost = sum(2 for t in c.tags if t.lower() in tagset)
            scored.append((overlap + tag_boost, c))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [c for _, c in scored[:k]] if scored else []
