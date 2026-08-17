import os
import glob
from datetime import datetime

# Lire toutes les analyses IA
analyses = glob.glob('/root/cyberia/.cyberia/ia_analysis_*.txt')
analyses.sort(reverse=True)

context = "=== MÉMOIRE CYBERIA ===\n\n"
for f in analyses[:10]:  # 10 dernières analyses
    with open(f, 'r') as file:
        context += file.read()[-500:] + "\n---\n"

# Sauvegarder le contexte consolidé
with open('/root/cyberia/.cyberia/cyberia_memory.txt', 'w') as f:
    f.write(context)

print(f'[MEMORY] Contexte consolidé : {len(analyses)} analyses')
