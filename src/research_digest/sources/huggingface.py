from __future__ import annotations
import time
from datetime import date
from ..models import Paper
from . import SourceError, request_json


class HuggingFaceSource:
    def __init__(self, client, limit=100, sleep=time.sleep):
        self.client, self.limit, self.sleep = client, limit, sleep

    def fetch(self, dates: list[date]) -> list[Paper]:
        result = []
        for day in dates:
            data = request_json(self.client, 'https://huggingface.co/api/daily_papers', label='Hugging Face',
                                params={'date': day.isoformat(), 'limit': self.limit}, sleep=self.sleep)
            try:
                if not isinstance(data, list):
                    raise ValueError()
                for rank, item in enumerate(data[:self.limit], 1):
                    paper = item['paper']
                    signals = {'hf_daily_rank': rank}
                    votes = paper.get('upvotes', item.get('upvotes'))
                    if isinstance(votes, (int, float)) and not isinstance(votes, bool) and votes >= 0:
                        signals['hf_upvotes'] = votes
                    posted = item.get('publishedAt') or paper.get('submittedOnDailyAt') or day.isoformat()+'T00:00:00Z'
                    result.append(Paper(arxiv_id=paper['id'], title=paper['title'], abstract=paper.get('summary') or '',
                        authors=[a['name'] for a in paper.get('authors', []) if a.get('name')],
                        url=f"https://huggingface.co/papers/{paper['id']}", published_at=paper.get('publishedAt'),
                        seen_at=posted, sources={'huggingface'}, signals=signals,
                        metadata={'hf_posted_date': posted[:10], 'hf_url': f"https://huggingface.co/papers/{paper['id']}"}))
            except (KeyError, ValueError, TypeError, AttributeError):
                raise SourceError('Hugging Face: invalid response') from None
        return result
