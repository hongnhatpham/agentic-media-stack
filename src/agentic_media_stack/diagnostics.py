from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence


@dataclass(frozen=True)
class ServiceProbe:
    name: str
    url: str
    check: Callable[[], bool]


@dataclass(frozen=True)
class Diagnostic:
    service: str
    ok: bool
    explanation: str
    recommended_action: str
    restart_allowed: bool = False


def diagnose(
    probes: Sequence[ServiceProbe], *, restart_count: int = 0, restart_cap: int = 2
) -> list[Diagnostic]:
    results: list[Diagnostic] = []
    statuses: dict[str, bool] = {}
    for probe in probes:
        try:
            statuses[probe.name] = bool(probe.check())
        except Exception as exc:  # diagnostics must report a broken probe, not crash the run
            statuses[probe.name] = False
            results.append(
                Diagnostic(
                    probe.name, False, f"probe failed: {exc}", "inspect logs and network route"
                )
            )
            continue
        if statuses[probe.name]:
            results.append(Diagnostic(probe.name, True, "service responded", "no action"))
        else:
            results.append(
                Diagnostic(
                    probe.name,
                    False,
                    "service did not respond",
                    "inspect network, DNS and service logs",
                )
            )
    if (
        statuses.get("gluetun") is False
        and statuses.get("flaresolverr") is False
        and statuses.get("prowlarr") is False
    ):
        action = "repair the Gluetun route and DNS, then recheck FlareSolverr and Prowlarr"
        if restart_count >= restart_cap:
            action += "; restart cap reached, do not restart automatically"
        results.append(
            Diagnostic(
                "failure-pattern",
                False,
                "Gluetun, FlareSolverr and Prowlarr are all unavailable",
                action,
                False,
            )
        )
    return results
