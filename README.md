# django-bigquery

A Django database backend for querying **Google BigQuery using Django ORM syntax**.

The project translates Django ORM queries such as:

```python
Model.objects.filter(status="active")
Model.objects.filter(amount__gte=100).order_by("-created_at")
Model.objects.values("sector").annotate(total=Count("id"))
```

into SQL that can be executed by BigQuery.

> **Status:** early/MVP. The current goal is reliable read/query support as well as basic `INSERT` and `UPDATE` DML operations. Schema migrations remain out of scope.

## Installation

From PyPI (when released):

```bash
pip install django-bigquery
```

For development from GitHub:

```bash
git clone https://github.com/natanbernardocorreia/django-bigquery.git
cd django-bigquery
pip install -e ".[test]"
```

## Django configuration

Add a BigQuery connection to `DATABASES` in `settings.py`:

```python
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    },

    "gcp": {
        "ENGINE": "django_bigquery.backends.bigquery",
        "PROJECT_ID": env("PROJECT_ID_OPER"),
        "DATASET_ID": env("DATASET_ID_OPER"),
    },
}
```

The important point is that **`ENGINE` points to the installed Python package**:

```python
"ENGINE": "django_bigquery.backends.bigquery"
```

The connection alias can still be called `gcp`.

### Google Cloud authentication

The backend uses the normal Google Cloud authentication mechanism provided by `google-cloud-bigquery`.

For example:

```bash
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/service-account.json"
```

or use Application Default Credentials in the environment where Django runs.

Do not commit service-account JSON files or credentials to Git.

## Model configuration

Models that represent BigQuery tables or views should normally be unmanaged:

```python
class ShakespeareWord(models.Model):
    word = models.CharField(max_length=255, primary_key=True)
    word_count = models.IntegerField(db_column="word_count")
    corpus = models.CharField(max_length=255)

    class Meta:
        managed = False
        db_table = "samples.shakespeare"
```

`db_table` accepts:

```text
dataset.table
```

or:

```text
project.dataset.table
```

For example:

```python
db_table = "samples.shakespeare"
```

means:

```text
PROJECT_ID.samples.shakespeare
```

where `PROJECT_ID` comes from the Django database configuration.

### Why `managed = False`?

BigQuery is being used as an analytical/read data source in this MVP. Django should not try to create or alter these BigQuery objects through migrations.

## Querying with Django ORM

If your normal Django database is `default`, explicitly select the BigQuery connection using `.using("gcp")`:

```python
ShakespeareWord.objects.using("gcp").filter(
    word="to be"
)
```

You can use familiar Django ORM operations, subject to the backend's current supported feature set:

```python
ShakespeareWord.objects.using("gcp").filter(
    word__icontains="django"
)

ShakespeareWord.objects.using("gcp").filter(
    word_count__gte=100
).order_by("-word_count")

ShakespeareWord.objects.using("gcp").values(
    "corpus"
).annotate(
    total=Count("word")
)
```

## Example using Public BigQuery Datasets

You can test queries using real Django models pointing to public BigQuery datasets (such as Google's public Shakespeare dataset) without needing your own populated GCP project:

```python
class ShakespeareWord(models.Model):
    word = models.CharField(max_length=255, primary_key=True)
    word_count = models.IntegerField(db_column="word_count")
    corpus = models.CharField(max_length=255)

    class Meta:
        managed = False
        db_table = "bigquery-public-data.samples.shakespeare"
```

Querying using Django ORM syntax:

```python
results = ShakespeareWord.objects.using("gcp").filter(
    word_count__gte=100
).order_by("-word_count")[:10]

for row in results:
    print(row.word, row.word_count, row.corpus)
```

## What the backend does

The basic execution path is:

```text
Django ORM
    ↓
Django SQL compiler
    ↓
django_bigquery backend
    ↓
BigQuery-compatible SQL
    ↓
google-cloud-bigquery
    ↓
BigQuery
```

The project was initially inspired by Django's SQLite backend, but BigQuery-specific execution and SQL adaptations live in this package.

## Current scope

### Intended for the MVP

- `filter()`
- `exclude()`
- `order_by()`
- `values()`
- annotations/aggregations supported by Django's SQL compiler and this backend
- lookups such as `exact`, `gt`, `gte`, `lt`, `lte`, `contains`, `icontains`, etc.
- querying BigQuery tables and views
- `INSERT` and `UPDATE` DML statement support
- Django models with `managed = False`

### Not the focus yet

- Django migrations against BigQuery
- `DELETE` DML support
- foreign-key management
- Django admin write operations
- full parity with every Django ORM/database feature

Unsupported operations should be treated as backend limitations until explicitly implemented and tested.

## Tests

The repository contains lightweight tests for the BigQuery-specific SQL/table-name conversion without requiring a live BigQuery project.

Run:

```bash
pip install -e ".[test]"
pytest
```

Integration tests requiring a real GCP project can be added separately.

## Development

Recommended workflow:

```bash
git clone https://github.com/natanbernardocorreia/django-bigquery.git
cd django-bigquery
python -m venv .venv
```

Activate the virtual environment and install:

```bash
pip install -e ".[test]"
```

Then:

```bash
pytest
```

## License

See [LICENSE](LICENSE).
