"""Schema conformance (Tables 3.2 and 3.3): the database built by the migrations has the six
tables of Figure 3.3, every principal field Table 3.2 lists, and the relationships of Table 3.3
as real foreign keys. Read from the live PostgreSQL catalogue, not from the Django models.
"""
import pytest
from django.db import IntegrityError, connection, models, transaction

from apps.twin.models import (
    MonitoringRecord,
    NetworkDevice,
    NetworkLink,
    Prediction,
    SimulationResult,
    SimulationScenario,
)

pytestmark = pytest.mark.django_db

# Table 3.2: the principal fields of each table (database column names)
PRINCIPAL_FIELDS = {
    "network_device": ["device_id", "name", "device_type", "ip_address", "location", "status"],
    "network_link": ["link_id", "source_device_id", "dest_device_id", "capacity_mbps", "status"],
    "monitoring_record": ["record_id", "device_id", "link_id", "timestamp", "traffic_in", "traffic_out",
                          "utilisation_pct", "error_count", "cpu_util"],
    "prediction": ["prediction_id", "link_id", "generated_at", "horizon_minutes", "predicted_utilisation",
                   "confidence_score", "is_warning"],
    "simulation_scenario": ["scenario_id", "created_by", "scenario_name", "scenario_type", "parameters",
                            "created_at"],
    "simulation_result": ["result_id", "scenario_id", "executed_at", "predicted_utilisation", "bottleneck_links",
                          "result_summary"],
}

# Table 3.3: (child table, foreign-key column, parent table), each one parent to many children
RELATIONSHIPS = [
    ("network_link", "source_device_id", "network_device"),
    ("network_link", "dest_device_id", "network_device"),
    ("monitoring_record", "device_id", "network_device"),
    ("monitoring_record", "link_id", "network_link"),
    ("prediction", "link_id", "network_link"),
    ("simulation_result", "scenario_id", "simulation_scenario"),
]
PRIMARY_KEYS = {table: fields[0] for table, fields in PRINCIPAL_FIELDS.items()}


def _columns(table: str) -> set[str]:
    with connection.cursor() as cursor:
        return {col.name for col in connection.introspection.get_table_description(cursor, table)}


def test_the_six_tables_exist_with_every_principal_field():
    tables = set(connection.introspection.table_names())
    for table, fields in PRINCIPAL_FIELDS.items():
        assert table in tables, f"missing table {table}"
        missing = set(fields) - _columns(table)
        assert not missing, f"{table} lacks {sorted(missing)}"


def test_primary_keys_are_the_named_id_fields():
    with connection.cursor() as cursor:
        for table, pk in PRIMARY_KEYS.items():
            assert connection.introspection.get_primary_key_column(cursor, table) == pk


def test_table_3_3_relationships_are_foreign_keys_in_the_database():
    with connection.cursor() as cursor:
        for child, column, parent in RELATIONSHIPS:
            relations = connection.introspection.get_relations(cursor, child)
            assert column in relations, f"{child}.{column} is not a foreign key"
            target_column, target_table = relations[column]
            assert (target_table, target_column) == (parent, PRIMARY_KEYS[parent])
        # SimulationScenario.created_by points to the user table (Figure 3.3)
        assert connection.introspection.get_relations(cursor, "simulation_scenario")["created_by"][1] == "auth_user"


def test_history_is_protected_from_cascading_deletes():
    """§6.3: deleting a referenced row is blocked, so history and results are never lost."""
    for model in (NetworkLink, MonitoringRecord, Prediction, SimulationScenario, SimulationResult):
        for field in model._meta.get_fields():
            if isinstance(field, models.ForeignKey):
                assert field.remote_field is not None
                assert field.remote_field.on_delete is models.PROTECT, f"{model.__name__}.{field.name}"


def test_a_reading_for_an_unknown_link_is_refused_by_the_database():
    from django.utils import timezone

    # Django creates foreign keys DEFERRABLE INITIALLY DEFERRED (checked at commit); check now instead
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
            MonitoringRecord.objects.create(link_id=999_999, timestamp=timezone.now(), utilisation_pct=10.0)
    assert not NetworkDevice.objects.exists()
