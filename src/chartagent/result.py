"""``ChartResult`` — the planner's result type (ADR-0020 Decision 2).

A thin wrapper over :class:`~chartagent.envelope.Envelope`, not itself a
wire type: ``Envelope``'s wire format is frozen at three keys (ADR-0005)
and ``ChartResult`` never widens that by flattening fields onto itself.
Studio serialises by reaching into ``.envelope.to_dict()``.
"""

from __future__ import annotations

from dataclasses import dataclass

from chartagent.bind import DataSource, bind
from chartagent.envelope import Envelope


@dataclass(frozen=True)
class ChartResult:
    """What a planner call hands back. Immutable — ``refresh`` returns a new one."""

    envelope: Envelope

    def refresh(self, data: DataSource) -> ChartResult:
        """Re-bind against new rows. Zero model calls, zero inference cost.

        Re-runs the stored transform (CONTEXT.md's zero-LLM refresh) —
        never re-plans, so there is no ``instruction=`` here. The stored
        frame carries bound rows at ``input["data"]`` already
        (``bind`` puts them there); ``InputFrame`` forbids inline
        ``data`` on the way back in, so that key is stripped before
        re-binding, not passed through.
        """
        stripped = {
            key: value for key, value in self.envelope.input.items() if key != "data"
        }
        new_envelope = bind(stripped, data, backend=self.envelope.backend)
        return ChartResult(envelope=new_envelope)
