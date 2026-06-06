# Multi-Tenancy Architecture — Krankenfahrt

**Task:** T4.3 Multi-Tenancy-Architektur  
**Author:** analyst  
**Date:** 2026-06-06  
**Phase:** 4 (Launch & Scale), Priority 3  
**Status:** Analysis & Recommendation

---

## Executive Summary

Krankenfahrt ist aktuell **single-tenant** — ein Deployment bedient genau ein Krankentransport-Unternehmen. Sobald ein zweiter Kunde (z.B. ein weiteres Unternehmen, eine weitere Filiale) das System nutzen will, muss die Architektur mandantenfähig werden.

Die Analyse evaluiert zwei Architekturansätze:

| Kriterium | A: Eine Instanz pro Kunde | B: Mandantenfähige DB |
|-----------|--------------------------|------------------------|
| Datenisolation | ✅ Perfekt (getrennte DBs) | ⚠️ Row-Level / Table-Level |
| DSGVO-Compliance | ✅ Trivial | ⚠️ Aufwändig |
| Betriebskosten (Railway) | ❌ Linear (N × $5/Monat) | ✅ Konstant (1 × $5/Monat) |
| Code-Komplexität | ✅ Minimal | ❌ Hoch (Tenant-Filter auf jedem Query) |
| Deployment-Aufwand | ⚠️ N Deployments pflegen | ✅ Ein Deployment |
| Cross-Tenant-Features | ❌ Kein Shared Dispatch | ✅ Einfach (Sammelfahrten über Grenzen?) |
| Skalierung (50+ Kunden) | ❌ Nicht praktikabel | ✅ DB-Level Scaling |
| Telegram-Bot-Verwaltung | ✅ 3 Tokens/Instanz, isoliert | ✅ 3N Tokens, zentral |

**Empfehlung: Ansatz A (eine Instanz pro Kunde) für Phase 4–5. Ansatz B (mandantenfähige DB) ist das langfristige Ziel, aber erst wenn 10+ Kunden die Kosten rechtfertigen.**

---

## 1. Ausgangslage: Aktuelle Single-Tenant-Architektur

### 1.1 Aktueller Stand

```python
# config.py — eine hartkodierte Company
COMPANY_NAME: str = "Krankenfahrt"
COMPANY_TAX_ID: str = "DE123456789"
COMPANY_IK_NUMMER: str = "123456789"

# main.py — drei feste Bot Tokens
PATIENT_BOT_TOKEN = os.environ["PATIENT_BOT_TOKEN"]    # @FahrGast
DRIVER_BOT_TOKEN = os.environ["DRIVER_BOT_TOKEN"]      # @FahrLenker
CHEF_BOT_TOKEN = os.environ["CHEF_BOT_TOKEN"]          # @FahrtenChef

# schema.py — keine Tenant-ID, keine Isolationsgrenze
class Patient(Model):
    id = fields.IntField(pk=True)
    telegram_id = fields.BigIntField(unique=True)  # global unique
```

**Implikationen:**
- `telegram_id` ist global unique — zwei Patienten verschiedener Unternehmen können nicht dieselbe Telegram-ID haben (kein praktisches Problem, da unterschiedliche Bots)
- Keine `company_id` / `tenant_id` in irgendeinem Modell
- SQLite als Einzeldatei, kein Connection-Pooling, kein Row-Level-Security-Mechanismus
- Drei Bot-Tokens via Environment — kein Mechanismus für dynamisches Bot-Management

### 1.2 Was muss mandantenfähig werden?

| Ebene | Single-Tenant (Heute) | Multi-Tenant (Ziel) |
|-------|----------------------|---------------------|
| **Daten** | Alle Tabellen ohne Tenant-Filter | Jeder Record hat `company_id` FK |
| **Bots** | 3 fixe Telegram Bots | 3N Bots, dynamisch gemanaged |
| **Config** | Environment-Variablen, eine Company | DB-gestützt, pro Tenant |
| **Dispatch** | Alle Fahrer im selben Pool | Fahrer sind Tenant-gebunden |
| **Billing** | Eine IK-Nummer, eine Steuer-ID | Pro Tenant eigene Abrechnungsdaten |
| **DSGVO** | Ein Verantwortlicher | Pro Tenant getrennte Verarbeitung |

---

## 2. Ansatz A: Eine Instanz pro Kunde

### 2.1 Architektur

```
┌─────────────────────────────────────────────────────────────┐
│                     Railway / Server                         │
│                                                              │
│  ┌──────────────────┐  ┌──────────────────┐  ┌────────────┐ │
│  │ Instanz A        │  │ Instanz B        │  │ Instanz C  │ │
│  │ (Kunde Acme)     │  │ (Kunde Beta)     │  │ (Kunde C)  │ │
│  │                  │  │                  │  │            │ │
│  │ SQLite: acme.db  │  │ SQLite: beta.db  │  │ ...        │ │
│  │ Bots:            │  │ Bots:            │  │            │ │
│  │  @AcmeFahrGast   │  │  @BetaFahrGast   │  │            │ │
│  │  @AcmeLenker     │  │  @BetaLenker     │  │            │ │
│  │  @AcmeChef       │  │  @BetaChef       │  │            │ │
│  │                  │  │                  │  │            │ │
│  │ Port: 8080       │  │ Port: 8081       │  │            │ │
│  └──────────────────┘  └──────────────────┘  └────────────┘ │
│                                                              │
│         Jede Instanz = eigener Prozess, eigene DB,           │
│         eigene Bot-Tokens, eigene Config                     │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 Vorteile

1. **Perfekte Datenisolation.** Kein Tenant kann versehentlich Daten eines anderen sehen — physikalisch getrennte SQLite-Dateien. Für DSGVO-Art.-32 (Sicherheit der Verarbeitung) die stärkste Garantie.

2. **Keine Code-Änderungen am Datenmodell.** Kein `company_id` Feld nötig, kein Query-Filter. Der gesamte existierende Code (`main.py`, `state_machine.py`, `dispatch.py`, `billing.py`) bleibt unverändert.

3. **Einfaches Onboarding.** Neuer Kunde = neues Deployment. `railway up` mit anderen Environment-Variablen. ~5 Minuten Aufwand.

4. **Unabhängige Updates.** Kunde A kann v0.2.0 laufen, Kunde B v0.3.0 — kein Big-Bang-Migration.

5. **Kostentransparenz.** Jeder Kunde ist eine eigene Instanz mit eigenen Kosten — direkt zurechenbar.

6. **DSGVO-Löschung.** Komplette Datenlöschung eines Kunden: Instanz herunterfahren, SQLite-Datei löschen, fertig. Kein `WHERE company_id = X` in allen Tabellen.

### 2.3 Nachteile

1. **Lineare Kosten.** Railway verlangt ~$5/Monat pro Service. Bei 20 Kunden: $100/Monat. Relativ zu den Einnahmen (Krankentransport-Software kostet 50-200 €/Monat pro Kunde) aber vernachlässigbar.

2. **Operational Overhead.** Jede Instanz muss separat deployed, gemonitored und aktualisiert werden. Bei 50 Kunden 50 Deployments.

3. **Keine Cross-Tenant-Features.** Wenn zwei Unternehmen Fahrer teilen wollen (z.B. bei Ausfällen) — unmöglich in diesem Modell. (Ist das ein reales Szenario? Vermutlich nicht — Krankentransport-Unternehmen sind Konkurrenten.)

4. **Railway-Limits.** Railway hat Service-Limits pro Account. Bei sehr vielen Kunden (50+) könnte das ein Problem werden.

5. **CI/CD-Komplexität.** Ein GitHub Push muss potenziell 50 Deployments triggern. Aber: `railway up --service=acme` ist scriptable.

### 2.4 Betriebskosten-Schätzung

| Kunden | Railway (1 Container/Kunde) | DeepSeek API (shared key) | Whisper (lokal) | Total/Monat |
|--------|----------------------------|---------------------------|-----------------|-------------|
| 1      | $5                         | $2–10                     | $0              | $7–15       |
| 5      | $25                        | $10–50                    | $0              | $35–75      |
| 10     | $50                        | $20–100                   | $0              | $70–150     |
| 20     | $100                       | $40–200                   | $0              | $140–300    |
| 50     | $250                       | $100–500                  | $0              | $350–750    |

*Annahme: Railway Hobby-Plan $5/Service/Monat. Upgrade auf Pro ($20/Service) nur nötig wenn ein einzelner Kunde >50GB Traffic oder >100h CPU.*

Bei einem Kundenpreis von €100–200/Monat ist selbst bei 10 Kunden die Marge noch >50%.

---

## 3. Ansatz B: Mandantenfähige Datenbank

### 3.1 Architektur

```
┌─────────────────────────────────────────────────────────────┐
│                     Railway: EIN Container                   │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              Krankenfahrt Prozess                     │   │
│  │                                                       │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────────────┐   │   │
│  │  │Bot Router│  │Bot Router│  │Bot Router        │   │   │
│  │  │Tenant A  │  │Tenant B  │  │Tenant C ...      │   │   │
│  │  │(@Acme*)  │  │(@Beta*)  │  │(@Gamma*)         │   │   │
│  │  └──────────┘  └──────────┘  └──────────────────┘   │   │
│  │         │              │               │             │   │
│  │         ▼              ▼               ▼             │   │
│  │  ┌──────────────────────────────────────────────┐   │   │
│  │  │         Tenant Middleware                     │   │   │
│  │  │  (extrahiert company_id aus Bot-Token)        │   │   │
│  │  └──────────────────────────────────────────────┘   │   │
│  │         │              │               │             │   │
│  │         ▼              ▼               ▼             │   │
│  │  ┌──────────────────────────────────────────────┐   │   │
│  │  │         SQLite: krankenfahrt.db               │   │   │
│  │  │  ALLE Tabellen mit company_id Spalte          │   │   │
│  │  │  JEDER Query: WHERE company_id = ?            │   │   │
│  │  └──────────────────────────────────────────────┘   │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 Was muss geändert werden?

#### Datenmodell

```python
# NEU: Company Model
class Company(Model):
    id = fields.IntField(pk=True)
    name = fields.CharField(max_length=200)
    tax_id = fields.CharField(max_length=50)
    ik_number = fields.CharField(max_length=50)
    billing_address = fields.TextField()
    created_at = fields.DatetimeField(auto_now_add=True)

# JEDES existierende Model bekommt:
class Patient(Model):
    company: fields.ForeignKeyRelation[Company] = fields.ForeignKeyField(
        "models.Company", related_name="patients"
    )
    telegram_id = fields.BigIntField()  # Unique entfernt — nur innerhalb Tenant unique

class Trip(Model):
    company: fields.ForeignKeyRelation[Company] = fields.ForeignKeyField(...)
    # ...

# Gleiches für: Driver, Vehicle, RecurringTrip, TripEvent
```

#### Tenant Middleware

```python
# Jeder Bot-Callback braucht:
async def tenant_middleware(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot_token = context.bot.token  # Aus dem Telegram Update
    company = await Company.get_or_none(patient_bot_token=bot_token)
    if not company:
        company = await Company.get_or_none(driver_bot_token=bot_token)
    if not company:
        company = await Company.get_or_none(chef_bot_token=bot_token)
    context.user_data["company_id"] = company.id
```

#### Query-Filter auf ALLEN Zugriffen

```python
# VORHER (single-tenant):
drivers = await Driver.filter(active=True)

# NACHHER (multi-tenant):
drivers = await Driver.filter(active=True, company_id=company_id)

# JEDER Query-Pfad muss geändert werden:
# - dispatch.py: 4 queries → +company_id
# - state_machine.py: Trip-Zugriffe → +company_id
# - billing.py: Export → +company_id
# - notification.py: keine Query, aber company-spezifische Templates
# - jeder Bot-Handler: Patient.query → +company_id
```

#### Bot-Token-Management

```python
# Config wird DB-gestützt:
class BotToken(Model):
    company: fields.ForeignKeyRelation[Company]
    bot_type = fields.CharField(max_length=20)  # patient | driver | chef
    token = fields.CharField(max_length=100)
    bot_username = fields.CharField(max_length=100)  # @AcmeFahrGast

# main.py wird dynamisch:
async def build_all_bots():
    tokens = await BotToken.filter().prefetch_related("company")
    apps = []
    for token in tokens:
        app = ApplicationBuilder().token(token.token).build()
        # Routing basierend auf token.company_id
        register_handlers(app, company_id=token.company.id)
        apps.append(app)
    return apps
```

### 3.3 Vorteile

1. **Konstante Betriebskosten.** Ein Deployment, ein Container, ein $5/Monat auf Railway. 1 Kunde oder 50 Kunden — gleicher Preis. (DeepSeek-API-Kosten skalieren natürlich trotzdem.)

2. **Zentrales Management.** Ein Log-Stream, ein Health-Endpoint, ein Deployment-Vorgang. Updates betreffen alle Kunden gleichzeitig.

3. **Einfachere CI/CD.** Ein `railway up` deployed alle Kunden auf einmal.

4. **Cross-Tenant-Features möglich.** Chef-Bot könnte Fahrer-Pool über Unternehmen hinweg sehen (wenn gewünscht). Abrechnungs-Dashboard über alle Kunden.

5. **Datenbank-Optimierung.** Ein SQLite-File, ein Connection-Pool, ein Cache. Effizienter als N getrennte DBs.

### 3.4 Nachteile

1. **Hohe Code-Komplexität.** Jeder Query braucht `company_id` Filter. Vergisst man einen, liest Kunde A die Daten von Kunde B — **Datenschutzverletzung nach DSGVO, meldepflichtig binnen 72h (Art. 33).**

2. **DSGVO-Isolation nur durch Code-Disziplin.** Kein technischer Enforcement-Mechanismus (SQLite hat kein Row-Level-Security wie PostgreSQL). Ein Bug = Datenleck.

3. **Refactoring-Aufwand.** Alle 19 Python-Dateien, 6 Tortoise-Modelle und ~50 Queries müssen angefasst werden. Geschätzt: 3–5 Tage Entwicklungszeit für das Refactoring + 2 Tage Testing.

4. **Keine unabhängigen Deployments.** Ein Bug im Code → alle Kunden betroffen. Ein DB-Corruption → alle Kunden offline.

5. **Löschung kompliziert.** DSGVO Art. 17: Patient will gelöscht werden → muss `WHERE company_id=X AND patient_id=Y` in allen Tabellen. Bei SQLite: `VACUUM` nötig um wirklich freizugeben.

6. **Single Point of Failure.** Ein Container, eine DB-Datei. Fällt das aus, sind ALLE Kunden offline.

7. **Telegram-Rate-Limits.** 3 Bots × N Kunden = 3N gleichzeitige Telegram-Polling-Verbindungen in einem Prozess. Bei 10 Kunden: 30 Verbindungen. Telegram erlaubt ~30 msg/s pro Bot — verteilt, aber der Prozess muss es handlen.

---

## 4. Vergleichsmatrix

| Kriterium | Gewicht | A: Instanz/Kunde | B: Mandantenfähig |
|-----------|---------|-----------------|-------------------|
| **Datenisolation** | Kritisch | ★★★★★ Physikalisch | ★★☆☆☆ Nur Code-Disziplin |
| **DSGVO-Compliance** | Kritisch | ★★★★★ Trivial | ★★☆☆☆ Riskant (SQLite) |
| **Code-Änderungen** | Hoch | ☆☆☆☆☆ Keine | ★☆☆☆☆ Alle Dateien |
| **Betriebskosten (5 Kunden)** | Mittel | ★★★☆☆ $25/Monat | ★★★★★ $5/Monat |
| **Betriebskosten (50 Kunden)** | Niedrig | ★★☆☆☆ $250/Monat | ★★★★★ $5/Monat |
| **Deployment-Aufwand** | Mittel | ★★☆☆☆ N Deployments | ★★★★★ 1 Deployment |
| **Fehler-Isolation** | Hoch | ★★★★★ Bug trifft 1 Kunde | ★☆☆☆☆ Bug trifft alle |
| **Monitoring-Komplexität** | Mittel | ★★☆☆☆ N Health-Checks | ★★★★★ 1 Health-Check |
| **Cross-Tenant Features** | Niedrig | ☆☆☆☆☆ Unmöglich | ★★★★★ Einfach |
| **Onboarding (neuer Kunde)** | Hoch | ★★★★☆ 5 Min | ★★★★★ 1 Min |
| **Langfristige Wartbarkeit** | Hoch | ★★★☆☆ Skaliert linear | ★★★★☆ Konstant |
| **Entwicklungsaufwand jetzt** | — | 0 Tage | 5–7 Tage |

---

## 5. Empfehlung

### 5.1 Kurzfristig (Phase 4–5, 1–10 Kunden): **Ansatz A — Eine Instanz pro Kunde**

**Begründung:**

1. **DSGVO ist der entscheidende Faktor.** Im deutschen Gesundheitswesen (Krankentransport) ist ein Datenleck katastrophal — nicht nur finanziell (Bußgeld bis 20 Mio € oder 4% des Umsatzes), sondern auch existenzbedrohend für das Vertrauen. Physikalische Datenisolation ist der stärkste Schutz.

2. **Entwicklungsaufwand = 0.** Keine Code-Änderungen nötig. Das Team kann sich auf Features konzentrieren (Phase 1–3), statt die Architektur umzubauen.

3. **Kosten sind vernachlässigbar.** Bei einem Kundenpreis von €100–200/Monat und Railway-Kosten von $5/Monat/Kunde beträgt die Infrastruktur-Marge >90%. Erst ab ~50 Kunden ($250/Monat) wird das spürbar — das ist ein Luxusproblem.

4. **Pilot-Tauglichkeit.** Phase 4 beginnt mit 1-2 Pilotkunden. Jeder Kunde kann unabhängig deployed, getestet und ggf. rückabgewickelt werden.

5. **Kein Refactoring-Risiko.** Jede Query-Änderung in Ansatz B ist ein potenzielles Datenleck. Warum das Risiko eingehen, wenn es eine einfachere Lösung gibt?

### 5.2 Mittelfristig (10+ Kunden): **Migration zu Ansatz B**

**Trigger:**
- >10 aktive Kunden oder
- Kosten >10% des Umsatzes oder
- Kunde verlangt Cross-Tenant-Feature (z.B. mehrere Filialen eines Unternehmens)

**Voraussetzungen für Migration:**
1. **PostgreSQL statt SQLite.** PostgreSQL bietet Row-Level-Security (`CREATE POLICY`), das Datenisolation auf DB-Ebene erzwingt — unabhängig von App-Code. SQLite hat das nicht.
2. **Integration-Test-Suite**, die jeden Query-Pfad auf korrekte Tenant-Isolation prüft.
3. **Company-Modell** als FK auf allen Entitäten (dann `RLS USING (company_id = current_setting('app.company_id'))`).

### 5.3 Was jetzt trotzdem vorbereitet werden sollte

Auch wenn Ansatz A gewählt wird, sollte der Code **tenant-ready** geschrieben werden:

1. **`Company`-Modell jetzt anlegen** (als Single-Row mit Default-Werten). Die Config-Werte (`COMPANY_NAME`, `COMPANY_TAX_ID`) aus `config.py` in die DB migrieren. Das macht den Config-Code sauberer und bereitet die spätere Multi-Tenant-Migration vor.

2. **`company_id` FK an alle Modelle, aber optional (`null=True`)**. Im Single-Tenant-Mode ist es immer die eine Company. Die Queries ändern sich nicht. Bei Migration zu Ansatz B wird `null=True` zu `null=False`.

3. **Bot-Tokens in DB statt Environment.** Statt `PATIENT_BOT_TOKEN` Env-Variable → `BotToken`-Modell. Erleichtert das spätere dynamische Bot-Management. (Vorteil sofort: Token-Rotation ohne Neustart)

```python
# Heute: Environment
config.PATIENT_BOT_TOKEN  # Neustart nötig bei Änderung

# Morgen: DB
class BotToken(Model):
    company = fields.ForeignKeyField("models.Company")
    bot_type = fields.CharField(max_length=20)  # patient | driver | chef
    token = fields.CharField(max_length=100)
    username = fields.CharField(max_length=100)

# main.py: dynamisches Bot-Loading
tokens = await BotToken.filter(company_id=company_id, active=True)
```

---

## 6. Bot-Factory: Design

### 6.1 Was ist eine Bot-Factory?

Eine Bot-Factory automatisiert das Erstellen der 3 Telegram-Bots pro Kunde. Heute ist das ein manueller Prozess:
1. @BotFather: `/newbot` → Name, Username → Token
2. Token in Environment-Variable kopieren
3. Deployment neu starten

Die Bot-Factory ersetzt Schritt 2–3 durch automatisierte DB-Speicherung und dynamisches Bot-Loading.

### 6.2 Design (Ansatz A: Instanz-basiert)

In Ansatz A braucht **jede** Instanz ihre eigene Bot-Factory? Nein — die Factory ist das Deployment-Skript selbst.

```bash
# scripts/create-customer.sh
#!/bin/bash
# Usage: ./scripts/create-customer.sh "Acme Transport" "acme"

CUSTOMER_NAME=$1
CUSTOMER_SLUG=$2

echo "=== Creating new Krankenfahrt customer: $CUSTOMER_NAME ==="

# 1. Create Telegram bots via BotFather API (manuell oder via MTProto)
echo "Step 1: Create bots with @BotFather"
echo "  → /newbot"
echo "  → $CUSTOMER_NAME Patient"
echo "  → ${CUSTOMER_SLUG}FahrGast"
echo "  → Copy token → $PATIENT_TOKEN"
echo "  → /newbot"
echo "  → $CUSTOMER_NAME Driver"
echo "  → ${CUSTOMER_SLUG}Lenker"
echo "  → Copy token → $DRIVER_TOKEN"
echo "  → /newbot"
echo "  → $CUSTOMER_NAME Chef"
echo "  → ${CUSTOMER_SLUG}Chef"
echo "  → Copy token → $CHEF_TOKEN"

# 2. Deploy Railway service
echo "Step 2: Deploy to Railway"
railway up \
  --service=${CUSTOMER_SLUG} \
  -e PATIENT_BOT_TOKEN=$PATIENT_TOKEN \
  -e DRIVER_BOT_TOKEN=$DRIVER_TOKEN \
  -e CHEF_BOT_TOKEN=$CHEF_TOKEN \
  -e COMPANY_NAME="$CUSTOMER_NAME" \
  -e DATABASE_URL="sqlite:///data/${CUSTOMER_SLUG}.db"
```

**Automatisierungsgrad:**

| Stufe | Bot-Erstellung | Token-Mgmt | Deployment | Aufwand |
|-------|---------------|------------|------------|---------|
| Heute | Manuell (@BotFather) | Manuell (Env) | Manuell | 15 Min/Kunde |
| Factory v1 | Manuell | Script | Script | 5 Min/Kunde |
| Factory v2 | Automatisch (MTProto) | Script | Script | 1 Min/Kunde |
| Factory v3 | Automatisch | DB | CI/CD | 0 Min (Self-Service) |

**Empfehlung: Factory v1 jetzt bauen, v2 wenn >3 Kunden, v3 als langfristige Vision.**

### 6.3 Design (Ansatz B: Mandantenfähig)

In Ansatz B wäre die Bot-Factory ein **API-Endpoint** im Chef-Bot oder ein Admin-Tool:

```python
# API: POST /api/tenants
{
    "company_name": "Acme Transport",
    "company_slug": "acme",
    "bot_username_prefix": "Acme"  # → @AcmeFahrGast, @AcmeLenker, @AcmeChef
}

# Backend:
# 1. BotToken records in DB anlegen
# 2. Company record anlegen
# 3. Bots dynamisch registrieren (ApplicationBuilder + start)
# 4. Optional: MTProto-Aufruf zum automatischen Bot-Erstellen
```

Das ist das langfristige Ziel — aber erst relevant wenn Ansatz B gewählt wird.

### 6.4 Bot-Naming Convention

```
Muster: {Unternehmens-Präfix}{Rolle}

Patient:  {Praefix}FahrGast    → @AcmeFahrGast, @BetaFahrGast
Driver:   {Praefix}Lenker      → @AcmeLenker, @BetaLenker
Chef:     {Praefix}Chef        → @AcmeChef, @BetaChef
```

Alternativ bei Namenskonflikten: `{Praefix}FahrGastBot`, `{Praefix}KF_Patient`, etc.

---

## 7. Kosten-Implikationen (Detail)

### 7.1 Ansatz A: Break-Even-Analyse

| Szenario | Kunden | Railway/Monat | Infrastruktur/Umsatz | Vorteilhaft? |
|----------|--------|---------------|---------------------|--------------|
| Pilot | 2 | $10 | 5% (bei €100/Kunde) | ✅ Sehr gut |
| Wachstum | 10 | $50 | 5% (bei €100/Kunde) | ✅ Gut |
| Skalierung | 50 | $250 | 5% (bei €100/Kunde) | ✅ Noch gut |
| Enterprise | 200 | $1.000 | 10% (bei €50/Kunde) | ⚠️ Migration prüfen |

**Break-Even für Migration zu Ansatz B:**
- Entwicklungsaufwand Migration: 5–7 Tage × €800/Tag = €4.000–5.600
- Laufende Ersparnis: $5 → $245/Monat bei 50 Kunden
- Amortisation: ~20 Monate bei 50 Kunden
- **Empfehlung: Migration erst ab 30+ Kunden oder wenn Railway-Limits erreicht werden.**

### 7.2 Hidden Costs beider Ansätze

| Kostenfaktor | Ansatz A | Ansatz B |
|-------------|----------|----------|
| Developer Time (initial) | €0 | €4.000–5.600 |
| Developer Time (ongoing) | Low (script fixes) | High (tenant-filter bugs) |
| DSGVO Audit | €500–1.000 (pro Instanz, einfach) | €3.000–5.000 (komplex, alle Queries prüfen) |
| Incident Response | 1 Kunde betroffen → begrenzt | Alle Kunden betroffen → kritisch |
| Onboarding pro Kunde | 5–15 Min | 1 Min |
| Telegram Bot Limits | N/A (getrennte Bots) | 20 Bots/Account (Telegram-Limit!) |

### 7.3 ⚠️ Telegram Bot Creation Limits

Wichtige Einschränkung: **Telegram erlaubt nur ~20 Bots pro Account.** Das betrifft beide Ansätze, aber:

- **Ansatz A:** Jeder Kunde = eigener BotFather-Account? Oder ein zentraler Account der alle Bots erstellt. Bei 20 Kunden (60 Bots) ist das Telegram-Limit erreicht. Lösung: Mehrere BotFather-Accounts oder MTProto-basierte Bot-Erstellung mit eigener App-ID.

- **Ansatz B:** Gleiches Problem. Zentraler Account verwaltet 3N Bots. Bei 10 Kunden = 30 Bots → schon über dem 20er-Limit.

**Dieses Limit macht Ansatz A attraktiver**, weil es die Bot-Erstellung auf verschiedene Accounts/Kunden verteilen kann ("Kunde erstellt seine Bots selbst und gibt uns die Tokens").

---

## 8. Migrationspfad (Zusammenfassung)

```
Phase 4 (Heute):          Phase 5 (10+ Kunden):       Phase 6 (30+ Kunden):
┌──────────────┐          ┌──────────────┐            ┌──────────────┐
│ Ansatz A     │          │ Ansatz A     │            │ Ansatz B     │
│              │          │              │            │              │
│ 1 Instanz    │ ───────→ │ N Instanzen  │ ────────→  │ Mandanten-   │
│ 1 Kunde      │          │ Scripted     │            │ fähige DB    │
│              │          │ Deployment   │            │              │
│ JETZT        │          │              │            │ PostgreSQL   │
│ vorbereiten: │          │ + BotFactory │            │ + RLS        │
│  Company-Mod │          │ + Monitoring │            │ + API Tenant │
│  FK optional │          │ + Templates  │            │   Mgmt       │
└──────────────┘          └──────────────┘            └──────────────┘
```

---

## 9. Umsetzungsplan (A: Jetzt machbare Schritte)

### T4.3a — Company-Modell & Config-Migration [analyst, 1 Tag]

1. `Company`-Modell in `schema.py` anlegen
2. `company_id` FK (optional) an `Patient`, `Driver`, `Vehicle`, `RecurringTrip`, `Trip`, `TripEvent`
3. Config-Werte (`COMPANY_NAME`, `COMPANY_TAX_ID`, etc.) aus `config.py` → `Company` DB-Record
4. Health-Check um `company_id` erwitern (damit Railway-Monitoring Tenant-spezifisch wird)

### T4.3b — BotFactory v1: Deployment-Script [ops, 1 Tag]

1. `scripts/create-customer.sh` (siehe §6.2)
2. `scripts/delete-customer.sh` (Cleanup: Service stoppen, DB löschen)
3. Railway Template für neue Services
4. Dokumentation im README

### T4.3c — Integration Test: Tenant-Isolation [backend-eng, 2 Tage]

1. Test: Patient von Tenant A kann nicht auf Trips von Tenant B zugreifen
2. Test: Driver von Tenant A sieht nur seine Fahrten
3. Test: Billing-Export enthält nur Tenant-Daten
4. Test: DSGVO-Löschung entfernt alle Daten eines Tenants

---

## 10. Appendix: Alternativen, die verworfen wurden

### 10.1 PostgreSQL mit Row-Level-Security (RLS)

Ideal für Ansatz B, aber:
- Railway bietet PostgreSQL nur im Pro-Plan ($20/Monat)
- Oder eigener PG-Server (managed: $15+/Monat)
- SQLite ist explizit gewählt für Einfachheit — PG wäre Overkill bei <10 Kunden

→ **Wiedervorlage bei Ansatz B.**

### 10.2 Schema-per-Tenant (SQLite ATTACH)

```sql
ATTACH DATABASE 'acme.db' AS acme;
SELECT * FROM acme.patients;
```

- SQLite unterstützt `ATTACH`, aber Tortoise ORM nicht
- Jeder Query bräuchte dynamisches Schema-Präfix
- Fehleranfälliger als Ansatz A oder B

→ **Verworfen.**

### 10.3 Telegram Business API (statt Bot API)

Telegram bietet eine Business API für Unternehmen — aber:
- Nur für verifizierte Unternehmen
- Eigener Server nötig (kein `getUpdates` Polling)
- Overkill für 3 Bots

→ **Nicht relevant.**

---

*Ende der Analyse. Nächste Schritte: T4.3a (Company-Modell) zur Vorbereitung, T4.3b (BotFactory) für operational readiness.*
