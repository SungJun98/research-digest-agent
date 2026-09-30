from __future__ import annotations
from contextlib import contextmanager
from dataclasses import dataclass,field
from datetime import datetime,date,timedelta,timezone
from zoneinfo import ZoneInfo
import fcntl
from .attention import attention_scores
from .config import AppConfig
from .delivery import DeliveryReport
from .embeddings import EmbeddingError,cosine
from .feedback import FeedbackService
from .identity import merge_papers
from .llm import InvalidEvaluation
from .render import render_digest,render_event
from .retrieval import Retriever
from .schedule import due_digest
from .selection import SelectionResult,score_candidates,select_daily
from .sources import SourceError
from .watch import WatchEvent,route_events


@dataclass
class PreviewReport:
    scored:list
    rejected:list
    sample_message:str
    retrieval_mode:str
    coverage_warnings:list[str]
    profile_suggestions:list
    selected:list=field(default_factory=list)
    source_failures:dict=field(default_factory=dict)


@dataclass
class RunReport:
    kind:str
    source_failures:dict[str,str]=field(default_factory=dict)
    delivery:DeliveryReport|None=None


def evaluate_candidates(papers,evaluator,topics,warnings=None):
    warnings=warnings if warnings is not None else []
    evaluations={}
    for paper in papers:
        try:evaluations[paper.canonical_id]=evaluator.evaluate(paper,topics)
        except InvalidEvaluation:
            warnings.append(f'{paper.canonical_id}: evaluation unavailable or rejected')
    return evaluations


class Runner:
    def __init__(self,config:AppConfig,store,sources,evaluator,dispatcher,clock=None,retriever=None,fulltext=None,
                 feedback=None,watch=None,semantic_source=None):
        self.config,self.store,self.sources,self.evaluator,self.dispatcher=config,store,sources,evaluator,dispatcher
        self.clock=clock or (lambda:datetime.now(timezone.utc))
        self.retriever=retriever or Retriever(config.retrieval)
        self.fulltext=fulltext
        self.feedback=feedback or FeedbackService(store)
        self.watch,self.semantic_source=watch,semantic_source

    @contextmanager
    def _lock(self):
        path=self.store.path.with_suffix('.lock')
        with path.open('a') as handle:
            path.chmod(0o600)
            try:fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:
                yield False;return
            try:yield True
            finally:fcntl.flock(handle,fcntl.LOCK_UN)

    def _channels(self):
        return [name for name in ['email','slack','discord','markdown'] if getattr(self.config.notifications,name).enabled]

    def _since(self,now):
        since=now-timedelta(hours=self.config.retrieval.lookback_hours)
        last=self.store.last_success('digest')
        if last:
            prior=datetime.combine(date.fromisoformat(last),datetime.min.time(),ZoneInfo(self.config.schedule.timezone)).astimezone(timezone.utc)
            since=min(since,prior)
        return max(since,now-timedelta(days=self.config.retrieval.catchup_days))

    def _collect(self,now,preview=False):
        candidates,failures=[],{}
        since=self._since(now)
        for source in self.sources:
            try:candidates.extend(source.fetch(since,preview=preview))
            except SourceError:failures[source.name]='source unavailable'
        if not preview:
            for paper in candidates:
                paper.metadata['digest_discovered_at']=now.isoformat()
            self.store.upsert_papers(candidates)
            for paper in self.store.list_papers():
                discovered=paper.metadata.get('digest_discovered_at')
                try:freshness=datetime.fromisoformat(discovered) if discovered else None
                except (TypeError,ValueError):freshness=None
                if freshness and freshness>=since:candidates.append(paper)
        return merge_papers(candidates),failures

    def _pipeline(self,papers,now,warnings):
        channels=self._channels()
        if channels:
            pending={c:self.store.pending_paper_ids(c) for c in channels}
            papers=[p for p in papers if not all(self.store.paper_delivered(p.canonical_id,c) or self.store.resolve(p.canonical_id) in pending[c] for c in channels)]
        batch=self.retriever.shortlist(papers,self.config.profile.topics)
        if batch.truncated:warnings.append(f'{batch.total_candidates} candidates shortlisted to {len(batch.papers)}; unevaluated papers are omitted')
        if 'embedding_failed' in batch.retrieval_mode:warnings.append('Embeddings unavailable; using source queries and categories')
        evaluations=evaluate_candidates(batch.papers,self.evaluator,self.config.profile.topics,warnings)
        # Enrich mature metrics once per UTC day. Missing/failed metrics stay unknown.
        if self.semantic_source:
            identifiers={p.canonical_id:('ARXIV:'+p.arxiv_id if p.arxiv_id else 'DOI:'+p.doi if p.doi else p.s2_id) for p in batch.papers if p.published_at and (now-p.published_at).days>=14}
            for paper in batch.papers:
                identifier=identifiers.get(paper.canonical_id)
                if not identifier:continue
                key=now.date().isoformat()+':'+identifier
                cached=self.store.get_cache('metric',key)
                if cached is None:
                    metric=self.semantic_source.paper_metrics([identifier]).get(identifier)
                    cached={'count':metric.count} if metric else {}
                    self.store.put_cache('metric',key,cached)
                if 'count' in cached:paper.signals['s2_citations']=cached['count']
        attention=attention_scores(batch.papers,evaluations,now)
        preliminary=score_candidates(batch.papers,evaluations,self.config.selection,attention)
        preliminary.sort(key=lambda item:(-item.score,item.paper.canonical_id))
        if self.fulltext and self.config.retrieval.fulltext_enabled:
            eligible=[item for item in preliminary if item.evaluation.relevance>=self.config.selection.min_relevance]
            for item in eligible[:self.config.retrieval.fulltext_top_k]:
                context=self.fulltext.fetch(item.paper,self.config.retrieval.fulltext_max_chars)
                if context:
                    try:evaluations[item.paper.canonical_id]=self.evaluator.reassess(item.paper,item.evaluation,context)
                    except InvalidEvaluation:warnings.append(f'{item.paper.canonical_id}: HTML reassessment rejected; retained abstract assessment')
        similarities=None
        if self.retriever.embedder and self.config.retrieval.embeddings_enabled and evaluations:
            ids=list(evaluations)
            try:
                vectors=self.retriever.embedder.embed([evaluations[i].problem_description for i in ids]+[evaluations[i].contribution_description for i in ids])
                similarities={(a,b):(cosine(vectors[i],vectors[j]),cosine(vectors[len(ids)+i],vectors[len(ids)+j])) for i,a in enumerate(ids) for j,b in enumerate(ids) if i<j}
            except EmbeddingError:warnings.append('Semantic diversity unavailable; using concept Jaccard')
        selection=select_daily(batch.papers,evaluations,self.config.selection,attention,similarities,
            topic_priorities={t.id:t.priority for t in self.config.profile.topics})
        return selection,batch

    def preview(self):
        now=self.clock();warnings=[]
        papers,failures=self._collect(now,preview=True)
        warnings.extend(f'{name}: source unavailable' for name in failures)
        selection,batch=self._pipeline(papers,now,warnings)
        events=[WatchEvent.model_validate(e) for e in self.store.pending_events()]
        chosen={self.store.resolve(i.paper.canonical_id) for i in selection.selected}
        events=[e for e in events if self.store.resolve(e.paper.canonical_id) not in chosen]
        message=render_digest(selection,events,self.config.profile.summary_language,self.config.notifications.max_chars_per_paper)
        return PreviewReport(selection.scored,selection.rejected,message,batch.retrieval_mode,warnings,self.feedback.suggest(self.config),selection.selected,failures)

    def _digest_complete(self,day):
        with self.store.connection() as db:
            rows=db.execute("SELECT id FROM notifications WHERE kind='digest' AND local_day=?",(day,)).fetchall()
        return bool(rows) and all(self.store.notification_complete(row[0]) for row in rows)

    def _drain(self):
        combined=DeliveryReport();days=set()
        local_day=self.clock().astimezone(ZoneInfo(self.config.schedule.timezone)).date().isoformat()
        pending=self.store.pending_notifications()
        covered=self.store.last_success('digest_covered_day')
        allowed_day=self.store.last_success('digest_covered_payload') if covered==local_day else next((n.local_day for n in pending if n.kind=='digest'),None)
        for notification in pending:
            if notification.kind=='digest' and notification.local_day!=allowed_day:continue
            result=self.dispatcher.send(notification.id,notification.subject,notification.body,notification.pending_channels)
            combined.delivered.extend(result.delivered);combined.failed.update(result.failed)
            if notification.kind=='digest' and result.delivered:
                self.store.set_last_success('digest_covered_day',local_day)
                self.store.set_last_success('digest_covered_payload',notification.local_day)
            if notification.kind=='digest' and notification.local_day:days.add(notification.local_day)
        for day in sorted(days):
            if self._digest_complete(day):
                last=self.store.last_success('digest')
                if not last or day>last:self.store.set_last_success('digest',day)
        return combined

    def run_digest(self,local_day):
        with self._lock() as acquired:
            if not acquired:return RunReport('digest',{'state':'another run is active'})
            delivery=self._drain()
            day=local_day.isoformat()
            if self._digest_complete(day):
                self.store.set_last_success('digest',day)
                return RunReport('digest',delivery=delivery)
            covered=self.store.last_success('digest_covered_day')
            if covered and covered>=day:return RunReport('digest',delivery=delivery)
            if any(n.kind=='digest' for n in self.store.pending_notifications()):return RunReport('digest',delivery=delivery)
            now=self.clock();warnings=[]
            papers,failures=self._collect(now)
            if not papers and failures and len(failures)==len(self.sources):return RunReport('digest',failures,delivery)
            selection,batch=self._pipeline(papers,now,warnings)
            if batch.papers and not selection.scored:
                return RunReport('digest',failures|{'evaluation':'all candidate assessments unavailable; retry later'},delivery)
            for item in selection.scored:item.paper.metadata['topic_id']=item.evaluation.topic_id
            self.store.upsert_papers([item.paper for item in selection.scored])
            events=[WatchEvent.model_validate(e) for e in self.store.pending_events()]
            channels=self._channels()
            if not channels:return RunReport('digest',{'channels':'no notification channels enabled'},delivery)
            entries=[]
            for channel in channels:
                owned=self.store.pending_paper_ids(channel)
                chosen=[i for i in selection.selected if not self.store.paper_delivered(i.paper.canonical_id,channel) and self.store.resolve(i.paper.canonical_id) not in owned]
                ids={self.store.resolve(i.paper.canonical_id) for i in chosen}
                pending=[e for e in events if not self.store.paper_delivered(e.paper.canonical_id,channel) and self.store.resolve(e.paper.canonical_id) not in owned]
                unique={}
                for event in pending:
                    root=self.store.resolve(event.paper.canonical_id)
                    if root not in ids:unique.setdefault(root,event)
                subset=SelectionResult(chosen,selection.scored,selection.rejected)
                body=render_digest(subset,list(unique.values()),self.config.profile.summary_language,self.config.notifications.max_chars_per_paper)
                if warnings or failures:body+='\n'+('일부 출처 또는 평가 누락이 있습니다. preview에서 확인하세요.\n' if self.config.profile.summary_language.startswith('ko') else 'Some sources or assessments were unavailable. Inspect preview.\n')
                entries.append(dict(key=f'digest:{day}:{channel}',subject=f'Research digest · {day}',body=body,channels=[channel],
                    paper_ids=[i.paper.canonical_id for i in chosen]+[e.paper.canonical_id for e in unique.values()],
                    event_ids=[e.id for e in pending],local_day=day,kind='digest'))
            self.store.create_notifications(entries)
            result=self._drain();delivery.delivered.extend(result.delivered);delivery.failed.update(result.failed)
            if self._digest_complete(day):self.store.set_last_success('digest',day)
            for event in events:
                if all(self.store.paper_delivered(event.paper.canonical_id,c) for c in channels):self.store.finish_event(event.id)
            return RunReport('digest',failures,delivery)

    def run_watch(self):
        with self._lock() as acquired:
            if not acquired:return RunReport('watch',{'state':'another run is active'})
            delivery=self._drain();now=self.clock()
            if not self.watch:return RunReport('watch',delivery=delivery)
            self.watch.scan(self.config.watchlist,now)
            events=[WatchEvent.model_validate(e) for e in self.store.pending_events()]
            channels=self._channels()
            # Coalesce same-paper watches and finish events already delivered everywhere.
            unique={}
            for event in events:
                if channels and all(self.store.paper_delivered(event.paper.canonical_id,c) for c in channels):
                    self.store.finish_event(event.id);continue
                unique.setdefault(self.store.resolve(event.paper.canonical_id),event)
            immediate,_=route_events(list(unique.values()),self.config.notifications,self.store,now,set(),timezone_name=self.config.schedule.timezone)
            day=now.astimezone(ZoneInfo(self.config.schedule.timezone)).date().isoformat()
            for event in immediate:
                missing=[c for c in channels if not self.store.paper_delivered(event.paper.canonical_id,c) and self.store.resolve(event.paper.canonical_id) not in self.store.pending_paper_ids(c)]
                if not missing:continue
                related=[e.id for e in events if self.store.resolve(e.paper.canonical_id)==self.store.resolve(event.paper.canonical_id)]
                self.store.create_notification('event:'+event.id,'Research follow-up',render_event(event,self.config.profile.summary_language,self.config.notifications.max_chars_per_paper),missing,[event.paper.canonical_id],related,day,'immediate')
            result=self._drain();delivery.delivered.extend(result.delivered);delivery.failed.update(result.failed)
            self.store.set_last_success('watch',now)
            return RunReport('watch',{'watch':'; '.join(self.watch.errors)} if self.watch.errors else {},delivery)

    def tick(self,now):
        reports=[]
        last=self.store.last_success('digest')
        covered=self.store.last_success('digest_covered_day')
        last=max(value for value in [last,covered] if value) if last or covered else None
        day=due_digest(now,self.config.schedule.timezone,self.config.schedule.digest_at,date.fromisoformat(last) if last else None)
        if day:
            local=now.astimezone(ZoneInfo(self.config.schedule.timezone))
            scheduled=datetime.combine(day,self.config.schedule.digest_at,local.tzinfo)
            if self.config.schedule.catchup or (local-scheduled).total_seconds()<60:reports.append(self.run_digest(day))
        last_watch=self.store.last_success('watch')
        if self.watch and (not last_watch or now-datetime.fromisoformat(last_watch)>=timedelta(minutes=self.config.schedule.watch_poll_minutes)):
            reports.append(self.run_watch())
        return reports
