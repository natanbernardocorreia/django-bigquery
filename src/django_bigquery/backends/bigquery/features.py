from django.db.backends.base.features import BaseDatabaseFeatures


class DatabaseFeatures(BaseDatabaseFeatures):
    max_query_params = 10000
    supports_temporal_subtraction = True
    supports_over_clause = True
