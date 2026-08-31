# Taskflow — End-to-End User Flow

> How a person actually moves through the product, start to finish — signup through
> daily task work. This folder sits alongside the API contract docs
> ([`../models.md`](../models.md), [`../api-endpoints.md`](../api-endpoints.md),
> [`../auth.md`](../auth.md), [`../database-schema.md`](../database-schema.md)) and
> exists to answer a different question: not *what does the endpoint return*, but
> *what does the user see, in what order, and who is allowed to do what*.
>
> Verified against the current codebase (Shell, Task MFE, Board MFE source) and the
> live `.NET` backend's Swagger/Postman collection as of 2026-08-30. Where the
> `PRD/` folder describes an earlier plan that the live system does not implement
> (most notably: fixed team roles), this folder calls that out explicitly rather
> than silently repeating it — see [Known gaps](#known-gaps-and-aspirational-vs-current)
> below.

---

## Index

| File | Covers |
|---|---|
| [01-signup-and-login.md](./01-signup-and-login.md) | Signup (OTP-gated, 2-step), default workspace + default role, login, session |
| [02-dashboard-and-navigation.md](./02-dashboard-and-navigation.md) | The home dashboard and every sidebar section it hands off to |
| [03-people-and-workspace.md](./03-people-and-workspace.md) | People (workspace directory), inviting members, pending invitations |
| [04-teams-and-assigned-teams.md](./04-teams-and-assigned-teams.md) | Creating/managing teams, team membership roles, teams assigned from other workspaces |
| [05-board-roles-and-permissions.md](./05-board-roles-and-permissions.md) | The Kanban board, the dynamic Role/permission model, what's actually enforced vs. shown |
| [06-tasks-lifecycle.md](./06-tasks-lifecycle.md) | Task creation, My Tasks, Team Task Board, task detail, comments, archiving, export |

---

## High-level journey

```
Sign up (2-step form, OTP-verified)
        │  → default Workspace auto-created, owned by this user
        │  → session cookies set (taskflow_session + display cookies)
        ▼
Log in (returning users)
        │  → session restored from cookie on every page load
        ▼
Dashboard ("/")
        │  4 stat cards + Tasks/Board app-preview cards + phase timeline
        │
        ├──────────────┬───────────────┬───────────────┬───────────────┐
        ▼              ▼               ▼               ▼               ▼
     People          Teams      Assigned Teams        Board           Tasks
  (workspace       (create /    (teams you're      (team Kanban,   (My Tasks +
   directory,       manage,      a member of        drag-drop,      per-team
   invite by        assign a     in someone          statuses)       list view)
   email)           role per     else's
                     member)      workspace)
```

**Order this typically happens in for a brand-new account:**

1. Sign up → a Workspace is auto-created for you, you are its owner.
2. Land on the Dashboard — it's empty (you're the only member).
3. Go to **People** and invite colleagues into the workspace by email.
4. Go to **Teams**, create a team, and assign each invited person a **role** (from
   the dynamic role list — see [05](./05-board-roles-and-permissions.md)).
5. Open the team's **Board** — three default statuses (Backlog / In Progress /
   Done) already exist; add more if needed.
6. Create tasks (from the Board's "+ Add Task", or from **Tasks → New Task**),
   assign them to team members.
7. Day to day: work happens in **Tasks** (cross-project personal list, or a
   single team's list view) and the **Board** (team Kanban) interchangeably —
   moving a card on one is reflected on the other.

---

## Cast of screens (sidebar → route → app)

| Sidebar label | Route | App (zone) | Nav type |
|---|---|---|---|
| Home | `/` | Shell | same-zone |
| Teams ▸ Workspace Teams | `/teams` | Shell | same-zone |
| Teams ▸ Assigned Teams | `/teams/assigned` | Shell | same-zone |
| Contributors ▸ People | `/people` | Shell | same-zone |
| Contributors ▸ Pending Invitations | `/invite` | Shell | same-zone |
| Task Board | `/board` | Board MFE (Angular) | **cross-zone** `<a>` |
| My Tasks | `/tasks` | Task MFE (Next.js) | **cross-zone** `<a>` |
| Chat | `/chat` | Shell (iframes an external chatbot app) | same-zone |
| Settings | `/settings` | Shell | same-zone |
| (avatar menu) Profile | `/profile` | Shell | same-zone |
| (avatar menu) Workspace details | `/workspace/:id` | Shell | same-zone |

Source: `shell/components/layout/Sidebar.tsx`. The "Teams" and "Contributors" items
are accordions with two sub-links each (see file for exact structure). Task Board
and My Tasks are marked `external: true` in the sidebar component and rendered as
plain `<a>` tags — never `<Link>` — because they cross into a different MFE zone.

---

## Known gaps and aspirational-vs-current

Read this before trusting any single permission claim elsewhere in this folder —
these are the places where "what's documented/planned" and "what the running code
actually does" diverge:

| Area | Planned / documented elsewhere | What the code actually does today |
|---|---|---|
| Team roles | `PRD/04-teams.md` describes a fixed `admin \| pm \| tl \| developer` enum with a full per-action permission table | Roles are **dynamic**, fetched from `GET /api/roles`. Current seed data (explicitly placeholders): Flow Controller, Manupulator, Team Admin, Team Manager, Tester, Visitor. Each role carries a free-form `permissions: string[]` (confirmed values: `Read`, `Write`, `Delete`, `Manage`, `Comment`). Only `Manage` is semantically load-bearing client-side (the "last admin" guard). See [05](./05-board-roles-and-permissions.md) |
| Board action gating | PRD implies status/task actions are restricted by role in the UI | **No client-side role gating exists in the Board MFE.** Every team member sees "+ Add Status", column ✎ (edit), and 🗑 (delete) regardless of role. A restriction only surfaces as a `403`/`422` from the backend after the action is attempted |
| "Edit only your own task" rule | Documented as a role-independent, always-on rule | Enforced client-side in `TaskRow` (My Tasks list) and `TeamTaskBoardScreen`, gating the progress control and the "⋮" Edit/Delete menu to the task's own assignee(s). **Not enforced in `TaskDetailScreen`** — the full task detail page currently shows Edit/Delete unconditionally, which is inconsistent with the list views |
| Auth cookie scheme | `auth.md`'s main section describes one `taskflow_session` httpOnly cookie | The live Shell/Task MFE/Board MFE actually use a short-lived **bearer access token** refreshed via an httpOnly `taskflow_refresh_token` cookie (see `shell/lib/http/client.ts`, `shell/lib/token.ts`, `mfe-board/src/app/core/auth.interceptor.ts` + `refresh.interceptor.ts`). `auth.md` flags this itself as an unreconciled section |
| Notifications | Bell icon exists in Shell/Task MFE topbars | Shell's bell is commented out / not wired; only the Board MFE topbar actually calls `GET /api/notifications` |
| Archived task drill-down | Implied parity across zones | Board MFE has a full Archived Task Details screen; Task MFE's Archived tab only lists — no detail page yet |
| Signup → logged-in state | Easy to assume signup lands you on the Dashboard already authenticated | It does not. `POST /api/auth/signup` returns user info only, no tokens — the user is redirected to `/login?registered=1` and must log in as a separate step. See [01](./01-signup-and-login.md) |
| Auth cookies | `../auth.md`'s main section describes one `taskflow_session` httpOnly cookie + separate display cookies | Actually two cookies, both set at **login** (not signup): `taskflow_access_token` (JS-readable) + `taskflow_refresh_token` (httpOnly), refreshed via `PATCH /api/auth/refresh`. No `taskflow_session`/`taskflow_name`/`taskflow_email`/`taskflow_title` cookies exist — display data comes from `GET /api/auth/me`. See [01](./01-signup-and-login.md) |
| Inviting people to a workspace | One invite flow (by email, pending → accept) | Two tabs, two outcomes: "Via Email" (`POST /api/people/invite`, produces a `pending` member who must accept) and **"Via Platform"** (`POST /api/people/enlist`, adds an existing platform user as `active` immediately — no pending state at all). See [03](./03-people-and-workspace.md) |
| Team-role display in Profile | Roles are fully dynamic, no fixed names | `shell/components/profile/ProfileScreen.tsx` still has a hardcoded `formatRole()`/`roleColor` map keyed on literal strings (`admin`, `tl`, `pm`, `developer`, `owner`, `member`) left over from an earlier fixed-role design. It's display-only (nothing is access-gated on it) but will silently fail to label/color a team's actual admin-tier role if that role's name isn't literally `"admin"` |
| Board "Archive status" button | Sits next to "Delete status", implies a working parallel action | It's UI-complete but backend-absent — `board.component.ts` has `// TODO: archive-status API (no endpoint yet)`; confirming the modal just closes it with no API call. Only "Delete status" is actually wired. See [05](./05-board-roles-and-permissions.md) |
| Team-invite email dedupe | `TeamInviteModal` takes an `existingEmails` prop to block re-inviting a current member | Its only caller (`TeamsScreen.tsx`) always passes `[]` — the check exists in code but isn't wired to real data; only the backend's `409` actually catches a duplicate invite today. See [04](./04-teams-and-assigned-teams.md) |

Everything downstream in this folder is written to match the **current** behavior,
with a note wherever it diverges from an older plan.
