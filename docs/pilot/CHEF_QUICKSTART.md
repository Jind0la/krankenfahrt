# Krankenfahrt — Kurzanleitung für den Disponenten

> Für Amir. Das ist dein tägliches Dashboard über Telegram.

## Erster Start

1. Öffne Telegram und starte **@FahrtenChefBot**
2. Sende `/start` — der Bot begrüßt dich

## Deine wichtigsten Befehle

| Befehl | Was es macht |
|--------|-------------|
| `/dashboard` | Alle heutigen Fahrten auf einen Blick |
| `/fahrer add <Name> <Telefon>` | Neuen Fahrer anlegen |
| `/fahrer list` | Alle Fahrer anzeigen |
| `/fahrzeug add <Kennzeichen> <Typ>` | Neues Fahrzeug anlegen |
| `/export` | Fahrten als CSV/PDF exportieren |
| `/eskalationen` | Offene Probleme anzeigen |

## Typischer Tagesablauf

1. **Morgens**: Fahrer bekommen automatisch ihre erste Fahrt per Push-Nachricht
2. **Unterwegs**: Fahrer tippen Status-Knöpfe (Losfahren → Angekommen → Patient an Bord → Abgesetzt)
3. **Du schaust ab und zu aufs Dashboard** — `/dashboard` zeigt alles live
4. **Nur wenn was schief geht**, bekommst du eine Eskalations-Nachricht mit Handlungsoptionen
5. **Abends**: `/export` für die Abrechnung

## Was du NICHT mehr tun musst

- ❌ Fahrten manuell zuteilen (macht die KI)
- ❌ Fahrer anrufen wegen Status (sieht man live)
- ❌ Abrechnung per Hand schreiben (CSV/PDF-Export)

## Falls was nicht funktioniert

- Fahrer meldet "Bot reagiert nicht" → Zuerst `/dashboard` checken. Wenn der Bot lebt, liegt's am Fahrer-Handy.
- Sprachnachricht wird falsch verstanden → Fahrer soll Knöpfe nutzen statt Sprache
- System komplett tot → Nimar anrufen

---

**Support**: Bei Fragen schreib Nimar direkt auf Telegram.
