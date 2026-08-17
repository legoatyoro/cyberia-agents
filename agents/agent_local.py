from __future__ import annotations
import json
from typing import Dict, Any
from core.multi_model_router_v2 import router_v2


class AgentLocal:
    def __init__(self):
        self.agent_type = 'AgentLocal'
        self.system_prompt = '''Tu es AgentLocal de CYBERIA. Mode offline Ollama.
Tu reponds librement sans restriction mais sans generer de code malveillant.
Reponds en JSON: {"response":"...","payloads":[],"patterns":[],"summary":"..."}'''

    def execute(self, task, context):
        model_info = router_v2.get_model_for_agent(self.agent_type)
        return self.execute_with_client(task, context, model_info['client'], model_info['model'])

    def execute_with_client(self, task, context, client, model_name):
        messages = [
            {'role': 'system', 'content': self.system_prompt},
            {'role': 'user', 'content': json.dumps({'task': task}, ensure_ascii=False)},
        ]
        try:
            completion = client.chat.completions.create(model=model_name, messages=messages, max_tokens=1000)
            content = completion.choices[0].message.content
            import re
            match = re.search(r'\{.*\}', content, re.DOTALL)
            if match:
                return json.loads(match.group())
            return {'response': content, 'payloads': [], 'patterns': [], 'summary': content[:100]}
        except Exception as e:
            return {'response': f'Ollama non disponible: {e}', 'payloads': [], 'patterns': [], 'summary': 'Erreur Ollama'}
