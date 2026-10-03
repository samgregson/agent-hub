from agent_hub_api.modules.observability import MetricsRegistry


def test_metrics_group_unknown_methods_without_leaking_values() -> None:
    metrics = MetricsRegistry()
    metrics.observe("SECRET-ONE", "unmatched", 405, 0.01)
    metrics.observe("SECRET-TWO", "unmatched", 405, 0.02)

    rendered = metrics.render()
    assert (
        'agent_hub_http_requests_total{method="OTHER",route="unmatched",status="405"} 2' in rendered
    )
    assert "SECRET-ONE" not in rendered
    assert "SECRET-TWO" not in rendered
