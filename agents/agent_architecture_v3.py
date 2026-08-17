from __future__ import annotations
import json
from typing import Dict, Any
from core.multi_model_router_v2 import router_v2
from core.json_parser import safe_json_parse


class AgentArchitectureV3:
    def __init__(self):
        self.agent_type = 'AgentArchitecture'
        self.system_prompt = '''Tu es AgentArchitecture v3 de CYBERIA. Architecte logiciel senior specialise cybersecurite.
Reponds en JSON: {"architecture":{"type":"...","stack":"...","modules":[]},"composants":[{"nom":"...","role":"..."}],"flux":[],"fichiers":[{"path":"...","description":"..."}],"diagramme":"...","recommandations":[],"patterns":[],"summary":"..."}'''

    def execute(self, task, context):
        model_info = router_v2.get_model_for_agent(self.agent_type)
        return self.execute_with_client(task, context, model_info['client'], model_info['model'])

    def execute_with_client(self, task, context, client, model_name):
        messages = [
            {'role': 'system', 'content': self.system_prompt},
            {'role': 'user', 'content': json.dumps(
                {'task': task, 'context': {
                    'scan': context.get('scan_results'),
                    'vulns': context.get('vulnerabilites'),
                    'owasp': context.get('owasp'),
                }}, ensure_ascii=False)},
        ]
        try:
            completion = client.chat.completions.create(model=model_name, messages=messages, max_tokens=2000)
            content = completion.choices[0].message.content
            default = {'summary': '', 'architecture': {}, 'composants': [], 'flux': [],
                       'fichiers': [], 'diagramme': '', 'recommandations': [], 'patterns': []}
            return safe_json_parse(content, default)
        except Exception as e:
            return {'summary': str(e), 'architecture': {}, 'composants': [], 'flux': [],
                    'fichiers': [], 'diagramme': '', 'recommandations': [], 'patterns': []}
