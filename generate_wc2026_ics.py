#!/usr/bin/env python3
"""
Génère un calendrier ICS de la Coupe du Monde 2026 (104 matchs).
Source des données : openfootball/worldcup.json (domaine public).

Usage :
    python3 generate_wc2026_ics.py            # tous les matchs
    python3 generate_wc2026_ics.py France     # filtre sur une équipe (groupes)

Le fichier produit (coupe_du_monde_2026.ics) s'importe dans n'importe quelle
appli calendrier (iOS, Google, Outlook...).
"""

import json
import re
import sys
import hashlib
import urllib.request
from datetime import datetime, timedelta, timezone

SOURCE_URL = "https://raw.githubusercontent.com/openfootball/worldcup.json/master/2026/worldcup.json"
DUREE_MATCH_MIN = 120  # durée bloquée dans le calendrier (2 h)

# --- Traduction FR des 48 équipes (mapping de commodité, pas inventé : ---
# --- chaque clé correspond à un nom réellement présent dans la source) ---
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

# Noms FR des tours à élimination directe
TOURS_FR = {
    "Round of 32": "Seizièmes de finale",
    "Round of 16": "Huitièmes de finale",
    "Quarter-final": "Quart de finale",
    "Semi-final": "Demi-finale",
    "Match for third place": "Match pour la 3e place",
    "Final": "Finale",
}


def traduire_equipe(nom):
    """Traduit un nom d'équipe, ou rend lisible un placeholder (W97 -> Vainqueur 97)."""
    if nom in EQUIPES_FR:
        return EQUIPES_FR[nom]
    m = re.fullmatch(r"W(\d+)", nom)
    if m:
        return f"Vainqueur match {m.group(1)}"
    m = re.fullmatch(r"L(\d+)", nom)
    if m:
        return f"Perdant match {m.group(1)}"
    return nom  # placeholders type "1A", "3C/E/F/H/I" -> laissés tels quels


def vers_utc(date_str, time_str):
    """'2026-06-11' + '13:00 UTC-6' -> datetime en UTC."""
    heure, fuseau = time_str.split(" ")
    h, mn = map(int, heure.split(":"))
    offset = int(re.search(r"UTC([+-]\d+)", fuseau).group(1))
    annee, mois, jour = map(int, date_str.split("-"))
    local = datetime(annee, mois, jour, h, mn)
    # une heure locale en (UTC+offset) vaut, en UTC : locale - offset
    return local - timedelta(hours=offset)


def echapper(texte):
    """Échappe les caractères spéciaux ICS (RFC 5545)."""
    return (texte.replace("\\", "\\\\").replace(";", "\\;")
                 .replace(",", "\\,").replace("\n", "\\n"))


def plier_ligne(ligne):
    """Replie une ligne à 75 octets (RFC 5545) : retour + espace en continuation."""
    octets = ligne.encode("utf-8")
    if len(octets) <= 75:
        return ligne
    morceaux, courant = [], b""
    for c in ligne:
        cb = c.encode("utf-8")
        if len(courant) + len(cb) > 75:
            morceaux.append(courant)
            courant = b" " + cb  # espace de continuation
        else:
            courant += cb
    morceaux.append(courant)
    return b"\r\n".join(morceaux).decode("utf-8")


def fmt(dt):
    """datetime UTC -> '20260611T190000Z'."""
    return dt.strftime("%Y%m%dT%H%M%SZ")


def construire_ics(matchs, nom_cal="Coupe du Monde 2026"):
    horodatage = fmt(datetime.now(timezone.utc))
    lignes = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//thibault//CDM2026//FR",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{nom_cal}",
        "X-WR-TIMEZONE:Europe/Paris",
    ]
    for x in matchs:
        debut = vers_utc(x["date"], x["time"])
        fin = debut + timedelta(minutes=DUREE_MATCH_MIN)
        t1, t2 = traduire_equipe(x["team1"]), traduire_equipe(x["team2"])

        # contexte du tour : groupe ou nom de la phase finale
        groupe = x.get("group", "")
        if groupe:
            contexte = "Gr. " + groupe.replace("Group ", "")
        else:
            contexte = TOURS_FR.get(x["round"], x["round"])

        titre = f"{t1} - {t2} ({contexte})"
        lieu = x.get("ground", "")
        phase = "Phase de groupes" if x["round"].startswith("Matchday") else TOURS_FR.get(x["round"], x["round"])
        description = f"Coupe du Monde 2026 · {phase} · {lieu}"

        # UID stable basé sur le créneau (date+heure+stade), PAS les équipes
        # -> quand un placeholder devient une vraie équipe, l'event se met à jour
        graine = f"{x['date']}{x['time']}{lieu}".encode("utf-8")
        uid = hashlib.md5(graine).hexdigest() + "@cdm2026"

        lignes += [
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{horodatage}",
            f"DTSTART:{fmt(debut)}",
            f"DTEND:{fmt(fin)}",
            f"SUMMARY:{echapper(titre)}",
            f"LOCATION:{echapper(lieu)}",
            f"DESCRIPTION:{echapper(description)}",
            "END:VEVENT",
        ]
    lignes.append("END:VCALENDAR")
    return "\r\n".join(plier_ligne(l) for l in lignes) + "\r\n"


def charger_donnees():
    try:
        with urllib.request.urlopen(SOURCE_URL, timeout=20) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        # repli sur la copie locale si pas de réseau
        return json.load(open("wc2026.json"))


def main():
    data = charger_donnees()
    matchs = data["matches"]

    filtre = sys.argv[1] if len(sys.argv) > 1 else None
    nom_cal = "Coupe du Monde 2026"
    if filtre:
        matchs = [m for m in matchs if filtre.lower() in (m["team1"] + m["team2"]).lower()]
        nom_cal = f"CDM 2026 - {filtre}"

    ics = construire_ics(matchs, nom_cal)
    sortie = "coupe_du_monde_2026.ics"
    with open(sortie, "w", encoding="utf-8", newline="") as f:
        f.write(ics)
    print(f"OK -> {sortie} ({len(matchs)} matchs)")


if __name__ == "__main__":
    main()
