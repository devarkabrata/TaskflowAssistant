# Teams & Assigned Teams

> API contract: [`../api-endpoints.md`](../api-endpoints.md) → Team Service,
> Role Service. Models: [`../models.md`](../models.md) → `Team`,
> `TeamRoleMapper`, `TeamInvitation`, `Role`.
>
> **Role names in this doc are illustrative, not fixed.** See
> [05-board-roles-and-permissions.md](./05-board-roles-and-permissions.md) for
> why — roles come from `GET /api/roles` and are expected to change.

A **team** is the unit everything else hangs off: every Kanban board is scoped
to one team, every task belongs to one team, and a person's access to a board
comes entirely through their team membership + role. A workspace member can
belong to any number of teams.

---

## Workspace Teams (`/teams`, Shell)

The list of teams that live inside **your own** workspace.

```
┌─────────────────────────────────────────────────────────┐
│  Teams                                    [New Team]     │
│  [Total Teams: 2] [Total Members: 4] [Pending Invites: 0]│
│  ● Taskflow Core   3 members   [Manage] [Invite] [Export]│
│  ● Design System   2 members   [Manage] [Invite] [Export]│
└─────────────────────────────────────────────────────────┘
```

### Create a team (`/teams/new`, full page)

1. **Team Details**: name (required, max 60), description (optional, max
   200), colour (8-swatch picker).
2. **Team Members**: the creator is always shown locked-in as admin-tier (a
   role whose `permissions` include `Manage`) — this row cannot be edited
   here. Optionally multi-select other workspace members to add immediately,
   each with a role picked from the same dynamic `GET /api/roles` dropdown
   (default: whichever role the API returns first).
3. Submit → `POST /api/teams` with `{ name, description, color, memberIds: [{ userId, role }] }`.
4. On success, the creator is added server-side with an admin-tier role
   **regardless of what was picked in the form** — you can't accidentally
   create a team you don't administer.
5. Three default board statuses are seeded automatically: **Backlog → In
   Progress → Done**.

### Manage a team (`/teams/:id`, full page — "Manage" button)

- Edit team meta (name / description / colour) — `PATCH /api/teams/:id`.
- Per-member role dropdown (same shared `RoleSelect` component, with a hover
  tooltip built from the role's `description` + `permissions[]`) —
  `PATCH /api/teams/:id/members/:userId`.
- Remove a member (confirm dialog) — `DELETE /api/teams/:id/members/:userId`.
  Removes them from the *team* only, not the workspace; their tasks remain
  with the assignment cleared.
- "Add from workspace": pick an existing workspace member + role, not already
  on this team — `POST /api/teams/:id/members`.
- **Last-admin protection**: if only one member currently holds an
  admin-tier role, their role dropdown and Remove button are both locked.
  Attempting to demote/remove them via the API returns `422`.
- Danger Zone: **Delete Team** — `DELETE /api/teams/:id`. Tasks are **not**
  deleted; they lose their team association.

### Invite by email into a team (modal, from the team card's "Invite" button)

Fields: email (required) · role (dynamic dropdown, default first role
returned) · **"Also add to workspace"** checkbox (opt-in, unchecked by
default).

- Unchecked → the invite is **team-scoped only**: if the email belongs to an
  existing workspace member, they're added to this team directly; if it's a
  new email, they get a team-only invitation — accepting it does **not** make
  them a workspace member.
- Checked → also creates a workspace-level invitation; accepting joins both.
- `POST /api/teams/:id/invite` `{ email, role, addToWorkspace }`. `409` if a
  pending invite already exists for that email + team. Expires after 7 days.
- **Known bug**: the modal accepts an `existingEmails` prop to client-side
  block re-inviting someone already on the team, but its only caller
  (`TeamsScreen.tsx`) always passes `[]`. The dedupe check exists in code but
  isn't wired to real data yet — a duplicate invite currently only gets
  caught by the backend's `409`, not pre-empted in the UI.

---

## Assigned Teams (`/teams/assigned`, Shell)

Teams you're a member of that belong to **someone else's workspace** — i.e.
you were invited cross-workspace. Fetched via `GET /api/teams?exclude_workspace=true`.

```
┌─────────────────────────────────────────────────────────┐
│  Assigned Teams                                          │
│  ● Client Platform Team   [View Tasks] [Export]          │
└─────────────────────────────────────────────────────────┘
```

**Only two actions here — no Manage, no Invite** — because you are not an
admin of these teams by construction of how you got on this list:

- **View Tasks** → cross-zone `<a href="/tasks/listview?teamid=...">` straight
  into the Task MFE's `TeamTaskBoardScreen` (per-team status-tab list).
- **Export** → same `ExportTasksModal` as Workspace Teams' Export.

The Board MFE mirrors this exact split: its `/board` landing
(`DashboardComponent`) has **Workspace Teams** and **Assigned Teams** tabs
side by side, and the in-board team-switcher dropdown fetches both lists so a
`teamId` from either resolves correctly.

---

## Roles per team member

Every team member row carries a **role**, which is a `Role.id` — not a fixed
string like `"admin"`. See
[05-board-roles-and-permissions.md](./05-board-roles-and-permissions.md) for
the full model and what each role currently grants. The two facts that matter
at the Teams-screen level:

- **A user can hold a different role on every team they belong to.**
- **A team must always have at least one member with an admin-tier role**
  (one whose `permissions` include `Manage`) — enforced by `422` on the
  API, and by disabling the last such member's controls in the Manage Team UI.
