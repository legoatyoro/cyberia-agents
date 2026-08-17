import os
import json
import re
from pathlib import Path
from datetime import datetime
from enum import Enum


def log_cdc_trigger(cdc: dict, history: list, project_name: str):
    log_path = Path('.cyberia/cdc_trace.jsonl')
    log_path.parent.mkdir(exist_ok=True)
    entry = {
        'timestamp': datetime.now().isoformat(),
        'project_name': project_name,
        'cdc': cdc,
        'last_user_messages': [m['content'] for m in history if m['role'] == 'user'][-3:],
        'history_length': len(history)
    }
    with open(log_path, 'a', encoding='utf-8') as f:
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')

class ConvState(str, Enum):
    DISCOVERY = 'discovery'
    CLARIFICATION = 'clarification'
    PROPOSAL = 'proposal'
    VALIDATION = 'validation'
    GENERATION = 'generation'
    ANALYSIS = 'analysis'

CDC_SCHEMA = {
    'project_name': '',
    'description': '',
    'target_users': '',
    'features': [],
    'out_of_scope': [],
    'stack': {'backend': '', 'frontend': '', 'database': '', 'auth': ''},
    'constraints': [],
    'estimated_files': 0,
    'complexity': 'medium',
    'ready': False
}

STACK_OPTIONS = {
    'simple': {
        'label': 'A. Simple et rapide (~2 min)',
        'stack': 'FastAPI + SQLite + Bootstrap',
        'description': 'Ideal pour MVP et test rapide',
        'files': 8
    },
    'pro': {
        'label': 'B. Professionnelle (~5 min)',
        'stack': 'FastAPI + PostgreSQL + Auth JWT',
        'description': 'Ideal pour app client, Railway',
        'files': 20
    },
    'enterprise': {
        'label': 'C. Complete (~15 min)',
        'stack': 'Django + DRF + React + Auth',
        'description': 'Ideal pour systeme complexe',
        'files': 60
    }
}

PROFILE_PATH = Path('.cyberia/user_profile.json')

def load_profile() -> dict:
    PROFILE_PATH.parent.mkdir(exist_ok=True)
    if PROFILE_PATH.exists():
        try:
            return json.loads(PROFILE_PATH.read_text(encoding='utf-8'))
        except Exception:
            pass
    return {
        'preferred_backend': 'FastAPI',
        'preferred_db': 'SQLite',
        'preferred_frontend': 'Bootstrap',
        'technical_level': 'intermediate',
        'total_projects': 0,
        'recent_stacks': [],
        'last_session': ''
    }

def save_profile(profile: dict):
    PROFILE_PATH.write_text(json.dumps(profile, indent=2, ensure_ascii=False), encoding='utf-8')

def update_profile_from_cdc(cdc: dict):
    profile = load_profile()
    stack = cdc.get('stack', {})
    if stack.get('backend'):
        profile['preferred_backend'] = stack['backend']
    if stack.get('database'):
        profile['preferred_db'] = stack['database']
    if stack.get('frontend'):
        profile['preferred_frontend'] = stack['frontend']
    profile['total_projects'] = profile.get('total_projects', 0) + 1
    profile['last_session'] = datetime.now().isoformat()
    stacks = profile.get('recent_stacks', [])
    stack_str = f'{stack.get("backend", "")}+{stack.get("database", "")}'
    if stack_str not in stacks:
        stacks.insert(0, stack_str)
    profile['recent_stacks'] = stacks[:5]
    save_profile(profile)

class ConversationEngine:
    def __init__(self):
        import uuid
        self.state = ConvState.DISCOVERY
        self.cdc = CDC_SCHEMA.copy()
        self.cdc['features'] = []
        self.cdc['out_of_scope'] = []
        self.cdc['constraints'] = []
        self.history = []
        self.profile = load_profile()
        self.session_id = f'conv_{uuid.uuid4().hex[:8]}'
        self._memory_context = None
        self._core_memory_context = None
        self._no_memory = False
        self.project_context = None
        self._setup_llm()

    def _setup_llm(self):
        anthropic_key = os.getenv('ANTHROPIC_API_KEY')
        self.use_claude = False
        if anthropic_key:
            try:
                import anthropic
                self.claude_client = anthropic.Anthropic(api_key=anthropic_key)
                self.use_claude = True
                print('  [CONV] Mode Claude Haiku active pour la conversation')
            except ImportError:
                import subprocess, sys
                subprocess.run([sys.executable, '-m', 'pip', 'install', 'anthropic', '-q'])
                try:
                    import anthropic
                    self.claude_client = anthropic.Anthropic(api_key=anthropic_key)
                    self.use_claude = True
                except Exception:
                    pass
        if not self.use_claude:
            try:
                from core.multi_model_router import get_router
                self.router = get_router()
            except Exception:
                self.router = None

    def _call_llm(self, system: str, user: str, temperature: float = 0.7) -> str:
        if self.use_claude:
            try:
                response = self.claude_client.messages.create(
                    model='claude-haiku-4-5-20251001',
                    max_tokens=500,
                    system=system,
                    messages=[{'role': 'user', 'content': user}]
                )
                return response.content[0].text
            except Exception as e:
                print(f'  [CONV] Claude erreur, fallback router : {e}')
        if self.router:
            try:
                return self.router.call(user, task_type='analysis', temperature=temperature)
            except Exception:
                pass
        return 'Decris-moi ton projet plus en detail.'

    def _load_core_memory(self, query: str, top_k: int = 5) -> str:
        if self._no_memory:
            return ''
        try:
            from core.memory_core import get_core
            results = get_core().search(query, top_k=top_k)
            if not results:
                return ''
            lines = []
            for r in results:
                key = r.get('key', '')
                value = r.get('value', '')
                sim = r.get('similarity', 0)
                if sim < 0.15:
                    continue
                lines.append('[MEMORY {}] {} : {}'.format(sim, key[:50], value[:150]))
            if lines:
                print('  [MEMORY_CORE] {} souvenirs charges ({} min sim)'.format(
                    len(lines), min(r.get('similarity', 0) for r in results[:len(lines)])))
            return '\n'.join(lines)
        except Exception:
            return ''

    def _get_system_prompt(self) -> str:
        if self._memory_context is None and self.history:
            from core.memory_hub import get_context_block
            first_user_msg = next((m['content'] for m in self.history if m['role'] == 'user'), '')
            self._memory_context = get_context_block(first_user_msg, min_similarity=0.2) or ''
        profile_context = (
            f'Preferences utilisateur : {self.profile.get("preferred_backend")} + '
            f'{self.profile.get("preferred_db")}. '
            f'{self.profile.get("total_projects", 0)} projets crees.'
        )
        cdc_context = f'CDC en cours : {json.dumps(self.cdc, ensure_ascii=False)[:500]}'
        project_block = (
            f'\n\nCODE SOURCE DU PROJET EN COURS D ANALYSE:\n{self.project_context[:4000]}\n...(tronque si long)'
            if self.project_context else ''
        )
        core_mem_block = (
            f'\n\nMEMOIRE TECHNIQUE CYBERIA:\n{self._core_memory_context}'
            if self._core_memory_context else ''
        )
        code_rules = (
            '- Tu peux analyser, expliquer et suggerer des corrections sur le code du projet charge\n'
            '- Tu peux generer des corrections de code si l utilisateur le demande\n'
            if self.project_context else
            '- Tu NE generes PAS de code, tu clarifies seulement le besoin\n'
        )
        return (
            'Tu es CYBERIA. Si tu vois dans l historique de conversation un message de toi contenant '
            'des informations sur l utilisateur, utilise-les naturellement dans tes reponses.'
            f'{project_block}\n\n'
            f'{core_mem_block}\n\n'
            f'Etat conversation : {self.state.value}\n'
            f'{profile_context}\n'
            f'{cdc_context}\n\n'
            'REGLES ABSOLUES :\n'
            '- Tu poses UNE SEULE question a la fois, ciblee et precise\n'
            '- Tu proposes des options lettrees A/B/C quand c est pertinent\n'
            '- Tu construis progressivement le CDC a partir des reponses\n'
            '- Tu es concis (3-5 phrases max par reponse)\n'
            '- Tu reponds en francais\n'
            f'{code_rules}\n'
            'Etat DISCOVERY : comprendre le besoin general\n'
            'Etat CLARIFICATION : preciser les fonctionnalites une par une\n'
            'Etat PROPOSAL : proposer 3 options de stack\n'
            'Etat VALIDATION : presenter le CDC et demander validation\n'
            'Etat GENERATION : confirmer avant lancer la generation'
        )

    def _extract_cdc_from_response(self, user_input: str, ai_response: str):
        user_lower = user_input.lower()
        keywords = {
            'auth': ['authentification', 'login', 'connexion', 'jwt', 'utilisateur'],
            'export': ['export', 'pdf', 'csv', 'excel', 'telecharger'],
            'dashboard': ['dashboard', 'tableau de bord', 'statistiques', 'graphique'],
            'search': ['recherche', 'filtrer', 'chercher'],
            'payment': ['paiement', 'stripe', 'facture', 'abonnement'],
            'email': ['email', 'mail', 'notification', 'alerte'],
            'api': ['api', 'rest', 'endpoint', 'json'],
        }
        for feature, kws in keywords.items():
            if any(kw in user_lower for kw in kws):
                if feature not in self.cdc['features']:
                    self.cdc['features'].append(feature)
        if any(w in user_lower for w in ['django', 'postgresql', 'postgres']):
            self.cdc['stack']['backend'] = 'django'
            self.cdc['stack']['database'] = 'postgresql'
        elif any(w in user_lower for w in ['fastapi', 'sqlite']):
            self.cdc['stack']['backend'] = 'fastapi'
            self.cdc['stack']['database'] = 'sqlite'
        if any(w in user_lower for w in ['react', 'vue', 'angular']):
            self.cdc['stack']['frontend'] = 'react'
        # project name is now extracted via _extract_project_name_from_history()

    def _user_message_count(self) -> int:
        return len([m for m in self.history if m['role'] == 'user'])

    def _extract_project_name_from_history(self):
        if self.cdc.get('project_name'):
            return
        first_user = next((m['content'] for m in self.history if m['role'] == 'user'), '')
        if not first_user:
            return
        words = [w for w in first_user.split() if len(w) > 3 and w.lower() not in
                 ('pour', 'avec', 'veux', 'voudrais', 'faire', 'creer', 'application', 'appli', 'site', 'une', 'mon', 'qui')]
        slug = (words[0] if words else first_user.split()[0]).lower()
        self.cdc['project_name'] = slug[:30]

    def _should_advance_state(self, user_input: str) -> bool:
        advance_words = ['oui', 'ok', 'parfait', 'c est bon', 'genere', 'vas-y', 'go', 'je valide', 'confirme']
        if any(w in user_input.lower() for w in advance_words):
            return True
        if self.state == ConvState.DISCOVERY and self._user_message_count() >= 2:
            return True
        if self.state == ConvState.CLARIFICATION and len(self.cdc['features']) >= 2:
            return True
        return False

    def _get_analysis_prompt(self) -> str:
        project_content = self.project_context[:6000] if self.project_context else ''
        core_mem_block = (
            f'\n\nMEMOIRE TECHNIQUE:\n{self._core_memory_context}'
            if self._core_memory_context else ''
        )
        return (
            'Tu es CYBERIA en mode analyse. Un projet a ete charge.\n'
            'Reponds aux questions de l utilisateur sur ce projet de facon directe et technique.\n'
            'Pas de recapitulatif CDC, pas de question sur le projet a creer. Juste analyser et repondre.\n'
            'Tu peux proposer des corrections de code, expliquer le fonctionnement, identifier des bugs.\n'
            'Sois concis et precis. Tu reponds en francais.\n\n'
            f'CODE SOURCE DU PROJET:\n{project_content}'
            + ('\n...(tronque)' if self.project_context and len(self.project_context) > 6000 else '')
            + core_mem_block
        )

    def _get_clarification_prompt(self) -> str:
        user_msgs = [m['content'] for m in self.history if m['role'] == 'user']
        return (
            'Tu es CYBERIA. L\'utilisateur veut créer : '
            + str(user_msgs)
            + '. Pose UNE question précise avec options A/B/C pour clarifier UN aspect du projet. '
            'Exemple : Combien d\'agents ? A) 3-5 B) 5-10 C) 10+'
        )

    def chat(self, user_input: str) -> tuple[str, bool]:
        if self._memory_context is None:
            from core.memory_hub import get_context_block
            self._memory_context = get_context_block(user_input, min_similarity=0.2) or ''
            if self._memory_context:
                print(f'  [MEMORY_HUB] Contexte memoire charge pour cette session')
            if self._memory_context and len(self.history) == 0:
                memory_lines = [l for l in self._memory_context.split('\n') if l.strip().startswith('-')]
                if memory_lines:
                    memory_intro = ('Je me souviens de toi ! Voici ce que je sais de nos echanges precedents :\n'
                                    + '\n'.join(memory_lines))
                    self.history.append({'role': 'assistant', 'content': memory_intro})
        self.history.append({'role': 'user', 'content': user_input})

        # Charger la memoire technique (memory_core) - silencieux si echec
        if self._core_memory_context is None:
            self._core_memory_context = self._load_core_memory(user_input, top_k=5)

        # Basculement automatique en mode ANALYSIS si un projet est charge
        if self.project_context is not None and self.state != ConvState.ANALYSIS:
            self.state = ConvState.ANALYSIS

        if self.state == ConvState.ANALYSIS:
            system = self._get_analysis_prompt()
            conv_history = '\n'.join([f'{m["role"]}: {m["content"]}' for m in self.history[-8:]])
            user_msg = f'Conversation:\n{conv_history}\n\nReponds directement a la question de l utilisateur.'
            response = self._call_llm(system, user_msg, temperature=0.4)
            self.history.append({'role': 'assistant', 'content': response})
            _TECH_MARKERS = ('def ', 'class ', 'import ', 'fix', 'correction', 'bug')
            if any(m in response.lower() for m in _TECH_MARKERS):
                try:
                    from core.memory_hub import save_exchange
                    save_exchange(self.session_id, response[:300], category='correction', force_save=True)
                except Exception:
                    pass
            return response, False

        self._extract_cdc_from_response(user_input, '')
        self._extract_project_name_from_history()
        if self._should_advance_state(user_input):
            self._advance_state()
        if self.state == ConvState.GENERATION:
            return self._prepare_generation(), True
        if self.state == ConvState.PROPOSAL:
            return self._present_options(), False
        if self.state == ConvState.VALIDATION:
            return self._present_cdc_summary(), False
        conv_history = '\n'.join([f'{m["role"]}: {m["content"]}' for m in self.history[-6:]])
        if self.state == ConvState.CLARIFICATION:
            system = self._get_clarification_prompt()
            user_msg = f'Conversation:\n{conv_history}\n\nPose ta question de clarification avec options A/B/C.'
        else:
            system = self._get_system_prompt()
            user_msg = f'Conversation:\n{conv_history}\n\nReponds de facon guidee.'
        response = self._call_llm(system, user_msg)
        self.history.append({'role': 'assistant', 'content': response})
        _TECH_MARKERS = ('def ', 'class ', 'import ', 'fix', 'correction', 'bug')
        if any(m in response.lower() for m in _TECH_MARKERS):
            try:
                from core.memory_hub import save_exchange
                save_exchange(self.session_id, response[:300], category='correction', force_save=True)
            except Exception:
                pass
        return response, False

    def _advance_state(self):
        transitions = {
            ConvState.DISCOVERY: ConvState.CLARIFICATION,
            ConvState.CLARIFICATION: ConvState.PROPOSAL,
            ConvState.PROPOSAL: ConvState.VALIDATION,
            ConvState.VALIDATION: ConvState.GENERATION,
        }
        if self.state in transitions:
            self.state = transitions[self.state]

    def _present_options(self) -> str:
        backend_default = self.profile.get('preferred_backend', 'FastAPI')
        response = 'Parfait ! Voici 3 approches pour ton projet :\n\n'
        for key, opt in STACK_OPTIONS.items():
            marker = ' <- Recommande (tes preferences)' if backend_default.lower() in opt['stack'].lower() else ''
            response += f'{opt["label"]}\n'
            response += f'  Stack : {opt["stack"]}{marker}\n'
            response += f'  {opt["description"]} · ~{opt["files"]} fichiers\n\n'
        response += 'Laquelle tu veux ? (A=Simple / B=Pro / C=Complete)'
        return response

    def _present_cdc_summary(self) -> str:
        features = self.cdc.get('features', [])
        stack = self.cdc.get('stack', {})
        summary = '=== RECAPITULATIF DE TON PROJET ===\n\n'
        summary += f'Projet : {self.cdc.get("project_name", "mon-projet")}\n'
        summary += f'Stack  : {stack.get("backend", "FastAPI")} + {stack.get("database", "SQLite")}\n'
        if features:
            summary += '\nFonctionnalites confirmees :\n'
            for f in features:
                summary += f'  - {f}\n'
        summary += '\nDuree estimee : ~3-5 minutes\n'
        summary += '\nTape "genere" pour lancer, ou dis-moi ce que tu veux modifier.'
        return summary

    def _is_cdc_valid_for_generation(self) -> tuple[bool, str]:
        if not self.cdc.get('project_name') or len(self.cdc.get('project_name', '')) < 3:
            return False, 'Nom de projet manquant ou trop court'
        if len(self.history) < 2:
            return False, 'Conversation trop courte pour générer un CDC fiable'
        user_messages = [m for m in self.history if m['role'] == 'user']
        if len(user_messages) < 1:
            return False, 'Aucun message utilisateur enregistré'
        return True, 'OK'

    def _prepare_generation(self) -> str:
        valid, reason = self._is_cdc_valid_for_generation()
        if not valid:
            self.state = ConvState.DISCOVERY
            return f"Je n'ai pas assez d'informations pour générer ({reason}). Reformule ton besoin en une phrase."
        if not self.cdc.get('stack', {}).get('backend'):
            self.cdc['stack']['backend'] = self.profile.get('preferred_backend', 'FastAPI')
            self.cdc['stack']['database'] = self.profile.get('preferred_db', 'SQLite')
        update_profile_from_cdc(self.cdc)
        log_cdc_trigger(self.cdc, self.history, self.cdc.get('project_name', ''))
        from core.memory_hub import extract_session_memories
        transcript = '\n'.join(f"{m['role']}: {m['content']}" for m in self.history)
        extract_session_memories(self.session_id, transcript, mode='conversation')
        return self.get_cdc_for_generation()

    def get_cdc_for_generation(self) -> str:
        stack = self.cdc.get('stack', {})
        features = self.cdc.get('features', [])
        cdc = f'Cree une application {self.cdc.get("project_name", "app")} avec '
        cdc += f'{stack.get("backend", "FastAPI")} + {stack.get("database", "SQLite")}. '
        if features:
            cdc += f'Fonctionnalites : {", ".join(features)}. '
        cdc += 'Interface web Bootstrap 5, fond sombre, responsive.'
        return cdc

    def reset(self):
        self.__init__()
