"""Look up part families in the user's local mechanical components catalog."""

import math
import os
import re
from collections import Counter
from pathlib import Path


def catalog_path():
    configured = os.environ.get("SOLIDWORKS_PARTS_LIBRARY")
    return Path(configured).expanduser() if configured else Path.home() / "Desktop" / "mechanical parts library.md"


def _entries(text):
    section = None
    for line in text.splitlines():
        line = line.strip()
        heading = re.fullmatch(r"(?:###\s+)?\d+\.\s+(.+)", line)
        if heading:
            section = heading[1]
            continue
        if not section or not line.startswith(("* ", "- ", "• ")):
            continue
        family, sep, descriptions = line[2:].replace("**", "").partition(":")
        if not sep:
            continue
        # Commas inside parentheses separate variants or standards of the same item.
        for description in re.split(r",\s*(?![^()]*\))", descriptions.strip().rstrip(".")):
            if description:
                yield section, family, description


def _terms(text):
    text = re.sub(r"\b(iso|din|astm|jis|as)\s*(?=\d)", r"\1 ", text.lower())
    text = re.sub(r"\b\d+(?:\.\d+)?\s*(?:mm|cm|inch|degrees?)\b", " ", text)
    ignore = {"a", "an", "the", "make", "create", "new", "plan", "design", "please", "with", "on",
              "of", "for", "and", "in", "to", "mm", "part", "parts", "my", "i", "need", "me", "it"}
    return {word.removesuffix("s") if len(word) > 3 and not word.endswith("ss") else word
            for word in re.findall(r"[a-z0-9]+", text) if word not in ignore}


def lookup(query, limit=6):
    path = catalog_path()
    records = list(_entries(path.read_text(encoding="utf-8-sig")))
    if not records:
        raise ValueError(f"No component catalog entries found in {path}.")
    wanted = _terms(query)
    indexed = [(_terms(desc), _terms(family), _terms(section)) for section, family, desc in records]
    counts = Counter(term for groups in indexed for term in set.union(*groups))
    weights = {term: math.log1p(len(records) / counts[term]) for term in wanted if counts[term]}
    ranked = []
    for record, (item, family, section) in zip(records, indexed):
        score = sum(weight * (3 if term in item else 1 if term in family else 0.25 if term in section else 0)
                    for term, weight in weights.items())
        if weights.keys() <= item:
            score *= 1.5
        if score:
            ranked.append((score, record))
    ranked.sort(key=lambda row: -row[0])
    return [f"{section} / {family} — {desc}" for score, (section, family, desc) in ranked[:limit]
            if score >= ranked[0][0] / 2]
