from __future__ import annotations
import json
from typing import Dict, Any
from core.multi_model_router_v2 import router_v2
from core.json_parser import safe_json_parse


class AgentMetaV1:
    def __init__(self):
        self.agent_type = 'AgentOptimisation'
        self.system_prompt = '''Tu es AgentMeta v1 de CYBERIA. Agent d auto-amelioration du systeme.
Analyse les performances des agents et propose des ameliorations.
Reponds en JSON: {"analyse":{},"points_faibles":[],"ameliorations":[],"optimisations_pipeline":[],"evolutions_systeme":[],"patterns":[],"score_sante":0.0,"summary":"..."}'''

    def execute(self, task, context):
        model_info = router_v2.get_model_for_agent(self.agent_type)
        return self.execute_with_client(task, context, model_info['client'], model_info['model'])

    def execute_with_client(self, task, context, client, model_name):
        messages = [
            {'role': 'system', 'content': self.system_prompt},
            {'role': 'user', 'content': json.dumps(
                {'task': task, 'agents_results': context.get('agents_results', {}), 'errors': context.get('errors', [])},
                ensure_ascii=False)},
        ]
        try:
            completion = client.chat.completions.create(model=model_name, messages=messages, max_tokens=600)
            content = completion.choices[0].message.content
            default = {'summary': '', 'analyse': {}, 'points_faibles': [], 'ameliorations': [],
                       'optimisations_pipeline': [], 'evolutions_systeme': [], 'patterns': [], 'score_sante': 5.0}
            return safe_json_parse(content, default)
        except Exception as e:
            return {'summary': str(e), 'analyse': {}, 'points_faibles': [], 'ameliorations': [],
                    'optimisations_pipeline': [], 'evolutions_systeme': [], 'patterns': [], 'score_sante': 0.0}
