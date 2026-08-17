import re
import json
from pathlib import Path
from typing import Optional, List, Dict, Tuple
from dataclasses import dataclass, field, asdict
from datetime import datetime

# ============================================================================
# Configuration et état global
# ============================================================================

ACTION_KEYWORDS = [
    'ecris', 'écris', 'cree', 'crée', 'corrige', 'remplace', 'applique',
    'genere', 'génère', 'produis', 'patch', 'fix', 'repare', 'répare',
    'modifie', 'supprime', 'ajoute', 'insere', 'insère', 'execute', 'exécute'
]

EXPLANATION_PATTERNS = [
    'voici comment', 'pour faire cela', 'tu peux', 'il suffit de',
    'je te suggere', 'je recommande', 'une approche', 'voici une solution',
    'tu pourrais', 'il faudrait', 'il est possible', 'approche recommandee'
]

# Patterns de correction connus (auto-appris)
KNOWN_FIX_PATTERNS: List[Dict] = []

# Fichier de persistance pour les patterns appris
FIX_PATTERNS_FILE = "known_fix_patterns.json"

@dataclass
class FixPattern:
    """Représente un pattern de correction appris"""
    error_pattern: str
    fix_pattern: str
    file_type: str
    success_count: int = 0
    fail_count: int = 0
    last_used: str = ""
    created_at: str = ""
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'FixPattern':
        return cls(**data)

class FixPatternManager:
    """Gère l'enregistrement et la récupération des patterns de correction"""
    
    def __init__(self, storage_file: str = FIX_PATTERNS_FILE):
        self.storage_file = storage_file
        self.patterns: List[FixPattern] = []
        self.load_patterns()
    
    def load_patterns(self) -> None:
        """Charge les patterns depuis le fichier de persistance"""
        try:
            if Path(self.storage_file).exists():
                with open(self.storage_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.patterns = [FixPattern.from_dict(p) for p in data]
        except (json.JSONDecodeError, IOError) as e:
            print(f"Erreur lors du chargement des patterns: {e}")
            self.patterns = []
    
    def save_patterns(self) -> None:
        """Sauvegarde les patterns dans le fichier de persistance"""
        try:
            with open(self.storage_file, 'w', encoding='utf-8') as f:
                json.dump([p.to_dict() for p in self.patterns], f, indent=2, ensure_ascii=False)
        except IOError as e:
            print(f"Erreur lors de la sauvegarde des patterns: {e}")
    
    def add_pattern(self, error_pattern: str, fix_pattern: str, file_type: str) -> None:
        """Ajoute un nouveau pattern de correction"""
        # Vérifier si le pattern existe déjà
        existing = self.find_pattern(error_pattern, file_type)
        if existing:
            existing.success_count += 1
            existing.last_used = datetime.now().isoformat()
        else:
            new_pattern = FixPattern(
                error_pattern=error_pattern,
                fix_pattern=fix_pattern,
                file_type=file_type,
                success_count=1,
                last_used=datetime.now().isoformat(),
                created_at=datetime.now().isoformat()
            )
            self.patterns.append(new_pattern)
        
        self.save_patterns()
    
    def find_pattern(self, error_pattern: str, file_type: str) -> Optional[FixPattern]:
        """Recherche un pattern correspondant"""
        for pattern in self.patterns:
            if (pattern.error_pattern == error_pattern and 
                pattern.file_type == file_type):
                return pattern
        return None
    
    def find_similar_patterns(self, error_text: str, file_type: str) -> List[FixPattern]:
        """Trouve des patterns similaires basés sur le texte d'erreur"""
        similar = []
        error_lower = error_text.lower()
        
        for pattern in self.patterns:
            if pattern.file_type != file_type:
                continue
            # Vérifier si le pattern d'erreur est contenu dans le texte
            if pattern.error_pattern.lower() in error_lower:
                similar.append(pattern)
            # Vérifier si des mots clés correspondent
            pattern_words = set(pattern.error_pattern.lower().split())
            error_words = set(error_lower.split())
            common_words = pattern_words & error_words
            if len(common_words) >= 2:  # Au moins 2 mots en commun
                similar.append(pattern)
        
        # Trier par taux de succès décroissant
        similar.sort(key=lambda p: p.success_count / max(p.success_count + p.fail_count, 1), reverse=True)
        return similar[:5]  # Retourner les 5 meilleurs
    
    def record_failure(self, error_pattern: str, file_type: str) -> None:
        """Enregistre un échec pour un pattern"""
        pattern = self.find_pattern(error_pattern, file_type)
        if pattern:
            pattern.fail_count += 1
            self.save_patterns()
    
    def get_statistics(self) -> Dict:
        """Retourne des statistiques sur les patterns appris"""
        if not self.patterns:
            return {"total_patterns": 0, "success_rate": 0}
        
        total_success = sum(p.success_count for p in self.patterns)
        total_fail = sum(p.fail_count for p in self.patterns)
        total_attempts = total_success + total_fail
        
        return {
            "total_patterns": len(self.patterns),
            "total_success": total_success,
            "total_fail": total_fail,
            "success_rate": total_success / max(total_attempts, 1) * 100,
            "most_used": max(self.patterns, key=lambda p: p.success_count).to_dict() if self.patterns else None
        }

# Initialisation du gestionnaire de patterns
fix_pattern_manager = FixPatternManager()

STATE = {
    'AUTOPILOT': False,
    'ACTION_MODE': False,
    'LAST_TARGET_FILE': None,
    'LAST_ERROR': None,
    'FIX_PATTERNS': fix_pattern_manager
}

# ============================================================================
# Fonctions principales
# ============================================================================

def detect_action_mode(user_input: str) -> bool:
    """Détecte si l'utilisateur demande une action"""
    if STATE.get('AUTOPILOT', False):
        return True
    
    lower = user_input.lower().strip()
    lower_normalized = lower.replace('é','e').replace('è','e').replace('ê','e').replace('à','a').replace('ô','o')
    
    if lower.startswith('/fix') or lower.startswith('/autopilot') or lower.startswith('/action'):
        return True
    
    for k in ACTION_KEYWORDS:
        if lower_normalized.startswith(k) or f' {k} ' in lower_normalized:
            return True
    
    file_pattern = re.search(r'[\w/\-]+\.(py|html|json|yml|yaml|txt|md|js|css)', lower)
    if file_pattern and any(k in lower_normalized for k in ACTION_KEYWORDS):
        STATE['LAST_TARGET_FILE'] = file_pattern.group(0)
        return True
    
    return False

def extract_code_block(content: str) -> str:
    """Extrait le bloc de code d'une réponse"""
    patterns = [
        r'\n(.*?)',
        r'\n(.*?)',
        r'\n(.*?)',
        r'\n(.*?)',
    ]
    for pattern in patterns:
        match = re.search(pattern, content, re.DOTALL)
        if match:
            return match.group(1).strip()
    return content.strip()

def is_explanation_response(llm_output: str) -> bool:
    """Vérifie si la réponse est une explication plutôt qu'une action"""
    lower = llm_output.lower()
    
    for pattern in EXPLANATION_PATTERNS:
        if pattern in lower:
            return True
    
    has_code_block = '' in llm_output
    has_file_write = any(x in llm_output for x in ['write_text', 'open(', 'WRITE_FILE', '[FILE:'])
    
    if has_code_block and not has_file_write and len(llm_output) > 500:
        explanation_ratio = sum(1 for p in EXPLANATION_PATTERNS if p in lower)
        if explanation_ratio >= 1:
            return True
    
    return False

def force_file_output(content: str, filename: str = None) -> str:
    """Force la sortie en format fichier"""
    code = extract_code_block(content)
    if filename:
        return f'[WRITE_FILE:{filename}]\n{code}'
    return code

def enforce_action_mode(llm_output: str, target_file: str = None) -> tuple[str, bool]:
    """Force le mode action si nécessaire"""
    if not target_file:
        target_file = STATE.get('LAST_TARGET_FILE')
    
    if is_explanation_response(llm_output):
        forced = force_file_output(llm_output, target_file)
        return forced, True
    
    return llm_output, False

def handle_meta_commands(user_input: str) -> tuple[bool, str]:
    """Gère les commandes méta"""
    lower = user_input.lower().strip()
    
    if '/autopilot on' in lower or 'autopilot on' in lower or 'agis directement' in lower:
        STATE['AUTOPILOT'] = True
        return True, 'Mode AUTOPILOT active - toutes les reponses seront des actions directes.'
    
    if '/autopilot off' in lower or 'autopilot off' in lower:
        STATE['AUTOPILOT'] = False
        return True, 'Mode AUTOPILOT desactive.'
    
    if lower.startswith('/fix '):
        parts = lower[5:].strip().split(' ', 1)
        if len(parts) >= 2:
            filename, problem = parts[0], parts[1]
            STATE['LAST_TARGET_FILE'] = filename
            STATE['ACTION_MODE'] = True
            STATE['LAST_ERROR'] = problem
            
            # Rechercher des patterns similaires
            file_ext = filename.split('.')[-1] if '.' in filename else ''
            similar_patterns = fix_pattern_manager.find_similar_patterns(problem, file_ext)
            
            if similar_patterns:
                # Utiliser le meilleur pattern trouvé
                best_pattern = similar_patterns[0]
                return True, f'__FIX_ACTION__:{filename}:{problem}:PATTERN:{best_pattern.fix_pattern}'
            
            return True, f'__FIX_ACTION__:{filename}:{problem}'
    
    return False, ''

def learn_from_error(error_text: str, fix_text: str, file_type: str) -> None:
    """Apprend d'une erreur et de sa correction"""
    # Extraire le pattern d'erreur (première ligne ou phrase clé)
    error_lines = error_text.strip().split('\n')
    error_pattern = error_lines[0] if error_lines else error_text
    
    # Limiter la taille du pattern
    if len(error_pattern) > 200:
        error_pattern = error_pattern[:200]
    
    # Ajouter le pattern appris
    fix_pattern_manager.add_pattern(error_pattern, fix_text, file_type)
    
    # Mettre à jour l'état
    STATE['LAST_ERROR'] = error_pattern

def get_fix_suggestions(error_text: str, file_type: str) -> List[str]:
    """Obtient des suggestions de correction basées sur les patterns appris"""
    similar_patterns = fix_pattern_manager.find_similar_patterns(error_text, file_type)
    return [p.fix_pattern for p in similar_patterns]

def get_pattern_statistics() -> Dict:
    """Retourne les statistiques des patterns appris"""
    return fix_pattern_manager.get_statistics()

# ============================================================================
# Tests
# ============================================================================

def run_tests():
    """Exécute les tests unitaires"""
    # Tests de base
    assert detect_action_mode('ecris le fichier main.py') == True
    assert detect_action_mode('cree models.py avec SQLAlchemy') == True
    assert detect_action_mode('corrige le bug dans main.py') == True
    assert detect_action_mode('comment faire une API ?') == False
    assert detect_action_mode('explique moi les templates') == False
    
    # Tests des commandes méta
    handled, msg = handle_meta_commands('autopilot on')
    assert handled == True
    assert STATE['AUTOPILOT'] == True
    
    handled, msg = handle_meta_commands('autopilot off')
    assert STATE['AUTOPILOT'] == False
    
    # Tests d'apprentissage
    learn_from_error("Erreur: variable non définie 'x'", "x = None  # Initialisation", "py")
    learn_from_error("Erreur: import manquant", "import os  # Ajout de l'import", "py")
    
    # Vérifier que les patterns sont sauvegardés
    assert len(fix_pattern_manager.patterns) == 2
    
    # Test de recherche de patterns similaires
    suggestions = get_fix_suggestions("Erreur: variable non définie 'y'", "py")
    assert len(suggestions) > 0
    assert "x = None" in suggestions[0]
    
    # Test des statistiques
    stats = get_pattern_statistics()
    assert stats['total_patterns'] == 2
    assert stats['total_success'] == 2
    
    print('Tous les tests action_detector passent')
    print(f'Patterns appris: {len(fix_pattern_manager.patterns)}')
    print(f'Statistiques: {get_pattern_statistics()}')

if __name__ == '__main__':
    run_tests()