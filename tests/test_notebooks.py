"""Every notebook must run from top to bottom without errors.

Each notebook is copied into a temporary folder and executed there against the
test database, so the run cannot change the committed notebook, the saved
figures, or the analysis database. The committed modeling results are copied
alongside, because notebook 03 reads them instead of retraining.
"""

import shutil
from pathlib import Path

import pytest

nbformat = pytest.importorskip("nbformat")
nbclient = pytest.importorskip("nbclient")

REPOSITORY = Path(__file__).resolve().parents[1]
NOTEBOOKS = sorted((REPOSITORY / "notebooks").glob("*.ipynb"))

pytestmark = pytest.mark.db


@pytest.mark.parametrize("path", NOTEBOOKS, ids=[path.name for path in NOTEBOOKS])
def test_notebook_runs(path, db_conn, test_database_url, tmp_path, monkeypatch):
    # The kernel inherits this environment, and load_dotenv does not
    # override variables that are already set.
    monkeypatch.setenv("DATABASE_URL", test_database_url)
    workdir = tmp_path / "notebooks"
    workdir.mkdir()
    shutil.copy(path, workdir)
    shutil.copytree(REPOSITORY / "reports" / "modeling", tmp_path / "reports" / "modeling")

    notebook = nbformat.read(workdir / path.name, as_version=4)
    client = nbclient.NotebookClient(notebook, timeout=300, kernel_name="python3",
                                     resources={"metadata": {"path": str(workdir)}})
    client.execute()

    errors = [output for cell in notebook.cells for output in cell.get("outputs", [])
              if output.get("output_type") == "error"]
    assert not errors
    assert any((tmp_path / "reports" / "figures").glob("*.png"))
