"""Strong identifier aliases; conservative title/first-author fallback."""
from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from typing import TYPE_CHECKING, Iterable
from urllib.parse import unquote, urlparse

if TYPE_CHECKING:
    from .models import Paper


def normalize_arxiv(value: str) -> str:
    value = unquote(value.strip()).lower().removeprefix('arxiv:')
    if 'arxiv.org/' in value:
        value = urlparse(value).path.removeprefix('/abs/').removeprefix('/pdf/').removeprefix('/html/')
    value = value.removesuffix('.pdf')
    return re.sub(r'v\d+$', '', value)


def normalize_doi(value: str) -> str:
    return unquote(value.strip()).lower().removeprefix('https://doi.org/').removeprefix('http://doi.org/').removeprefix('doi:').strip()


def slug(text: str) -> str:
    return ' '.join(re.findall(r'\w+', unicodedata.normalize('NFKC', text).casefold()))


def aliases(paper: Paper) -> set[str]:
    identifiers = set()
    if paper.doi:
        identifiers.add('doi:' + normalize_doi(paper.doi))
    if paper.arxiv_id:
        identifiers.add('arxiv:' + normalize_arxiv(paper.arxiv_id))
    if paper.s2_id:
        identifiers.add('s2:' + paper.s2_id.lower())
    return identifiers or {'title:' + slug(paper.title) + ':' + slug(paper.authors[0] if paper.authors else '')}


def canonicalize(paper: Paper) -> str:
    return min(aliases(paper), key=lambda a: ({'doi': 0, 'arxiv': 1, 's2': 2, 'title': 3}[a.split(':', 1)[0]], a))


def merge_pair(a: Paper, b: Paper) -> Paper:
    data = a.model_dump()
    for key in ['doi', 'arxiv_id', 's2_id', 'url']:
        data[key] = data[key] or getattr(b, key)
    for key in ['title', 'abstract']:
        if len(getattr(b, key)) > len(data[key]):
            data[key] = getattr(b, key)
    data['authors'] = list(dict.fromkeys(a.authors + b.authors))
    data['sources'] = a.sources | b.sources
    data['signals'] = a.signals | b.signals
    data['metadata'] = a.metadata | b.metadata
    for key in ['published_at', 'seen_at']:
        dates = [d for d in [getattr(a, key), getattr(b, key)] if d]
        data[key] = (min(dates) if key == 'published_at' else max(dates)) if dates else None
    return a.__class__.model_validate(data)


def merge_papers(papers: Iterable[Paper]) -> list[Paper]:
    papers = list(papers)
    parent = list(range(len(papers)))
    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    owners = {}
    for i, paper in enumerate(papers):
        for alias in aliases(paper):
            if alias in owners:
                parent[root(i)] = root(owners[alias])
            else:
                owners[alias] = i
    groups = defaultdict(list)
    for i, paper in enumerate(papers):
        groups[root(i)].append(paper)
    merged = []
    for group in groups.values():
        paper = group[0]
        for other in group[1:]:
            paper = merge_pair(paper, other)
        merged.append(paper)
    return merged
