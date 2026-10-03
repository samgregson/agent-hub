"""Process-local HTTP counters and latency histograms with bounded labels."""

from dataclasses import dataclass, field

_BUCKETS = (0.01, 0.05, 0.1, 0.5, 1.0, 5.0, 30.0)
_METHODS = {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}


@dataclass(slots=True)
class _Sample:
    count: int = 0
    duration_sum: float = 0.0
    buckets: list[int] = field(default_factory=lambda: [0] * len(_BUCKETS))


class MetricsRegistry:
    """One registry per API process; labels never include user-controlled values."""

    def __init__(self) -> None:
        self._samples: dict[tuple[str, str, int], _Sample] = {}

    def observe(self, method: str, route: str, status: int, duration_seconds: float) -> None:
        key = (method if method in _METHODS else "OTHER", route, status)
        sample = self._samples.setdefault(key, _Sample())
        sample.count += 1
        sample.duration_sum += duration_seconds
        for index, upper_bound in enumerate(_BUCKETS):
            if duration_seconds <= upper_bound:
                sample.buckets[index] += 1

    def render(self) -> str:
        lines = [
            "# HELP agent_hub_http_requests_total Completed HTTP requests.",
            "# TYPE agent_hub_http_requests_total counter",
        ]
        for (method, route, status), sample in sorted(self._samples.items()):
            labels = _labels(method, route, status)
            lines.append(f"agent_hub_http_requests_total{{{labels}}} {sample.count}")
        lines.extend(
            [
                "# HELP agent_hub_http_request_duration_seconds HTTP request duration.",
                "# TYPE agent_hub_http_request_duration_seconds histogram",
            ]
        )
        for (method, route, status), sample in sorted(self._samples.items()):
            labels = _labels(method, route, status)
            for index, upper_bound in enumerate(_BUCKETS):
                lines.append(
                    "agent_hub_http_request_duration_seconds_bucket"
                    f'{{{labels},le="{upper_bound:g}"}} {sample.buckets[index]}'
                )
            lines.append(
                "agent_hub_http_request_duration_seconds_bucket"
                f'{{{labels},le="+Inf"}} {sample.count}'
            )
            lines.append(
                f"agent_hub_http_request_duration_seconds_sum{{{labels}}} {sample.duration_sum:.6f}"
            )
            lines.append(
                f"agent_hub_http_request_duration_seconds_count{{{labels}}} {sample.count}"
            )
        return "\n".join(lines) + "\n"


def _labels(method: str, route: str, status: int) -> str:
    return f'method="{_escape(method)}",route="{_escape(route)}",status="{status}"'


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')
