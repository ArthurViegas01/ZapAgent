"""Per-task context propagation for the agent graph.

LangGraph passes a ``config`` dict to each node, but its ``configurable``
slot filters keys via internal heuristics — and in our version those
heuristics drop the ``db_pool`` object before it reaches the nodes
(observed empirically: ``configurable_keys=[]`` even when we pass
``{"db_pool": pool}``). Rather than fight LangGraph's internals, we
propagate the pool via :class:`contextvars.ContextVar`, which is the
right abstraction for "task-scoped value that flows through ``await``
boundaries":

* asyncio's task-local copy-on-write semantics keep the value scoped
  to the current task and any sub-tasks it spawns.
* No serialization happens (the saver checkpoints only the typed
  AgentState fields, never the contextvar).
* No mutable globals → no event-loop hazard across Celery tasks.

The worker sets the pool at the start of ``_run_agent`` and the
``retrieve_context`` node reads it. That's the only path of record.
"""

from __future__ import annotations

import contextvars
from typing import Any

_db_pool_var: contextvars.ContextVar[Any | None] = contextvars.ContextVar(
    "agent_db_pool", default=None
)


def set_db_pool(pool: Any | None) -> None:
    """Bind ``pool`` to the current async task's context.

    Subsequent calls to :func:`get_db_pool` from the same task (and any
    sub-tasks LangGraph spawns) return this value until the task exits.
    """
    _db_pool_var.set(pool)


def get_db_pool() -> Any | None:
    """Return the pool bound by the enclosing task, or ``None``.

    ``None`` is the signal for nodes to fall back to their offline
    behavior (e.g. ``retrieve_context`` returns empty stubs).
    """
    return _db_pool_var.get()
