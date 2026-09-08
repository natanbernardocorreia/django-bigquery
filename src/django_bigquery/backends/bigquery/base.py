"""
BigQuery backend for the bigquery module in the standard library.
"""

import decimal
import itertools
import re
import warnings
from abc import ABC
from datetime import date, datetime
from sqlite3 import dbapi2 as Database

from django.core.exceptions import ImproperlyConfigured
from django.db.backends.base.base import BaseDatabaseWrapper
from django.utils.dateparse import parse_datetime, parse_time
from google.cloud import bigquery

from .client import DatabaseClient
from .creation import DatabaseCreation
from .features import DatabaseFeatures
from .introspection import DatabaseIntrospection
from .operations import DatabaseOperations

warnings.filterwarnings("ignore", message="Your application has authenticated using")


def decoder(conv_func):
    """
    Convert bytestrings from Python's sqlite3 interface to a regular string.
    """
    return lambda s: conv_func(s.decode())


Database.register_converter("bool", b"1".__eq__)
Database.register_converter("time", decoder(parse_time))
Database.register_converter("datetime", decoder(parse_datetime))
Database.register_converter("timestamp", decoder(parse_datetime))

Database.register_adapter(decimal.Decimal, str)


class DatabaseWrapper(BaseDatabaseWrapper, ABC):
    vendor = "bigquery"
    display_name = "BigQuery"
    operators = {
        "exact": "= %s",
        "iexact": "LIKE %s",
        "contains": "LIKE %s",
        "icontains": "LIKE %s",
        "regex": "REGEXP_CONTAINS(col, %s)",
        "iregex": "REGEXP_CONTAINS(col, %s, 'i')",
        "gt": "> %s",
        "gte": ">= %s",
        "lt": "< %s",
        "lte": "<= %s",
        "startswith": "LIKE %s",
        "endswith": "LIKE %s",
        "istartswith": "LIKE %s",
        "iendswith": "LIKE %s",
    }
    # The patterns below are used to generate SQL pattern lookup clauses when
    # the right-hand side of the lookup isn't a raw string (it might be an expression
    # or the result of a bilateral transformation).
    # In those cases, special characters for LIKE operators (e.g. \, *, _) should be
    # escaped on database side.
    #
    # Note: we use str.format() here for readability as '%' is used as a wildcard for
    # the LIKE operator.
    pattern_esc = r"{}"
    pattern_ops = {
        "contains": "LIKE '%%' || {} || '%%'",
        "icontains": "LIKE '%%' || UPPER({}) || '%%'",
        "startswith": "LIKE {} || '%%'",
        "istartswith": "LIKE UPPER({}) || '%%'",
        "endswith": "LIKE '%%' || {}",
        "iendswith": "LIKE '%%' || UPPER({})",
    }
    Database = Database
    client_class = DatabaseClient
    creation_class = DatabaseCreation
    features_class = DatabaseFeatures
    introspection_class = DatabaseIntrospection
    ops_class = DatabaseOperations

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.client = bigquery.Client(project=self.settings_dict["PROJECT_ID"])

    def close(self):
        pass

    def get_new_connection(self, conn_params):
        gcp_credentials = conn_params.get("GCP_CREDENTIALS")
        if not gcp_credentials:
            return self.client
        else:
            return self.client.from_service_account_json(gcp_credentials)

    def create_cursor(self, name=None):
        return BigQueryCursorWrapper(self.client, self.settings_dict)

    def _commit(self):
        pass

    def _rollback(self):
        pass

    def check_constraints(self, table_names=None):
        pass

    def disable_constraint_checking(self):
        pass

    def enable_constraint_checking(self):
        pass

    def is_usable(self):
        return True

    def get_connection_params(self):
        settings_dict = self.settings_dict
        if not settings_dict["PROJECT_ID"]:
            raise ImproperlyConfigured(
                "settings.DATABASES is improperly configured. Please supply the PROJECT_ID value."
            )

        kwargs = {**settings_dict}

        return kwargs

    def _set_autocommit(self, autocommit):
        pass


class BigQueryCursorWrapper:
    def __init__(self, client, settings_dict):
        self.settings_dict = settings_dict
        self.result = None
        self.client: bigquery.Client = client
        self.rowcount = -1

    def close(self):
        pass

    def execute(self, query, params=()):
        query = self.convert_query(query)
        params = self.convert_params(params)
        # print(query % params)
        query_job = self.client.query(query % params)
        self.result = query_job.result()
        self.rowcount = self.result.total_rows or query_job.num_dml_affected_rows or 0
        return self

    def fetch(self, size=None):
        if size is None:
            self.result, temp = itertools.tee(self.result)
            size = sum(1 for _ in temp)
        rows = []
        for i in range(size):
            try:
                row = next(self.result)
                rows.append(row)
            except StopIteration:
                break
        return rows

    def fetchone(self):
        try:
            return next(self.result)
        except StopIteration:
            return None

    def fetchmany(self, size=None):
        return self.fetch(size)

    def fetchall(self):
        return self.fetch()

    def get_table(self, table_name):
        split_table_name = table_name.split(".")
        len_split_table_name = len(split_table_name)
        if len_split_table_name == 2:
            new_table_name = f"{self.settings_dict['PROJECT_ID']}.{split_table_name[0]}.{split_table_name[1]}"
        elif len_split_table_name == 3:
            new_table_name = ".".join(split_table_name)
        else:
            raise ImproperlyConfigured(
                "Invalid format for table_name. Use 'dataset.table' or 'project.dataset.table'."
            )

        return new_table_name

    def convert_query(self, query):
        # Extract the table name from the query
        # match = re.search('FROM\s+"?([\w.-]+)"?', query)
        matchs = re.findall(
            r"(?:FROM|UPDATE|INSERT INTO)\s+[\"']?([\w.-]+)[\"']?", query
        )
        for match in matchs:
            table_name = match
            new_table_name = self.get_table(table_name)
            s_table_name = table_name.split(".")
            query = query.replace(f'"{table_name}"."', f"{s_table_name[-1]}.")
            for cl in "FROM|UPDATE|INSERT INTO".split("|"):
                query = query.replace(
                    f'{cl} "{table_name}" ', f'{cl} "{new_table_name}" '
                ).replace(f'{cl} "{table_name}"', f'{cl} "{new_table_name}"')
        match_joins = re.findall(r"(?:INNER JOIN)\s+[\"']?([\w.-]+)[\"']?", query)
        for match_join in match_joins:
            table_name_join = match_join
            new_table_name = self.get_table(table_name_join)
            s_table_name_join = table_name_join.split(".")
            query = query.replace(f'"{table_name_join}"."', f"{s_table_name_join[-1]}.")
            for cl in "INNER JOIN".split("|"):
                query = query.replace(
                    f'{cl} "{table_name_join}"', f'{cl} "{new_table_name}"'
                )

        # remove "
        query = query.replace('"', "")

        r"""
        # Add a row number column to the SELECT statement
        replace_id = re.findall(r"[a-z\d_]+(?=,?\s*FROM)", query)
        if replace_id:
            query = query.replace('id,', f'ROW_NUMBER() OVER(ORDER BY {replace_id[0]} ASC) as id,')
        """

        # Replace "col" with the actual column names in the REGEXP_CONTAINS clauses
        col_matches = re.findall(r"[.a-z\d_]+(?=,?\s*REGEXP_CONTAINS)", query)
        for col in col_matches:
            query = query.replace(
                f"{col} REGEXP_CONTAINS", "REGEXP_CONTAINS", 1
            ).replace("col", col, 1)

        # "qualify" is a reserved word in bigquery
        query = query.replace(" qualify ", " qualified ")

        return query

    @staticmethod
    def try_cast(value):
        try:
            return isinstance(value, (str, datetime, date))
        except Exception:
            return False

    def convert_params(self, params):
        tuple_params = ()
        for p in params:
            if self.try_cast(p):
                if isinstance(p, str):
                    p = p.replace("\\", "\\\\")
                tuple_params = tuple_params + (f"'{p}'",)
            elif p is None:
                tuple_params = tuple_params + (f"NULL",)
            else:
                tuple_params = tuple_params + (p,)

        return tuple_params

    @property
    def description(self):
        return (
            (
                field.name,
                field.field_type,
                field.mode,
                field.default_value_expression,
                field.description,
                field.fields,
                field.policy_tags,
            )
            for field in self.result.schema
        )
