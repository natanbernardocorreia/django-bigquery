import pytest
import django
from django.conf import settings
from django.db import models
from unittest.mock import MagicMock, patch
from datetime import datetime, date
from django_bigquery.backends.bigquery.base import BigQueryCursorWrapper

if not settings.configured:
    settings.configure(
        DATABASES={
            "default": {
                "ENGINE": "django.db.backends.sqlite3",
                "NAME": ":memory:",
            },
            "gcp": {
                "ENGINE": "django_bigquery.backends.bigquery",
                "PROJECT_ID": "bigquery-public-data",
                "DATASET_ID": "samples",
            },
        },
        INSTALLED_APPS=[],
    )
    django.setup()


class ShakespeareWord(models.Model):
    word = models.CharField(max_length=255, primary_key=True)
    word_count = models.IntegerField(db_column="word_count")
    corpus = models.CharField(max_length=255)

    class Meta:
        managed = False
        db_table = "bigquery-public-data.samples.shakespeare"
        app_label = "tests"


@pytest.fixture
def wrapper():
    # Avoid constructing DatabaseWrapper, which would initialize a real
    # google.cloud.bigquery.Client.
    obj = BigQueryCursorWrapper.__new__(BigQueryCursorWrapper)
    obj.settings_dict = {
        "PROJECT_ID": "bigquery-public-data",
        "DATASET_ID": "samples",
    }
    return obj


def test_get_table_with_dataset_and_table(wrapper):
    assert wrapper.get_table("samples.shakespeare") == (
        "bigquery-public-data.samples.shakespeare"
    )


def test_get_table_with_project_dataset_and_table(wrapper):
    assert wrapper.get_table("bigquery-public-data.samples.shakespeare") == (
        "bigquery-public-data.samples.shakespeare"
    )


def test_get_table_rejects_invalid_name(wrapper):
    with pytest.raises(Exception):
        wrapper.get_table("shakespeare")


def test_convert_query_qualifies_bigquery_table(wrapper):
    sql = 'SELECT "word", "word_count" FROM "samples.shakespeare" WHERE "word_count" = %s'
    converted = wrapper.convert_query(sql)

    assert "bigquery-public-data.samples.shakespeare" in converted
    assert 'FROM "samples.shakespeare"' not in converted


def test_convert_query_insert(wrapper):
    sql = 'INSERT INTO "samples.shakespeare" ("word", "word_count") VALUES (%s, %s)'
    converted = wrapper.convert_query(sql)

    assert "INSERT INTO bigquery-public-data.samples.shakespeare" in converted
    assert '"' not in converted


def test_convert_query_update(wrapper):
    sql = 'UPDATE "samples.shakespeare" SET "word_count" = %s WHERE "word" = %s'
    converted = wrapper.convert_query(sql)

    assert "UPDATE bigquery-public-data.samples.shakespeare" in converted
    assert "SET word_count = %s" in converted
    assert '"' not in converted


def test_convert_query_inner_join(wrapper):
    sql = 'SELECT "word" FROM "samples.shakespeare" INNER JOIN "samples.corpus" ON "shakespeare"."corpus_id" = "corpus"."id"'
    converted = wrapper.convert_query(sql)

    assert "bigquery-public-data.samples.shakespeare" in converted
    assert "bigquery-public-data.samples.corpus" in converted


def test_convert_query_qualify_keyword(wrapper):
    sql = 'SELECT * FROM "samples.shakespeare" qualify row_number() over() = 1'
    converted = wrapper.convert_query(sql)

    assert "qualified" in converted


def test_convert_params_quotes_strings_and_null(wrapper):
    assert wrapper.convert_params(("active", None, 10)) == ("'active'", "NULL", 10)


def test_convert_params_with_backslash(wrapper):
    assert wrapper.convert_params(("path\\to\\file",)) == ("'path\\\\to\\\\file'",)


def test_try_cast(wrapper):
    assert wrapper.try_cast("test") is True
    assert wrapper.try_cast(datetime.now()) is True
    assert wrapper.try_cast(date.today()) is True
    assert wrapper.try_cast(123) is False


@patch("google.cloud.bigquery.Client")
def test_shakespeare_model_orm_compilation(mock_client_cls):
    qs = ShakespeareWord.objects.using("gcp").filter(word_count__gte=100).order_by("-word_count")
    compiler = qs.query.get_compiler("gcp")
    sql, params = compiler.as_sql()

    assert "bigquery-public-data.samples.shakespeare" in sql
    assert "word_count" in sql
    assert params == (100,)


def test_cursor_execute_and_fetch(wrapper):
    mock_client = MagicMock()
    mock_job = MagicMock()
    mock_result = MagicMock()
    mock_result.total_rows = 2
    items = [("to be", 500), ("not to be", 300)]
    mock_result.__iter__.return_value = iter(items)
    mock_result.__next__ = lambda self: next(self._iter)
    mock_result._iter = iter(items)

    mock_job.result.return_value = mock_result
    mock_job.num_dml_affected_rows = 0
    mock_client.query.return_value = mock_job
    wrapper.client = mock_client

    cursor = wrapper
    res = cursor.execute('SELECT "word", "word_count" FROM "samples.shakespeare" WHERE "word_count" = %s', (500,))
    assert res is cursor
    assert cursor.rowcount == 2
    
    row = cursor.fetchone()
    assert row == ("to be", 500)
    
    row2 = cursor.fetchone()
    assert row2 == ("not to be", 300)


def test_cursor_fetchall(wrapper):
    mock_client = MagicMock()
    mock_job = MagicMock()
    mock_result = MagicMock()
    mock_result.total_rows = 2
    items = [("to be", 500), ("not to be", 300)]
    mock_result.__iter__.return_value = iter(items)
    mock_result.__next__ = lambda self: next(self._iter)
    mock_result._iter = iter(items)

    mock_job.result.return_value = mock_result
    mock_job.num_dml_affected_rows = 0
    mock_client.query.return_value = mock_job
    wrapper.client = mock_client

    cursor = wrapper
    cursor.execute('SELECT "word", "word_count" FROM "samples.shakespeare"', ())
    rows = cursor.fetchall()
    assert rows == [("to be", 500), ("not to be", 300)]
