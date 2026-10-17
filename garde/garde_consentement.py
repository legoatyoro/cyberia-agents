#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CYBERIA - garde-fou de consentement (v2).

Une seule regle : un scan n'est autorise que par une PREUVE, jamais par un drapeau.

Trois sources, dans cet ordre :
  1. liste blanche (`surveillance-urls.txt`) : laboratoires locaux + sites du proprietaire ;
  2. une ligne CONFIRMEE dans `consentement_scan_actif` (token + confirme_le non nul) ;
  3. rien d'autre.

Posture : REFUS par defaut. Base injoignable, psycopg2 absent, site inconnu -> refus, journalise.
Un garde-fou qui s'ouvre quand il ne sait pas n'est pas un garde-fou.

Il ignore volontairement `cibles_scan.autorisation_confirmee` (voir ALERTE-PERIMETRE-...).

Tests :
  python garde_consentement.py --auto-test     # 5 cas, refus par defaut
  python garde_consentement.py --test-base     # exerce la branche qui AUTORISE,
                                               # via une table temporaire annulee (ROLLBACK)
"""
import json
import pathlib
import re
import sys
import urllib.parse
from datetime import datetime

ICI = pathlib.Path(__file__).resolve().parent
LISTE = ICI / "surveillance-urls.txt"
JOURNAL = ICI / "refus_consentement.jsonl"

BLOCKLIST = ("169.254.169.254", "metadata.google.internal", "metadata.azure.com",
             "100.100.100.200", "localhost:2375")

# La requete qui fait foi. Une seule definition, utilisee par le garde-fou ET par le test.
SQL_CONSENTEMENT = """SELECT 1 FROM consentement_scan_actif
                       WHERE confirme_le IS NOT NULL AND token IS NOT NULL
                         AND (lower(site) = %s OR lower(site) LIKE %s)
                       LIMIT 1"""


def charger_liste(chemin=LISTE):
    urls = []
    try:
        for ligne in pathlib.Path(chemin).read_text(encoding="utf-8", errors="replace").splitlines():
            l = ligne.split("#", 1)[0].strip()
            if l:
                urls.append(l)
    except FileNotFoundError:
        pass
    return urls


def origine(url):
    m = re.match(r"^(https?://[^/]+)", url or "", re.I)
    return m.group(1).lower().rstrip("/") if m else ""


def hote(url):
    return urllib.parse.urlparse(url).netloc.lower().split(":")[0]


def _connecter():
    """Porte d'entree unique : connexion_securisee si present, sinon psycopg2 direct."""
    try:
        sys.path.insert(0, "/opt/waf-bench")
        from connexion_securisee import connecter          # noqa: PLC0415
        return connecter()
    except Exception:
        import psycopg2                                    # noqa: PLC0415
        return psycopg2.connect(host="127.0.0.1", dbname="waf_hunter", user="postgres",
                                connect_timeout=5)


def consentement_en_base(hote_cible, cn=None):
    """True uniquement si un consentement confirme existe. Toute erreur -> False."""
    propre = cn is None
    try:
        cn = cn or _connecter()
        cur = cn.cursor()
        cur.execute(SQL_CONSENTEMENT, (hote_cible, "%" + hote_cible + "%"))
        trouve = cur.fetchone() is not None
        cur.close()
        if propre:
            cn.close()
        return trouve, ("consentement confirmé en base" if trouve else "aucun consentement en base")
    except Exception as e:
        return False, f"base injoignable ({type(e).__name__}) : refus par défaut"


def autorisation(url, liste=None):
    liste = charger_liste() if liste is None else liste
    h = hote(url)
    if not h:
        return False, "URL sans hôte"
    for b in BLOCKLIST:
        if b in url.lower():
            return False, f"blocklist ({b})"
    o = origine(url)
    if o and o in {origine(u) for u in liste}:
        return True, "liste blanche : laboratoire ou site du propriétaire"
    return consentement_en_base(h)


def journaliser(url, autorise, motif, chemin=JOURNAL):
    try:
        with pathlib.Path(chemin).open("a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": datetime.now().isoformat(timespec="seconds"),
                                "url": url, "autorise": autorise, "motif": motif},
                               ensure_ascii=False) + "\n")
    except Exception:
        pass


def verifier(url, liste=None, journal=True):
    ok, motif = autorisation(url, liste)
    if journal and not ok:
        journaliser(url, ok, motif)
    return ok, motif


def auto_test(liste=None):
    cas = [
        ("http://127.0.0.1:8099/", True, "laboratoire local (liste blanche)"),
        ("https://mytabacticket.com/", True, "site du propriétaire (liste blanche)"),
        ("https://www.fnac.com/", False, "tiers réel sans consentement"),
        ("http://169.254.169.254/latest/meta-data/", False, "blocklist métadonnées"),
        ("https://inconnu-sans-preuve.example/", False, "inconnu"),
    ]
    echecs = 0
    for url, attendu, description in cas:
        ok, motif = verifier(url, liste)
        if ok != attendu:
            echecs += 1
        print(f"  [{'OK ' if ok == attendu else 'ECHEC'}] {url[:42]:44s} autorisé={ok!s:5s} | {motif}")
    print(f"\n{len(cas) - echecs}/{len(cas)} cas conformes")
    return echecs


def test_base():
    """Exerce la branche qui AUTORISE, sans rien ecrire definitivement.

    On ouvre une transaction, on cree une table TEMPORAIRE du meme nom (elle masque la vraie
    dans cette session), on insere un consentement fictif, on rejoue la requete de reference,
    puis ROLLBACK. Si la branche ne s'ouvre pas ici, elle ne s'ouvrira jamais en production -
    et un garde-fou incapable d'autoriser n'est pas testé, il est seulement bloquant.
    """
    try:
        cn = _connecter()
    except Exception as e:
        print(f"ECHEC : base injoignable ({type(e).__name__}) — test impossible")
        return 1
    cur = cn.cursor()
    try:
        cur.execute("""CREATE TEMP TABLE consentement_scan_actif
                       (site text, token text, confirme_le timestamp) ON COMMIT DROP""")
        cur.execute("INSERT INTO consentement_scan_actif VALUES ('www.exemple-autorise.fr','jeton-test',now())")
        trouve, motif = consentement_en_base("www.exemple-autorise.fr", cn=cn)
        print(f"  branche positive : autorisé={trouve!s:5s} | {motif}")
        cur.execute(SQL_CONSENTEMENT, ("www.fnac.com", "%www.fnac.com%"))
        intrus, _ = consentement_en_base("www.fnac.com", cn=cn)
        print(f"  controle négatif : autorisé={intrus!s:5s} | doit être False")
        ok = trouve and not intrus
        print("\n" + ("OK : la branche qui autorise fonctionne, la branche par defaut refuse."
                      if ok else "ECHEC : le garde-fou ne discrimine pas."))
        return 0 if ok else 1
    finally:
        cn.rollback()
        cn.close()


if __name__ == "__main__":
    if "--auto-test" in sys.argv:
        sys.exit(1 if auto_test() else 0)
    if "--test-base" in sys.argv:
        sys.exit(test_base())
    if "--url" in sys.argv:
        cible = sys.argv[sys.argv.index("--url") + 1]
        ok, motif = verifier(cible)
        print(("AUTORISÉ" if ok else "REFUSÉ") + f" : {cible}\n  motif : {motif}")
        sys.exit(0 if ok else 2)
    print(__doc__)
    sys.exit(1)
