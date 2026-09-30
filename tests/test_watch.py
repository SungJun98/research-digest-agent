from pathlib import Path
from datetime import datetime,timezone,timedelta
from research_digest.models import Paper,Evaluation
from research_digest.config import Watchlist,AuthorWatch,PaperWatch,NotificationConfig,Topic
from research_digest.store import Store

NOW=datetime(2026,9,30,tzinfo=timezone.utc)


class Source:
    def __init__(self):
        self.authors=[Paper(title='Old',s2_id='old',abstract='Old abstract')]
        self.citations=[]
    def author_papers(self,author_id,since):return self.authors
    def paper_citations(self,paper_id,since):return self.citations
    def paper(self,paper_id):return Paper(title='Followed work',abstract='Reliable oversight under uncertainty.',s2_id='target')


class Evaluator:
    def __init__(self):self.topics=[]
    def evaluate(self,paper,topics):
        self.topics.extend(topics)
        ev=Evaluation.model_validate_json(Path('tests/fixtures/evaluations.json').read_text())
        return ev.model_copy(update={'topic_id':topics[0].id,'relevance':1 if paper.title=='Irrelevant' else 4})


def test_baseline_new_author_and_substantive_citation(tmp_path):
    from research_digest.watch import WatchService
    source=Source();store=Store(tmp_path/'state.db');evaluator=Evaluator()
    service=WatchService(source,store,evaluator,topics=[Topic(id='safety',description='Safety')])
    watch=Watchlist(authors=[AuthorWatch(id='123')],papers=[PaperWatch(id='ARXIV:2605.21849')])
    assert service.scan(watch,NOW)==[] and store.get_watch_cursor('author:123')
    source.authors.append(Paper(title='New Safety',s2_id='new',abstract='New safety method'))
    source.citations=[Paper(title='Extension',s2_id='extension',abstract='Extends uncertainty-aware oversight.'),Paper(title='Irrelevant',s2_id='unrelated',abstract='Cites work incidentally.')]
    events=service.scan(watch,NOW+timedelta(hours=1))
    assert {e.kind for e in events}=={'author_paper','paper_citation'}
    assert any('Reliable oversight' in t.description for t in evaluator.topics)
    assert store.watch_item_seen('paper:ARXIV:2605.21849','s2:unrelated')
    assert service.scan(watch,NOW+timedelta(hours=2))==[]
    assert len(store.pending_events())==2


def test_route_cap_dedup_overflow_and_midnight(tmp_path):
    from research_digest.watch import WatchEvent,route_events
    store=Store(tmp_path/'state.db')
    evaluation=Evaluation.model_validate_json(Path('tests/fixtures/evaluations.json').read_text())
    events=[WatchEvent(id=f'e{i}',kind='author_paper',subject_id='a',paper=Paper(title=f'P{i}',s2_id=str(i)),discovered_at=NOW,evaluation=evaluation,delivery_policy='immediate') for i in range(5)]
    policy=NotificationConfig()
    immediate,queued=route_events(events,policy,store,NOW,{'s2:0'},timezone_name='UTC')
    assert len(immediate)==3 and len(queued)==1 and store.pending_events()
    for e in immediate:store.create_notification('event:'+e.id,'P','B',['markdown'],local_day=NOW.date().isoformat(),kind='immediate')
    immediate,queued=route_events([events[4]],policy,Store(tmp_path/'state.db'),NOW,set(),timezone_name='UTC')
    assert immediate==[] and len(queued)==1
    immediate,_=route_events([events[4]],policy,store,NOW+timedelta(days=1),set(),timezone_name='UTC')
    assert len(immediate)==1
