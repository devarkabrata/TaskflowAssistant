# Tasks Lifecycle

> API contract: [`../api-endpoints.md`](../api-endpoints.md) → Task Service,
> Comment Service, Board Service, Export Service. Models:
> [`../models.md`](../models.md) → `Task`, `AssigneeSummary`, `ApiArchivedTask`,
> `Comment`, `ExportTasksPayload`.

The Task MFE (`mfe-task/`, Next.js, served at `/tasks`) is where task content
itself is created, read, and edited. The Board MFE handles status/column
management and drag-drop; both operate on the same underlying `Task` records.

---

## My Tasks (`/tasks`, Task MFE — the default landing)

A personal inbox: every task assigned to the logged-in user, aggregated across
every team they belong to. **Not** a single-team view.

- 4 stat cards: Total · In Progress · In Review · Done (from `GET /api/tasks/stats`
  equivalent — `assigneeId=me`).
- Filter tabs (status) + a team dropdown ("All Teams" + one option per team).
  Status tabs only appear once a single team is selected, since statuses are
  per-team, not global.
- Each row: priority dot, title (click → detail), label badge, team badge,
  status pill, due date, assignee avatar, a permanent **✏ Edit** icon and
  **↗ Open** icon (both always visible, not hover-gated).
- Row-level Edit/Delete/progress-update controls are gated to the task's own
  assignee(s) — see
  [05-board-roles-and-permissions.md](./05-board-roles-and-permissions.md#what-is-not-gated-by-role-in-the-board-mfe-today)
  for exactly how and where this is enforced (and where it isn't).

## Team Task Board (`/tasks/listview?teamid=`, Task MFE)

Reached from Shell's Assigned Teams "View Tasks" button or the team switcher —
a per-team status-tab list view (an alternate lens on the same data the
Board MFE's Kanban shows, `GET /api/tasks/team/:teamId/board`). Has its own
Archived tab (list-only; no detail drill-down here — that only exists in the
Board MFE) and its own Export button.

## Create a task (`/tasks/new`)

Reached either from **My Tasks → "New Task"** or from a **Board column's
"+ Add Task"** (which pre-fills and locks `teamId` + `statusId` via query
string).

| Field | Required | Notes |
|---|---|---|
| Title | yes | max 200 chars |
| Description | no | CKEditor 5 rich text, dark theme, image upload |
| Team | yes | immutable after creation — cannot be changed on edit |
| Status | yes | dropdown of the selected team's statuses (`GET /api/board-statuses/team/:teamId`) |
| Assignees | no | multi-select, team members, `assigneeIds: string[]` |
| Priority | no | High / Medium / Low, defaults Medium |
| Label | no | Feature / Bug / Design / Docs / Infra / Refactor |
| Expected completion | no | date picker |
| Progress % | no | manual 0–100, defaults 0 |
| Images | no | multi-upload |

Submit → `POST /api/tasks`.

## Edit a task (`/tasks/:id/edit`)

Same form, pre-filled, **minus the Team field** — a task's team is immutable
once created (`UpdateTaskRequestDto` has no `teamId` field at all). Submit →
`PUT /api/tasks/:id`.

## Task detail (`/tasks/:id`)

Full page (not a drawer) — title, rich-text description, status/priority/
label/team/assignee, expected completion, progress %, images, a **Comments**
panel, and (in the Board MFE's equivalent archived flow) history. Edit/Delete
buttons here currently render **unconditionally** — see the note in
[05](./05-board-roles-and-permissions.md#what-is-not-gated-by-role-in-the-board-mfe-today)
about this being inconsistent with the list views' assignee-only gating.

Comments: `GET/POST /api/comments?taskId=`, `PUT/DELETE /api/comments/:commentId`
— edit/delete restricted to the comment's own author.

## Archiving

Deleting a **board status** soft-deletes every task that was in it
(`tasks.deleted_at` set — never hard-deleted). These surface in:

- Board MFE: `/board/archived/:teamId` list → `/board/archived-task/:taskId`
  detail (`GET /api/migrate/task/archived[/:taskId]`).
- Task MFE: an **Archived** tab on the Team Task Board screen — list only, no
  detail page yet.

## Export

Any team's tasks (active, optionally including archived) can be downloaded as
CSV or XLSX from a shared `ExportTasksModal`/`ExportTasksComponent`, available
from: Shell's TeamCard/AssignedTeamCard, the Task MFE's Team Task Board header,
and both the Board MFE dashboard card and Kanban header.
`POST /api/tasks/export` `{ teamId, fileName, isIncludeArchiveTask, format }`
— response is a raw file, not the JSON envelope.

---

## The daily loop, end to end

```
Board (Kanban)  ←──── same Task records ────→  My Tasks / Team Task Board (list)
     │                                                    │
     │  drag card between statuses                       │  update progress / status
     │  PATCH /api/tasks/:id/status                       │  from ProgressModal
     ▼                                                    ▼
        Both views re-fetch and reflect the change immediately
        (cache invalidation covers both the tasks.* and board.team(teamId) keys)
```
