# People & Workspace Invitations

> API contract: [`../api-endpoints.md`](../api-endpoints.md) → People / Workspace
> Service. Models: [`../models.md`](../models.md) → `WorkspaceMember`,
> `WorkspaceInvitation`, `Invitation`.

This is the **workspace-level** member directory — distinct from team
membership. Adding someone here does not put them on any team; it just gives
them workspace access. Teams are managed separately (see
[04-teams-and-assigned-teams.md](./04-teams-and-assigned-teams.md)).

---

## People (`/people`, Shell)

```
┌──────────────────────────────────────────────────────────────────┐
│  People                               [Invite to workspace]      │
│  [Total: 5] [Active: 4] [Pending: 1] [Teams: 3]                  │
│  [Search…]  [All teams ▾]  [All status ▾]                        │
│  Avt  Name          Title         Teams        Status  Actions   │
│  AC   Arkabrata C.  Engineer      Core · DS    Active  ...       │
│  PR   Priya R.      —             —            Pending ...       │
└──────────────────────────────────────────────────────────────────┘
```

### Who can do what

| Action | Who |
|---|---|
| View member list | Any workspace member |
| Invite member | Workspace admin (the workspace owner) |
| Resend invite | Workspace admin |
| Remove member / cancel invite | Workspace admin |

### Invite flow — two tabs, two different outcomes

Clicking **"Invite to workspace"** opens a modal with two tabs
(`InviteModal.tsx`) — these are not the same flow with different framing,
they hit different endpoints and produce different member states:

**"Via Email"** — invite someone who may not have an account yet:

1. Single email field (Formik + Yup — required, valid format).
2. Submit → `POST /api/people/invite` `{ email }`.
3. On success, the invitee appears in the list immediately with
   `status: "pending"` — their display name is derived from the email prefix
   until they accept and complete a profile.
4. Server sends the invitation email. Errors: `409` if already an active
   member or already has a pending invite; a **resend** to the same pending
   email reuses this same `POST /api/people/invite` call (no dedicated resend
   endpoint) and returns `200` (not `409`), resetting the expiry.
5. When the invitee accepts, their row flips to `status: "active"`.

Invitations expire after **7 days**.

**"Via Platform"** — add someone who already has a Taskflow account, skipping
the invite/accept step entirely:

1. Multi-select (react-select, `isMulti`) of existing platform users, sourced
   from a full user list; anyone already in this workspace is shown disabled.
2. Submit → `POST /api/people/enlist` `{ userIds: string[] }`.
3. Selected users are added as **`status: "active"` immediately** — there is
   no pending state, no invitation email, and no accept/decline step for this
   path.

This means "pending" only ever happens via the email path — anyone added via
"Via Platform" is a full active member the moment the request succeeds.

### The recipient's side: Pending Invitations (`/invite`, Shell)

This is the mirror screen for **invitations addressed to you** — i.e. someone
in a *different* workspace invited your account. `GET /api/people/invitations?userId=`
lists them (workspace name, who invited you, when it expires). Each carries
**Accept** and **Reject** actions:

- Accept → `POST /api/people/invitations/accept` `{ workspaceId, userId }` —
  you become an active member of *that* workspace too (this is how a user ends
  up belonging to more than one workspace — see
  [Active workspace selection](./01-signup-and-login.md#active-workspace-selection)).
- Reject → `POST /api/people/invitations/decline` `{ workspaceId, userId }`.

### Remove / cancel

- Admin clicks **Remove** → confirmation modal (`useConfirm()`), copy differs
  for pending ("Cancel invitation?") vs. active ("Remove member?").
- `DELETE /api/people/:userId` handles both cases — same endpoint, different
  DB action underneath.
- **A user cannot remove themselves.**
- Removing an active member also removes them from every team in this
  workspace (cascade). Their existing tasks are **not** deleted — the
  assignment just becomes unassigned.

### Data model note

There is no separate "workspace membership" table the People screen reads
from directly — `WorkspaceMember` rows are derived at request time from every
`User.workspaces[]` array entry matching the current workspace. Inviting =
appending a membership entry to the invitee's `User` document; removing =
stripping that entry (plus any `TeamMembership` entries scoped to this
workspace).
