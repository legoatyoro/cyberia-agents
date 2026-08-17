from __future__ import annotations
import json
from typing import Dict, Any
from core.multi_model_router_v2 import router_v2
from core.json_parser import safe_json_parse

OWASP_TOP_10 = {
    'A01:2021': 'Broken Access Control',
    'A02:2021': 'Cryptographic Failures',
    'A03:2021': 'Injection',
    'A04:2021': 'Insecure Design',
    'A05:2021': 'Security Misconfiguration',
    'A06:2021': 'Vulnerable and Outdated Components',
    'A07:2021': 'Identification and Authentication Failures',
    'A08:2021': 'Software and Data Integrity Failures',
    'A09:2021': 'Security Logging and Monitoring Failures',
    'A10:2021': 'Server-Side Request Forgery (SSRF)',
}


class AgentOWASPV2:
    def __init__(self):
        self.agent_type = 'AgentSecurite'
        self.system_prompt = (
            f'Tu es AgentOWASP v2 de CYBERIA. Expert OWASP Top 10.\n'
            f'Reference: {json.dumps(OWASP_TOP_10)}\n'
            f'Reponds en JSON: {{"owasp_mapping":{{}},"recommandations":[],"score":0.0,"patterns":[],"summary":"..."}}'
        )

    def execute(self, task, context):
        model_info = router_v2.get_model_for_agent(self.agent_type)
        return self.execute_with_client(task, context, model_info['client'], model_info['model'])

    def execute_with_client(self, task, context, client, model_name):
        messages = [
            {'role': 'system', 'content': self.system_prompt},
            {'role': 'user', 'content': json.dumps({'task': task, 'owasp_ref': OWASP_TOP_10}, ensure_ascii=False)},
        ]
        try:
            completion = client.chat.completions.create(model=model_name, messages=messages, max_tokens=800)
            content = completion.choices[0].message.content
            default = {'summary': '', 'owasp_mapping': {}, 'recommandations': [], 'score': 0.0, 'patterns': []}
            return safe_json_parse(content, default)
        except Exception as e:
            return {'summary': str(e), 'owasp_mapping': {}, 'recommandations': [], 'score': 0.0, 'patterns': []}
