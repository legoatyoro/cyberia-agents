import json
from pathlib import Path
from core.llm_client import LLMClient
from core.expert_profiles import get_business_experts, get_technical_experts, EXPERT_PROFILES
from schemas.agent_schemas import TaskType, AgentOutput

class RouterExpertAgent:
    def __init__(self):
        self.llm = LLMClient()
        self.name = 'ROUTER_EXPERT'

    def build_execution_plan(self, cdc: str, blueprint: dict) -> dict:
        print(f'🎯 [{self.name}] Analyse du CDC et sélection des experts...')
        stack = blueprint.get('stack', {})
        business_experts = get_business_experts(cdc)
        technical_experts = get_technical_experts(stack)
        dominant_pair = business_experts[:2] if business_experts else []
        all_experts = technical_experts + [e for e in business_experts if e not in technical_experts]

        execution_order = (
            ['ARCHITECTE'] +
            ['EXPERT_DATABASE'] +
            [e for e in all_experts if e not in ['EXPERT_DATABASE', 'EXPERT_DEVOPS', 'EXPERT_SECURITY']] +
            dominant_pair +
            ['EXPERT_SECURITY'] +
            ['VALIDATOR', 'FIXER', 'TESTER', 'RUNNER'] +
            ['EXPERT_DEVOPS'] +
            ['DOCUMENTER', 'DEPLOYER']
        )

        seen = set()
        execution_order = [x for x in execution_order if not (x in seen or seen.add(x))]

        plan = {
            'dominant_experts': dominant_pair,
            'technical_experts': technical_experts,
            'business_experts': business_experts,
            'execution_order': execution_order,
            'profiles_used': {e: EXPERT_PROFILES.get(e, {}).get('role', '')[:100] for e in all_experts},
            'stack': stack
        }

        print(f'  ✅ Plan : {len(execution_order)} étapes')
        print(f'  🏢 Experts métier : {dominant_pair or ["généraliste"]}')
        print(f'  🔧 Experts techniques : {technical_experts}')
        return plan

    def run(self, cdc: str, blueprint: dict) -> AgentOutput:
        plan = self.build_execution_plan(cdc, blueprint)
        return AgentOutput(agent_name=self.name, success=True, artifacts={'plan': plan})
