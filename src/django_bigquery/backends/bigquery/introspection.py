import sqlparse
from django.db.backends.base.introspection import (
    BaseDatabaseIntrospection,
    FieldInfo,
    TableInfo,
)


class DatabaseIntrospection(BaseDatabaseIntrospection):
    data_types_reverse = {
        # Boolean
        "bool": "BooleanField",
        "boolean": "BooleanField",
        # Integer types
        "int": "BigIntegerField",
        "int64": "BigIntegerField",
        "smallint": "IntegerField",
        "integer": "BigIntegerField",
        "bigint": "BigIntegerField",
        "tinyint": "IntegerField",
        "byteint": "IntegerField",
        # Floating point
        "float": "FloatField",
        "float64": "FloatField",
        # Numeric / Decimal
        "numeric": "DecimalField",
        "decimal": "DecimalField",
        "bignumeric": "DecimalField",
        "bigdecimal": "DecimalField",
        # String types
        "string": "TextField",
        "varchar": "CharField",
        "char": "CharField",
        # Bytes
        "bytes": "BinaryField",
        # Date/time types
        "date": "DateField",
        "datetime": "DateTimeField",
        "timestamp": "DateTimeField",
        "time": "TimeField",
        # JSON / Struct / Geography / Array
        "json": "JSONField",
        "struct": "JSONField",
        "record": "JSONField",
        "array": "JSONField",
        "geography": "TextField",  # representation WKT/WKB
        "range": "JSONField",  # no exact equivalent in Django
        "interval": "DurationField",
    }

    def get_field_type(self, data_type, description):
        field_type = super().get_field_type(data_type, description)

        if field_type == "TextField" and description.internal_size:
            field_type = "CharField"

        return field_type

    def get_table_list(self, cursor):
        """Return a list of table and view names in the current dataset."""
        # Skip the sqlite_sequence system table used for autoincrement key
        # generation.
        cursor.execute(
            """
                  SELECT table_name as name, table_type as type
                  FROM %s.INFORMATION_SCHEMA.TABLES
                  WHERE table_type IN ('BASE TABLE', 'VIEW') ORDER BY name
            """
            % cursor.settings_dict["DATASET_ID"]
        )
        table_info = [
            TableInfo(row[0], {"BASE TABLE": "t", "VIEW": "v"}.get(row[1]))
            for row in cursor.fetchall()
        ]

        return table_info

    def get_table_description(self, cursor, table_name):
        """
        Return a description of the table with the DB-API cursor.description
        interface.
        """
        table_ref = cursor.client.dataset(cursor.settings_dict["DATASET_ID"]).table(
            table_name
        )
        table = cursor.client.get_table(table_ref)
        fields = []
        for field in table.schema:
            """
            is_primary_key = False
            for pk_field in table.primary_key:
                if pk_field.name == name:
                    is_primary_key = True
                    break
            """
            fields.append(
                FieldInfo(
                    name=field.name,
                    type_code=field.field_type.lower(),
                    display_size=field.max_length,
                    internal_size=field.max_length,
                    precision=field.precision,
                    scale=field.scale,
                    null_ok=field.is_nullable,
                    default=field.default_value_expression,
                    collation=None,
                )
            )
        return fields

    def get_sequences(self, cursor, table_name, table_fields=()):
        pk_col = self.get_primary_key_column(cursor, table_name)
        return [{"table": table_name, "column": pk_col}]

    def get_relations(self, cursor, table_name):
        """
        Return a dictionary of {column_name: (ref_column_name, ref_table_name)}
        representing all foreign keys in the given table.
        """

        cursor.execute(
            """
            SELECT CONSTRAINT_NAME, COLUMN_NAME, TABLE_NAME
            FROM %s.INFORMATION_SCHEMA.KEY_COLUMN_USAGE
            WHERE TABLE_NAME = '%s'
            """
            % (cursor.settings_dict["DATASET_ID"], table_name)
        )
        return {
            field_name: (other_field, other_table)
            for field_name, other_field, other_table in cursor.fetchall()
        }

    def get_primary_key_column(self, cursor, table_name):
        """Return the column name of the primary key for the given table."""
        cursor.execute(
            f"""
            SELECT column_name
            FROM {cursor.settings_dict["DATASET_ID"]}.INFORMATION_SCHEMA.KEY_COLUMN_USAGE
            WHERE table_name = '{table_name}' AND constraint_name = 'PRIMARY_KEY'
            """
        )
        row = cursor.fetchone()
        if row:
            return row[0]
        return None

    def _parse_column_or_constraint_definition(self, tokens, columns):
        token = None
        is_constraint_definition = None
        field_name = None
        constraint_name = None
        unique = False
        unique_columns = []
        check = False
        check_columns = []
        braces_deep = 0
        for token in tokens:
            if token.match(sqlparse.tokens.Punctuation, "("):
                braces_deep += 1
            elif token.match(sqlparse.tokens.Punctuation, ")"):
                braces_deep -= 1
                if braces_deep < 0:
                    # End of columns and constraints for table definition.
                    break
            elif braces_deep == 0 and token.match(sqlparse.tokens.Punctuation, ","):
                # End of current column or constraint definition.
                break
            # Detect column or constraint definition by first token.
            if is_constraint_definition is None:
                is_constraint_definition = token.match(
                    sqlparse.tokens.Keyword, "CONSTRAINT"
                )
                if is_constraint_definition:
                    continue
            if is_constraint_definition:
                # Detect constraint name by second token.
                if constraint_name is None:
                    if token.ttype in (sqlparse.tokens.Name, sqlparse.tokens.Keyword):
                        constraint_name = token.value
                    elif token.ttype == sqlparse.tokens.Literal.String.Symbol:
                        constraint_name = token.value[1:-1]
                # Start constraint columns parsing after UNIQUE keyword.
                if token.match(sqlparse.tokens.Keyword, "UNIQUE"):
                    unique = True
                    unique_braces_deep = braces_deep
                elif unique:
                    if unique_braces_deep == braces_deep:
                        if unique_columns:
                            # Stop constraint parsing.
                            unique = False
                        continue
                    if token.ttype in (sqlparse.tokens.Name, sqlparse.tokens.Keyword):
                        unique_columns.append(token.value)
                    elif token.ttype == sqlparse.tokens.Literal.String.Symbol:
                        unique_columns.append(token.value[1:-1])
            else:
                # Detect field name by first token.
                if field_name is None:
                    if token.ttype in (sqlparse.tokens.Name, sqlparse.tokens.Keyword):
                        field_name = token.value
                    elif token.ttype == sqlparse.tokens.Literal.String.Symbol:
                        field_name = token.value[1:-1]
                if token.match(sqlparse.tokens.Keyword, "UNIQUE"):
                    unique_columns = [field_name]
            # Start constraint columns parsing after CHECK keyword.
            if token.match(sqlparse.tokens.Keyword, "CHECK"):
                check = True
                check_braces_deep = braces_deep
            elif check:
                if check_braces_deep == braces_deep:
                    if check_columns:
                        # Stop constraint parsing.
                        check = False
                    continue
                if token.ttype in (sqlparse.tokens.Name, sqlparse.tokens.Keyword):
                    if token.value in columns:
                        check_columns.append(token.value)
                elif token.ttype == sqlparse.tokens.Literal.String.Symbol:
                    if token.value[1:-1] in columns:
                        check_columns.append(token.value[1:-1])
        unique_constraint = (
            {
                "unique": True,
                "columns": unique_columns,
                "primary_key": False,
                "foreign_key": None,
                "check": False,
                "index": False,
            }
            if unique_columns
            else None
        )
        check_constraint = (
            {
                "check": True,
                "columns": check_columns,
                "primary_key": False,
                "unique": False,
                "foreign_key": None,
                "index": False,
            }
            if check_columns
            else None
        )
        return constraint_name, unique_constraint, check_constraint, token

    def _parse_table_constraints(self, sql, columns):
        # Check constraint parsing is based of SQLite syntax diagram.
        # https://www.sqlite.org/syntaxdiagrams.html#table-constraint
        statement = sqlparse.parse(sql)[0]
        constraints = {}
        unnamed_constrains_index = 0
        tokens = (token for token in statement.flatten() if not token.is_whitespace)

        # Go to columns and constraint definition
        for token in tokens:
            if token.match(sqlparse.tokens.Punctuation, "("):
                break
        # Parse columns and constraint definition
        while True:
            (
                constraint_name,
                unique,
                check,
                end_token,
            ) = self._parse_column_or_constraint_definition(tokens, columns)
            if unique:
                if constraint_name:
                    constraints[constraint_name] = unique
                else:
                    unnamed_constrains_index += 1
                    constraints[
                        "__unnamed_constraint_%s__" % unnamed_constrains_index
                    ] = unique
            if check:
                if constraint_name:
                    constraints[constraint_name] = check
                else:
                    unnamed_constrains_index += 1
                    constraints[
                        "__unnamed_constraint_%s__" % unnamed_constrains_index
                    ] = check
            if end_token.match(sqlparse.tokens.Punctuation, ")"):
                break

        return constraints

    def get_constraints(self, cursor, table_name):
        """
        Retrieve any constraints or keys (unique, pk, fk, check, index) across
        one or more columns.
        """
        cursor.execute(
            """
            SELECT
                constraint_type, column_name,
                CASE WHEN is_deferrable = 'NO' THEN 0 ELSE 1 END AS is_deferrable,
                CASE WHEN is_deferrable = 'NO' THEN 0 ELSE 1 END AS initially_deferred,
            FROM
                  {}.INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
            JOIN
                  {}.INFORMATION_SCHEMA.KEY_COLUMN_USAGE kcu
            ON
                  tc.constraint_catalog = kcu.constraint_catalog
                  AND tc.constraint_schema = kcu.constraint_schema
                  AND tc.constraint_name = kcu.constraint_name
            WHERE
                  tc.table_catalog = %s
                  AND tc.table_schema = %s
                  AND tc.table_name = %s
          """.format(
                cursor.settings_dict["DATASET_ID"], cursor.settings_dict["DATASET_ID"]
            ),
            [
                cursor.settings_dict["DATASET_ID"],
                cursor.settings_dict["DATASET_ID"],
                table_name,
            ],
        )
        constraints = {}
        for row in cursor.fetchall():
            (
                constraint_name,
                constraint_type,
                column_name,
                is_deferrable,
                initially_deferred,
                referenced_table_name,
                referenced_column_name,
            ) = row
            if constraint_type == "PRIMARY KEY":
                constraints["PRIMARY KEY"] = {"columns": [column_name]}
            elif constraint_type == "UNIQUE":
                constraints[constraint_name] = {
                    "unique": True,
                    "columns": [column_name],
                }
            elif constraint_type == "FOREIGN KEY":
                constraints[constraint_name] = {
                    "foreign_key": True,
                    "columns": [column_name],
                    "references": (referenced_table_name, referenced_column_name),
                }
            elif constraint_type == "CHECK":
                constraints[constraint_name] = {
                    "check": True,
                    "sql": "",
                    "columns": [column_name],
                }
            elif constraint_type == "INDEX":
                if constraint_name not in constraints:
                    constraints[constraint_name] = {
                        "index": True,
                        "columns": [column_name],
                    }
                else:
                    constraints[constraint_name]["columns"].append(column_name)
        return constraints

    def _get_index_columns_orders(self, sql):
        tokens = sqlparse.parse(sql)[0]
        for token in tokens:
            if isinstance(token, sqlparse.sql.Parenthesis):
                columns = str(token).strip("()").split(", ")
                return ["DESC" if info.endswith("DESC") else "ASC" for info in columns]
        return None

    def _get_column_collations(self, cursor, table_name):
        row = cursor.execute(
            """
            SELECT sql
            FROM sqlite_master
            WHERE type = 'table' AND name = %s
        """,
            [table_name],
        ).fetchone()
        if not row:
            return {}

        sql = row[0]
        columns = str(sqlparse.parse(sql)[0][-1]).strip("()").split(", ")
        collations = {}
        for column in columns:
            tokens = column[1:].split()
            column_name = tokens[0].strip('"')
            for index, token in enumerate(tokens):
                if token == "COLLATE":
                    collation = tokens[index + 1]
                    break
            else:
                collation = None
            collations[column_name] = collation
        return collations
