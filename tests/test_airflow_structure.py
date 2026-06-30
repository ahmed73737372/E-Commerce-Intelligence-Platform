"""
tests/test_airflow_structure.py
=================================

Structural tests for Phase 5 — Airflow DAG and task wrappers.

Tests verify:
  - DAG loads without errors
  - DAG has the correct ID, schedule, and configuration
  - All 7 expected tasks are present
  - Task dependencies match the required graph
  - Task callables exist and are importable
  - Task modules contain no business logic (correct delegation pattern)

NO Airflow server is required — tests run against the DAG Python object directly.
NO API calls are made — task callables are not executed.

Run:
    python -m pytest tests/test_airflow_structure.py -v

Skip automatically if Apache Airflow is not installed:
    All tests are marked with @pytest.mark.skipif(no_airflow, ...)
"""

import sys
import importlib
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# ── Check if Airflow is available (and functional) ────────────────────────────
# A partial install exposes the `airflow` package but not core classes.
# We test the specific import we need in the DAG fixture.
try:
    from airflow import DAG as _AirflowDAG            # noqa: F401
    from airflow.operators.python import PythonOperator as _PO  # noqa: F401
    AIRFLOW_AVAILABLE = True
except (ImportError, Exception):
    AIRFLOW_AVAILABLE = False

airflow_required = pytest.mark.skipif(
    not AIRFLOW_AVAILABLE,
    reason="Apache Airflow is not installed. Run: pip install apache-airflow",
)

# ── Expected task topology ─────────────────────────────────────────────────────
EXPECTED_TASKS = {
    "fetch_world_bank",
    "fetch_imf",
    "fetch_fred",
    "transform_data",
    "validate_dataset",
    "load_database",
    "calculate_stress_scores",
}

# Tasks that must run in parallel (no dependency between them)
PARALLEL_INGESTION_TASKS = {"fetch_world_bank", "fetch_imf", "fetch_fred"}

# Expected linear chain after transform_data
EXPECTED_CHAIN = [
    "transform_data",
    "validate_dataset",
    "load_database",
    "calculate_stress_scores",
]


# ── Fixture: load DAG ─────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def dag():
    """
    Load the DAG object by importing the DAG module directly via file path.
    Returns the DAG object for inspection.
    """
    if not AIRFLOW_AVAILABLE:
        pytest.skip("Airflow not installed")

    import importlib.util

    dag_file = Path(__file__).resolve().parent.parent / "airflow" / "dags" / "economic_stress_pipeline.py"

    # Patch setup_logging so it doesn't write to disk during tests
    with patch("src.utils.logger.setup_logging"):
        spec   = importlib.util.spec_from_file_location("economic_stress_pipeline", dag_file)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

    return module.dag


# ══════════════════════════════════════════════════════════════════════════════
# DAG-level configuration tests
# ══════════════════════════════════════════════════════════════════════════════

class TestDAGConfiguration:

    @airflow_required
    def test_dag_id_is_correct(self, dag):
        assert dag.dag_id == "economic_stress_pipeline"

    @airflow_required
    def test_schedule_interval(self, dag):
        """DAG must run daily at 02:00 UTC."""
        # Airflow stores schedule_interval as a string or timedelta
        schedule = dag.schedule_interval or dag.timetable
        assert "0 2 * * *" in str(schedule)

    @airflow_required
    def test_catchup_is_false(self, dag):
        assert dag.catchup is False

    @airflow_required
    def test_max_active_runs_is_1(self, dag):
        assert dag.max_active_runs == 1

    @airflow_required
    def test_dag_has_correct_number_of_tasks(self, dag):
        assert len(dag.tasks) == len(EXPECTED_TASKS)

    @airflow_required
    def test_dag_tags_present(self, dag):
        assert dag.tags is not None
        assert len(dag.tags) > 0


# ══════════════════════════════════════════════════════════════════════════════
# Task presence tests
# ══════════════════════════════════════════════════════════════════════════════

class TestTaskPresence:

    @airflow_required
    def test_all_expected_tasks_exist(self, dag):
        task_ids = {t.task_id for t in dag.tasks}
        assert task_ids == EXPECTED_TASKS

    @airflow_required
    @pytest.mark.parametrize("task_id", sorted(EXPECTED_TASKS))
    def test_each_task_is_present(self, dag, task_id):
        task_ids = {t.task_id for t in dag.tasks}
        assert task_id in task_ids, f"Task '{task_id}' not found in DAG"

    @airflow_required
    def test_all_tasks_use_python_operator(self, dag):
        """Every task must be a PythonOperator — no BashOperator allowed."""
        from airflow.operators.python import PythonOperator
        for task in dag.tasks:
            assert isinstance(task, PythonOperator), (
                f"Task '{task.task_id}' is {type(task).__name__}, expected PythonOperator"
            )


# ══════════════════════════════════════════════════════════════════════════════
# Dependency graph tests
# ══════════════════════════════════════════════════════════════════════════════

class TestTaskDependencies:

    def _upstream_ids(self, dag, task_id: str) -> set[str]:
        task = dag.get_task(task_id)
        return {t.task_id for t in task.upstream_list}

    def _downstream_ids(self, dag, task_id: str) -> set[str]:
        task = dag.get_task(task_id)
        return {t.task_id for t in task.downstream_list}

    @airflow_required
    def test_transform_waits_for_all_collectors(self, dag):
        """transform_data must have all 3 collectors as upstream."""
        upstream = self._upstream_ids(dag, "transform_data")
        assert PARALLEL_INGESTION_TASKS.issubset(upstream), (
            f"transform_data upstream: {upstream}, expected: {PARALLEL_INGESTION_TASKS}"
        )

    @airflow_required
    def test_ingestion_tasks_have_no_upstream(self, dag):
        """Collector tasks must have no upstream — they are root tasks."""
        for task_id in PARALLEL_INGESTION_TASKS:
            upstream = self._upstream_ids(dag, task_id)
            assert upstream == set(), (
                f"Task '{task_id}' should have no upstream, but has: {upstream}"
            )

    @airflow_required
    def test_ingestion_tasks_not_dependent_on_each_other(self, dag):
        """Collector tasks must be independent (parallel execution)."""
        for task_id in PARALLEL_INGESTION_TASKS:
            upstream = self._upstream_ids(dag, task_id)
            overlap = upstream & PARALLEL_INGESTION_TASKS
            assert overlap == set(), (
                f"Task '{task_id}' has ingestion dependencies: {overlap}. "
                "Ingestion tasks should run in parallel."
            )

    @airflow_required
    def test_validate_dataset_upstream_is_transform(self, dag):
        upstream = self._upstream_ids(dag, "validate_dataset")
        assert "transform_data" in upstream

    @airflow_required
    def test_load_database_upstream_is_validate(self, dag):
        upstream = self._upstream_ids(dag, "load_database")
        assert "validate_dataset" in upstream

    @airflow_required
    def test_calculate_stress_upstream_is_load(self, dag):
        upstream = self._upstream_ids(dag, "calculate_stress_scores")
        assert "load_database" in upstream

    @airflow_required
    def test_calculate_stress_has_no_downstream(self, dag):
        """calculate_stress_scores is the terminal task."""
        downstream = self._downstream_ids(dag, "calculate_stress_scores")
        assert downstream == set()

    @airflow_required
    def test_linear_chain_is_correct(self, dag):
        """Verify the sequential chain: transform → validate → load → score."""
        for i in range(len(EXPECTED_CHAIN) - 1):
            upstream_of_next = self._upstream_ids(dag, EXPECTED_CHAIN[i + 1])
            assert EXPECTED_CHAIN[i] in upstream_of_next, (
                f"Expected '{EXPECTED_CHAIN[i]}' to be upstream of "
                f"'{EXPECTED_CHAIN[i + 1]}'"
            )


# ══════════════════════════════════════════════════════════════════════════════
# Task callable import tests (no Airflow needed)
# ══════════════════════════════════════════════════════════════════════════════

class TestTaskCallablesAreImportable:
    """
    Verify all task callable functions exist and are importable.
    These tests do NOT require Airflow to be installed.
    """

    def test_ingestion_callables_exist(self):
        from src.airflow_tasks.ingestion_tasks import (
            run_world_bank_collector,
            run_imf_collector,
            run_fred_collector,
        )
        assert callable(run_world_bank_collector)
        assert callable(run_imf_collector)
        assert callable(run_fred_collector)

    def test_transformation_callable_exists(self):
        from src.airflow_tasks.transformation_tasks import run_transformer
        assert callable(run_transformer)

    def test_database_callables_exist(self):
        from src.airflow_tasks.database_tasks import validate_dataset, run_loader
        assert callable(validate_dataset)
        assert callable(run_loader)

    def test_analytics_callable_exists(self):
        from src.airflow_tasks.analytics_tasks import run_stress_engine
        assert callable(run_stress_engine)


# ══════════════════════════════════════════════════════════════════════════════
# Delegation pattern tests (no business logic in task wrappers)
# ══════════════════════════════════════════════════════════════════════════════

class TestTaskDelegation:
    """
    Verify task wrappers delegate to the correct underlying module.
    Business logic must live in the original modules, not in task wrappers.
    """

    def test_world_bank_task_delegates_to_collector(self):
        """run_world_bank_collector must instantiate WorldBankCollector."""
        from src.airflow_tasks import ingestion_tasks

        mock_collector = MagicMock()
        mock_collector.run.return_value = None  # triggers RuntimeError

        with patch.object(ingestion_tasks, "WorldBankCollector",
                          return_value=mock_collector):
            from src.airflow_tasks.ingestion_tasks import run_world_bank_collector
            with pytest.raises(RuntimeError):
                run_world_bank_collector()
            mock_collector.run.assert_called_once()

    def test_imf_task_delegates_to_collector(self):
        """run_imf_collector must call IMFCollector.run()."""
        with patch("src.airflow_tasks.ingestion_tasks.IMFCollector") as MockIMF:
            MockIMF.return_value.run.return_value = None  # triggers RuntimeError
            from src.airflow_tasks.ingestion_tasks import run_imf_collector
            with pytest.raises(RuntimeError):
                run_imf_collector()
            MockIMF.assert_called_once()

    def test_transformer_task_delegates_to_data_transformer(self):
        """run_transformer must call DataTransformer.load_and_transform_all()."""
        import pandas as pd
        with patch("src.airflow_tasks.transformation_tasks.DataTransformer") as MockDT:
            MockDT.return_value.load_and_transform_all.return_value = pd.DataFrame()
            from src.airflow_tasks.transformation_tasks import run_transformer
            with pytest.raises(RuntimeError):  # empty DF → RuntimeError
                run_transformer()
            MockDT.assert_called_once()
            MockDT.return_value.load_and_transform_all.assert_called_once()

    def test_validate_task_delegates_to_etl_pipeline(self):
        """validate_dataset must call ETLPipeline.run_validation()."""
        from src.pipeline.etl_pipeline import StageResult
        mock_result = StageResult(
            name="Stage 3 — Validation", success=False,
            error="Test error"
        )
        with patch("src.airflow_tasks.database_tasks.ETLPipeline") as MockPipeline:
            MockPipeline.return_value.run_validation.return_value = mock_result
            from src.airflow_tasks.database_tasks import validate_dataset
            with pytest.raises(RuntimeError, match="FAILED"):
                validate_dataset()
            MockPipeline.assert_called_once()
            MockPipeline.return_value.run_validation.assert_called_once()

    def test_loader_task_delegates_to_load_to_database(self):
        """run_loader must call load_to_database()."""
        with patch("src.airflow_tasks.database_tasks.load_to_database", return_value=False) as mock_load:
            from src.airflow_tasks.database_tasks import run_loader
            with pytest.raises(RuntimeError, match="FAILED"):
                run_loader()
            mock_load.assert_called_once()

    def test_stress_task_delegates_to_stress_engine(self):
        """run_stress_engine must call StressEngine.run()."""
        with patch("src.airflow_tasks.analytics_tasks.StressEngine") as MockEngine:
            MockEngine.return_value.run.return_value = (0, 0)  # 0 inserted → RuntimeError
            from src.airflow_tasks.analytics_tasks import run_stress_engine
            with pytest.raises(RuntimeError, match="0 scores"):
                run_stress_engine()
            MockEngine.assert_called_once()
            MockEngine.return_value.run.assert_called_once()
