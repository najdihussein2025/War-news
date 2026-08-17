"""Logs interfaces."""
from app.logs.interfaces.login_log_repository_interface import LoginLogRepositoryInterface
from app.logs.interfaces.ingestion_log_repository_interface import IngestionLogRepositoryInterface

__all__ = ["LoginLogRepositoryInterface", "IngestionLogRepositoryInterface"]
