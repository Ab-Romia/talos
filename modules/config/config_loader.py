import yaml
from typing import Dict, Any
import os


class RAGConfig:
    """Configuration loader for Modular RAG system"""

    def __init__(self, config_path: str = None):
        if config_path is None:
            config_path = "config/rag_config.yaml"

        if not os.path.exists(config_path):
            raise FileNotFoundError(f"Config file not found: {config_path}")

        with open(config_path, 'r') as f:
            self.config = yaml.safe_load(f)

    @property
    def pipeline_type(self) -> str:
        return self.config.get('pipeline', {}).get('type', 'simple')

    @property
    def retriever_config(self) -> Dict[str, Any]:
        return self.config.get('retriever', {})

    @property
    def reranker_config(self) -> Dict[str, Any]:
        return self.config.get('reranker', {})

    @property
    def generator_config(self) -> Dict[str, Any]:
        return self.config.get('generator', {})

    @property
    def query_processor_config(self) -> Dict[str, Any]:
        return self.config.get('query_processor', {})

    @property
    def orchestration_config(self) -> Dict[str, Any]:
        return self.config.get('orchestration', {})

    def is_reranker_enabled(self) -> bool:
        return self.reranker_config.get('enabled', False)

    def is_query_processing_enabled(self) -> bool:
        return self.query_processor_config.get('enabled', False)

    def is_routing_enabled(self) -> bool:
        return self.orchestration_config.get('routing_enabled', False)
