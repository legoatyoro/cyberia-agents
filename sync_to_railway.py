import psycopg2
import sqlite3
from datetime import datetime

# Lire les nouveaux payloads depuis SQLite
local_db = sqlite3.connect('/root/cyberia/.cyberia/payload_lab.db')
local_cur = local_db.cursor()
local_cur.execute("""
    SELECT payload, category, score, bypasses 
    FROM payloads 
    WHERE created_at > datetime('now', '-1 hour')
    AND bypasses > 10
""")
new_payloads = local_cur.fetchall()

if new_payloads:
    # Pousser vers Railway PostgreSQL
    conn = psycopg2.connect(
        host='switchyard.proxy.rlwy.net',
        port=24033,
        database='railway',
        user='postgres',
        password='rAVfYqePNHrhiyDEirWOgFlcPnWpNJwp'
    )
    cur = conn.cursor()
    
    for payload, category, score, bypasses in new_payloads:
        cur.execute("""
            INSERT INTO elite_payloads (payload, type, fitness_score, bypass_count, first_seen)
            VALUES (%s, %s, %s, %s, NOW())
            ON CONFLICT DO NOTHING
        """, (payload, category, float(score or 0), int(bypasses or 0)))
    
    conn.commit()
    print(f"[SYNC] {len(new_payloads)} payloads → Railway")
    conn.close()

local_db.close()
