"""Explicit synthetic fixtures; never an alternative live scoring implementation."""
import json
from importlib.resources import files
from .models import Paper,Evaluation
from .runner import Runner
from .store import Store
from .delivery import Dispatcher
from .retrieval import Retriever,concepts


def offline_runner(config,state_path):
    data=json.loads(files('research_digest').joinpath('demo/papers.json').read_text())
    papers=[Paper.model_validate(item['paper']) for item in data]
    evaluations={p.canonical_id:Evaluation.model_validate(item['evaluation']) for p,item in zip(papers,data)}
    class Source:
        name='offline_synthetic_fixtures'
        def fetch(self,since,preview=False):return papers
    class FixtureEvaluator:
        def evaluate(self,paper,topics):
            result=evaluations[paper.canonical_id]
            if result.topic_id not in {t.id for t in topics}:
                text=concepts(paper.title+' '+paper.abstract)
                topic=max(topics,key=lambda t:len(text&concepts(t.description)))
                result=result.model_copy(update={'topic_id':topic.id})
            return result
    cfg=config.model_copy(deep=True)
    cfg.retrieval.embeddings_enabled=False
    store=Store(state_path)
    return Runner(cfg,store,[Source()],FixtureEvaluator(),Dispatcher(store,{}),retriever=Retriever(cfg.retrieval))
