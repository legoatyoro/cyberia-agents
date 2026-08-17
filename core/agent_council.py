from core.multi_model_router import MultiModelRouter
import json, re


class AgentCouncil:
    def __init__(self):
        self.router = MultiModelRouter()
        self.agents = {
            'architect': {
                'name': 'ARCHITECT',
                'role': 'Expert architecture systeme et patterns de conception',
                'emoji': 'ARCH',
                'focus': 'scalabilite, maintenabilite, patterns SOLID'
            },
            'security': {
                'name': 'GUARDIAN',
                'role': 'Expert securite et vulnerabilites',
                'emoji': 'SEC',
                'focus': 'injections, auth, secrets, OWASP'
            },
            'performance': {
                'name': 'OPTIMIZER',
                'role': 'Expert performance, complexite algorithmique et optimisation',
                'emoji': 'OPTIM',
                'focus': 'requetes N+1, cache, complexite O(n), memoire, temps de reponse'
            },
            'ux': {
                'name': 'DESIGNER',
                'role': 'Expert UX et experience utilisateur',
                'emoji': 'UX',
                'focus': 'ergonomie, feedback utilisateur, accessibilite'
            },
            'testing': {
                'name': 'TESTER',
                'role': 'Expert tests, qualite et couverture de code',
                'emoji': 'TEST',
                'focus': 'couverture tests, cas limites, mocking, integration vs unitaire'
            },
        }

    def consult(self, question, context='', agents_to_use=None):
        if agents_to_use is None:
            agents_to_use = ['architect', 'security', 'performance']
        opinions = {}
        for agent_key in agents_to_use:
            agent = self.agents.get(agent_key)
            if not agent:
                continue
            prompt = f'''Tu es {agent["name"]}, {agent["role"]}.
Focus exclusif sur: {agent["focus"]}
Contexte: {context[:1000]}
Question: {question}
Reponds en 3-5 phrases max, tres concis, tres actionnable. Commence par ton point le plus critique.'''
            response = self.router.call(prompt, task_type='analysis')
            opinions[agent_key] = {'agent': agent, 'opinion': response}
            print(f'  [{agent["name"]}] Opinion recue')
        return opinions

    def reach_consensus(self, opinions, original_question):
        if not opinions:
            return 'Aucun consensus'
        opinions_text = '\n'.join(
            f'{v["agent"]["name"]}: {v["opinion"]}' for v in opinions.values()
        )
        prompt = f'''Ces agents experts ont analyse la question: {original_question}

OPINIONS:
{opinions_text}

Synthetise leurs points en:
1. ACTION PRIORITAIRE (la plus urgente, tous les agents d accord)
2. ACTIONS SECONDAIRES (2-3 points importants)
3. POINT DE DESACCORD (si present, lequel privilegier et pourquoi)

Sois ultra-concis et actionnable. En francais.'''
        return self.router.call(prompt, task_type='analysis')

    def collaborative_review(self, project_dir):
        from pathlib import Path
        path = Path(project_dir)
        sample_files = list(path.rglob('*.py'))[:5] + list(path.rglob('*.js'))[:3]
        context = '\n'.join(
            f'=== {f.name} ===\n{f.read_text(encoding="utf-8", errors="ignore")[:800]}'
            for f in sample_files[:5]
            if 'node_modules' not in str(f) and '__pycache__' not in str(f)
        )
        question = f'Analyse ce projet ({path.name}) et identifie les problemes les plus critiques'
        print(f'\n  [COUNCIL] Consultation du conseil d agents sur {path.name}...')
        opinions = self.consult(question, context, agents_to_use=['architect', 'security', 'performance', 'ux', 'testing'])
        consensus = self.reach_consensus(opinions, question)
        return opinions, consensus

    def deep_analysis(self, project_dir):
        from pathlib import Path
        path = Path(project_dir)
        files = [f for f in path.rglob('*.py') if '__pycache__' not in str(f)][:8]
        context = '\n'.join(
            f'=== {f.name} ===\n{f.read_text(encoding="utf-8", errors="ignore")[:1000]}'
            for f in files[:5]
        )

        # Passe 1 : chaque agent analyse independamment
        print(f'  [COUNCIL] Passe 1 : analyse independante des 5 agents...')
        opinions_1 = self.consult(
            f'Analyse approfondie de {path.name}',
            context,
            agents_to_use=list(self.agents.keys())
        )

        # Passe 2 : synthese croisee
        cross_prompt = f'Voici les analyses de 5 experts sur ce projet :\n'
        for key, data in opinions_1.items():
            cross_prompt += f'\n{data["agent"]["name"]}: {data["opinion"][:200]}\n'
        cross_prompt += (
            '\nIdentifie les 3 problemes les plus critiques sur lesquels tous les experts s accordent, '
            'et propose le plan d action prioritaire.'
        )

        print(f'  [COUNCIL] Passe 2 : synthese croisee...')
        consensus_final = self.router.call(cross_prompt, task_type='analysis')
        return opinions_1, consensus_final

    def design_together(self, feature_description, stack):
        question = f'Comment implementer cette fonctionnalite en {stack}: {feature_description}'
        context = f'Stack: {stack}\nFeature: {feature_description}'
        opinions = self.consult(question, context, agents_to_use=['architect', 'security', 'ux'])
        consensus = self.reach_consensus(opinions, question)
        return opinions, consensus
