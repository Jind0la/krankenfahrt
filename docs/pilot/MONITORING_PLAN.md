# Pilot Monitoring & Incident Response Plan

## Während des Piloten

### Health Checks (automatisch)
Railway prüft alle 30 Sekunden `GET /health` — bei 3 Fehlern in Folge wird der Container neu gestartet.

### Zu überwachen (manuell, täglich)

| Was | Wie | Wer |
|---|---|---|
| Bot-Status (alle 3 Bots online) | `/health` Endpoint aufrufen | Disponent |
| Fahrten-Status (keine hängen geblieben) | Chef-Bot `/dashboard` checken | Disponent |
| Fehler-Logs | `railway logs` oder Railway Dashboard | Entwickler |
| Datenbank-Integrität | Keine korrupten Fahrten (Status != null) | Entwickler |
| Speichernutzung | Railway Dashboard → Metrics | Entwickler |

### Alarmierungen

| Ereignis | Schweregrad | Aktion |
|---|---|---|
| Health-Check schlägt 3x fehl | 🔴 CRITICAL | Railway restartet Container automatisch |
| Bot antwortet >5s nicht | 🟡 WARNING | Manuell `railway logs` prüfen, ggf. `railway up` |
| Fahrer meldet "Bot reagiert nicht" | 🔴 CRITICAL | Sofort prüfen: `/health`, Logs, ggf. Neustart |
| Datenbank-Fehler im Log | 🔴 CRITICAL | DB-Backup prüfen, nicht neu starten ohne Analyse |
| Speicher >80% | 🟡 WARNING | Prüfen ob Memory-Leak, ggf. DB aufräumen |

## Logging

### Was wird geloggt?
- Jeder Bot-Befehl (User-ID, Command, Timestamp)
- Jeder Status-Wechsel einer Fahrt
- Alle Fehler mit Stacktraces
- Datenbank-Operationen (nur Errors)

### Log-Zugriff
```bash
# Live-Logs streamen
railway logs

# Letzte 100 Zeilen
railway logs --lines 100

# Nach Fehlern filtern
railway logs | grep -i "error\|exception\|traceback"
```

## Backup-Strategie

- **Datenbank**: SQLite-Datei (`/app/data/krankenfahrt.db`) wird via Railway Volume gesichert
- **Backup-Skript** (läuft als Cron-Job im Container):
  ```bash
  cp /app/data/krankenfahrt.db /app/data/backup-$(date +%Y%m%d).db
  ```
- **Aufbewahrung**: 7 tägliche Backups (rollierend, älteste werden überschrieben)
- **Wiederherstellung**: `cp /app/data/backup-YYYYMMDD.db /app/data/krankenfahrt.db` + Railway-Neustart

## Incident Response

### Bot reagiert nicht mehr
1. `railway logs` prüfen — letzter Log-Eintrag?
2. `/health` Endpoint aufrufen: `curl https://<app>.railway.app/health`
3. Wenn tot: `railway up` (redeploy)
4. Wenn up aber langsam: `railway logs | tail -50` → nach Fehlern suchen
5. Fahrer informieren (Support-Chat)

### Fahrt hängt in falschem Status
1. Nicht manuell in DB ändern!
2. Chef-Bot `/dashboard` → Fahrt finden → manuell korrigieren
3. Falls Chef-Bot nicht hilft: Entwickler kontaktieren

### Sprachnachricht wird falsch verstanden
1. Nicht kritisch — Fahrer kann immer Knöpfe nutzen
2. Fahrer bitten, Knopf zu drücken statt Sprache zu nutzen
3. Im Feedback-Formular dokumentieren
