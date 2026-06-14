# Planara Plugin — Architecture Diagrams

## 1. High-Level System Topology

The plugin is a **hybrid Ruby + Python** system. SketchUp only speaks Ruby, so a thin Ruby shell extracts geometry and forwards it over localhost HTTP to a Python sidecar that does all the heavy compliance work.

```mermaid
graph TB
    subgraph SketchUp["🏗️ SketchUp Process (Ruby)"]
        direction TB
        Boot["boot.rb<br/>Extension registration & menus"]
        Observers["observers/<br/>Model · Entities · Tools"]
        Extractor["geometry/extractor.rb<br/>SketchUp API → JSON snapshot"]
        Client["engine_client.rb<br/>HTTP client + JWT header"]
        Supervisor["engine_supervisor.rb<br/>Spawn / healthcheck / stop"]
        UI["ui/<br/>Login · Results · History · ProjectPicker"]
        Session["session.rb<br/>JWT storage"]
        Config["config.rb<br/>Engine URL, paths"]
    end

    subgraph Engine["⚙️ Python Sidecar (FastAPI / Uvicorn)"]
        direction TB
        API["api/<br/>FastAPI routers"]
        Auth["auth/<br/>bcrypt · JWT · user store"]
        Domain["domain/<br/>Pydantic schemas"]
        Rules["rules/<br/>JSON rule packs + loader"]
        RuleEngine["engine/<br/>Rule selection & dispatch"]
        Compliance["compliance/<br/>FSI · Setback · Coverage · Height · Parking · Lift"]
        Geometry["geometry/<br/>Shapely polygon ops"]
        Reporting["reporting/<br/>HTML · Diff · Archive"]
        Persistence["persistence/<br/>SQLite via SQLModel"]
        Core["core/<br/>Settings · Logging · Errors"]
    end

    subgraph Storage["💾 Storage"]
        DB[("planara.db<br/>SQLite")]
        RulePacks["rules/packs/<br/>bangalore-v1.0.json"]
    end

    Boot --> Supervisor
    Supervisor -->|spawns| Engine
    Observers -->|geometry changed| Extractor
    Extractor -->|JSON snapshot| Client
    Client <-->|"HTTP/JSON<br/>localhost:port"| API
    API --> Auth
    API --> RuleEngine
    API --> Reporting
    RuleEngine --> Rules
    RuleEngine --> Compliance
    Compliance --> Geometry
    Reporting --> Persistence
    Persistence --> DB
    Rules --> RulePacks
    Client --> Session
    Client --> UI

    style SketchUp fill:#1e293b,stroke:#3b82f6,stroke-width:2px,color:#e2e8f0
    style Engine fill:#1e293b,stroke:#10b981,stroke-width:2px,color:#e2e8f0
    style Storage fill:#1e293b,stroke:#f59e0b,stroke-width:2px,color:#e2e8f0
```

---

## 2. Ruby Plugin — Module Breakdown

```mermaid
graph LR
    subgraph Plugin["planara_plugin/planara/"]
        Boot["boot.rb<br/>━━━━━━━━━━━━<br/>• Extension registration<br/>• Menu items (8+)<br/>• Lifecycle orchestration<br/>• Live compliance toggle"]
        Sup["engine_supervisor.rb<br/>━━━━━━━━━━━━<br/>• Spawn uvicorn process<br/>• Poll /health until ready<br/>• SIGTERM → SIGKILL on exit"]
        EC["engine_client.rb<br/>━━━━━━━━━━━━<br/>• POST /validate<br/>• POST /auth/login<br/>• POST /reports, /history<br/>• GET /history, /history/{id}/diff<br/>• JWT header injection<br/>• Retry logic"]
        Ext["geometry/extractor.rb<br/>━━━━━━━━━━━━<br/>• Sketchup::Model traversal<br/>• Floor detection<br/>• Plot polygon extraction<br/>• Unit conversion → meters"]
        Units["geometry/units.rb<br/>━━━━━━━━━━━━<br/>• SketchUp unit helpers"]
        Obs["observers/live_validator.rb<br/>━━━━━━━━━━━━<br/>• EntitiesObserver<br/>• Debounced validate calls"]
        Sess["session.rb<br/>━━━━━━━━━━━━<br/>• JWT token storage<br/>• Classification/zone state<br/>• Login state management"]
        Conf["config.rb<br/>━━━━━━━━━━━━<br/>• PLANARA_ENGINE_URL<br/>• Path resolution"]
        Log["logger.rb<br/>━━━━━━━━━━━━<br/>• Timestamped file logging"]
        Upd["update_checker.rb<br/>━━━━━━━━━━━━<br/>• Version check on startup"]
    end

    subgraph UILayer["planara_plugin/planara/ui/"]
        Login["login_dialog.rb<br/>HtmlDialog for auth"]
        Results["results_dialog.rb<br/>Live violation display"]
        History["history_dialog.rb<br/>Browse saved reports"]
        Picker["project_picker.rb<br/>Classification + zone selector"]
        Browser["browser_view.rb<br/>Open HTML reports externally"]
    end

    Boot --> Sup
    Boot --> EC
    Boot --> Obs
    Boot --> Sess
    Boot --> UILayer
    EC --> Ext
    EC --> Sess
    Obs --> EC

    style Plugin fill:#0f172a,stroke:#3b82f6,stroke-width:2px,color:#e2e8f0
    style UILayer fill:#0f172a,stroke:#8b5cf6,stroke-width:2px,color:#e2e8f0
```

---

## 3. Python Engine — Module Breakdown

```mermaid
graph TB
    subgraph APILayer["api/"]
        App["app.py — FastAPI app factory"]
        Health["routes_health.py — GET /health"]
        AuthR["routes_auth.py — POST /auth/*"]
        Validate["routes_validate.py — POST /validate"]
        Reports["routes_reports.py — POST /reports"]
        HistoryR["routes_history.py — GET/POST /history, diff"]
        Projects["routes_projects.py — CRUD projects"]
        Middleware["middleware.py — request-id, logging"]
        Errors["errors.py — exception handlers"]
    end

    subgraph DomainLayer["domain/"]
        Snapshot["snapshot.py"]
        Plot["plot.py"]
        Building["building.py"]
        ProjCtx["project_context.py"]
        Violation["violation.py"]
        Geom["geometry.py"]
    end

    subgraph RulesLayer["rules/"]
        Schema["schema.py — Rule model"]
        Loader["loader.py — Load packs"]
        Packs["packs/bangalore-v1.0.json"]
    end

    subgraph EngineLayer["engine/"]
        RE["RuleEngine<br/>Select applicable rules<br/>Dispatch to evaluators<br/>Aggregate violations"]
    end

    subgraph ComplianceLayer["compliance/"]
        FSI["fsi.py"]
        Setback["setback.py"]
        Coverage["coverage.py"]
        Height["height.py"]
        RoomH["room_height.py"]
        Parking["parking.py"]
        Lift["lift_required.py"]
        Params["params.py"]
    end

    subgraph GeometryLayer["geometry/"]
        Poly["Shapely polygon ops<br/>offset · union · intersection · area"]
    end

    subgraph ReportingLayer["reporting/"]
        Archive["archive.py"]
        Diff["diff.py"]
        DiffHTML["diff_html.py"]
        HTMLRend["html_renderer.py"]
    end

    subgraph PersistenceLayer["persistence/"]
        Database["database.py — SQLite engine"]
        Models["models.py — SQLModel tables"]
        ReportsRepo["reports.py — Report CRUD"]
        ProjectsRepo["projects.py — Project CRUD"]
        Repo["repository.py — Base"]
    end

    subgraph CoreLayer["core/"]
        Settings["Settings · Logging · Errors"]
    end

    Validate --> RE
    RE --> Loader
    Loader --> Packs
    RE --> ComplianceLayer
    ComplianceLayer --> Poly
    HistoryR --> ReportingLayer
    ReportingLayer --> PersistenceLayer
    PersistenceLayer --> Database
    AuthR --> CoreLayer

    style APILayer fill:#064e3b,stroke:#10b981,stroke-width:2px,color:#e2e8f0
    style DomainLayer fill:#1e1b4b,stroke:#818cf8,stroke-width:2px,color:#e2e8f0
    style RulesLayer fill:#78350f,stroke:#f59e0b,stroke-width:2px,color:#e2e8f0
    style EngineLayer fill:#7f1d1d,stroke:#ef4444,stroke-width:2px,color:#e2e8f0
    style ComplianceLayer fill:#4c1d95,stroke:#a78bfa,stroke-width:2px,color:#e2e8f0
    style GeometryLayer fill:#164e63,stroke:#22d3ee,stroke-width:2px,color:#e2e8f0
    style ReportingLayer fill:#3f3f46,stroke:#a1a1aa,stroke-width:2px,color:#e2e8f0
    style PersistenceLayer fill:#1c1917,stroke:#d6d3d1,stroke-width:2px,color:#e2e8f0
    style CoreLayer fill:#1e293b,stroke:#64748b,stroke-width:2px,color:#e2e8f0
```

---

## 4. Data Flow — Validation Pipeline

This is the core flow: user edits geometry in SketchUp → violations appear in real time.

```mermaid
sequenceDiagram
    actor User as 👤 Architect
    participant SU as SketchUp
    participant Obs as LiveValidator Observer
    participant Ext as GeometryExtractor
    participant Client as EngineClient
    participant API as FastAPI /validate
    participant RE as RuleEngine
    participant Rules as Rule Packs
    participant Comp as Compliance Evaluators
    participant Geo as Shapely Geometry
    participant UI as Results Dialog

    User->>SU: Edit geometry (move wall, add floor)
    SU->>Obs: onChangeEntity / onElementAdded
    Note over Obs: Debounce (500ms)
    Obs->>Ext: snapshot(model)
    Ext->>Ext: Traverse faces, detect floors,<br/>extract plot polygon, convert to meters
    Ext-->>Client: JSON snapshot
    Client->>API: POST /validate<br/>Authorization: Bearer JWT
    API->>RE: evaluate(snapshot)
    RE->>Rules: load applicable rules<br/>(city + classification + zone)
    Rules-->>RE: matched rules[]
    
    loop For each rule
        RE->>Comp: evaluator(snapshot, params)
        Comp->>Geo: polygon offset / area / union
        Geo-->>Comp: computed values
        Comp-->>RE: pass | violation
    end

    RE-->>API: ValidationResponse
    API-->>Client: JSON response
    Client-->>UI: show_results(violations)
    UI-->>User: 🔴 FSI exceeds limit 2.5<br/>🟡 Side setback 1.2m < 1.5m required
```

---

## 5. API Surface

```mermaid
graph LR
    subgraph Routes["FastAPI Route Map"]
        H["GET /health<br/>Engine status check"]
        A1["POST /auth/register<br/>Create user account"]
        A2["POST /auth/login<br/>Returns JWT token"]
        V["POST /validate<br/>Core compliance check"]
        R1["POST /reports<br/>Stateless report render"]
        R2["GET /reports/html<br/>HTML report view"]
        H1["POST /history<br/>Save validation + persist"]
        H2["GET /history<br/>List saved reports (paginated)"]
        H3["GET /history/{id}<br/>Full archived report"]
        H4["GET /history/{id}/diff<br/>Auto-diff vs. prior run"]
        H5["GET /history/diff?from=X&to=Y<br/>Explicit two-report diff"]
        H6["GET /history/{id}/html<br/>HTML view of saved report"]
        H7["GET /history/{id}/diff/html<br/>HTML diff view"]
        P1["POST /projects<br/>Create project"]
        P2["GET /projects<br/>List projects"]
        P3["GET /projects/{id}<br/>Get project"]
        P4["PATCH /projects/{id}<br/>Update project"]
    end

    subgraph Auth["🔒 Auth Required"]
        V
        R1
        R2
        H1
        H2
        H3
        H4
        H5
        H6
        H7
        P1
        P2
        P3
        P4
    end

    style Routes fill:#0f172a,stroke:#3b82f6,stroke-width:2px,color:#e2e8f0
    style Auth fill:#7f1d1d,stroke:#ef4444,stroke-width:1px,color:#fca5a5
```

---

## 6. Rule Engine Pipeline

```mermaid
flowchart TD
    Snap["📐 Incoming Snapshot<br/>city: Bangalore<br/>classification: CBD<br/>zone: Residential"] --> Load

    Load["📦 Rule Loader<br/>Load bangalore-v1.0.json"] --> Filter

    Filter["🔍 Applicability Filter<br/>Match classification + zone<br/>against applies_when"] --> Matched

    Matched["✅ Matched Rules<br/>blr.fsi.cbd.residential<br/>blr.setback.cbd.residential<br/>blr.coverage.cbd.residential<br/>blr.height.cbd.residential<br/>..."]

    Matched --> E1["FSI Evaluator<br/>max_fsi: 2.5"]
    Matched --> E2["Setback Evaluator<br/>front: 4.5m, side: 1.5m"]
    Matched --> E3["Coverage Evaluator<br/>max_coverage: 65%"]
    Matched --> E4["Height Evaluator<br/>max_height: 15m"]
    Matched --> E5["Parking Evaluator<br/>ratio per unit"]
    Matched --> E6["Room Height Evaluator<br/>min: 2.75m"]
    Matched --> E7["Lift Required Evaluator<br/>threshold: 4 floors"]

    E1 --> Agg["📊 Aggregator"]
    E2 --> Agg
    E3 --> Agg
    E4 --> Agg
    E5 --> Agg
    E6 --> Agg
    E7 --> Agg

    Agg --> Result["ValidationResponse<br/>ok: true/false<br/>violations[]<br/>metrics{}"]

    style Snap fill:#1e40af,stroke:#3b82f6,color:#e2e8f0
    style Load fill:#065f46,stroke:#10b981,color:#e2e8f0
    style Filter fill:#78350f,stroke:#f59e0b,color:#e2e8f0
    style Matched fill:#4c1d95,stroke:#a78bfa,color:#e2e8f0
    style Agg fill:#7f1d1d,stroke:#ef4444,color:#e2e8f0
    style Result fill:#064e3b,stroke:#10b981,color:#e2e8f0
```

---

## 7. Application Lifecycle

```mermaid
stateDiagram-v2
    [*] --> SketchUpStarts

    SketchUpStarts --> ExtensionRegistered: boot.rb loads
    ExtensionRegistered --> MenuVisible: Register extension + menu items

    MenuVisible --> SpawningEngine: User clicks "Planara ▸ Start"
    SpawningEngine --> HealthPolling: engine_supervisor spawns uvicorn
    HealthPolling --> EngineReady: GET /health returns 200
    HealthPolling --> SpawnFailed: Timeout after retries

    SpawnFailed --> MenuVisible: Show error dialog

    EngineReady --> LoginPrompt: Show login dialog
    LoginPrompt --> Authenticated: POST /auth/login → JWT
    LoginPrompt --> EngineReady: Login failed, retry

    Authenticated --> ProjectSelection: Show project picker
    ProjectSelection --> LiveCompliance: User picks classification + zone

    LiveCompliance --> Validating: Geometry changes detected
    Validating --> LiveCompliance: Show violations in results panel

    LiveCompliance --> SaveReport: User clicks "Save current run"
    SaveReport --> LiveCompliance: POST /history

    LiveCompliance --> ViewHistory: User clicks "Recent runs"
    ViewHistory --> LiveCompliance: Browse / diff past reports

    LiveCompliance --> Shutdown: SketchUp closes OR user stops
    Shutdown --> [*]: SIGTERM uvicorn → cleanup
```

---

## 8. File Tree Summary

```
Planara-Plugin/
├── planara_plugin/                    # Ruby — SketchUp extension shell
│   ├── loader.rb                      # SketchUp extension entry point
│   └── planara/
│       ├── boot.rb                    # Lifecycle, menus, orchestration
│       ├── config.rb                  # Engine URL, path config
│       ├── engine_client.rb           # HTTP client → Python engine
│       ├── engine_supervisor.rb       # Spawn/stop Python sidecar
│       ├── session.rb                 # JWT + project state
│       ├── logger.rb                  # File-based logging
│       ├── update_checker.rb          # Version check
│       ├── geometry/
│       │   ├── extractor.rb           # SketchUp model → JSON snapshot
│       │   └── units.rb               # Unit conversion helpers
│       ├── observers/
│       │   └── live_validator.rb      # Debounced auto-validation
│       └── ui/
│           ├── login_dialog.rb        # Auth HtmlDialog
│           ├── results_dialog.rb      # Live violations panel
│           ├── history_dialog.rb      # Report history browser
│           ├── project_picker.rb      # Zone/classification picker
│           ├── browser_view.rb        # External HTML report viewer
│           └── assets/                # CSS, JS, images for dialogs
│
├── planara_engine/                    # Python — FastAPI compliance engine
│   └── src/planara_engine/
│       ├── api/                       # HTTP layer (no business logic)
│       │   ├── app.py                 # FastAPI app factory
│       │   ├── routes_validate.py     # POST /validate
│       │   ├── routes_auth.py         # POST /auth/*
│       │   ├── routes_health.py       # GET /health
│       │   ├── routes_reports.py      # POST /reports, GET /reports/html
│       │   ├── routes_history.py      # CRUD /history + diff endpoints
│       │   ├── routes_projects.py     # CRUD /projects
│       │   ├── middleware.py          # Request-ID, logging
│       │   └── errors.py             # Exception → HTTP response
│       ├── auth/                      # JWT mint/verify, bcrypt, user store
│       ├── domain/                    # Pydantic models (THE contract)
│       │   ├── snapshot.py            # DesignSnapshot schema
│       │   ├── plot.py                # Plot polygon + metadata
│       │   ├── building.py            # Building + Floor schemas
│       │   ├── project_context.py     # City/classification/zone
│       │   ├── violation.py           # Violation + ValidationResponse
│       │   └── geometry.py            # Polygon type definitions
│       ├── rules/                     # Declarative rule system
│       │   ├── schema.py              # Rule model
│       │   ├── loader.py              # Load + index rule packs
│       │   └── packs/                 # JSON rule packs per city
│       ├── engine/                    # Rule selection + dispatch
│       ├── compliance/                # One evaluator per bylaw concern
│       │   ├── fsi.py                 # Floor Space Index
│       │   ├── setback.py             # Building setbacks
│       │   ├── coverage.py            # Ground coverage %
│       │   ├── height.py              # Building height limits
│       │   ├── room_height.py         # Minimum room height
│       │   ├── parking.py             # Parking requirements
│       │   ├── lift_required.py       # Lift/elevator requirements
│       │   └── params.py              # Shared param extraction
│       ├── geometry/                  # Shapely polygon operations
│       ├── reporting/                 # Output formatting
│       │   ├── archive.py             # ArchivalReport builder
│       │   ├── html_renderer.py       # Standalone HTML reports
│       │   ├── diff.py                # Report comparison logic
│       │   └── diff_html.py           # HTML diff renderer
│       ├── persistence/               # Data layer
│       │   ├── database.py            # SQLite engine + sessions
│       │   ├── models.py              # SQLModel table definitions
│       │   ├── reports.py             # Report repository
│       │   ├── projects.py            # Project repository
│       │   └── repository.py          # Base repository
│       └── core/                      # Cross-cutting concerns
│
├── bangalore_bylaws/                  # Reference bylaw documents
├── legacy/SV-Abid/                    # Original Ruby-only prototype
├── scripts/                           # Build & dev scripts
└── docs/                              # Additional documentation
```
