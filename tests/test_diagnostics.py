from agentic_media_stack.diagnostics import ServiceProbe, diagnose


def test_failure_pattern_is_explained_and_never_auto_restarts():
    probes = [
        ServiceProbe(name, f"http://{name}", lambda: False)
        for name in ("gluetun", "flaresolverr", "prowlarr")
    ]
    results = diagnose(probes, restart_count=2, restart_cap=2)
    pattern = next(item for item in results if item.service == "failure-pattern")
    assert "restart cap reached" in pattern.recommended_action
    assert pattern.restart_allowed is False


def test_probe_errors_are_reported():
    results = diagnose([ServiceProbe("prowlarr", "http://prowlarr", lambda: 1 / 0)])
    assert results[0].ok is False
    assert "probe failed" in results[0].explanation
