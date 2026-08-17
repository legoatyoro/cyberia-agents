from __future__ import annotations
import os
from dataclasses import dataclass
from typing import Dict, Any
from openai import OpenAI
from dotenv import load_dotenv
load_dotenv()

@dataclass
class ModelConfig:
    name: str
    provider: str
    base_url: str
    api_key_env: str

MODELS: Dict[str, ModelConfig] = {
    # MiMo PAYG — provider principal
    'mimo_pro': ModelConfig(
        name='mimo-v2.5-pro', provider='mimo',
        base_url='https://api.xiaomimimo.com/v1',
        api_key_env='MIMO_API_KEY'),
    'mimo_flash': ModelConfig(
        name='mimo-v2.5', provider='mimo',
        base_url='https://api.xiaomimimo.com/v1',
        api_key_env='MIMO_API_KEY'),
    # Fallbacks
    'together_llama': ModelConfig(
        name='meta-llama/Llama-3.3-70B-Instruct-Turbo', provider='together',
        base_url='https://api.together.xyz/v1',
        api_key_env='TOGETHER_API_KEY'),
    'deepseek_chat': ModelConfig(
        name='deepseek/deepseek-chat', provider='openrouter',
        base_url='https://openrouter.ai/api/v1',
        api_key_env='OPENROUTER_API_KEY'),
    'deepseek_main': ModelConfig(
        name='deepseek-chat', provider='deepseek',
        base_url='https://api.deepseek.com',
        api_key_env='DEEPSEEK_API_KEY'),
    'groq_fast': ModelConfig(
        name='llama-3.3-70b-versatile', provider='groq',
        base_url='https://api.groq.com/openai/v1',
        api_key_env='GROQ_API_KEY'),
    'ollama_local': ModelConfig(
        name='llama3.2', provider='ollama',
        base_url='http://localhost:11434/v1',
        api_key_env='OLLAMA_API_KEY'),
}

AGENT_MODEL_MAP = {
    # Agents securite -> MiMo Pro (qualite)
    'AgentSecurite': 'deepseek_main',
    'AgentSecurity':      'deepseek_main',
    'AgentScan':          'together_llama',
    'AgentVuln':          'deepseek_main',
    'AgentAlgoSec':       'together_llama',
    'AgentSecuriteV2':    'mimo_pro',
    'AgentOWASPV2':       'mimo_pro',
    'AgentArchitectureV3':'mimo_pro',
    'AgentBlueTeam':      'mimo_pro',
    # Agents code -> MiMo Pro (qualite)
    'AgentCode': 'deepseek_main',
    'AgentBDD':           'mimo_pro',
    'AgentAPI':           'mimo_pro',
    'AgentCodeV3':        'mimo_pro',
    # Agents volume/masse -> MiMo Flash (rapide, pas cher)
    'AgentPayloadLab':    'openrouter_deepseek',
    'AgentCyberResearch': 'together_llama',
    'AgentRecherche': 'deepseek_main',
    'AgentDocumentation': 'together_llama',
    'AgentMeta':          'mimo_flash',
    'AgentMetaV1':        'mimo_flash',
    # Agents monitoring -> Groq (ultra rapide)
    'AgentTest':          'groq_fast',
    'AgentMonitoring':    'groq_fast',
    'AgentOptimisation':  'mimo_flash',
    'AgentOptimisationV3':'mimo_flash',
    'AgentArchitecture':  'mimo_flash',
    # Local
    'AgentUnrestricted':  'ollama_local',
    'AgentLocal':         'ollama_local',
}

# Ordre de fallback global
FALLBACK_CHAIN = [
    'mimo_pro',
    'mimo_flash',
    'together_llama',
    'deepseek_main',
    'groq_fast',
]

class MultiModelRouterV2:
    def __init__(self):
        self._clients: Dict[str, OpenAI] = {}

    def _get_client(self, model_key: str) -> OpenAI:
        if model_key in self._clients:
            return self._clients[model_key]
        if model_key == 'ollama_local':
            client = OpenAI(api_key='ollama', base_url='http://localhost:11434/v1')
            self._clients[model_key] = client
            return client
        cfg = MODELS[model_key]
        api_key = os.getenv(cfg.api_key_env)
        if not api_key:
            raise RuntimeError(f'API key manquante: {cfg.api_key_env}')
        client = OpenAI(api_key=api_key, base_url=cfg.base_url)
        self._clients[model_key] = client
        return client

    def get_model_for_agent(self, agent_type: str) -> Dict[str, Any]:
        model_key = AGENT_MODEL_MAP.get(agent_type, 'mimo_pro')
        # Essaie le provider assigne, puis fallback chain
        keys_to_try = [model_key] + [k for k in FALLBACK_CHAIN if k != model_key]
        for key in keys_to_try:
            try:
                client = self._get_client(key)
                return {
                    'client': client,
                    'model': MODELS[key].name,
                    'provider': MODELS[key].provider,
                }
            except Exception:
                continue
        raise RuntimeError(f'Aucun provider disponible pour {agent_type}')

    def call(self, prompt: str, task_type: str = 'analysis', agent_type: str = None) -> str:
        model_info = self.get_model_for_agent(agent_type or 'AgentSecurite')
        keys_to_try = FALLBACK_CHAIN
        for key in keys_to_try:
            try:
                client = self._get_client(key)
                completion = client.chat.completions.create(
                    model=MODELS[key].name,
                    messages=[{'role': 'user', 'content': prompt}],
                    max_tokens=2000,
                )
                return completion.choices[0].message.content or ''
            except Exception:
                continue
        raise RuntimeError('Tous les providers ont echoue')

    def available_models(self) -> Dict[str, bool]:
        result = {}
        for key, cfg in MODELS.items():
            if key == 'ollama_local':
                try:
                    import urllib.request
                    urllib.request.urlopen('http://localhost:11434', timeout=2)
                    result[key] = True
                except Exception:
                    result[key] = False
            else:
                result[key] = bool(os.getenv(cfg.api_key_env))
        return result

router_v2 = MultiModelRouterV2()







