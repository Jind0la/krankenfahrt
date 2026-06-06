# Krankenfahrt — AI-First Medical Transport Dispatch

**Drei Telegram-Bots ersetzen den menschlichen Disponenten.**

- `@FahrGast` — Patienten: Buchung per Text/Sprachnachricht, Live-Tracking
- `@FahrLenker` — Fahrer: Aufträge annehmen, 1-Tap Status-Updates
- `@FahrtenChef` — Inhaber: Dashboard, Eskalation, Abrechnung

## Warum?

Krankentransport-Unternehmen haben einen strukturellen Flaschenhals: den Disponenten.
Ein Mensch, der in Echtzeit Fahrer zuteilt, Telefone bedient und auf Ausfälle reagiert.
Existierende Software (DMRZ, ZADTools, SanDispo) assistiert — aber ersetzt nicht.

**Unser Ansatz**: KI macht 80% der Disposition autonom. Der Mensch greift nur bei Eskalationen ein.

## Architektur

- **Plattform**: Telegram (keine App-Installation nötig)
- **Sprache**: Python 3.12+, asyncio, ein Prozess
- **Datenbank**: SQLite via Tortoise ORM
- **NLU**: DeepSeek Flash für Buchungs-Extraktion
- **Voice**: faster-whisper (lokal, CPU) für Sprachnachrichten
- **Routing**: Haversine (MVP) → OR-Tools (Phase 2)
- **Deployment**: Railway, ein Container

## Quick Start

```bash
# Install
pip install -e ".[voice]"

# Set tokens
export PATIENT_BOT_TOKEN="..."
export DRIVER_BOT_TOKEN="..."
export CHEF_BOT_TOKEN="..."
export DEEPSEEK_API_KEY="sk-..."

# Run
python -m krankenfahrt.main
```

## Projektstruktur

```
src/krankenfahrt/
├── main.py              # Entry point, 3 Bot Applications
├── config.py            # Environment-based config
├── bots/                # Telegram bot handlers (patient, driver, chef)
├── core/                # Business logic
│   ├── state_machine.py # Trip lifecycle (geplant → abgeschlossen)
│   ├── dispatch.py      # Driver assignment engine
│   ├── notification.py  # Message templates (German)
│   └── billing.py       # CSV/PDF export
├── models/
│   └── schema.py        # Tortoise ORM models (6 tables)
└── services/
    ├── llm.py           # DeepSeek NLU
    ├── voice.py         # faster-whisper transcription
    └── geo.py           # Haversine distance, future OSRM
```

## Docker Deployment

```bash
# Build
docker build -t krankenfahrt -f docker/Dockerfile .

# Run with persistent volume for model cache and database
docker run -d \
  -v krankenfahrt_data:/data \
  -e PATIENT_BOT_TOKEN="..." \
  -e DRIVER_BOT_TOKEN="..." \
  -e CHEF_BOT_TOKEN="..." \
  -e DEEPSEEK_API_KEY="sk-..." \
  -p 8000:8000 \
  krankenfahrt
```

### Whisper Model Caching

On first start, the entrypoint script downloads the faster-whisper model (~1-3 GB) to
`/data/models/whisper`. Subsequent restarts detect the cached model and skip the download.

The model is stored on the persistent `/data` volume, so it survives container restarts.
No network activity for model download on subsequent starts.

**Configuration:**

| Env Var | Default | Description |
|---|---|---|
| `WHISPER_MODEL` | `small` | Model size: tiny, base, small, medium, large-v3 |
| `WHISPER_CACHE_DIR` | `/data/models/whisper` | Persistent cache directory |
| `WHISPER_DEVICE` | `cpu` | Device: cpu, cuda, auto |

### Pre-caching Models (Optional)

To pre-cache a model without starting the full application:

```bash
docker run --rm \
  -v krankenfahrt_data:/data \
  -e WHISPER_MODEL=small \
  krankenfahrt \
  python3 -c "
from faster_whisper import WhisperModel
m = WhisperModel('small', device='cpu', compute_type='int8', download_root='/data/models/whisper')
print('Model cached.')
"
```

## Lizenz

MIT
