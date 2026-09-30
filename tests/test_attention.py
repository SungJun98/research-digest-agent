from datetime import datetime,timezone,timedelta
import json
from pathlib import Path

NOW=datetime(2026,9,30,tzinfo=timezone.utc)


def cohort(count=10,age=20):
    from research_digest.models import Paper,Evaluation
    ev=Evaluation.model_validate_json(Path('tests/fixtures/evaluations.json').read_text())
    papers=[Paper(title=f'P{i}',arxiv_id=str(i),published_at=NOW-timedelta(days=age),signals={'hf_upvotes':i,'s2_citations':i},metadata={'hf_posted_date':'2026-09-30'}) for i in range(count)]
    return papers,{p.canonical_id:ev for p in papers}


def test_measured_zero_missing_and_small_cohort():
    from research_digest.attention import attention_scores
    papers,evs=cohort()
    scores=attention_scores(papers,evs,NOW)
    assert scores[papers[0].canonical_id]==0 and scores[papers[-1].canonical_id]==5
    papers[0].signals={}
    scores=attention_scores(papers,evs,NOW)
    assert all(v is None for v in scores.values())
    papers,evs=cohort(9)
    assert all(v is None for v in attention_scores(papers,evs,NOW).values())


def test_age_topic_and_day_separate_cohorts():
    from research_digest.attention import attention_scores
    papers,evs=cohort(age=13)
    for p in papers: p.signals.pop('hf_upvotes')
    assert all(v is None for v in attention_scores(papers,evs,NOW).values())
    papers[0].published_at=NOW-timedelta(days=40)
    assert all(v is None for v in attention_scores(papers,evs,NOW).values())
    papers,evs=cohort()
    papers[0].metadata['hf_posted_date']='2026-09-29'
    for p in papers:p.signals.pop('s2_citations')
    assert all(v is None for v in attention_scores(papers,evs,NOW).values())
