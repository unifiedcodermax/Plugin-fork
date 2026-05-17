# Sprint 2 — Auth: SQLite + bcrypt + JWT + login dialog

**Dates:** 2026-05-16 05:10–06:15 IST (~65 min)
**Version:** 0.1.0-dev
**Commits:** 6
**Headline:** A user can log in from a SketchUp HtmlDialog and the engine refuses unauthenticated requests on every route except `/health` and `/auth/login`.

---

## Goal

Establish the auth boundary before anything else builds on top.
Future endpoints (`/validate`, `/reports`, `/history`) will be
guarded by the same dependency, so the dependency has to exist
first.

Specifically: SQLite users, bcrypt-hashed passwords, JWT issued
by `/auth/login`, a `current_user` FastAPI dependency, and a
login dialog rendered as an HtmlDialog in the plugin.

---

## Commits

| SHA | Date | Subject |
|---|---|---|
| `f2e8a07` | 05:10:40 | feat(engine/persistence): SQLite engine + User model + repository |
| `51eb9d0` | 05:33:13 | feat(engine/auth): bcrypt password helpers and JWT mint/verify |
| `dd63053` | 05:37:01 | feat(engine/auth): service layer + FastAPI dependencies |
| `d88b1ec` | 05:50:11 | feat(engine/api): /auth/login and /auth/me routes |
| `de56086` | 06:02:11 | feat(engine/cli): planara-engine create-user subcommand |
| `d287ae2` | 06:15:39 | feat(plugin/ui): login HtmlDialog wired through to engine |

---

## Engine deliverables

### Persistence layer (`persistence/`)

```
persistence/
  database.py                # SQLModel engine, session factory
  models.py                  # User table
  repository.py              # Base repo, UserRepository
```

`User` table fields:

- `id` (UUID, primary key)
- `email` (unique, indexed)
- `password_hash` (bcrypt)
- `created_at`

### Auth modules (`auth/`)

```
auth/
  passwords.py               # bcrypt.hash, bcrypt.verify
  tokens.py                  # jwt.mint(user_id, exp), jwt.verify(token)
  service.py                 # login(email, password), get_user(id)
  deps.py                    # current_user FastAPI dependency
```

### Endpoints

| Method | Path | Auth | Returns |
|---|---|---|---|
| POST | `/auth/login` | none | `{access_token, expires_at}` |
| GET | `/auth/me` | Bearer | `MeResponse {id, email, created_at}` |

### CLI

`planara-engine create-user --email <e> --password <p>` — for
bootstrapping the first user. Auto-seeds an admin user on first
engine boot if no users exist.

---

## Plugin deliverables

### Login HtmlDialog

```
planara_plugin/planara/ui/
  login_dialog.rb            # Wraps HtmlDialog with assets/login.html
  assets/login.html          # Plain HTML + vanilla JS form
```

Flow:

```
User clicks Planara → Login
  → LoginDialog.show
    → HtmlDialog.set_file("assets/login.html")
    → JS submit handler calls sketchup.login(email, password)
    → Ruby callback → EngineClient.login → POST /auth/login
    → Session.token = response.access_token
    → dialog closes
```

### `Session` extended

- `Session.token` — JWT string.
- `Session.user_id`.
- `Session.authenticated?` boolean for guards.

`EngineClient` now attaches `Authorization: Bearer <token>` to
every request when `Session.token` is set.

---

## Tests added

### Engine

- `tests/unit/test_passwords.py` — bcrypt round-trip, salt
  uniqueness, verify-with-wrong-password.
- `tests/unit/test_tokens.py` — mint + verify, expiry,
  tamper-detection.
- `tests/unit/test_auth_service.py` — login happy path,
  unknown-user, wrong-password (no-leak invariant).
- `tests/integration/test_auth_routes.py` — POST /auth/login,
  GET /auth/me with/without token, `password_hash`-never-in-
  response invariant.
- `tests/unit/test_persistence.py` — User repo CRUD.

---

## Files added/changed

```
+ planara_engine/src/planara_engine/persistence/{database,models,repository}.py
+ planara_engine/src/planara_engine/auth/{passwords,tokens,service,deps}.py
+ planara_engine/src/planara_engine/api/routes_auth.py
+ planara_engine/src/planara_engine/cli.py                (extended)
+ planara_plugin/planara/ui/login_dialog.rb
+ planara_plugin/planara/ui/assets/login.html
+ planara_plugin/planara/session.rb                       (extended)
+ planara_plugin/planara/engine_client.rb                 (auth header)
```

---

## Invariants locked

### D7 — No-leak login

> verbatim:
> *"No-leak auth: identical message + timing-balanced bcrypt for
> 'no such user' vs 'wrong password'. Test enforces this; a
> regression would be silent and bad."*

The `/auth/login` handler runs bcrypt **even when the user
doesn't exist** (against a fixed dummy hash) so timing is
constant. The error message is identical for both failure modes.

### D8 — `password_hash` boundary via `MeResponse`

The ORM `User` model has `password_hash`. The wire response model
(`MeResponse`) does not. An integration test asserts the field
never appears in any response body.

### D6 — JWT lifetime: 30 days, HS256

Plugin doesn't decode it — just stores and sends back.

### D38 — No frontend framework

Login HTML is plain HTML + vanilla JS. No build step.

---

## Risks mitigated

| Risk | How |
|---|---|
| R12 — auth leaks (timing, message) | No-leak invariant; integration test enforces. |
| R13 — `password_hash` leak via response | `MeResponse` boundary; integration test asserts absence. |

---

## Deferred from this sprint

- Refresh tokens (deferred indefinitely — 30-day access tokens
  are sufficient for MVP).
- Multi-org / SSO / OAuth (out of MVP).
- Password reset flow (out of MVP — admin can reset via CLI).
- Per-user rate limiting (out of MVP).

---

## Why `de56086` (create-user CLI) matters

Without the CLI, the only way to create a user is via the
auto-seed admin or a direct DB write. The CLI gives ops a clean
path:

```bash
planara-engine create-user --email alice@example.com --password ...
```

It's tiny, it's listed because it's the boundary between dev and
prod user provisioning.
