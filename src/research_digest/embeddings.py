from __future__ import annotations
import hashlib
import json
import math
import os
import httpx


class EmbeddingError(RuntimeError):
    pass


def cosine(a,b):
    if len(a) != len(b): raise EmbeddingError('embedding dimensions differ')
    denominator = math.sqrt(sum(v*v for v in a))*math.sqrt(sum(v*v for v in b))
    return max(0.0,min(1.0,sum(x*y for x,y in zip(a,b))/denominator)) if denominator else 0.0


class Embedder:
    def __init__(self,client,config,store):
        self.client,self.config,self.store = client,config,store

    def _key(self,text):
        return hashlib.sha256(json.dumps([self.config.embedding_base_url,self.config.embedding_model,text],ensure_ascii=False).encode()).hexdigest()

    def embed(self,texts):
        key = os.environ.get(self.config.embedding_key_env)
        if not key: raise EmbeddingError('embedding key is missing')
        vectors, missing = {}, []
        for text in dict.fromkeys(texts):
            cached = self.store.get_cache('embedding',self._key(text))
            if cached: vectors[text] = cached['vector']
            else: missing.append(text)
        try:
            for start in range(0,len(missing),128):
                batch = missing[start:start+128]
                response = self.client.post(self.config.embedding_base_url.rstrip('/')+'/embeddings',
                    json={'model':self.config.embedding_model,'input':batch},headers={'Authorization':f'Bearer {key}'},timeout=30)
                response.raise_for_status()
                data = response.json()['data']
                if len(data) != len(batch) or {d['index'] for d in data} != set(range(len(batch))): raise ValueError()
                for item in data:
                    vector = item['embedding']
                    if not vector or any(not isinstance(v,(float,int)) or isinstance(v,bool) or not math.isfinite(v) for v in vector): raise ValueError()
                    vectors[batch[item['index']]] = vector
            if len({len(v) for v in vectors.values()}) > 1: raise ValueError()
            for text in missing:
                self.store.put_cache('embedding',self._key(text),{'vector':vectors[text]})
            return [vectors[text] for text in texts]
        except (httpx.HTTPError,KeyError,ValueError,TypeError):
            raise EmbeddingError('embedding provider failed') from None
