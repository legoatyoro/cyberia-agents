from __future__ import annotations
import json
from typing import Dict, Any
from core.multi_model_router_v2 import router_v2
from core.json_parser import safe_json_parse


class AgentTestV3:
    def __init__(self):
        self.agent_type = 'AgentTest'
        self.system_prompt = '''Tu es AgentTest v3 de CYBERIA. Expert tests unitaires integration securite.
Reponds en JSON: {"tests":[{"path":"...","content":"...","description":"...","type":"unit|integration|security"}],"fuzzing":[],"patterns":[],"coverage_score":0.0,"summary":"..."}'''

    def execute(self, task, context):
        model_info = router_v2.get_model_for_agent(self.agent_type)
        return self.execute_with_client(task, context, model_info['client'], model_info['model'])

    def execute_with_client(self, task, context, client, model_name):
        messages = [
            {'role': 'system', 'content': self.system_prompt},
            {'role': 'user', 'content': json.dumps(
                {'task': task, 'context': {
                    'architecture': context.get('architecture'),
                    'vulns': context.get('vulnerabilites'),
                }}, ensure_ascii=False)},
        ]
        try:
            completion = client.chat.completions.create(model=model_name, messages=messages, max_tokens=800)
            content = completion.choices[0].message.content
            default = {'summary': '', 'tests': [], 'fuzzing': [], 'patterns': [], 'coverage_score': 0.0}
            return safe_json_parse(content, default)
        except Exception as e:
            return {'summary': str(e), 'tests': [], 'fuzzing': [], 'patterns': [], 'coverage_score': 0.0}
