#!/usr/bin/env python3
"""
Génère un (ou deux) calendrier(s) ICS de la Coupe du Monde 2026.
Source : openfootball/worldcup.json (domaine public).

Produit :
  - coupe_du_monde_2026.ics      : les 104 matchs (équipes suivies marquées d'un ★)
  - cdm2026_france_portugal.ics  : uniquement les équipes suivies (pour une couleur dédiée sur iPhone)

Nouveautés : scores auto-remplis, robustesse (un match cassé ne fait plus planter
le calendrier entier), mise en avant des équipes suivies.
"""

import json
import re
import sys
import hashlib
import urllib.request
from datetime import datetime, timedelta, timezone

SOURCE_URL = "https://raw.githubusercontent.com/openfootball/worldcup.json/master/2026/worldcup.json"

# ----- Réglages faciles à modifier -----
EQUIPES_SUIVIES = ["France", "Portugal"]  # noms tels qu'écrits dans la source
COULEUR_SUIVI = "blue"    # propriété COLOR (RFC 7986) ; ignorée par Apple, OK ailleurs
DUREE_GROUPE_MIN = 120    # 2 h pour la phase de groupes
DUREE_KO_MIN = 150        # 2 h 30 pour les phases finales (prolongations possibles)

EQUIPES_FR = {
    "Algeria": "Algérie", "Argentina": "Argentine", "Australia": "Australie",
    "Austria": "Autriche", "Belgium": "Belgique", "Bosnia & Herzegovina": "Bosnie-Herzégovine",
    "Brazil": "Brésil", "Canada": "Canada", "Cape Verde": "Cap-Vert",
    "Colombia": "Colombie", "Croatia": "Croatie", "Curaçao": "Curaçao",
    "Czech Republic": "République tchèque", "DR Congo": "RD Congo", "Ecuador": "Équateur",
    "Egypt": "Égypte", "England": "Angleterre", "France": "France", "Germany": "Allemagne",
    "Ghana": "Ghana", "Haiti": "Haïti", "Iran": "Iran", "Iraq": "Irak",
    "Ivory Coast": "Côte d'Ivoire", "Japan": "Japon", "Jordan": "Jordanie",
    "Mexico": "Mexique", "Morocco": "Maroc", "Netherlands": "Pays-Bas",
    "New Zealand": "Nouvelle-Zélande", "Norway": "Norvège", "Panama": "Panama",
    "Paraguay": "Paraguay", "Portugal": "Portugal", "Qatar": "Qatar",
    "Saudi Arabia": "Arabie saoudite", "Scotland": "Écosse", "Senegal": "Sénégal",
    "South Africa": "Afrique du Sud", "South Korea": "Corée du Sud", "Spain": "Espagne",
    "Sweden": "Suède", "Switzerland": "Suisse", "Tunisia": "Tunisie",
    "Turkey": "Turquie", "USA": "États-Unis", "Uruguay": "Uruguay", "Uzbekistan": "Ouzbékistan",
}
TOURS_FR = {
    "Round of 32": "Seizièmes de finale", "Round of 16": "Huitièmes de finale",
    "Quarter-final": "Quart de finale", "Semi-final": "Demi-finale",
    "Match for third place": "Match pour la 3e place", "Final": "Finale",
}


def traduire_equipe(nom):
    if nom in EQUIPES_FR:
        return EQUIPES_FR[nom]
    m = re.fullmatch(r"W(\d+)", nom)
    if m:
        return f"Vainqueur match {m.group(1)}"
    m = re.fullmatch(r"L(\d+)", nom)
    if m:
        return f"Perdant match {m.group(1)}"
    return nom


def vers_utc(date_str, time_str):
    """'2026-06-11' + '13:00 UTC-6' -> datetime UTC. Lève ValueError si format inattendu."""
    heure, fuseau = time_str.strip().split(" ")
    h, mn = map(int, heure.split(":"))
    offset = int(re.search(r"UTC([+-]\d+)", fuseau).group(1))
    annee, mois, jour = map(int, date_str.split("-"))
    return datetime(annee, mois, jour, h, mn) - timedelta(hours=offset)


def score_texte(score):
    """Construit la portion de score, ou None si le match n'est pas joué.
    Ex : [3,3] a.p. + tab [2,4] -> ('3 - 3 a.p.', ' (t.a.b. 2-4)')."""
    if not isinstance(score, dict):
        return None
    base = score.get("et") or score.get("ft")
    if not (isinstance(base, list) and len(base) == 2):
        return None
    core = f"{base[0]} - {base[1]}"
    suffixe = " a.p." if score.get("et") else ""
    pen = score.get("p")
    if isinstance(pen, list) and len(pen) == 2:
        suffixe += f" (t.a.b. {pen[0]}-{pen[1]})"
    return core, suffixe


def echapper(t):
    return t.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def plier_ligne(ligne):
    if len(ligne.encode("utf-8")) <= 75:
        return ligne
    morceaux, courant = [], b""
    for c in ligne:
        cb = c.encode("utf-8")
        if len(courant) + len(cb) > 75:
            morceaux.append(courant)
            courant = b" " + cb
        else:
            courant += cb
    morceaux.append(courant)
    return b"\r\n".join(morceaux).decode("utf-8")


def fmt(dt):
    return dt.strftime("%Y%m%dT%H%M%SZ")


def est_suivi(nom1, nom2):
    return any(e.lower() in (nom1.lower(), nom2.lower()) for e in EQUIPES_SUIVIES)


def construire_vevent(x, horodatage):
    """Construit les lignes d'un VEVENT. Lève une exception si la donnée est inexploitable."""
    debut = vers_utc(x["date"], x["time"])
    is_ko = not x.get("group")
    fin = debut + timedelta(minutes=DUREE_KO_MIN if is_ko else DUREE_GROUPE_MIN)

    nom1, nom2 = x["team1"], x["team2"]
    t1, t2 = traduire_equipe(nom1), traduire_equipe(nom2)

    contexte = TOURS_FR.get(x["round"], x["round"]) if is_ko else "Gr. " + x["group"].replace("Group ", "")

    sc = score_texte(x.get("score"))
    if sc:
        core, suffixe = sc
        titre = f"{t1} {core} {t2}{suffixe} ({contexte})"
    else:
        titre = f"{t1} - {t2} ({contexte})"

    suivi = est_suivi(nom1, nom2)

    lieu = x.get("ground", "")
    phase = "Phase de groupes" if not is_ko else TOURS_FR.get(x["round"], x["round"])
    description = f"Coupe du Monde 2026 · {phase} · {lieu}"

    uid = hashlib.md5(f"{x['date']}{x['time']}{lieu}".encode("utf-8")).hexdigest() + "@cdm2026"

    lignes = [
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{horodatage}",
        f"DTSTART:{fmt(debut)}",
        f"DTEND:{fmt(fin)}",
        f"SUMMARY:{echapper(titre)}",
        f"LOCATION:{echapper(lieu)}",
        f"DESCRIPTION:{echapper(description)}",
    ]
    if suivi and COULEUR_SUIVI:
        lignes.append(f"COLOR:{COULEUR_SUIVI}")          # honorée par certains clients
        lignes.append("CATEGORIES:Equipe suivie")
    # rappel 30 min avant le coup d'envoi
    lignes += [
        "BEGIN:VALARM",
        "ACTION:DISPLAY",
        "DESCRIPTION:Coup d'envoi dans 30 min",
        "TRIGGER:-PT30M",
        "END:VALARM",
        "END:VEVENT",
    ]
    return lignes


def construire_ics(matchs, nom_cal):
    horodatage = fmt(datetime.now(timezone.utc))
    lignes = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//thibault//CDM2026//FR",
        "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
        f"X-WR-CALNAME:{nom_cal}", "X-WR-TIMEZONE:Europe/Paris",
    ]
    ignores = 0
    for i, x in enumerate(matchs):
        try:
            lignes += construire_vevent(x, horodatage)
        except Exception as e:
            ignores += 1
            print(f"  [!] match #{i} ignoré ({e})", file=sys.stderr)
    lignes.append("END:VCALENDAR")
    if ignores:
        print(f"  -> {ignores} match(s) ignoré(s) faute de données exploitables", file=sys.stderr)
    return "\r\n".join(plier_ligne(l) for l in lignes) + "\r\n"


def ecrire(matchs, nom_fichier, nom_cal):
    with open(nom_fichier, "w", encoding="utf-8", newline="") as f:
        f.write(construire_ics(matchs, nom_cal))
    print(f"OK -> {nom_fichier} ({len(matchs)} matchs)")


def charger_donnees():
    try:
        with urllib.request.urlopen(SOURCE_URL, timeout=20) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        print(f"  [!] réseau indisponible ({e}), repli sur la copie locale", file=sys.stderr)
        return json.load(open("wc2026.json"))


def main():
    data = charger_donnees()
    matchs = data["matches"]

    if EQUIPES_SUIVIES:
        suivis = [m for m in matchs if est_suivi(m.get("team1", ""), m.get("team2", ""))]
        autres = [m for m in matchs if not est_suivi(m.get("team1", ""), m.get("team2", ""))]
        # calendrier principal SANS les équipes suivies -> aucun doublon entre les deux
        ecrire(autres, "coupe_du_monde_2026.ics", "Coupe du Monde 2026 (hors équipes suivies)")
        # calendrier dédié, à abonner avec sa propre couleur sur iPhone
        ecrire(suivis, "cdm2026_france_portugal.ics", "CDM 2026 - France & Portugal")
    else:
        ecrire(matchs, "coupe_du_monde_2026.ics", "Coupe du Monde 2026")


if __name__ == "__main__":
    main()
