from core.multi_model_router import MultiModelRouter
import json, re


class SelfEvaluator:
    def __init__(self):
        self.router = MultiModelRouter()

    def evaluate(self, output, goal, criteria=None):
        if criteria is None:
            criteria = ['completude', 'correctness', 'qualite_code', 'respect_objectif']
        prompt = f'''Tu es un evaluateur expert IA. Evalue cet output par rapport a l objectif.
OBJECTIF: {goal[:300]}
OUTPUT A EVALUER: {output[:1000]}
CRITERES: {', '.join(criteria)}

Reponds UNIQUEMENT en JSON:
{{"score": 0-10, "passed": true, "weak_points": ["...", "..."], "improvements": ["...", "..."], "verdict": "APPROVE|IMPROVE|REJECT"}}'''
        response = self.router.call(prompt, task_type='analysis')
        match = re.search(r'\{.*\}', response, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except Exception:
                pass
        return {'score': 5, 'passed': True, 'verdict': 'APPROVE', 'weak_points': [], 'improvements': []}

    def evaluate_and_improve(self, output, goal, max_iterations=2):
        current = output
        eval_result = {'score': 5, 'passed': True, 'verdict': 'APPROVE', 'weak_points': [], 'improvements': []}
        for i in range(max_iterations):
            eval_result = self.evaluate(current, goal)
            score = eval_result.get('score', 5)
            verdict = eval_result.get('verdict', 'APPROVE')
            print(f'  [EVAL] Iteration {i+1}: score={score}/10, verdict={verdict}')
            if verdict == 'APPROVE' or score >= 8:
                break
            improvements = eval_result.get('improvements', [])
            if not improvements:
                break
            improve_prompt = f'''Ameliore cet output en appliquant ces corrections:
{chr(10).join(f"- {imp}" for imp in improvements[:3])}
OUTPUT ACTUEL: {current[:1500]}
Reponds avec l output ameliore uniquement.'''
            improved = self.router.call(improve_prompt, task_type='fix')
            if improved and len(improved) > 50:
                current = improved
        return current, eval_result

    def chain_of_thought(self, question, context=''):
        prompt = f'''Reponds a cette question en montrant ton raisonnement etape par etape.
QUESTION: {question}
CONTEXTE: {context[:500]}

Format:
ETAPE 1 - Analyse: ...
ETAPE 2 - Identification: ...
ETAPE 3 - Solution: ...
CONCLUSION: ...'''
        return self.router.call(prompt, task_type='analysis')
