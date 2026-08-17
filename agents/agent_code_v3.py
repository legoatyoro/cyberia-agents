from __future__ import annotations
import json
from typing import Dict, Any
from core.multi_model_router_v2 import router_v2
from core.json_parser import safe_json_parse


class AgentCodeV3:
    def __init__(self):
        self.agent_type = 'AgentCode'
        self.system_prompt = '''Tu es AgentCode v3 de CYBERIA. Generateur de code production-ready specialise cybersecurite.
Reponds en JSON: {"arborescence":[],"fichiers":[{"path":"...","content":"...","description":"..."}],"patterns":[],"summary":"..."}'''

    def execute(self, task, context):
        model_info = router_v2.get_model_for_agent(self.agent_type)
        return self.execute_with_client(task, context, model_info['client'], model_info['model'])

    def execute_with_client(self, task, context, client, model_name):
        messages = [
            {'role': 'system', 'content': self.system_prompt},
            {'role': 'user', 'content': json.dumps(
                {'task': task, 'context': {
                    'architecture': context.get('architecture'),
                    'composants': context.get('composants'),
                    'patterns': context.get('patterns'),
                }}, ensure_ascii=False)},
        ]
        try:
            completion = client.chat.completions.create(model=model_name, messages=messages, max_tokens=3000)
            content = completion.choices[0].message.content
            default = {'summary': '', 'arborescence': [], 'fichiers': [], 'patterns': []}
            return safe_json_parse(content, default)
        except Exception as e:
            return {'summary': str(e), 'arborescence': [], 'fichiers': [], 'patterns': []}
