"""Gate outcome type.

A small result type retained as plumbing for ``versioning.upsert_item_version``
(which maps ``decision`` → version status) and the read-path tests that seed
data through it. The v1 gate *policy* (publish/review/reject evaluation) was
removed with the rest of the claim/fold/gate machinery in the v2 OKF cutover;
the autonomous OKF pipeline does not gate.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class GateOutcome(BaseModel):
    """A publish/review/reject decision plus the reasons for it.

    Attributes:
        decision: One of ``"publish"``, ``"review"``, or ``"reject"``.
        reasons: Human-readable strings explaining the decision.
            Empty for a clean ``"publish"`` outcome.
    """

    decision: Literal["publish", "review", "reject"]
    reasons: list[str]
