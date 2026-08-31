# Board, Roles & Permissions

> API contract: [`../api-endpoints.md`](../api-endpoints.md) → Board Service,
> Role Service, Task Service. Models: [`../models.md`](../models.md) → `Role`,
> `BoardStatus`, `Task`.
>
> **Read this whole page before treating any role name below as fixed.** The
> single most important fact about permissions in Taskflow: **roles are not a
> hardcoded enum anywhere in the frontend.** They are rows fetched live from
> `GET /api/roles`, and the current data is explicitly seeded as placeholders
> the backend team expects to replace. Nothing in Shell, Task MFE, or Board MFE
> hardcodes a role name, a role count, or a fixed permission table.

---

## The Role model

```ts
interface Role {
  id: string;              // UUID — PK
  name: string;             // display name, e.g. "Team Admin" — can change
  description?: string;
  permissions: string[];   // array of permission key strings
  created_at: string;
  updated_at: string;
}
```

Fetched via `GET /api/roles`, surfaced through `shell/lib/hooks/useRoles.ts`
and rendered by the shared `shell/components/teams/RoleSelect.tsx` component —
used in three places: the "Assign roles" rows on Create Team, the role
dropdown in the team Invite-by-email modal, and the per-member role dropdown +
"Add from workspace" role picker on the Manage Team page. Every dropdown
option shows a native hover tooltip built from that role's `description` +
its `permissions` list, so a team admin can see what a role grants *before*
assigning it — without needing this document open.

### Currently seeded roles (confirmed live — expect these to change)

| Role name | Notes |
|---|---|
| Flow Controller | placeholder |
| Manupulator | placeholder (sic — this is the live spelling) |
| Team Admin | placeholder — intended as the "full access" role |
| Team Manager | placeholder |
| Tester | placeholder |
| Visitor | placeholder |

### Permission keys (confirmed values seen so far)

| Key | Meaning (as used by the client) |
|---|---|
| `Read` | View access |
| `Write` | Create/edit access |
| `Delete` | Delete access |
| `Manage` | **Admin-tier signal** — see below |
| `Comment` | Can comment on tasks |

**`Manage` is the only permission key with client-side meaning today.** Any
role whose `permissions` array includes `Manage` counts toward "admin-tier"
for the one hard rule the frontend enforces: *a team must always have at
least one member holding an admin-tier role.* This is why the Manage Team
page locks the role dropdown and Remove button for the sole remaining
`Manage`-holder, and why the backend returns `422` if you try to route around
that in the API directly. It is **not** literally checking for a role named
"Admin" — a role called anything, as long as its `permissions` includes
`Manage`, satisfies this.

Beyond that one rule, `Read` / `Write` / `Delete` / `Comment` are not
currently wired into any client-side branch — they exist as descriptive
metadata shown in the tooltip, and (per the backend's own documentation) as
whatever the server checks before returning `403`.

---

## What this means in practice, walking the flow

1. When a team is created, the creator is force-assigned an admin-tier role
   server-side, no matter what the Create Team form shows — you can't found a
   team you don't control.
2. When an admin invites or adds someone to a team, they pick a role from
   whatever `GET /api/roles` currently returns. There's no guarantee "Visitor"
   or "Tester" means the same thing across two different workspaces if the
   backend's seed data ever diverges per-tenant — treat role *names* as
   presentational, and only the `Manage` permission as load-bearing.
3. Changing someone's role, at any time, is `PATCH /api/teams/:id/members/:userId`
   with a new `role` (a `Role.id`) — the "role may be changed later" the
   product intends is exactly this control, gated only to whoever already
   holds an admin-tier role on that team.

---

## The Board itself (`/board`, Board MFE — Angular)

Routes:

| Route | Renders |
|---|---|
| `/board` | `DashboardComponent` — "My Boards" landing, Workspace Teams / Assigned Teams tabs (same split as Shell's Teams sidebar), one card per team |
| `/board/:teamId` | `BoardComponent` — the Kanban itself |
| `/board/archived/:teamId` | `ArchivedTasklistComponent` |
| `/board/archived-task/:taskId` | `ArchivedTaskdetailsComponent` |

Each team card on the landing page shows a colour dot, name, member avatars,
per-status task counts, and four actions: **Open Kanban**, **Archived Task**,
**Export**, and (Workspace Teams tab only) whatever Manage/Invite affordances
exist at the Shell level are *not* duplicated here — Board MFE is
view/act-on-tasks only, not team administration.

### Kanban view (`/board/:teamId`)

- **Columns are fully dynamic per team** — no global status enum. Fetched via
  `GET /api/tasks/team/:teamId/board`, which returns `{ teamId, columns: [...] }`,
  each column carrying its own tasks embedded (no separate pagination call in
  the current live contract).
- **Assignee filter**: multi-select of workspace people; selecting narrows the
  same endpoint by a comma-separated `assigneeId` param.
- **Add Status** (dashboard card, or "+ Add Status" in the Kanban header) →
  `POST /api/board-statuses/create` `{ name, description, teamId, isArchievable }`.
- **Edit status** (✎ on a column) → `PATCH /api/board/:teamId/statuses/:statusId`.
- **Delete status** (🗑, confirm modal) → `DELETE /api/board-statuses/:statusId`.
  Tasks in that status are **soft-deleted**, not destroyed. The last remaining
  status of a team cannot be deleted (`422`).
- **Archive status** (a separate icon next to Delete, own confirm modal) —
  **this button does not do anything yet.** `board.component.ts` has a literal
  `// TODO: archive-status API (no endpoint yet).` where the confirmed action
  should fire; the modal just closes. Don't document this as a working
  feature — it's UI-complete, backend-absent.
- **Drag-and-drop** a card to another column → `PATCH /api/tasks/:id/status`
  `{ statusId }`. Snaps back with a toast on API error.
- **"+ Add Task"** per column header → cross-zone navigate to
  `/tasks/new?teamId=&statusId=` (pre-fills team + status, locked).
- Card's **↗** icon → cross-zone navigate to `/tasks/:id` (Task MFE detail
  page).
- **Export** button (dashboard card and Kanban header) → CSV/XLSX download of
  the team's tasks, optionally including archived ones.
- **Archived Task** → a read-only paginated list of soft-deleted tasks for
  this team, each with a drill-down detail page (`ArchivedTaskdetailsComponent`)
  — this detail drill-down currently exists **only** in the Board MFE; the
  Task MFE's own Archived tab lists but has no detail page yet.

### What is *not* gated by role in the Board MFE, today

This is worth stating plainly because it's easy to assume the permission
table above is enforced visually — **it isn't, yet**. Every team member,
regardless of role, sees the same "+ Add Status", ✎, and 🗑 controls on every
column, and the same drag-and-drop affordance on every card. There is no
`*ngIf` anywhere in `board.component.html` or `dashboard.component.html`
keyed off a role or permission. The only place a restriction actually bites is
**server-side**: attempting an action you don't have permission for returns
`403` (or `422` for the last-status/last-admin cases), surfaced to the user as
a toast/error — not a hidden or disabled button beforehand.

The one exception, and it's **not role-based** — it's assignment-based:

- In the **Task MFE's** list views (`TaskRow` on My Tasks, and
  `TeamTaskBoardScreen`), the progress-update control and the "⋮" Edit/Delete
  menu are only interactive for a task's own assignee(s) — everyone else sees
  the identical row, dulled and non-interactive, with a tooltip explaining why.
  This has nothing to do with the team-role system above; it's a plain
  `task.assignees.some(a => a.userId === currentUserId)` check.
- This same check is **not** applied on the Task MFE's `TaskDetailScreen` (the
  full task detail page) — Edit/Delete render there regardless of assignee.
  Treat that as an inconsistency in the current build, not an intentional
  "detail page bypasses restrictions" design.

---

## Summary table — what actually decides "can I do X" right now

| Question | What actually decides it |
|---|---|
| Can I administer this team (roles, membership, delete)? | Whether my `Role.permissions` on this team includes `Manage` — enforced server-side, not hidden in the UI |
| Can I add/edit/delete a board status? | Server-side check only — every member sees the controls; a `403` is the only signal of "no" |
| Can I drag any card, or only my own? | Server-side check only, same as above |
| Can I edit/delete a specific task from a list view? | Client-side: am I one of its assignees? (Task MFE list views only) |
| Can I edit/delete a task from its detail page? | Currently: yes, unconditionally — no gating implemented there yet |
| Can I remove the last admin-tier member from a team? | No — blocked both in the Manage Team UI (disabled controls) and by the API (`422`) |
