from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests
import yaml
from flask import Flask, jsonify, render_template


CONFIG_PATH = os.environ.get("STATUS_CONFIG", "config.yaml")
FALLBACK_CONFIG = "config.example.yaml"

STATUS_ORDER = {
    "major_outage": 4,
    "partial_outage": 3,
    "degraded_performance": 2,
    "operational": 1,
    "unknown": 0,
}


def serialize_dt(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None


@dataclass
class ServiceConfig:
    name: str
    url: str
    method: str = "GET"
    expected_statuses: List[int] = field(default_factory=lambda: [200])
    component: str = "Service"
    timeout_seconds: Optional[int] = None
    headers: Dict[str, str] = field(default_factory=dict)
    verify_ssl: Any = True
    reachable_only: bool = False


@dataclass
class ServiceState:
    name: str
    component: str
    status: str
    url: str
    response_ms: Optional[int]
    message: str
    checked_at: datetime


@dataclass
class Incident:
    service: str
    status: str
    summary: str
    started_at: datetime


@dataclass
class StatusConfig:
    poll_interval_seconds: int = 60
    timeout_seconds: int = 5
    slow_threshold_ms: Optional[int] = None
    max_incidents: int = 20
    services: List[ServiceConfig] = field(default_factory=list)


def load_config() -> StatusConfig:
    """Load YAML config, falling back to the example if needed."""
    config_path = CONFIG_PATH if os.path.exists(CONFIG_PATH) else FALLBACK_CONFIG
    if not os.path.exists(config_path):
        raise FileNotFoundError(
            f"Config file not found at {CONFIG_PATH}. Provide one or copy {FALLBACK_CONFIG}."
        )

    with open(config_path, "r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}

    services = []
    for raw in data.get("services", []):
        services.append(
            ServiceConfig(
                name=raw.get("name", raw.get("component", "Service")),
                url=raw["url"],
                method=raw.get("method", "GET").upper(),
                expected_statuses=raw.get("expected_statuses", [200]),
                component=raw.get("component", "Service"),
                timeout_seconds=raw.get("timeout_seconds"),
                headers=raw.get("headers", {}),
                verify_ssl=raw.get("verify_ssl", True),
                reachable_only=raw.get("reachable_only", False),
            )
        )

    return StatusConfig(
        poll_interval_seconds=data.get("poll_interval_seconds", 60),
        timeout_seconds=data.get("timeout_seconds", 5),
        slow_threshold_ms=data.get("slow_threshold_ms"),
        max_incidents=data.get("max_incidents", 20),
        services=services,
    )


class HealthMonitor:
    def __init__(self, config: StatusConfig):
        self.config = config
        self.state: Dict[str, ServiceState] = {}
        self.incidents: List[Incident] = []
        self.last_updated: Optional[datetime] = None
        self.lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return

        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()

    def _poll_loop(self) -> None:
        # Run immediately at startup so the page isn't empty.
        self._poll_once()
        while True:
            time.sleep(self.config.poll_interval_seconds)
            self._poll_once()

    def _poll_once(self) -> None:
        for service in self.config.services:
            result = self._check_service(service)
            self._record_result(service, result)
        with self.lock:
            self.last_updated = datetime.now(timezone.utc)

    def _check_service(self, service: ServiceConfig) -> ServiceState:
        started = time.perf_counter()
        timeout = service.timeout_seconds or self.config.timeout_seconds
        headers = {"Accept": "application/json"}
        headers.update(service.headers)

        try:
            response = requests.request(
                service.method,
                service.url,
                headers=headers,
                timeout=timeout,
                verify=service.verify_ssl,
            )
            elapsed_ms = int((time.perf_counter() - started) * 1000)

            ok_status = (
                True if service.reachable_only else response.status_code in service.expected_statuses
            )
            slow = (
                self.config.slow_threshold_ms is not None
                and elapsed_ms > self.config.slow_threshold_ms
            )

            if ok_status and not slow:
                status = "operational"
                message = (
                    "Reachable"
                    if service.reachable_only
                    else f"{response.status_code} OK"
                )
            elif ok_status and slow:
                status = "degraded_performance"
                message = (
                    (
                        "Reachable but slow"
                        if service.reachable_only
                        else f"{response.status_code} OK but slow"
                    )
                    + f" ({elapsed_ms}ms > {self.config.slow_threshold_ms}ms)"
                )
            else:
                status = "partial_outage"
                message = f"Unexpected status {response.status_code}"

            return ServiceState(
                name=service.name,
                component=service.component,
                status=status,
                url=service.url,
                response_ms=elapsed_ms,
                message=message,
                checked_at=datetime.now(timezone.utc),
            )
        except requests.Timeout:
            return ServiceState(
                name=service.name,
                component=service.component,
                status="major_outage",
                url=service.url,
                response_ms=None,
                message=f"Timeout after {timeout}s",
                checked_at=datetime.now(timezone.utc),
            )
        except requests.RequestException as exc:
            return ServiceState(
                name=service.name,
                component=service.component,
                status="major_outage",
                url=service.url,
                response_ms=None,
                message=str(exc),
                checked_at=datetime.now(timezone.utc),
            )

    def _record_result(self, service: ServiceConfig, result: ServiceState) -> None:
        with self.lock:
            previous = self.state.get(service.name)
            self.state[service.name] = result

            if result.status != "operational":
                should_log = previous is None or previous.status == "operational"
                if should_log:
                    incident = Incident(
                        service=service.name,
                        status=result.status,
                        summary=result.message,
                        started_at=result.checked_at,
                    )
                    self.incidents.insert(0, incident)
                    self.incidents = self.incidents[: self.config.max_incidents]

    def snapshot(self) -> Dict[str, Any]:
        with self.lock:
            services = list(self.state.values())
            incidents = list(self.incidents)
            last_updated = self.last_updated

        overall_status = self._overall_status(services)
        return {
            "services": services,
            "incidents": incidents,
            "last_updated": last_updated,
            "overall": overall_status,
        }

    def _overall_status(self, services: List[ServiceState]) -> str:
        if not services:
            return "unknown"
        return max(
            (service.status for service in services),
            key=lambda status: STATUS_ORDER.get(status, 0),
            default="unknown",
        )


config = load_config()
monitor = HealthMonitor(config)
monitor.start()

app = Flask(__name__)


@app.template_filter("fmt_time")
def fmt_time(value: Optional[datetime]) -> str:
    if not value:
        return "–"
    return value.astimezone(timezone.utc).strftime("%b %d, %H:%M UTC")


@app.template_filter("status_label")
def status_label(status: str) -> str:
    return {
        "operational": "All Systems Operational",
        "degraded_performance": "Degraded Performance",
        "partial_outage": "Partial Outage",
        "major_outage": "Major Outage",
        "unknown": "Status Unknown",
    }.get(status, status.title())


@app.route("/")
def index() -> str:
    snapshot = monitor.snapshot()
    return render_template(
        "index.html",
        services=snapshot["services"],
        incidents=snapshot["incidents"],
        last_updated=snapshot["last_updated"],
        overall=snapshot["overall"],
        poll_interval=config.poll_interval_seconds,
    )


@app.route("/errors")
def errors() -> str:
    snapshot = monitor.snapshot()
    if snapshot["incidents"]:
        latest = snapshot["incidents"][0]
        message = f"{latest.service}: {latest.summary}"
    else:
        message = "No recorded incidents."

    return render_template(
        "error.html",
        message=message,
        overall=snapshot["overall"],
        last_updated=snapshot["last_updated"],
    )


@app.route("/api/status")
def api_status() -> Any:
    snapshot = monitor.snapshot()
    return jsonify(
        {
            "overall_status": snapshot["overall"],
            "last_updated": serialize_dt(snapshot["last_updated"]),
            "services": [
                {
                    "name": service.name,
                    "component": service.component,
                    "status": service.status,
                    "url": service.url,
                    "response_ms": service.response_ms,
                    "message": service.message,
                    "checked_at": serialize_dt(service.checked_at),
                }
                for service in snapshot["services"]
            ],
            "incidents": [
                {
                    "service": incident.service,
                    "status": incident.status,
                    "summary": incident.summary,
                    "started_at": serialize_dt(incident.started_at),
                }
                for incident in snapshot["incidents"]
            ],
        }
    )


@app.route("/healthz")
def healthcheck() -> Any:
    return jsonify({"status": "ok"})


@app.errorhandler(Exception)
def handle_error(error: Exception):
    app.logger.exception("Unhandled error: %s", error)
    snapshot = monitor.snapshot()
    return (
        render_template(
            "error.html",
            message=str(error),
            overall=snapshot["overall"],
            last_updated=snapshot["last_updated"],
        ),
        500,
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 9090))
    app.run(host="0.0.0.0", port=port, debug=False)
