"""``ChartResult`` — the planner's result type (ADR-0020 D2, ADR-0027 D9).

Not itself a wire type: ``Envelope``'s wire format is frozen at three keys
(ADR-0005) and ``ChartResult`` never widens that by flattening either payload
onto itself. Exactly one of ``envelope`` (deterministic rail) or ``recipe``
(custom rail) is set; there is no ``kind`` field, the payload is the
discriminator. An envelope result serialises through ``.envelope.to_dict()``.
A recipe result has no envelope; the stored artifact is the recipe, and a
recipe refresh's rows ride on ``bound``.
"""

from __future__ import annotations

from dataclasses import dataclass

from chartagent.bind import DataSource, bind
from chartagent.envelope import Envelope
from chartagent.recipe import BoundRecipe, ChartRecipe, bind_recipe
from chartagent.review import ReviewReport


@dataclass(frozen=True)
class ChartResult:
    """What a planner call hands back. Immutable — ``refresh`` returns a new one.

    ``review`` is the report for the returned artifact; ``create_chart`` always
    sets it and ``refresh`` never does. ``bound`` holds a recipe's rows after a
    ``refresh``, since a ``ChartRecipe`` stores no rows; it is ``None`` on an
    envelope result, whose rows ride in ``envelope.input["data"]``."""

    envelope: Envelope | None = None
    recipe: ChartRecipe | None = None
    review: ReviewReport | None = None
    bound: BoundRecipe | None = None

    def __post_init__(self) -> None:
        if (self.envelope is None) == (self.recipe is None):
            raise ValueError("ChartResult carries exactly one of envelope or recipe")
        if self.bound is not None and self.recipe is None:
            raise ValueError("bound rows belong to a recipe result")

    def refresh(self, data: DataSource) -> ChartResult:
        """Re-bind against new rows. Zero model calls, zero inference cost.

        Re-runs the stored transform (CONTEXT.md's zero-LLM refresh) —
        never re-plans, so there is no ``instruction=`` here — and returns a
        new result with ``review=None``: a copied report would be stale and a
        fresh one is ``create_chart``'s job.

        An envelope already carries bound rows at ``input["data"]``
        (``bind`` puts them there); ``InputFrame`` forbids inline ``data`` on
        the way back in, so that key is stripped before re-binding. A recipe
        goes through ``bind_recipe``, which never reads its document.
        """
        if self.recipe is not None:
            return ChartResult(recipe=self.recipe, bound=bind_recipe(self.recipe, data))
        assert self.envelope is not None
        stripped = {
            key: value for key, value in self.envelope.input.items() if key != "data"
        }
        return ChartResult(envelope=bind(stripped, data, backend=self.envelope.backend))
