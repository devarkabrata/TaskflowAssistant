# Signup & Login

> Full contract detail: [`../auth.md`](../auth.md) (cookie/token spec) and
> [`../api-endpoints.md`](../api-endpoints.md) (Auth Service + OTP Service).
> This page is the narrative walk-through of the same flow.

---

## Signup — 2-step form, OTP-gated

**Entry point**: `/signup` (Shell). Component: `SignupForm.tsx` — one Formik
instance spanning both steps, validated against one combined Yup schema.

```
Step 1 — Account details              Step 2 — Role & workspace
┌──────────────────────────┐          ┌───────────────────────────────┐
│ name                     │          │ title (designation, required) │
│ email                    │  Next →  │ workspaceName (required,      │
│ password                 │          │   pre-filled with default,    │
│ confirmPassword          │  ← Back  │   editable)                   │
└──────────────────────────┘          └───────────────────────────────┘
                                                     │
                                          "Create account" submit
                                                     │
                                                     ▼
                                    POST /api/otp/generate {event:"signup"}
                                                     │
                                          OTP modal opens (6 boxes)
                                                     │
                                    POST /api/otp/verify {event:"signup"}
                                                     │
                                              only on verify success
                                                     ▼
                                          POST /api/auth/signup
                                     { name, email, password, confirmPassword,
                                       title, workspaceName }
                                                     │
                                        ┌────────────┴────────────┐
                                        │ user info only —        │
                                        │  NO tokens, NOT logged in│
                                        │ → redirect to            │
                                        │   "/login?registered=1"  │
                                        └──────────────────────────┘
```

**This is the one detail worth internalizing**: submitting step 2 does **not**
call `/api/auth/signup` directly. It calls `POST /api/otp/generate`, waits for the
user to enter the code emailed to them, verifies it via `POST /api/otp/verify`,
and only then fires the actual `POST /api/auth/signup` with the data collected
across both steps. If the user abandons the flow after entering their details but
before verifying the OTP, no account is created.

**Signup does not auto-login the user.** Confirmed in `shell/app/api/auth/signup/route.ts`
— the code comment there is explicit: *"Signup returns SignupResponseDto (user
info only — no tokens)."* No `taskflow_access_token`/`taskflow_refresh_token`
cookies are set at this point. The new user is redirected to
`/login?registered=1` and must log in as a separate step immediately after.
(An earlier draft of this doc assumed signup redirected straight to `/` with
session cookies already set — that is not what the code does.)

### Step 1 fields — Account details

| Field | Validation |
|---|---|
| `name` | Required, min 2 characters |
| `email` | Required, valid email format |
| `password` | Required, min 6 characters |
| `confirmPassword` | Must match `password` |

### Step 2 fields — Role & workspace

| Field | Type | Validation |
|---|---|---|
| `title` (designation) | React Select dropdown | Required — the form cannot advance to submission without a selection |
| `workspaceName` | Text input | Required, min 2 characters. **Pre-filled** the moment step 1 completes, with `"<name>'s Workspace"` — freely editable |

**Designation options**: Engineer · Designer · Product Manager · QA Engineer ·
DevOps · Team Lead · Manager · Director · Founder · Other. Selecting "Other"
reveals a free-text input; that free-text value is what gets sent as `title` —
the literal string `"Other"` is never persisted.

### The default workspace and the default role

This is the part of the flow the user specifically needs documented, so to be
explicit about exactly what "default" means here:

- **Every signup auto-creates exactly one `Workspace` row**, owned by the new
  user (`Workspace.owner_id = <new user's id>`). There is no "skip creating a
  workspace" path — signup and workspace creation are the same transaction.
- **The workspace's name is not server-generated** — it's the `workspaceName`
  field from step 2, which the UI pre-fills with `"<name>'s Workspace"` but the
  user can rename before submitting (and can rename again later from the
  Workspace Details screen or Settings).
- **All of this user's tasks, teams, and invited people live inside this one
  workspace by default.** Multi-workspace membership is possible later (a user
  can accept an invite into someone *else's* workspace — see
  [Active workspace selection](#active-workspace-selection) below) but a brand
  new account only has the one it just created.
- **There is no workspace-level "role" field on the user separate from team
  roles.** `GET /api/auth/me`'s `workspaces[]` array does carry a `role` per
  membership (e.g. `"owner"`), but this is fixed by *how* the user is
  associated with the workspace (creator = `owner`; invited-and-accepted =
  something else) — it is not a role picked at signup and is not the same
  dynamic `Role` concept used for teams. Team-level roles (Flow Controller,
  Team Admin, etc.) only enter the picture once the user is added to a
  **team** — see [04-teams-and-assigned-teams.md](./04-teams-and-assigned-teams.md)
  and [05-board-roles-and-permissions.md](./05-board-roles-and-permissions.md).
  "The role may be changed later" in practice means: a team admin can change
  which team-role a member holds, at any time, from the Manage Team page.

### Cookies — actually set at LOGIN, not signup

Confirmed against `shell/app/api/auth/login/route.ts` and
`shell/app/api/auth/refresh/route.ts` — signup itself sets nothing (see above).
These are set the moment the user's first `POST /api/auth/login` succeeds:

| Cookie | HttpOnly | Max age | Purpose |
|---|---|---|---|
| `taskflow_access_token` | **No** | 8 days (30 min–1 hr on refresh, per JWT `exp`) | Bearer token, read client-side and attached to API calls |
| `taskflow_refresh_token` | Yes | 7 days | Used only by `PATCH /api/auth/refresh` to mint a new access token; never read by app code directly |

Both: `Path=/; SameSite=Lax`. Neither is named `taskflow_session`, and there
are no separate `taskflow_name`/`taskflow_email`/`taskflow_title` display
cookies — display data (name, email, title) comes from the in-memory
`GET /api/auth/me` response instead, not from cookies.

> **This supersedes an earlier planned contract** (still described in
> `../auth.md`'s main section) of one `taskflow_session` httpOnly cookie plus
> separate JS-readable display cookies. That plan was never implemented as
> written; `auth.md` itself flags this section as unreconciled. The
> access/refresh token scheme above is what actually ships. Token-refresh
> mechanics live in `shell/lib/http/client.ts` and `shell/middleware.ts`
> (which decodes the JWT manually, Edge-runtime-safe, and treats a token as
> valid unless positively proven expired).

### Validation failures

`422 Unprocessable` with `{ ok: false, errors: [...] }` → inline field errors,
no redirect. Common case: `DUPLICATE` on `email` (account already exists).

---

## Login

**Entry point**: `/login` (Shell), reached directly or via
`/login?registered=1` right after signup. Component: `LoginForm.tsx`.

```
User submits email + password
        │
        ▼
POST /api/auth/login
        │
   ┌────┴──────────────────────────────────┐
   │ 200 OK → Set-Cookie:                   │
   │   taskflow_access_token (JS-readable)  │
   │   taskflow_refresh_token (httpOnly)    │
   │ → router.push("/"); router.refresh()   │
   └─────────────────────────────────────────┘
        │
   ┌────┴──────┐
   │ 401       │ → banner error, no redirect
   └───────────┘
```

On every subsequent page load (any zone), the access token is read and, once
it's close to expiry, silently refreshed via `PATCH /api/auth/refresh` using
the httpOnly refresh-token cookie — no re-login needed. Unauthenticated
requests to any protected route redirect to `/login?redirect=<original-path>`
(enforced by `shell/middleware.ts`), and an authenticated user hitting
`/login` or `/signup` is redirected away to `/`.

### Forgot Password (also OTP-gated)

1. User clicks "Forgot password?" on the Login page, enters their email.
2. `POST /api/otp/generate` (`event: "forgotpassword"`).
3. OTP modal → `POST /api/otp/verify` (`event: "forgotpassword"`) — confirmed
   live to return only `{ verified, event }`, **no `userId`**.
4. "Set new password" modal → `PUT /api/users/change/password` with
   `{ email, newPassword, confirmPassword }` in the body and **no** bearer
   token (the user isn't logged in during this flow — the account is resolved
   by the `email` in the body, since the OTP-verify response gives back no id).

---

## Active workspace selection

A user can end up belonging to more than one workspace: the one auto-created at
their own signup, plus any they've accepted an invite into. `workspaces[]` on
`GET /api/auth/me` is **not** ordered by ownership. Every zone resolves the
"active" workspace the same way:

```
workspaces.find(w => w.role === 'owner') ?? workspaces[0]
```

i.e. prefer the workspace this user owns; fall back to the first membership
only if they don't own one. **Open gap**: there is currently no UI to switch to
a *non*-owned workspace if a user belongs to several and owns none of them.

---

## Logout

`POST /api/auth/logout` → `200`, clears all session/token cookies.
