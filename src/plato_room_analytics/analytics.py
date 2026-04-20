"""Room usage analytics and trend tracking."""
import time
from dataclasses import dataclass, field
from collections import defaultdict
from enum import Enum

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
