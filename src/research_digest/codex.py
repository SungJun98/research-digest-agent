"""Codex CLI login backend; source assessment has no shell or connected-app tools."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from .llm import EVALUATION_RULES, Evaluator, InvalidEvaluation
from .models import Evaluation


def command_path(command):
    resolved=shutil.which(str(Path(command).expanduser()))
    if not resolved:raise InvalidEvaluation('Codex CLI executable unavailable')
    return resolved


def codex_logged_in(command):
    try:
        result=subprocess.run([command_path(command),'login','status'],capture_output=True,text=True,timeout=15)
        return result.returncode==0 and 'Logged in' in result.stdout+result.stderr
    except (OSError,subprocess.SubprocessError,InvalidEvaluation):return False


def strict_schema(schema):
    schema=copy.deepcopy(schema)
    def visit(node):
        if isinstance(node,dict):
            node.pop('default',None)
            if node.get('type')=='object':
                node['additionalProperties']=False
                node['required']=list(node.get('properties',{}))
            for value in node.values():visit(value)
        elif isinstance(node,list):
            for value in node:visit(value)
    visit(schema)
    return schema


class CodexEvaluator(Evaluator):
    def __init__(self,command,model,store,timeout_seconds=240,batch_size=5,**kwargs):
        self.command,self.timeout_seconds,self.batch_size=command,timeout_seconds,batch_size
        self.cli_model=model
        super().__init__(None,'codex-cli:'+command,model or 'CLI default','saved CLI login',store,**kwargs)

    def _invoke(self,payload,schema):
        executable=command_path(self.command)
        if not self.store.reserve_llm_request(self.clock().date().isoformat(),self.limit):
            raise InvalidEvaluation('daily LLM request budget exhausted')
        with tempfile.TemporaryDirectory(prefix='research-digest-codex-') as temporary:
            root=Path(temporary); schema_path=root/'schema.json'; output=root/'result.json'; events=root/'events.jsonl'
            schema_path.write_text(json.dumps(strict_schema(schema)))
            args=[executable,'exec','--ignore-user-config','--sandbox','read-only','--ephemeral','--skip-git-repo-check',
                  '--cd',temporary,'--output-schema',str(schema_path),'--output-last-message',str(output),'--json']
            for feature in ['shell_tool','apps','plugins','hooks','browser_use','computer_use','multi_agent','view_image','goals','image_generation']:
                args.extend(['--disable',feature])
            args.extend(['-c','web_search="disabled"'])
            if self.cli_model:args.extend(['--model',self.cli_model])
            args.append('-')
            prompt=EVALUATION_RULES+'\nUse only supplied sources. Do not use tools. For a batch, return one evaluation per paper_id.\nINPUT_JSON\n'+json.dumps(payload,ensure_ascii=False)
            allowed={'PATH','HOME','USER','LOGNAME','TMPDIR','LANG','LC_ALL','CODEX_HOME','SSL_CERT_FILE','HTTPS_PROXY','HTTP_PROXY','NO_PROXY','SHELL'}
            environment={key:value for key,value in os.environ.items() if key in allowed}
            try:
                with events.open('w') as stream:
                    result=subprocess.run(args,input=prompt,text=True,stdout=stream,stderr=subprocess.DEVNULL,
                                          timeout=self.timeout_seconds,env=environment)
                if result.returncode or not output.exists() or output.stat().st_size>500_000 or events.stat().st_size>2_000_000:
                    raise InvalidEvaluation('Codex evaluation failed or output exceeded limit')
                records=[json.loads(line) for line in events.read_text().splitlines() if line.strip()]
                if not any(record.get('type')=='turn.completed' for record in records):
                    raise InvalidEvaluation('Codex turn did not complete')
                for record in records:
                    item=record.get('item') or {}
                    if record.get('type')=='turn.failed' or (item and item.get('type') not in {'reasoning','agent_message'}):
                        raise InvalidEvaluation('Codex assessment attempted an unexpected tool')
                return json.loads(output.read_text())
            except InvalidEvaluation:raise
            except (OSError,subprocess.SubprocessError,ValueError,TypeError,AttributeError):
                raise InvalidEvaluation('Codex evaluation unavailable or malformed') from None

    def _call(self,payload):
        key=self._cache_key(payload)
        cached=self.store.get_cache('evaluation',key)
        return (cached if cached else self._invoke(payload,Evaluation.model_json_schema())),key

    def evaluate_many(self,papers,topics):
        results={}; missing=[]
        for paper in papers:
            try:
                payload=self._evaluation_payload(paper,topics);key=self._cache_key(payload)
                cached=self.store.get_cache('evaluation',key)
                if cached:results[paper.canonical_id]=self._validate(cached,paper.model_copy(update={'abstract':payload['abstract']}),topics)
                else:missing.append((paper,payload,key))
            except InvalidEvaluation:continue
        evaluation=Evaluation.model_json_schema(); definitions=evaluation.pop('$defs',{})
        schema={'type':'object','properties':{'evaluations':{'type':'array','items':{'type':'object','properties':{
            'paper_id':{'type':'string'},'evaluation':evaluation}}}},'$defs':definitions}
        for start in range(0,len(missing),self.batch_size):
            group=missing[start:start+self.batch_size]
            inputs=[{'paper_id':paper.canonical_id,'input':payload} for paper,payload,_ in group]
            try:
                raw=self._invoke({'items':inputs},schema)
                entries=raw['evaluations']
                if not isinstance(entries,list) or len(entries)>len(group):raise InvalidEvaluation('invalid batch')
                by_id={item['paper_id']:item['evaluation'] for item in entries}
                if len(by_id)!=len(entries) or set(by_id)-{paper.canonical_id for paper,_,_ in group}:
                    raise InvalidEvaluation('unknown or duplicate batch ID')
            except (InvalidEvaluation,KeyError,TypeError):continue
            for paper,payload,key in group:
                if paper.canonical_id not in by_id:continue
                try:result=self._validate(by_id[paper.canonical_id],paper.model_copy(update={'abstract':payload['abstract']}),topics)
                except InvalidEvaluation:continue
                self.store.put_cache('evaluation',key,result.model_dump(mode='json'))
                results[paper.canonical_id]=result
        return results
