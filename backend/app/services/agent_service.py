"""Agent manager - manages agent instances per session"""
import threading
from typing import Dict, Optional


class AgentManager:
    def __init__(self):
        self._lock = threading.RLock()
        self._instances: Dict[str, object] = {}
        # Lazy import agent classes to avoid circular imports
        self._agent_classes = {
            "naive_rag": "app.agents.naive_rag_agent.NaiveRagAgent",
            "graph_rag": "app.agents.graph_agent.GraphAgent",
            "hybrid_rag": "app.agents.hybrid_agent.HybridAgent",
            "fusion_rag": "app.agents.fusion_agent.FusionAgent",
            "deep_research": "app.agents.deep_research_agent.DeepResearchAgent",
        }

    def _load_class(self, class_path: str):
        """Dynamically import and return agent class"""
        module_path, class_name = class_path.rsplit(".", 1)
        import importlib
        module = importlib.import_module(module_path)
        return getattr(module, class_name)

    def get_agent(self, agent_type: str, session_id: str = "default"):
        """Get or create agent instance for session"""
        if agent_type not in self._agent_classes:
            raise ValueError(f"Unknown agent type: {agent_type}")
        key = f"{agent_type}:{session_id}"
        with self._lock:
            if key not in self._instances:
                cls = self._load_class(self._agent_classes[agent_type])
                self._instances[key] = cls()
            return self._instances[key]

    def close_all(self):
        with self._lock:
            self._instances.clear()


agent_manager = AgentManager()
