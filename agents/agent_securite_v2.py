from __future__ import annotations
import json
from typing import Dict, Any
from core.multi_model_router_v2 import router_v2
from core.json_parser import safe_json_parse


class AgentSecuriteV2:
    def __init__(self):
        self.agent_type = 'AgentSecurite'
        self.system_prompt = '''Tu es AgentSecurite v2 de CYBERIA. Expert cybersecurite OWASP CVSS.
Reponds STRICTEMENT en JSON:
{"vulnerabilites":[{"type":"...","severity":"critical|high|medium","description":"...","fix":"..."}],"owasp_mapping":{},"cvss":{"score":0},"correctifs":[],"patterns":[],"summary":"..."}'''

    def execute(self, task: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        model_info = router_v2.get_model_for_agent(self.agent_type)
        return self.execute_with_client(task, context, model_info['client'], model_info['model'])

    def execute_with_client(self, task, context, client, model_name):
        messages = [
            {'role': 'system', 'content': self.system_prompt},
            {'role': 'user', 'content': json.dumps(
                {'task': task, 'context': {'domain': 'security', 'business': context.get('business', '')}},
                ensure_ascii=False)},
        ]
        try:
            completion = client.chat.completions.create(model=model_name, messages=messages, max_tokens=2000)
            content = completion.choices[0].message.content
            default = {'summary': '', 'vulnerabilites': [], 'correctifs': [],
                       'owasp_mapping': {}, 'cvss': {'score': 0}, 'patterns': []}
            return safe_json_parse(content, default)
        except Exception as e:
            return {'summary': f'Erreur: {e}', 'vulnerabilites': [], 'correctifs': [],
                    'owasp_mapping': {}, 'cvss': {'score': 0}, 'patterns': []}
