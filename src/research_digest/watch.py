from __future__ import annotations
from datetime import datetime, timezone
from typing import Literal
from zoneinfo import ZoneInfo
from pydantic import BaseModel
from .models import Paper,Evaluation
from .config import Topic,default_topics
from .identity import merge_pair
from .sources import SourceError
from .llm import InvalidEvaluation


class WatchEvent(BaseModel):
    id: str
    kind: Literal['author_paper','paper_citation']
    subject_id: str
    paper: Paper
    discovered_at: datetime
    evaluation: Evaluation
    delivery_policy: Literal['immediate','next_digest']


class WatchService:
    def __init__(self,source,store,evaluator,topics=None):
        self.source,self.store,self.evaluator=source,store,evaluator
        self.topics=topics or default_topics()
        self.errors=[]

    def scan(self,watchlist,now,scholar_candidates=None):
        events=[];self.errors=[]
        enrichment={self.store.resolve(p.canonical_id):p for p in (scholar_candidates or [])}
        epoch=datetime(1970,1,1,tzinfo=timezone.utc)
        for kind,watches in [('author',watchlist.authors),('paper',watchlist.papers)]:
            for watched in watches:
                subject=f'{kind}:{watched.id}'
                try:
                    papers=self.source.author_papers(watched.id,epoch) if kind=='author' else self.source.paper_citations(watched.id,epoch)
                    self.store.upsert_papers(papers)
                    if self.store.get_watch_cursor(subject) is None:
                        for paper in papers:self.store.mark_watch_item_seen(subject,self.store.resolve(paper.canonical_id))
                        self.store.set_watch_cursor(subject,now.isoformat())
                        continue
                    topics=self.topics
                    if kind=='paper':
                        followed=self.source.paper(watched.id)
                        topics=[Topic(id='followup',description=(
                            'Select ONLY substantive extensions, comparisons, corrections or new evidence addressing the followed problem. '
                            'An incidental citation is insufficient: assign relevance below 3 if there is no concrete relationship. '
                            f'Followed work: {followed.title}. Problem and method: {followed.abstract[:8000]}'))]
                    elif not watched.topic_filter:
                        topics=[Topic(id='author',description='New research by this explicitly followed author, in any subject.')]
                    for paper in papers:
                        stable_id=self.store.resolve(paper.canonical_id)
                        if self.store.watch_item_seen(subject,stable_id):continue
                        if stable_id in enrichment:paper=merge_pair(paper,enrichment[stable_id])
                        try:evaluation=self.evaluator.evaluate(paper,topics)
                        except InvalidEvaluation:
                            self.errors.append(f'{subject}: evaluation unavailable; retry later')
                            continue
                        self.store.mark_watch_item_seen(subject,stable_id)
                        if evaluation.relevance<3 or (kind=='paper' and (evaluation.importance<3 or evaluation.evidence<3 or evaluation.topic_id!='followup')):continue
                        event_kind='author_paper' if kind=='author' else 'paper_citation'
                        event_id=f'{event_kind}:{watched.id}:{stable_id}'
                        event=WatchEvent(id=event_id,kind=event_kind,subject_id=watched.id,paper=paper,
                            discovered_at=now,evaluation=evaluation,delivery_policy=watched.policy)
                        self.store.queue_event(event_id,event)
                        events.append(event)
                    self.store.set_watch_cursor(subject,now.isoformat())
                except SourceError:
                    self.errors.append(f'{subject}: source unavailable; cursor preserved')
        return events


def route_events(events,policy,store,now,selected_today_ids,timezone_name='Asia/Seoul'):
    local_day=now.astimezone(ZoneInfo(timezone_name)).date().isoformat()
    slots=max(0,policy.max_immediate_per_day-store.immediate_count(local_day))
    immediate,queued=[],[]
    selected={store.resolve(p) for p in selected_today_ids}
    for event in events:
        store.queue_event(event.id,event)
        if store.resolve(event.paper.canonical_id) in selected:continue  # Daily renderer coalesces the persisted event with the paper.
        if event.delivery_policy=='immediate' and len(immediate)<slots:
            immediate.append(event)
        else:
            event=event.model_copy(update={'delivery_policy':'next_digest'})
            with store.connection() as db:
                db.execute('UPDATE events SET data=? WHERE id=? AND done=0',(event.model_dump_json(),event.id))
            queued.append(event)
    return immediate,queued
