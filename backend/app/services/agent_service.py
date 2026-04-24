"""Agent manager - manages agent instances per session"""

import threading
import time
from typing import Dict

from app.config.settings import settings


class AgentManager:
    def __init__(self):
        self._lock = threading.RLock()
        self._instances: Dict[str, tuple[object, float]] = {}
        self._agent_classes = {
            "naive_rag": "app.agents.naive_rag_agent.NaiveRagAgent",
            "graph_rag": "app.agents.graph_agent.GraphAgent",
            "hybrid_rag": "app.agents.hybrid_agent.HybridAgent",
            "fusion_rag": "app.agents.fusion_agent.FusionAgent",
            "deep_research": "app.agents.deep_research_agent.DeepResearchAgent",
        }

    def _load_class(self, class_path: str):
        """Dynamically import and return agent class."""
        import importlib

        module_path, class_name = class_path.rsplit(".", 1)
        module = importlib.import_module(module_path)
        return getattr(module, class_name)

    def _prune_locked(self, now: float) -> None:
        ttl_seconds = max(60, int(settings.security.agent_ttl_seconds))
        max_size = max(8, int(settings.security.agent_cache_size))

        expired_keys = [
            key
            for key, (_, last_used_at) in self._instances.items()
            if now - last_used_at > ttl_seconds
        ]
        for key in expired_keys:
            self._instances.pop(key, None)

        while len(self._instances) > max_size:
            oldest_key = min(
                self._instances,
                key=lambda item_key: self._instances[item_key][1],
            )
            self._instances.pop(oldest_key, None)

    def get_agent(self, agent_type: str, session_id: str = "default"):
        """Get or create agent instance for session."""
        if agent_type not in self._agent_classes:
            raise ValueError(f"Unknown agent type: {agent_type}")

        now = time.time()
        key = f"{agent_type}:{session_id}"
        with self._lock:
            self._prune_locked(now)
            if key not in self._instances:
                cls = self._load_class(self._agent_classes[agent_type])
                self._instances[key] = (cls(), now)
                return self._instances[key][0]

            agent, _last_used_at = self._instances[key]
            self._instances[key] = (agent, now)
            return agent

    def close_all(self):
        with self._lock:
            self._instances.clear()


agent_manager = AgentManager()
