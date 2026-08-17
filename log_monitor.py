import time, sqlite3, os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv('/root/cyberia/.env')

LOG_FILES = [
    '/root/cyberia/.cyberia/evolve_main.log',
    '/root/cyberia/.cyberia/red_blue.log',
    '/root/cyberia/.cyberia/sync.log',
]

def monitor():
    positions = {f: 0 for f in LOG_FILES}
    print('[MONITOR] Surveillance logs démarrée...')
    
    while True:
        for log_file in LOG_FILES:
            try:
                with open(log_file, 'r') as f:
                    f.seek(positions[log_file])
                    new_lines = f.readlines()
                    positions[log_file] = f.tell()
                    
                    for line in new_lines:
                        if 'BYPASS 23/23' in line:
                            print(f'[✅ ELITE] {line.strip()}')
                        elif 'Stagnation' in line:
                            print(f'[⚠️ STAGNATION] {line.strip()}')
                        elif 'Erreur' in line and '402' not in line:
                            print(f'[❌ ERREUR] {line.strip()}')
            except:
                pass
        time.sleep(10)

monitor()
