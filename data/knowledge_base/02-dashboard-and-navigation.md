# Dashboard & Navigation

> API contract: [`../api-endpoints.md`](../api-endpoints.md) → Dashboard Service,
> Auth Service (`/api/auth/me/stats`). This page covers what the user sees and
> where each element sends them.

---

## Dashboard (`/`, Shell)

The first screen after login. Purely a jumping-off point — no data entry
happens here.

```
┌─────────────────────────────────────────────────────────┐
│  Sidebar  │  Welcome back, {name}                        │
│           │  {workspace name} · {date}                   │
│           │                                              │
│           │  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐        │
│           │  │Total │ │Arch- │ │Total │ │Total │        │
│           │  │Tasks │ │ived  │ │Team  │ │Work- │        │
│           │  │      │ │Task  │ │      │ │space │        │
│           │  └──────┘ └──────┘ └──────┘ └──────┘        │
│           │                                              │
│           │  ┌────────────────┐  ┌──────────────────┐   │
│           │  │  Tasks App     │  │  Board App       │   │
│           │  │  [Open Tasks →]│  │  [Open Board →]  │   │
│           │  └────────────────┘  └──────────────────┘   │
│           │                                              │
│           │  Project Timeline ──────────────────────    │
└─────────────────────────────────────────────────────────┘
```

### Stat cards

Fed by `GET /api/auth/me/stats` (`authService.meStats()`), **not** a separate
`/api/dashboard/stats` call:

| Card | Derived from |
|---|---|
| Total Tasks | `taskCount.activeTasks + taskCount.archieveTask` |
| Archived Task | `taskCount.archieveTask` |
| Total Team | `teamCount` |
| Total Workspace | `workspaceCount` |

(`archieveTask` is the exact backend field spelling — mirrored intentionally,
see [`../models.md`](../models.md#mestats-api-response-shape--get-apiauthmestats).)
No trend badges. On a brand new account these are all `0` — no special empty
state beyond that.

### App preview cards

Two cards, purely navigational — **both use `<a href="...">`, never `<Link>`**,
because `/tasks` and `/board` are different MFE zones:

- **Tasks** → `<a href="/tasks">` — opens the Task MFE's My Tasks list.
- **Board** → `<a href="/board">` — opens the Board MFE's team landing.

### Project Timeline

Static — a horizontal strip of phase labels, no API call.

---

## Sidebar — every section, in the order it appears

| Group | Item | Route | What it's for |
|---|---|---|---|
| — | Home | `/` | Dashboard (above) |
| Teams | Workspace Teams | `/teams` | Teams inside *your* workspace — create, manage, invite. See [04](./04-teams-and-assigned-teams.md) |
| Teams | Assigned Teams | `/teams/assigned` | Teams you belong to that live in **someone else's** workspace — view/export only. See [04](./04-teams-and-assigned-teams.md) |
| Contributors | People | `/people` | Your workspace's member directory — invite by email, active vs. pending. See [03](./03-people-and-workspace.md) |
| Contributors | Pending Invitations | `/invite` | Invitations addressed **to you** (from other workspaces) — Accept / Reject. See [03](./03-people-and-workspace.md) |
| Tools | Task Board | `/board` | Cross-zone → Board MFE. See [05](./05-board-roles-and-permissions.md) |
| Tools | My Tasks | `/tasks` | Cross-zone → Task MFE. See [06-tasks-lifecycle.md](./06-tasks-lifecycle.md) |
| Workspace | Chat | `/chat` | Full-bleed iframe embedding an external chatbot app — no backend calls of ours involved |
| — | Settings | `/settings` | Profile, notification preferences, task-archiving window, change password |
| (avatar menu) | Profile | `/profile` | (separate from Settings — profile-only view) |
| (avatar menu) | Workspace details | `/workspace/:id` | Owner, full team list, full member list for one workspace — `GET /api/workspace/:workspaceId/info` |

**"Teams" and "Contributors" are accordions** (`shell/components/layout/Sidebar.tsx`
— `TeamsAccordion`, `ContributorsAccordion`), each opening to reveal their two
sub-links; they auto-expand when the current route is inside that section.

**Task Board and My Tasks are the only two sidebar items marked `external: true`**
— rendered as plain `<a>` tags. Everything else in the Shell sidebar uses
Next.js `<Link>` since it stays inside the Shell zone.

---

## Sidebar / Topbar identity elements

Every zone (Shell, Task MFE, Board MFE) independently calls `GET /api/auth/me`
to populate:

- **Workspace indicator** — the *active* workspace's `.name` (see
  [Active workspace selection](./01-signup-and-login.md#active-workspace-selection)).
- **User card** — display name + avatar initials/URL.

The Board MFE topbar additionally polls `GET /api/notifications` for a bell
icon. The Shell and Task MFE topbars have a bell icon in the markup but it is
currently **not wired to any endpoint** in the Shell (commented out).
