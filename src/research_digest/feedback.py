from __future__ import annotations
from dataclasses import dataclass
from collections import defaultdict
from typing import Literal

FeedbackKind = Literal['useful','not_relevant','already_known','weak_evidence']
KINDS = {'useful','not_relevant','already_known','weak_evidence'}


@dataclass
class ProfileSuggestion:
    topic_id: str | None
    field: str
    proposed_value: str | int
    reason: str
    supporting_paper_ids: list[str]


class FeedbackService:
    def __init__(self,store): self.store=store

    def record(self,paper_id,kind,topic_id,now):
        if kind not in KINDS: raise ValueError('invalid feedback kind')
        paper=self.store.get_paper(paper_id)
        if not paper: raise ValueError('unknown paper ID')
        self.store.record_feedback(paper_id,kind,topic_id or paper.metadata.get('topic_id'),now)

    def suggest(self,config):
        if not config.feedback.enabled or not config.feedback.suggestions_enabled: return []
        groups=defaultdict(set)
        for row in self.store.list_feedback():
            groups[(row['topic_id'],row['kind'])].add(row['paper_id'])
        suggestions=[]
        for topic in config.profile.topics:
            for kind,delta in [('useful',1),('not_relevant',-1)]:
                support=groups[(topic.id,kind)]
                opposing=groups[(topic.id,'not_relevant' if kind=='useful' else 'useful')]
                proposed=max(1,min(5,topic.priority+delta))
                if len(support)>=config.feedback.min_explicit_signals and not opposing and proposed!=topic.priority:
                    suggestions.append(ProfileSuggestion(topic.id,'priority',proposed,f'Repeated explicit {kind} feedback',sorted(support)))
        weak=set().union(*(ids for (_,kind),ids in groups.items() if kind=='weak_evidence')) if groups else set()
        if len(weak)>=config.feedback.min_explicit_signals and config.selection.min_evidence<5:
            suggestions.append(ProfileSuggestion(None,'selection.min_evidence',config.selection.min_evidence+1,'Repeated explicit weak_evidence feedback',sorted(weak)))
        return suggestions
