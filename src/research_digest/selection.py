from __future__ import annotations
from dataclasses import dataclass
from collections import Counter
from .attention import attention_label


@dataclass
class ScoredPaper:
    paper: object
    evaluation: object
    score: float
    attention_label: str


@dataclass
class Rejection:
    paper: object
    reason: str


@dataclass
class SelectionResult:
    selected: list[ScoredPaper]
    scored: list[ScoredPaper]
    rejected: list[Rejection]


def score_candidates(papers,evaluations,config,attention):
    result=[]
    for paper in papers:
        ev=evaluations.get(paper.canonical_id)
        if ev is None: continue
        att=attention.get(paper.canonical_id)
        values={'importance':ev.importance,'evidence':ev.evidence,'fit':ev.fit,'attention':att}
        weights={k:v for k,v in config.weights.items() if values[k] is not None}
        total=sum(weights.values())
        score=sum(v*values[k] for k,v in weights.items())/total if total else 0
        result.append(ScoredPaper(paper,ev,score,attention_label(paper,att)))
    return result


def _jaccard(a,b):
    a={s.casefold().strip() for s in a}; b={s.casefold().strip() for s in b}
    return len(a&b)/len(a|b) if a|b else 0


def select_daily(papers,evaluations,config,attention,similarities=None,topic_priorities=None):
    similarities,topic_priorities=similarities or {},topic_priorities or {}
    scored=score_candidates(papers,evaluations,config,attention)
    rejected=[Rejection(p,'evaluation unavailable') for p in papers if p.canonical_id not in evaluations]
    eligible=[]
    for item in scored:
        ev=item.evaluation
        reason=None
        if ev.relevance<config.min_relevance or ev.importance<config.min_importance or ev.evidence<config.min_evidence: reason='minimum score'
        elif ev.topic_id is None and not ev.is_adjacent: reason='topic unavailable'
        elif attention.get(item.paper.canonical_id) is None and (ev.importance<config.unknown_attention_min or ev.evidence<config.unknown_attention_min): reason='unknown attention requires stronger importance and evidence'
        elif item.score<config.base_min_score: reason='composite score'
        if reason: rejected.append(Rejection(item.paper,reason))
        else: eligible.append(item)
    selected,topic_counts,adjacent_count=[],Counter(),0
    def similarity(a,b):
        key=(a.paper.canonical_id,b.paper.canonical_id)
        pair=similarities.get(key,similarities.get(key[::-1]))
        if pair is not None: return pair,config.duplicate_semantic_threshold
        return (_jaccard(a.evaluation.problem_concepts,b.evaluation.problem_concepts),_jaccard(a.evaluation.method_concepts,b.evaluation.method_concepts)),config.duplicate_jaccard_threshold
    while eligible and len(selected)<config.max_count:
        available=[]
        for item in eligible:
            ev=item.evaluation
            reason=None
            if len(selected)>=config.base_count and item.score<config.extra_min_score: reason='extra minimum score'
            elif topic_counts[ev.topic_id]>=config.max_per_topic: reason='topic cap'
            elif ev.is_adjacent and adjacent_count>=config.max_adjacent: reason='adjacent cap'
            comparisons=[similarity(item,other) for other in selected]
            if not reason and any(pair[0]>=threshold and pair[1]>=threshold for pair,threshold in comparisons): reason='near duplicate problem and contribution'
            if reason: rejected.append(Rejection(item.paper,reason));continue
            redundancy=max(((pair[0]+pair[1])/2 for pair,_ in comparisons),default=0)
            mmr=config.mmr_relevance_weight*item.score/5-(1-config.mmr_relevance_weight)*redundancy
            recency=item.paper.seen_at.timestamp() if item.paper.seen_at else 0
            available.append(((-mmr,-topic_priorities.get(ev.topic_id,0),-recency,item.paper.canonical_id),item))
        if not available: break
        available.sort(key=lambda x:x[0])
        chosen=available[0][1]
        selected.append(chosen)
        topic_counts[chosen.evaluation.topic_id]+=1
        adjacent_count+=int(chosen.evaluation.is_adjacent)
        eligible=[item for _,item in available[1:]]
    for item in eligible:
        if item not in selected and not any(r.paper.canonical_id==item.paper.canonical_id for r in rejected):
            rejected.append(Rejection(item.paper,'daily count cap'))
    return SelectionResult(selected,scored,rejected)
