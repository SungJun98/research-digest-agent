from __future__ import annotations
from dataclasses import dataclass
import re
from .embeddings import cosine, EmbeddingError
from .identity import merge_papers

STOP = {'and','the','of','in','for','to','a','an','with','under','or','model','models','learning'}


def concepts(text):
    return set(re.findall(r'\w+',text.casefold()))-STOP


@dataclass
class CandidateBatch:
    papers: list
    retrieval_mode: str
    truncated: bool
    total_candidates: int


class Retriever:
    def __init__(self,config,embedder=None):
        self.config,self.embedder = config,embedder

    def shortlist(self,papers,topics):
        papers = merge_papers(papers)
        topics = sorted(topics,key=lambda t:(-t.priority,t.id))
        mode, vectors = 'source_queries_and_categories', None
        if self.config.embeddings_enabled and self.embedder:
            try:
                vectors = self.embedder.embed([t.description for t in topics]+[p.title+'\n'+p.abstract[:12000] for p in papers])
                mode = 'semantic_embeddings'
            except EmbeddingError:
                mode += ':embedding_failed'
        rankings = []
        for index,topic in enumerate(topics):
            terms = concepts(topic.description+' '+' '.join(topic.include))
            def score(pair):
                i,p = pair
                if vectors is not None: return cosine(vectors[index],vectors[len(topics)+i])
                return len(terms & concepts(p.title+' '+p.abstract))/max(1,len(terms))
            rankings.append([p for _,p in sorted(enumerate(papers),key=lambda pair:(-score(pair),pair[1].canonical_id))])
        # Fair coverage first; priority controls deterministic ordering when the cap is tight.
        topic_budget = max(1,self.config.max_evaluations-self.config.extra_candidates)
        picked = {}
        for rank in range(self.config.top_k_per_topic):
            for ranking in rankings:
                for paper in ranking[rank:]:
                    if paper.canonical_id not in picked:
                        picked[paper.canonical_id] = paper
                        break
                if len(picked) >= topic_budget: break
            if len(picked) >= topic_budget: break
        adjacent = {'uncertainty','robustness','efficient','efficiency','verification','risk'}
        def extra_score(p):
            votes = p.signals.get('hf_upvotes',-1)
            citations = p.signals.get('s2_citations',-1)
            return (votes,citations,len(adjacent & concepts(p.title+' '+p.abstract)))
        added = 0
        for paper in sorted(papers,key=lambda p:(tuple(-v for v in extra_score(p)),p.canonical_id)):
            if added >= self.config.extra_candidates or len(picked) >= self.config.max_evaluations: break
            if paper.canonical_id not in picked:
                picked[paper.canonical_id] = paper
                added += 1
        chosen = list(picked.values())[:self.config.max_evaluations]
        return CandidateBatch(chosen,mode,len(chosen)<len(papers),len(papers))
