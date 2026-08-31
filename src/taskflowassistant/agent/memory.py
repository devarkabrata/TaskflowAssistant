"""Multi-turn conversation memory for the TaskFlow agent.

`create_agent` (see agent/executor.py) takes a `checkpointer` — an object
that saves and restores conversation state between calls, keyed by a
`thread_id` you pass at invoke time. `InMemorySaver` keeps that state in a
plain Python dict inside this process: nothing to set up, and enough for
local dev / a single running instance. It resets whenever the process
restarts (nothing is written to disk) — swap it for a persistent
checkpointer (e.g. Postgres/SQLite-backed) later if conversations need to
survive a restart.
"""

from langgraph.checkpoint.memory import InMemorySaver

# Shared by the whole app: one saver, many conversations, separated by thread_id.
checkpointer = InMemorySaver()
