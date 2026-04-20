"""Room usage analytics and trend tracking."""
import time
import csv
import json
import io
from dataclasses import dataclass, field, asdict
from collections import defaultdict
from datetime import datetime, timezone
from enum import Enum
from typing import Literal


class Trend(Enum):
    RISING = "rising"
    FALLING = "falling"
    STABLE = "stable"


@dataclass
class Metric:
    name: str
    value: float
    timestamp: float = field(default_factory=time.time)
    tags: dict = field(default_factory=dict)


@dataclass
class AgentActivity:
    agent: str
    actions: int = 0
    tiles_created: int = 0
    tiles_accessed: int = 0
    time_spent: float = 0.0
    last_active: float = field(default_factory=time.time)


class RoomAnalytics:
    def __init__(self, window_size: int = 100):
        self.window_size = window_size
        self._metrics: dict[str, list[Metric]] = defaultdict(list)
        self._agents: dict[str, AgentActivity] = {}
        self._events: list[dict] = []

    def record(self, name: str, value: float, tags: dict = None):
        m = Metric(name=name, value=value, tags=tags or {})
        history = self._metrics[name]
        history.append(m)
        if len(history) > self.window_size:
            self._metrics[name] = history[-self.window_size:]

    def track_agent(self, agent: str, action: str = "", tiles_created: int = 0, tiles_accessed: int = 0):
        if agent not in self._agents:
            self._agents[agent] = AgentActivity(agent=agent)
        a = self._agents[agent]
        a.actions += 1
        a.tiles_created += tiles_created
        a.tiles_accessed += tiles_accessed
        a.last_active = time.time()
        self._events.append({"agent": agent, "action": action, "time": time.time()})
        if len(self._events) > 1000:
            self._events = self._events[-1000:]

    def trend(self, name: str) -> Trend:
        history = self._metrics.get(name, [])
        if len(history) < 3:
            return Trend.STABLE
        recent = [m.value for m in history[-5:]]
        older = [m.value for m in history[-10:-5]] if len(history) >= 10 else history[:len(history)-5]
        if not older:
            return Trend.STABLE
        recent_avg = sum(recent) / len(recent)
        older_avg = sum(older) / len(older)
        if older_avg == 0:
            return Trend.STABLE if recent_avg == 0 else Trend.RISING
        change = (recent_avg - older_avg) / older_avg
        if change > 0.1:
            return Trend.RISING
        elif change < -0.1:
            return Trend.FALLING
        return Trend.STABLE

    def summary(self, name: str) -> dict:
        history = self._metrics.get(name, [])
        if not history:
            return {"name": name, "count": 0, "min": 0, "max": 0, "avg": 0, "trend": "stable"}
        values = [m.value for m in history]
        return {"name": name, "count": len(values), "min": min(values),
                "max": max(values), "avg": sum(values)/len(values),
                "trend": self.trend(name).value}

    def top_agents(self, n: int = 5, metric: str = "actions") -> list[dict]:
        agents = sorted(self._agents.values(), key=lambda a: getattr(a, metric, 0), reverse=True)
        return [{"agent": a.agent, metric: getattr(a, metric, 0)} for a in agents[:n]]

    @property
    def stats(self) -> dict:
        return {"metrics_tracked": len(self._metrics),
                "total_datapoints": sum(len(v) for v in self._metrics.values()),
                "agents_tracked": len(self._agents),
                "events": len(self._events)}


# ---------------------------------------------------------------------------
# 1. Time-series aggregation
# ---------------------------------------------------------------------------

Bucket = Literal["hourly", "daily", "weekly"]


class TimeSeriesAggregator:
    """Aggregate metrics into hourly, daily, or weekly buckets."""

    _BUCKET_SECONDS = {"hourly": 3600, "daily": 86400, "weekly": 604800}

    def __init__(self, metrics: list[Metric]):
        self._metrics = metrics

    @staticmethod
    def _bucket_ts(ts: float, bucket: Bucket) -> float:
        secs = TimeSeriesAggregator._BUCKET_SECONDS[bucket]
        return (ts // secs) * secs

    def aggregate(self, bucket: Bucket) -> dict[float, dict]:
        """Return {bucket_start: {count, sum, min, max, avg}}."""
        buckets: dict[float, list[float]] = defaultdict(list)
        for m in self._metrics:
            buckets[self._bucket_ts(m.timestamp, bucket)].append(m.value)

        result = {}
        for bkt, values in sorted(buckets.items()):
            result[bkt] = {
                "count": len(values),
                "sum": sum(values),
                "min": min(values),
                "max": max(values),
                "avg": sum(values) / len(values),
            }
        return result

    def to_list(self, bucket: Bucket) -> list[dict]:
        """Human-readable list with ISO timestamps."""
        out = []
        for bkt, stats in sorted(self.aggregate(bucket).items()):
            row = {"timestamp": datetime.fromtimestamp(bkt, tz=timezone.utc).isoformat(), **stats}
            out.append(row)
        return out


# ---------------------------------------------------------------------------
# 2. Funnel analysis
# ---------------------------------------------------------------------------

class FunnelStage:
    def __init__(self, name: str):
        self.name = name
        self._agents: set[str] = set()

    def add(self, agent: str):
        self._agents.add(agent)

    @property
    def count(self) -> int:
        return len(self._agents)

    def __repr__(self):
        return f"FunnelStage({self.name!r}, count={self.count})"


class Funnel:
    """Track conversion of agents through an ordered sequence of stages."""

    def __init__(self, stage_names: list[str]):
        self.stages = [FunnelStage(name) for name in stage_names]
        self._stage_index = {name: idx for idx, name in enumerate(stage_names)}

    def record(self, agent: str, stage_name: str):
        idx = self._stage_index.get(stage_name)
        if idx is None:
            raise ValueError(f"Unknown stage: {stage_name}")
        # Agent completes this stage and all preceding stages
        for i in range(idx + 1):
            self.stages[i].add(agent)

    def analysis(self) -> list[dict]:
        out = []
        for i, stage in enumerate(self.stages):
            conversion = 1.0 if i == 0 else (stage.count / self.stages[0].count)
            dropoff = 0.0 if i == 0 else ((self.stages[i - 1].count - stage.count) / self.stages[i - 1].count)
            out.append({
                "stage": stage.name,
                "count": stage.count,
                "conversion_rate": round(conversion, 4),
                "dropoff_rate": round(dropoff, 4),
            })
        return out


# ---------------------------------------------------------------------------
# 3. Cohort analysis
# ---------------------------------------------------------------------------

class CohortAnalyzer:
    """Group agents by join date (daily bucket) and track retention."""

    def __init__(self):
        self._join_ts: dict[str, float] = {}
        self._activity: dict[str, list[float]] = defaultdict(list)

    def register(self, agent: str, timestamp: float = None):
        if agent not in self._join_ts:
            self._join_ts[agent] = timestamp or time.time()

    def record_activity(self, agent: str, timestamp: float = None):
        ts = timestamp or time.time()
        self.register(agent, ts)
        self._activity[agent].append(ts)

    @staticmethod
    def _day_bucket(ts: float) -> float:
        return (ts // 86400) * 86400

    def _cohort_key(self, agent: str) -> str:
        return datetime.fromtimestamp(self._join_ts[agent], tz=timezone.utc).strftime("%Y-%m-%d")

    def retention(self) -> dict[str, dict[int, int]]:
        """Return {cohort_date: {day_offset: active_agents}}."""
        cohorts: dict[str, dict[str, set[int]]] = defaultdict(lambda: defaultdict(set))
        for agent, times in self._activity.items():
            cohort = self._cohort_key(agent)
            join_day = self._day_bucket(self._join_ts[agent])
            for ts in times:
                day_offset = int((self._day_bucket(ts) - join_day) / 86400)
                cohorts[cohort][agent].add(day_offset)

        result = {}
        for cohort, agent_days in sorted(cohorts.items()):
            result[cohort] = {}
            for day_offset in range(max((max(days) for days in agent_days.values()), default=0) + 1):
                result[cohort][day_offset] = sum(1 for days in agent_days.values() if day_offset in days)
        return result

    def analysis(self) -> list[dict]:
        """Flatten retention into a list of rows."""
        rows = []
        for cohort, days in sorted(self.retention().items()):
            total = days.get(0, 0)
            for day_offset, count in sorted(days.items()):
                rate = round(count / total, 4) if total else 0.0
                rows.append({
                    "cohort": cohort,
                    "day": day_offset,
                    "active": count,
                    "retention_rate": rate,
                })
        return rows


# ---------------------------------------------------------------------------
# 4. Anomaly detection (simple threshold-based)
# ---------------------------------------------------------------------------

@dataclass
class Anomaly:
    metric_name: str
    timestamp: float
    value: float
    expected_low: float
    expected_high: float
    severity: str  # "warning" | "critical"


class ThresholdAnomalyDetector:
    """Flag values outside [mean - k*std, mean + k*std]."""

    def __init__(self, k_warning: float = 2.0, k_critical: float = 3.0):
        self.k_warning = k_warning
        self.k_critical = k_critical

    def _stats(self, values: list[float]) -> tuple[float, float]:
        n = len(values)
        if n == 0:
            return 0.0, 0.0
        mean = sum(values) / n
        variance = sum((x - mean) ** 2 for x in values) / n
        return mean, variance ** 0.5

    def detect(self, metrics: list[Metric]) -> list[Anomaly]:
        if not metrics:
            return []
        values = [m.value for m in metrics]
        mean, std = self._stats(values)
        anomalies = []
        for m in metrics:
            deviation = abs(m.value - mean)
            if std > 0 and deviation > self.k_critical * std:
                anomalies.append(Anomaly(
                    metric_name=m.name,
                    timestamp=m.timestamp,
                    value=m.value,
                    expected_low=round(mean - self.k_critical * std, 4),
                    expected_high=round(mean + self.k_critical * std, 4),
                    severity="critical",
                ))
            elif std > 0 and deviation > self.k_warning * std:
                anomalies.append(Anomaly(
                    metric_name=m.name,
                    timestamp=m.timestamp,
                    value=m.value,
                    expected_low=round(mean - self.k_warning * std, 4),
                    expected_high=round(mean + self.k_warning * std, 4),
                    severity="warning",
                ))
        return anomalies


# ---------------------------------------------------------------------------
# 5. Export to JSON/CSV
# ---------------------------------------------------------------------------

class AnalyticsExporter:
    """Export analytics artefacts to JSON or CSV."""

    @staticmethod
    def to_json(data, pretty: bool = False) -> str:
        """Serialize *data* (dict or list) to a JSON string."""
        if pretty:
            return json.dumps(data, indent=2, default=str)
        return json.dumps(data, default=str)

    @staticmethod
    def to_csv(rows: list[dict]) -> str:
        """Flatten list of dicts to a CSV string."""
        if not rows:
            return ""
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
        return output.getvalue()

    @classmethod
    def export_metrics(cls, metrics: list[Metric], fmt: Literal["json", "csv"], pretty: bool = False) -> str:
        rows = [asdict(m) for m in metrics]
        return cls.to_json(rows, pretty=pretty) if fmt == "json" else cls.to_csv(rows)

    @classmethod
    def export_summary(cls, analytics: RoomAnalytics, fmt: Literal["json", "csv"], pretty: bool = False) -> str:
        rows = [analytics.summary(name) for name in analytics._metrics]
        return cls.to_json(rows, pretty=pretty) if fmt == "json" else cls.to_csv(rows)

    @classmethod
    def export_funnel(cls, funnel: Funnel, fmt: Literal["json", "csv"], pretty: bool = False) -> str:
        rows = funnel.analysis()
        return cls.to_json(rows, pretty=pretty) if fmt == "json" else cls.to_csv(rows)

    @classmethod
    def export_cohorts(cls, cohort_analyzer: CohortAnalyzer, fmt: Literal["json", "csv"], pretty: bool = False) -> str:
        rows = cohort_analyzer.analysis()
        return cls.to_json(rows, pretty=pretty) if fmt == "json" else cls.to_csv(rows)

    @classmethod
    def export_anomalies(cls, anomalies: list[Anomaly], fmt: Literal["json", "csv"], pretty: bool = False) -> str:
        rows = [asdict(a) for a in anomalies]
        return cls.to_json(rows, pretty=pretty) if fmt == "json" else cls.to_csv(rows)
