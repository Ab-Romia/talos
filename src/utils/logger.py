"""
Structured logging setup for the RAG system.

Provides consistent logging across all components with support for
different output formats and log levels.
"""

import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from src.core.config_loader import LoggingConfig


class RAGLogger:
    """
    Custom logger wrapper with structured logging support.

    Provides consistent logging format and metrics collection.
    """

    def __init__(
        self,
        name: str,
        config: Optional[LoggingConfig] = None,
    ):
        self.name = name
        self.config = config or LoggingConfig()
        self._logger = self._setup_logger()
        self._metrics: Dict[str, Any] = {}

    def _setup_logger(self) -> logging.Logger:
        """Set up the logger with configured handlers."""
        logger = logging.getLogger(self.name)
        logger.setLevel(getattr(logging, self.config.level))

        # Clear existing handlers
        logger.handlers = []

        # Console handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(getattr(logging, self.config.level))

        # Format
        formatter = logging.Formatter(self.config.format)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

        # File handler if configured
        if self.config.file_path:
            file_path = Path(self.config.file_path)
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(file_path)
            file_handler.setLevel(getattr(logging, self.config.level))
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)

        return logger

    def debug(self, message: str, **kwargs) -> None:
        """Log debug message."""
        self._log(logging.DEBUG, message, **kwargs)

    def info(self, message: str, **kwargs) -> None:
        """Log info message."""
        self._log(logging.INFO, message, **kwargs)

    def warning(self, message: str, **kwargs) -> None:
        """Log warning message."""
        self._log(logging.WARNING, message, **kwargs)

    def error(self, message: str, **kwargs) -> None:
        """Log error message."""
        self._log(logging.ERROR, message, **kwargs)

    def critical(self, message: str, **kwargs) -> None:
        """Log critical message."""
        self._log(logging.CRITICAL, message, **kwargs)

    def exception(self, message: str, **kwargs) -> None:
        """Log exception with traceback."""
        self._logger.exception(self._format_message(message, **kwargs))

    def _log(self, level: int, message: str, **kwargs) -> None:
        """Internal log method with metadata."""
        formatted_message = self._format_message(message, **kwargs)
        self._logger.log(level, formatted_message)

    def _format_message(self, message: str, **kwargs) -> str:
        """Format message with additional context."""
        if kwargs:
            context = " | ".join(f"{k}={v}" for k, v in kwargs.items())
            return f"{message} | {context}"
        return message

    def log_metric(self, metric_name: str, value: Any, tags: Optional[Dict[str, str]] = None) -> None:
        """Log a metric value."""
        if not self.config.enable_metrics:
            return

        timestamp = datetime.now().isoformat()
        metric_key = f"{metric_name}_{timestamp}"
        self._metrics[metric_key] = {
            "value": value,
            "tags": tags or {},
            "timestamp": timestamp,
        }

        self.debug(f"METRIC: {metric_name}={value}", **(tags or {}))

    def log_latency(self, operation: str, latency_ms: float) -> None:
        """Log operation latency."""
        self.log_metric(f"{operation}_latency_ms", latency_ms)

    def log_retrieval(
        self,
        query: str,
        num_results: int,
        method: str,
        latency_ms: float,
    ) -> None:
        """Log retrieval operation."""
        self.info(
            "Retrieval completed",
            query=query[:50] + "..." if len(query) > 50 else query,
            num_results=num_results,
            method=method,
            latency_ms=f"{latency_ms:.2f}",
        )
        self.log_latency("retrieval", latency_ms)

    def log_generation(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        latency_ms: float,
        model: str,
    ) -> None:
        """Log generation operation."""
        self.info(
            "Generation completed",
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            model=model,
            latency_ms=f"{latency_ms:.2f}",
        )
        self.log_latency("generation", latency_ms)

    def get_metrics(self) -> Dict[str, Any]:
        """Get collected metrics."""
        return self._metrics.copy()

    def clear_metrics(self) -> None:
        """Clear collected metrics."""
        self._metrics.clear()


# Module-level logger cache
_loggers: Dict[str, RAGLogger] = {}


def get_logger(name: str, config: Optional[LoggingConfig] = None) -> RAGLogger:
    """
    Get or create a logger instance.

    Args:
        name: Logger name (usually module name)
        config: Optional logging configuration

    Returns:
        RAGLogger instance
    """
    if name not in _loggers:
        _loggers[name] = RAGLogger(name, config)
    return _loggers[name]


def setup_logging(config: LoggingConfig) -> None:
    """
    Set up global logging configuration.

    Args:
        config: Logging configuration
    """
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, config.level))

    # Clear existing handlers
    root_logger.handlers = []

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(getattr(logging, config.level))
    formatter = logging.Formatter(config.format)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # File handler
    if config.file_path:
        file_path = Path(config.file_path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(file_path)
        file_handler.setLevel(getattr(logging, config.level))
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
