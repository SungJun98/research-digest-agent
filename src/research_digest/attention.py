"""Compare only measured reactions within sufficiently large, comparable cohorts."""
from collections import defaultdict
import math


def observed(value):
    return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) and value>=0


def attention_scores(papers,evaluations,now):
    cohorts=defaultdict(list)
    result={p.canonical_id:None for p in papers}
    for p in papers:
        ev=evaluations.get(p.canonical_id)
        if not ev: continue
        topic=ev.topic_id or 'adjacent'
        votes=p.signals.get('hf_upvotes')
        day=p.metadata.get('hf_posted_date')
        if observed(votes) and day:
            cohorts[('hf',topic,day)].append((p.canonical_id,votes))
        citations=p.signals.get('s2_citations')
        if observed(citations) and p.published_at:
            age=(now-p.published_at).total_seconds()/86400
            if age>=14:
                age_bin='14-30' if age<=30 else '31-180' if age<=180 else '181+'
                cohorts[('s2',topic,age_bin)].append((p.canonical_id,citations/age))
    values=defaultdict(list)
    for cohort in cohorts.values():
        if len(cohort)<10: continue
        ordered=sorted(v for _,v in cohort)
        for paper_id,value in cohort:
            ranks=[i for i,v in enumerate(ordered) if v==value]
            percentile=sum(ranks)/len(ranks)/(len(cohort)-1)
            values[paper_id].append(percentile*5)
    for paper_id,scores in values.items(): result[paper_id]=sum(scores)/len(scores)
    return result


def attention_label(paper,score):
    measured=[]
    for key,label in [('hf_upvotes','HF votes'),('s2_citations','S2 citations')]:
        value=paper.signals.get(key)
        if observed(value): measured.append(f'{label} {value:g}')
    raw=', '.join(measured)
    if score is None: return 'attention unknown'+(f' ({raw}; insufficient comparable cohort)' if raw else '')
    return f'attention {score:.1f}/5'+(f' ({raw})' if raw else '')
