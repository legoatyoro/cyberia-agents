import json, re
from pathlib import Path
from datetime import datetime
from core.multi_model_router import MultiModelRouter


class CoCreationSession:
    PHASES = ['discovery', 'validation', 'generation', 'testing', 'iteration', 'done']

    def __init__(self):
        self.router = MultiModelRouter()
        self.phase = 'discovery'
        self.project_spec = {}
        self.questions_asked = []
        self.answers = {}
        self.project_dir = None
        self.iteration = 0
        self.history = []

    def chat(self, user_message: str) -> dict:
        self.history.append({'role': 'user', 'content': user_message})
        response = ''
        action = None

        if self.phase == 'discovery':
            response, action = self._phase_discovery(user_message)
        elif self.phase == 'validation':
            response, action = self._phase_validation(user_message)
        elif self.phase == 'generation':
            response, action = self._phase_generation(user_message)
        elif self.phase == 'testing':
            response, action = self._phase_testing(user_message)
        elif self.phase == 'iteration':
            response, action = self._phase_iteration(user_message)

        self.history.append({'role': 'assistant', 'content': response})
        return {'reply': response, 'phase': self.phase, 'action': action, 'spec': self.project_spec}

    def _phase_discovery(self, msg: str) -> tuple:
        if not self.project_spec.get('description'):
            self.project_spec['description'] = msg

        if msg.lower() not in ('oui', 'non', 'ok', 'yes', 'no') and self.questions_asked:
            last_q_key = self.questions_asked[-1]
            self.answers[last_q_key] = msg
            self.project_spec[f'{last_q_key}_confirmed'] = True
            if last_q_key == 'stack':
                for s in ['fastapi', 'django', 'node', 'flask', 'python']:
                    if s in msg.lower():
                        self.project_spec['stack'] = s
                        break
                else:
                    self.project_spec['stack'] = 'fastapi'
            elif last_q_key == 'auth':
                self.project_spec['auth'] = 'oui' in msg.lower() or 'yes' in msg.lower()
            elif last_q_key == 'db':
                self.project_spec['db'] = 'postgresql' if 'post' in msg.lower() else 'sqlite'
            elif last_q_key == 'features':
                self.project_spec['features'] = msg

        desc = self.project_spec.get('description', '').lower()
        if not self.project_spec.get('stack_confirmed'):
            for s in ['fastapi', 'django', 'flask', 'node']:
                if s in desc:
                    self.project_spec['stack'] = s
                    self.project_spec['stack_confirmed'] = True
                    break

        needed_info = []
        if not self.project_spec.get('stack_confirmed'):
            needed_info.append(('stack', 'Quel stack tu veux ? FastAPI (simple, rapide), Django (complet), Node.js (JavaScript)'))
        if not self.project_spec.get('auth_confirmed'):
            needed_info.append(('auth', "Tu veux de l'authentification utilisateur ? (oui/non)"))
        if not self.project_spec.get('db_confirmed'):
            needed_info.append(('db', 'Base de donnees : SQLite (local, simple) ou PostgreSQL (production) ?'))
        if not self.project_spec.get('features_confirmed'):
            needed_info.append(('features', 'Fonctionnalites cles a avoir absolument ? (liste les en quelques mots)'))

        remaining = [q for q in needed_info if q[0] not in self.project_spec.get('_asked', [])]

        if remaining:
            key, question = remaining[0]
            if '_asked' not in self.project_spec:
                self.project_spec['_asked'] = []
            self.project_spec['_asked'].append(key)
            self.questions_asked.append(key)
            return question, None
        else:
            self.phase = 'validation'
            return self._build_validation_summary(), 'show_plan'

    def _build_validation_summary(self) -> str:
        stack = self.project_spec.get('stack', 'fastapi')
        auth = 'oui' if self.project_spec.get('auth') else 'non'
        db = self.project_spec.get('db', 'sqlite')
        features = self.project_spec.get('features', 'CRUD de base')
        desc = self.project_spec.get('description', '')

        prompt = f'''Tu es un architecte logiciel. Propose un plan de projet structure pour :
Description: {desc}
Stack: {stack}
Auth: {auth}
DB: {db}
Features: {features}

Reponds avec :
1. Nom du projet suggere
2. Liste des fichiers qui seront crees (max 12)
3. Endpoints principaux (max 8)
4. Dependances pip necessaires
5. Temps de generation estime

Sois concis et precis. En francais.'''

        plan = self.router.call(prompt, task_type='architecture')
        self.project_spec['plan'] = plan

        return (f'Voici le plan que je propose pour ton projet :\n\n{plan}\n\n'
                f'---\nTu valides ? (oui pour lancer / non pour modifier / modifie: <ce que tu veux changer>)')

    def _phase_validation(self, msg: str) -> tuple:
        msg_lower = msg.lower().strip()
        if msg_lower in ('oui', 'ok', 'yes', 'go', 'valide', 'lance', 'genere', 'c est bon'):
            self.phase = 'generation'
            return ('Parfait ! Je genere la structure de base en premier.\n\n'
                    'Je commence par les fichiers core (main.py, models, config) avant les routes et la logique metier.\n'
                    'Une fois pret, tu testeras chaque partie avec moi.'), 'start_generation'
        elif msg_lower.startswith('modifie') or msg_lower.startswith('change') or msg_lower.startswith('non'):
            modification = re.sub(r'^(modifie|change|non,?)\s*', '', msg_lower).strip()
            if modification:
                self.project_spec['modifications'] = modification
                new_plan = self._build_validation_summary_with_mod(modification)
                return f'Plan mis a jour :\n\n{new_plan}\n\n---\nTu valides maintenant ?', None
            return 'Qu est-ce que tu veux changer dans ce plan ?', None
        else:
            self.project_spec['modifications'] = msg
            return f'Je prends en compte : {msg}\n\nAutre chose a modifier ou on lance ? (oui / non)', None

    def _build_validation_summary_with_mod(self, mod: str) -> str:
        plan = self.project_spec.get('plan', '')
        prompt = (f'Modifie ce plan de projet en tenant compte de : {mod}\n\n'
                  f'Plan actuel :\n{plan}\n\nRetourne le plan mis a jour uniquement.')
        return self.router.call(prompt, task_type='architecture')

    def _phase_generation(self, msg: str) -> tuple:
        self.iteration += 1
        if self.iteration == 1:
            try:
                from core.orchestrator import Orchestrator
                desc = self.project_spec.get('description', '')
                stack = self.project_spec.get('stack', 'fastapi')
                features = self.project_spec.get('features', '')
                mods = self.project_spec.get('modifications', '')
                full_desc = f'{desc}. Stack: {stack}. Features: {features}. {mods}'.strip('. ')
                result = Orchestrator().run(full_desc)
                project_name = result.get('project_name', result.get('name', 'projet_genere'))
                files_count = result.get('files_generated', result.get('files', 0))
                score = result.get('score', result.get('final_score', 0))
                self.project_dir = Path('generated') / project_name
                self.project_spec['project_name'] = project_name
                self.phase = 'testing'

                files_list = []
                if self.project_dir.exists():
                    files_list = [
                        str(f.relative_to(self.project_dir))
                        for f in self.project_dir.rglob('*.py')
                        if '__pycache__' not in str(f)
                    ][:10]

                files_txt = '\n'.join(f'  {f}' for f in files_list) or '  (voir dossier generated/)'
                return (f'Projet genere : {project_name} ({files_count} fichiers, score {score}/10)\n\n'
                        f'Fichiers crees :\n{files_txt}\n\n'
                        f'Maintenant on teste ensemble.\n'
                        f'Lance : python launch.py {project_name}\n\n'
                        f'Dis-moi ce que tu vois (demarre / erreur / ...) ?'), 'test_now'
            except Exception as e:
                self.phase = 'testing'
                return f'Erreur lors de la generation : {e}\n\nDis-moi ce que tu vois dans la console.', None
        return 'Generation deja lancee. Dis-moi ce que tu vois dans la console.', None

    def _phase_testing(self, msg: str) -> tuple:
        self.phase = 'iteration'
        msg_lower = msg.lower()
        if any(w in msg_lower for w in ['demarre', 'marche', 'fonctionne', 'ok', 'running', 'localhost']):
            return ('Super, ca demarre ! Maintenant teste les endpoints principaux.\n\n'
                    'Essaie dans un autre terminal :\n'
                    'Invoke-WebRequest -Uri "http://localhost:8000" -UseBasicParsing\n\n'
                    'Ou ouvre http://localhost:8000/docs dans ton navigateur.\n\n'
                    'Qu est-ce que tu vois ?'), None
        elif any(w in msg_lower for w in ['erreur', 'error', 'bug', 'crash', 'traceback', 'ne marche pas']):
            fix_prompt = (f'Le projet {self.project_spec.get("project_name")} a cette erreur au demarrage :\n'
                          f'{msg}\n\n'
                          f'Diagnostique l erreur et propose le fix exact (fichier + ligne + correction).\n'
                          f'Sois concis et direct.')
            fix = self.router.call(fix_prompt, task_type='fix')
            return f'Je vois le probleme. Voici le fix :\n\n{fix}\n\nApres correction, relance et dis-moi si c est regle.', 'apply_fix'
        else:
            return 'Dis-moi exactement ce que tu vois : demarre bien ? erreur ? message ?', None

    def _phase_iteration(self, msg: str) -> tuple:
        msg_lower = msg.lower()
        if any(w in msg_lower for w in ['parfait', 'nickel', 'top', 'super', 'fonctionne', 'ok', 'genial']):
            return ('Projet valide !\n\nQue veux-tu faire maintenant ?\n'
                    '  -> Ajouter une fonctionnalite : dis-moi laquelle\n'
                    '  -> Generer les tests : tape tests\n'
                    '  -> Analyser le code : tape analyse\n'
                    '  -> Nouveau projet : tape nouveau'), None
        elif any(w in msg_lower for w in ['erreur', 'bug', 'probleme', 'marche pas']):
            prompt = (f'Projet en cours : {self.project_spec.get("project_name")}\n'
                      f'Probleme signale : {msg}\n'
                      f'Propose un diagnostic et le fix precis.')
            fix = self.router.call(prompt, task_type='fix')
            return f'Voici comment regler ca :\n\n{fix}\n\nApres correction, relance et dis-moi si c est regle.', None
        elif 'test' in msg_lower:
            return 'Je genere les tests. Lance : python cyberia.py puis option 20.', 'generate_tests'
        elif 'analyse' in msg_lower:
            return 'Je lance l analyse. Lance : python cyberia.py puis option 3.', 'analyze'
        elif 'nouveau' in msg_lower:
            self.__init__()
            return 'Nouveau projet ! Decris ce que tu veux creer.', 'restart'
        else:
            prompt = (f'Tu es l assistant CYBERIA. Le projet {self.project_spec.get("project_name")} est en cours de test.\n'
                      f'L utilisateur dit : {msg}\n'
                      f'Reponds de facon concise et actionnable pour continuer le developpement.')
            reply = self.router.call(prompt, task_type='analysis')
            return reply, None
