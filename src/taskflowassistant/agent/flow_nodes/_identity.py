"""Shared identity-block text injected into every model-facing prompt
(the supervisor and every specialist) once flow_nodes/hydrate_user.py has
cached the caller's profile in state — keeps this one string in one place
instead of copy-pasted across every node that needs it.
"""

IDENTITY_BLOCK_TEMPLATE = """

The caller's own TaskFlow profile (already fetched via get_current_user by
flow_nodes/hydrate_user.py — do NOT call get_current_user again this
conversation unless the user explicitly asks you to refresh it):
{profile}"""
