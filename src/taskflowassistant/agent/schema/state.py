from typing import Annotated
from langgraph.channels.untracked_value import UntrackedValue
from langgraph.graph.message import add_messages, AnyMessage
from typing_extensions import TypedDict


class TaskFlowState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    taskflow_token: str | None
    # The caller's own `/auth/me` profile (id, name, email, workspace, teams),
    # fetched once by `flow_nodes/hydrate_user.py` and cached here for the
    # rest of the conversation. Plain field, no reducer/UntrackedValue — it
    # SHOULD persist across every turn of the whole thread via the
    # checkpointer (that's the entire point: fetch it once per conversation,
    # not once per turn), unlike `llm_calls` below.
    current_user: dict | None
    # `UntrackedValue` is never checkpointed — it resets to unavailable every
    # time this thread's state is reloaded for a new invocation, so this
    # genuinely counts model calls made in the CURRENT run only (as
    # `flow_nodes/model_limit.py` compares it against
    # `MODEL_CALL_LIMIT_PER_RUN`). A plain reducer-summed field here would
    # instead persist and keep growing across every turn of the whole thread
    # (the same way `messages` does, via the checkpointer) — after enough
    # total turns it would permanently exceed the run limit and every future
    # message would immediately dead-end at `limit_reached` having done no
    # work. `flow_nodes/main_agent.py` increments this itself
    # (`state.get("llm_calls", 0) + 1`); there's no reducer here for the same
    # reason the upstream `ModelCallLimitMiddleware` doesn't use one either —
    # `UntrackedValue.update()` is last-value-wins, not summing.
    llm_calls: Annotated[int, UntrackedValue]