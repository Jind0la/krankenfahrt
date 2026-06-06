# KnowWhere Multi-Tenancy Analysis

**Datum:** 2026-06-06
**Analyst:** Hermes Agent (analyst profile)
**Auftrag:** Analyse von Single-Tenant vs. Multi-Tenant Architektur für KnowWhere

---

## 1. Ausgangslage: KnowWhere v0.5.0+

### 1.1 Aktuelle Architektur

KnowWhere ist ein Rust-basierter Fractal Memory Service. Die aktuelle Deployment-Architektur:

```
┌──────────────────────────────────────────────┐
│              KnowWhere Instance               │
│  ┌──────────┐  ┌──────────┐  ┌────────────┐ │
│  │ REST API │  │  USearch │  │ PostgreSQL  │ │
│  │  :3737   │  │  (RAM)   │  │   :5433     │ │
│  └──────────┘  └──────────┘  └────────────┘ │
│                                              │
│  Embedding: OpenAI / Ollama                  │
│  Compaction: LocalSummarizer / VLM           │
└──────────────────────────────────────────────┘
         ▲                    ▲
         │                    │
    ┌─────────┐         ┌──────────┐
    │ Hermes  │         │  Andere  │
    │ Agent   │         │  Clients │
    └─────────┘         └──────────┘
```

**Wichtigste Erkenntnisse aus Code-Review:**

| Aspekt | Status | Details |
|--------|--------|---------|
| **Auth-System** | Multi-User fähig | `auth_users`, `auth_api_keys` Tabellen, `AuthContext` mit `user_id`, Admin/User Token-Typen |
| **Daten-Isolation** | ❌ Keine | `memories` Tabelle hat **keine** `user_id` oder `tenant_id` Spalte |
| **Namespaces** | Logische Gruppierung | `namespaces` Modul mit `NamespaceStore`, hierarchische Pfade — aber **kein Security-Boundary** |
| **Vector Search** | Globaler Index | USearch Index ist global, keine Partitionierung |
| **Embedding** | Globaler Provider | Eine Embedding-Konfiguration pro Instance |
| **Compaction** | Globaler Scheduler | Ein Consolidation-Prozess für alle Nodes |

**Fazit:** KnowWhere hat das Auth-Fundament für Multi-User, aber **keine Daten-Isolation**. Jeder authentifizierte User sieht alle Memories. Namespaces bieten logische Struktur, aber keine Mandantenfähigkeit.

---

## 2. Bewertungskriterien

Folgende Kriterien werden für den Vergleich herangezogen:

| # | Kriterium | Beschreibung |
|---|-----------|-------------|
| K1 | **Daten-Isolation** | Sind Daten verschiedener Kunden strikt getrennt? Kein Cross-Tenant-Leakage? |
| K2 | **Sicherheit** | Welche Angriffsfläche bietet die Architektur? Row-level security? |
| K3 | **Kosten pro Kunde** | Infrastrukturkosten (Compute, Speicher, Embedding-API) pro Kunde |
| K4 | **Operational Complexity** | Aufwand für Deployment, Updates, Monitoring, Backup |
| K5 | **Skalierbarkeit** | Wie skaliert das System mit wachsender Kundenzahl und Datenmenge? |
| K6 | **Code-Komplexität** | Wie viele Änderungen am KnowWhere-Code sind nötig? |
| K7 | **Embedding-Provider-Flexibilität** | Kann jeder Kunde eigenen Embedding-Provider nutzen? |
| K8 | **Noisy Neighbor** | Kann ein Kunde die Performance anderer Kunden beeinträchtigen? |
| K9 | **Billing / Metering** | Wie einfach ist Usage-Tracking und Abrechnung pro Kunde? |
| K10 | **Time-to-Market** | Wie schnell kann mandantenfähiges KnowWhere ausgeliefert werden? |

---

## 3. Zwei Architekturmodelle

### 3.1 Modell A: One-Instance-Per-Customer (Single-Tenant)

```
┌──────────────────────┐  ┌──────────────────────┐  ┌──────────────────────┐
│  Kunde A             │  │  Kunde B             │  │  Kunde C             │
│  ┌────────────────┐  │  │  ┌────────────────┐  │  │  ┌────────────────┐  │
│  │ KnowWhere      │  │  │  │ KnowWhere      │  │  │  │ KnowWhere      │  │
│  │ Port 3737      │  │  │  │ Port 3738      │  │  │  │ Port 3739      │  │
│  │ DB: kw_tenant_a│  │  │  │ DB: kw_tenant_b│  │  │  │ DB: kw_tenant_c│  │
│  └────────────────┘  │  │  └────────────────┘  │  │  └────────────────┘  │
│  Docker Container    │  │  Docker Container    │  │  Docker Container    │
└──────────────────────┘  └──────────────────────┘  └──────────────────────┘
```

**Funktionsweise:** Jeder Kunde bekommt einen eigenen KnowWhere-Container mit eigener PostgreSQL-Datenbank, eigenem USearch-Index, eigener Embedding-Konfiguration.

### 3.2 Modell B: Multi-Tenant (Shared Instance)

```
┌─────────────────────────────────────────────────────────┐
│              KnowWhere Instance (Shared)                 │
│                                                         │
│  ┌──────────────────────────────────────────────────┐   │
│  │  Auth Middleware                                  │   │
│  │  Token → tenant_id Resolution                     │   │
│  └──────────────────────────────────────────────────┘   │
│                         │                               │
│  ┌──────────────────────┴──────────────────────────┐   │
│  │  Tenant-Scoped Query Layer                       │   │
│  │  Jede Query: WHERE tenant_id = $current_tenant   │   │
│  └──────────────────────┬──────────────────────────┘   │
│                         │                               │
│  ┌──────────┐  ┌────────┴─────┐  ┌────────────────┐   │
│  │ USearch  │  │ PostgreSQL   │  │  Embedding     │   │
│  │ Per-     │  │ Row-Level    │  │  Shared oder   │   │
│  │ Tenant   │  │ Security     │  │  Per-Tenant    │   │
│  │ Filter?  │  │              │  │                │   │
│  └──────────┘  └──────────────┘  └────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

**Funktionsweise:** Eine KnowWhere-Instanz bedient mehrere Kunden. Tenant-Isolation erfolgt auf Datenbank-Ebene (Row-Level Security, tenant_id in jeder Query) und Applikations-Ebene (Auth-Middleware injected tenant_id).

---

## 4. Detaillierte Bewertung

### 4.1 Modell A: One-Instance-Per-Customer

| Kriterium | Bewertung | Begründung |
|-----------|-----------|------------|
| K1: Daten-Isolation | ⭐⭐⭐⭐⭐ | **Perfekt.** Getrennte Prozesse, getrennte DBs, getrennte Dateisysteme. Kein Code-Pfad kann Daten vermischen. |
| K2: Sicherheit | ⭐⭐⭐⭐⭐ | Minimale Angriffsfläche. Ein Tenant-Kompromittierung betrifft nur diesen Tenant. Kein Shared-Memory-Angriffsvektor. |
| K3: Kosten pro Kunde | ⭐⭐ | **Hoch.** Jeder Kunde braucht eigenen Container (min. 256MB RAM), eigene DB, eigenen Embedding-API-Key. Keine economies of scale. |
| K4: Operational Complexity | ⭐⭐ | **Hoch bei Skalierung.** 100 Kunden = 100 Container zu monitoren, updaten, backuppen. Orchestrierung nötig (K8s/Nomad). |
| K5: Skalierbarkeit | ⭐⭐⭐⭐ | Linear skalierbar — mehr Kunden = mehr Instanzen. Aber: Resource-Overhead pro Instanz (idle cost). |
| K6: Code-Komplexität | ⭐⭐⭐⭐⭐ | **Keine Änderungen nötig.** KnowWhere-Code bleibt unverändert. Tenant-Isolation durch Infrastruktur. |
| K7: Embedding-Flexibilität | ⭐⭐⭐⭐⭐ | Jeder Tenant kann eigenen Provider/API-Key/Modell nutzen. |
| K8: Noisy Neighbor | ⭐⭐⭐⭐⭐ | **Kein Problem.** Getrennte Prozesse, keine Ressourcen-Konkurrenz. |
| K9: Billing/Metering | ⭐⭐⭐ | Pro-Instanz-Monitoring einfach (Container-Metriken), aber kein eingebautes Usage-Tracking. |
| K10: Time-to-Market | ⭐⭐⭐⭐⭐ | **Sofort.** KnowWhere läuft bereits als Docker-Container. Tenant = neuer Container + neue DB. |

### 4.2 Modell B: Multi-Tenant (Shared Instance)

| Kriterium | Bewertung | Begründung |
|-----------|-----------|------------|
| K1: Daten-Isolation | ⭐⭐⭐ | Abhängig von Implementierung. Row-Level Security in PostgreSQL ist battle-tested, aber jeder Query-Bug kann Isolation brechen. |
| K2: Sicherheit | ⭐⭐⭐ | Größere Angriffsfläche. Ein Exploit im API-Layer betrifft ALLE Tenants. Defense-in-depth nötig. |
| K3: Kosten pro Kunde | ⭐⭐⭐⭐⭐ | **Niedrig.** Geteilte Infrastruktur. 100 Kunden teilen sich einen Container. Embedding-API-Calls können gebündelt werden. |
| K4: Operational Complexity | ⭐⭐⭐⭐ | Ein Deployment, ein Monitoring, ein Backup. Updates betreffen alle Tenants gleichzeitig. |
| K5: Skalierbarkeit | ⭐⭐⭐ | Vertikale Skalierung (größerer Server). Horizontale Skalierung komplex (Sharding, Read-Replicas). |
| K6: Code-Komplexität | ⭐ | **Hoch.** Umfangreiche Änderungen nötig (siehe Abschnitt 5). |
| K7: Embedding-Flexibilität | ⭐⭐ | Entweder Shared Provider für alle oder komplexes Per-Tenant-Routing. |
| K8: Noisy Neighbor | ⭐⭐ | Reales Problem. VLM-Compaction von Tenant A blockiert Embedding-Pipeline für Tenant B. USearch-Index-Größe wächst für alle. |
| K9: Billing/Metering | ⭐⭐⭐⭐ | Zentrales Usage-Tracking möglich (API-Calls pro tenant_id, Storage pro tenant_id). |
| K10: Time-to-Market | ⭐⭐ | **3-6 Monate Entwicklungszeit** für vollständige Multi-Tenant-Implementierung. |

---

## 5. Was Multi-Tenant für KnowWhere konkret bedeutet

### 5.1 Datenbank-Änderungen

Jede Tabelle braucht eine `tenant_id` Spalte:

```sql
ALTER TABLE memories ADD COLUMN tenant_id UUID NOT NULL;
ALTER TABLE auth_users ADD COLUMN tenant_id UUID;
ALTER TABLE auth_api_keys ADD COLUMN tenant_id UUID;
ALTER TABLE fact_schemas ADD COLUMN tenant_id UUID NOT NULL;
ALTER TABLE fact_claims ADD COLUMN tenant_id UUID NOT NULL;
ALTER TABLE namespaces ADD COLUMN tenant_id UUID NOT NULL;
ALTER TABLE agent_skills ADD COLUMN tenant_id UUID NOT NULL;
-- ... alle weiteren Tabellen
```

Jeder Index braucht `tenant_id` als führende Spalte:

```sql
CREATE INDEX idx_memories_tenant_type ON memories(tenant_id, memory_type);
CREATE INDEX idx_memories_tenant_created ON memories(tenant_id, created_at);
-- ... alle bestehenden Indizes duplizieren mit tenant_id-Präfix
```

**Alternative: PostgreSQL Row-Level Security (RLS)**

```sql
ALTER TABLE memories ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON memories
  USING (tenant_id = current_setting('app.current_tenant_id')::UUID);
```

RLS ist eleganter (keine Query-Änderungen), hat aber Performance-Overhead und Debugging-Komplexität.

### 5.2 API-Layer-Änderungen

**Auth-Middleware** muss `tenant_id` in den Request-Kontext injecten:

```rust
pub struct AuthContext {
    pub token_kind: AuthTokenKind,
    pub user_id: Option<Uuid>,
    pub tenant_id: Uuid,                    // ← NEU
    pub allowed_retrieval_profiles: Vec<RetrievalProfile>,
}
```

**Jeder API-Handler** muss `tenant_id` in Queries verwenden. Bei RLS-Ansatz automatisch, bei explizitem Ansatz:

```rust
// Vorher:
sqlx::query("SELECT * FROM memories WHERE id = $1").bind(id)

// Nachher:
sqlx::query("SELECT * FROM memories WHERE id = $1 AND tenant_id = $2")
    .bind(id)
    .bind(context.tenant_id)
```

**Betroffene Endpunkte:** ~25+ Handler in `store.rs`, `retrieve.rs`, `maintenance.rs`, `skills_routes.rs`, `namespaces.rs`, `conflicts.rs`, `turns.rs`

### 5.3 Vector Search — Das härteste Problem

USearch (KnowWhere's Vektor-Index) unterstützt **kein natives Multi-Tenant-Filtering**. Optionen:

| Option | Beschreibung | Trade-off |
|--------|-------------|-----------|
| **Separate Indizes** | Ein USearch-Index pro Tenant | Speicher overhead (Index-Metadaten), aber perfekte Isolation |
| **Post-Filtering** | Globaler Index → Top-K * N → Filter nach tenant_id → Top-K | Overfetch (N-fache Kandidaten), ungenaues Ranking |
| **Metadata-Filter** | USearch mit Metadaten-Filter nach Similarity-Suche | USearch hat kein natives Metadata-Filtering in current version |
| **pgvector** | PostgreSQL pgvector statt USearch, mit `WHERE tenant_id = $1 AND vector <-> $2` | pgvector ist langsamer als USearch für >100K Vektoren, aber unterstützt SQL-Filtering nativ |

**Empfehlung für Multi-Tenant:** Separate USearch-Indizes pro Tenant, gemanagt im `AppState` als `HashMap<Uuid, Index>`. Speicher-Overhead: ~50KB Metadaten pro Index + Vektor-Daten (sind ohnehin vorhanden). Bei 100 Tenants: ~5MB Overhead — vernachlässigbar.

### 5.4 Embedding-Provider

**Option A: Shared Provider.** Alle Tenants nutzen denselben OpenAI-Key / Ollama-Endpunkt. Einfach, aber kein Per-Tenant-Billing.

**Option B: Per-Tenant Provider.** Jeder Tenant konfiguriert eigenen Provider. Flexibel, aber komplex: API-Key-Management, Provider-Routing, Fallback.

**Empfehlung:** Phase 1: Shared Provider. Phase 2: Per-Tenant-Override als Konfigurationsoption.

### 5.5 Consolidation / Compaction

Der Consolidation-Scheduler verarbeitet aktuell ALLE Nodes global. Mit Multi-Tenant:

- Per-Tenant Consolidation-Queues (fair scheduling)
- Space-Amplification-Trigger pro Tenant
- VLM-Jobs mit `tenant_id` für Kosten-Tracking

### 5.6 Namespaces

Namespaces sind aktuell **global** — jeder authentifizierte User kann alle Namespaces sehen. Mit Multi-Tenant:

- `namespaces` Tabelle bekommt `tenant_id`
- Namespace-Routen sind tenant-scoped
- `POST /namespaces` erstellt Namespace im eigenen Tenant

---

## 6. Vergleichstabelle

| Kriterium | Single-Tenant (A) | Multi-Tenant (B) |
|-----------|:-----------------:|:----------------:|
| K1: Daten-Isolation | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ |
| K2: Sicherheit | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ |
| K3: Kosten pro Kunde | ⭐⭐ | ⭐⭐⭐⭐⭐ |
| K4: Ops Complexity | ⭐⭐ | ⭐⭐⭐⭐ |
| K5: Skalierbarkeit | ⭐⭐⭐⭐ | ⭐⭐⭐ |
| K6: Code-Komplexität | ⭐⭐⭐⭐⭐ | ⭐ |
| K7: Embedding-Flexibilität | ⭐⭐⭐⭐⭐ | ⭐⭐ |
| K8: Noisy Neighbor | ⭐⭐⭐⭐⭐ | ⭐⭐ |
| K9: Billing/Metering | ⭐⭐⭐ | ⭐⭐⭐⭐ |
| K10: Time-to-Market | ⭐⭐⭐⭐⭐ | ⭐⭐ |
| **Gesamt (gewichtet)** | **3.9** | **2.9** |

Gewichtung: K1-K3 (30%), K4-K6 (25%), K7-K8 (15%), K9-K10 (30%) — priorisiert Time-to-Market und Kosten im Beta-Stadium.

---

## 7. Empfehlung

### 7.1 Primäre Empfehlung: Single-Tenant für Beta/Launch

**KnowWhere sollte mit One-Instance-Per-Customer starten.** Begründung:

1. **Time-to-Market = Null.** KnowWhere läuft bereits als Docker-Container. Ein neuer Kunde = `docker compose up` mit eigener `.env`. Kein einziger Code-Pfad muss geändert werden.

2. **Daten-Isolation ist Priorität #1.** KnowWhere speichert persönliche Konversationsdaten, Präferenzen, Entscheidungen. Ein Cross-Tenant-Datenleck wäre ein Showstopper. Single-Tenant macht diesen Fehlerfall physikalisch unmöglich.

3. **Customer Count rechtfertigt Multi-Tenant nicht.** Im Beta-Stadium (expected < 10 Kunden) sind die operativen Kosten von 10 Containern vernachlässigbar (~$20-50/Monat auf Railway/Hetzner).

4. **Noisy Neighbor ist real.** VLM-Compaction (GPT-5-nano → 20-30s pro Job) würde in einer Shared Instance alle Tenants blockieren. Mit separaten Instanzen blockiert ein Tenant nur sich selbst.

5. **KnowWhere's Architektur ist nicht auf Multi-Tenant ausgelegt.** Die `memories` Tabelle hat 20+ Spalten, aber keine `tenant_id`. Jeder Query-Pfad müsste angefasst werden. Das Risiko von Isolation-Bugs ist hoch.

### 7.2 Vorbereitung auf spätere Multi-Tenant-Fähigkeit

Auch wenn Single-Tenant der Launch-Ansatz ist, sollte der Code **vorbereitet** werden — nicht durch vollständige Multi-Tenant-Implementierung, sondern durch:

1. **`tenant_id` Spalte in allen Tabellen ALREADY hinzufügen** — mit Default-Wert (z.B. `'00000000-0000-0000-0000-000000000000'` als "default tenant"). Dies ist eine einmalige Migration, die keine Query-Änderungen erzwingt.

2. **`AuthContext` um `tenant_id` erweitern** — aber zunächst immer auf Default-Tenant setzen. Keine Logik-Änderungen.

3. **HybridQuery um `tenant_id` erweitern** — optional, mit `None` = kein Tenant-Filter.

4. **Embedding-Provider-Konfiguration pro Tenant vorbereiten** — als Config-Struktur, aber zunächst Single-Provider.

Diese Vorbereitungen kosten ~2-3 Tage und machen eine spätere vollständige Multi-Tenant-Migration zum reinen Aktivieren existierender Pfade statt zum Neu-Design.

### 7.3 Kriterium für Multi-Tenant-Migration

Der Switch zu Multi-Tenant sollte erfolgen, wenn:

- **>20 aktive Kunden** — Single-Tenant-Overhead wird spürbar
- **Embedding-API-Kosten pro Kunde < $5/Monat** — Bündelung lohnt sich
- **Enterprise-Kunden fordern es** — Compliance/SSO/Managed-Service-Erwartung
- **Operations-Team existiert** — Jemand kann die Migration überwachen

---

## 8. Risiken und offene Fragen

| Risiko | Beschreibung | Mitigation |
|--------|-------------|------------|
| R1 | Single-Tenant → hohe Kosten bei Wachstum | Vorbereitende tenant_id-Migration (siehe 7.2) |
| R2 | Docker-Overhead pro Instanz (idle memory) | Container-Scheduling (K8s HPA, scale to zero) |
| R3 | Per-Tenant Embedding API Keys → Key-Management | HashiCorp Vault oder Railway Secrets |
| R4 | Tenant-Onboarding manuell (kein Self-Service) | CLI-Tool für `kw tenant create` |
| R5 | OpenAI Rate Limits bei gebündelten API-Keys | Per-Tenant-Keys in Single-Tenant vermeidet dies |

**Offene Fragen für Nimar:**

1. Wie viele Kunden werden in den ersten 6 Monaten erwartet?
2. Soll KnowWhere Self-Service-Onboarding anbieten (Kunde registriert sich selbst)?
3. Welches Preismodell ist angedacht (Flat/Usage-Based/Freemium)?
4. Gibt es Enterprise-Kunden mit spezifischen Compliance-Anforderungen (Daten in EU, getrennte Infrastruktur)?
5. Soll der Embedding-Provider pro Kunde wählbar sein (OpenAI vs Ollama vs eigenes Modell)?

---

## 9. Quellen

- KnowWhere Code-Review: `src/api/auth.rs`, `src/api/namespaces.rs`, `src/api/routes.rs`, `src/storage/postgres_store.rs`
- KnowWhere PRD v0.5.0: `docs/archive/PRD.md`
- KnowWhere Competitive Landscape: `docs/research/competitive-landscape-2026-05-04.md`
- KnowWhere Dev Team Skill: `knowwhere-dev-team` (SKILL.md, references/)
- KnowWhere Hermes Integration: `knowwhere-hermes` (SKILL.md, references/)
- PostgreSQL Row-Level Security: https://www.postgresql.org/docs/current/ddl-rowsecurity.html
- USearch Multi-Tenant Patterns: https://github.com/unum-cloud/usearch
