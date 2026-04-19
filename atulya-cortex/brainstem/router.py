"""router.py — the Stimulus router.

Every `Stimulus` first lands here. The router:

1. Asks the `ReflexChain` whether to allow / deny / pair / sandbox.
2. On `allow` (or `sandbox`), hands the stimulus to the cortex.
3. On `deny`, drops it (logs only).
4. On `pair`, emits a friendly Intent back through `Reply` asking the
   operator to confirm the pairing; the operator approves out of band.

The router is the *only* place that knows about the bridge between the
brainstem and the cortex. Senors hand stimuli in, motors take intents out;
the router glues them together.

Naming voice: `Router.route` is the verb the rest of the brain calls.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from cortex.bus import Action, Intent, Reflex, Stimulus

CortexCallable = Callable[[Stimulus, Reflex], Awaitable[Intent | None]]
MotorCallable = Callable[[Intent], Awaitable[Any]]


@dataclass
class RoutingOutcome:
    """What happened to one stimulus."""

    stimulus: Stimulus
    reflex: Reflex
    intent: Intent | None = None
    motor_result: Any = None
    notes: list[str] = field(default_factory=list)


class Router:
    """Wires Sensors -> Reflexes -> Cortex -> Motors."""

    def __init__(
        self,
        *,
        reflexes: Any,
        cortex: CortexCallable,
        reply_motor: MotorCallable | None = None,
        pairing_message: str = ("This channel isn't paired yet. The operator will approve it shortly."),
    ) -> None:
        self._reflexes = reflexes
        self._cortex = cortex
        self._reply_motor = reply_motor
        self._pairing_message = pairing_message

    async def route(self, stimulus: Stimulus) -> RoutingOutcome:
        reflex: Reflex = await self._reflexes.evaluate(stimulus)
        outcome = RoutingOutcome(stimulus=stimulus, reflex=reflex)

        if reflex.decision == "deny":
            outcome.notes.append(f"denied: {reflex.reason}")
            return outcome

        if reflex.decision == "pair":
            outcome.notes.append(f"pairing: {reflex.reason}")
            if self._reply_motor is not None:
                pair_intent = Intent(
                    action=Action(kind="reply", payload={"text": self._pairing_message}),
                    channel=stimulus.channel,
                    sender=stimulus.sender,
                )
                outcome.intent = pair_intent
                outcome.motor_result = await self._reply_motor(pair_intent)
            return outcome

        intent = await self._cortex(stimulus, reflex)
        if intent is None:
            outcome.notes.append("cortex returned no intent (noop)")
            return outcome

        outcome.intent = intent
        if self._reply_motor is not None and intent.action.kind == "reply":
            outcome.motor_result = await self._reply_motor(intent)
        return outcome


__all__ = ["CortexCallable", "MotorCallable", "Router", "RoutingOutcome"]
