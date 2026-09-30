from pathlib import Path
from research_digest.models import Paper,Evaluation
from research_digest.config import SelectionConfig


def candidate(index,**changes):
    p=Paper(title=f'Paper{index}',arxiv_id=str(index))
    ev=Evaluation.model_validate_json(Path('tests/fixtures/evaluations.json').read_text()).model_copy(update={'problem_concepts':[f'p{index}'],'method_concepts':[f'm{index}']}|changes)
    return p,ev


def select(items,attention=None,config=None,**kwargs):
    from research_digest.selection import select_daily
    papers=[p for p,_ in items]
    evaluations={p.canonical_id:ev for p,ev in items}
    scores={p.canonical_id:4.0 for p in papers} if attention is None else attention
    return select_daily(papers,evaluations,config or SelectionConfig(),scores,**kwargs)


def test_related_minor_popular_irrelevant_and_unknown_attention():
    items=[candidate(1,importance=2),candidate(2,relevance=2),candidate(3,evidence=3),candidate(4)]
    result=select(items,{p.canonical_id:None for p,_ in items})
    assert [s.paper.arxiv_id for s in result.selected]==['4']
    assert any('unknown attention' in r.reason for r in result.rejected)


def test_thresholds_and_extra_quality_do_not_pad():
    items=[candidate(i,topic_id=f't{i//2}',importance=4,evidence=4,fit=3) for i in range(6)]
    result=select(items)
    assert len(result.selected)==3  # weighted score 3.85, insufficient for extras
    low=[candidate(7,importance=3,evidence=3,fit=3)]
    assert not select(low,{'arxiv:7':3}).selected
    assert not select([]).selected


def test_topic_adjacent_and_duplicate_limits():
    assert len(select([candidate(i) for i in range(8)]).selected)==2
    assert len(select([candidate(i,topic_id=f't{i}',is_adjacent=True) for i in range(4)]).selected)==1
    pair=[candidate(1),candidate(2)]
    result=select(pair,similarities={('arxiv:1','arxiv:2'):(.96,.94)})
    assert len(result.selected)==1
    pair[1]=(pair[1][0],pair[1][1].model_copy(update={'problem_concepts':['p1'],'method_concepts':['different']}))
    assert len(select(pair).selected)==2  # same problem, distinct contribution


def test_five_strong_papers_with_deterministic_priority_ties():
    items=[candidate(i,topic_id=f't{i}') for i in range(7)]
    result=select(items,topic_priorities={'t6':5})
    assert len(result.selected)==5 and result.selected[0].paper.arxiv_id=='6'
    assert not any(s.evaluation.is_adjacent for s in result.selected)
