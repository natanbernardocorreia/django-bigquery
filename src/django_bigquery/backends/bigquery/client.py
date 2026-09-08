from abc import ABC

from django.db.backends.base.client import BaseDatabaseClient


class DatabaseClient(BaseDatabaseClient, ABC):
    pass
