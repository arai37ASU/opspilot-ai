"""Guards for the container setup. These read the files only; building and
running the image is checked by hand (see docs/api.md)."""

from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[1]


def test_secrets_and_large_local_files_stay_out_of_the_image():
    ignored = {line.strip() for line in (REPOSITORY / ".dockerignore").read_text().splitlines()
               if line.strip() and not line.startswith("#")}
    assert {".env", ".venv/", ".git/", "data/", "models/"} <= ignored


def test_container_runs_as_a_non_root_user():
    lines = (REPOSITORY / "Dockerfile").read_text().splitlines()
    users = [line.split()[1] for line in lines if line.startswith("USER ")]
    assert users and users[-1] != "root"


def test_container_has_a_health_check_on_the_health_endpoint():
    assert "/health" in (REPOSITORY / "Dockerfile").read_text().split("HEALTHCHECK", 1)[1]


def test_api_service_reaches_the_database_by_service_name_and_mounts_the_model_read_only():
    compose = (REPOSITORY / "compose.yaml").read_text()
    api = compose.split("\n  api:\n", 1)[1]
    assert "@postgres:5432/" in api
    assert "./models:/app/models:ro" in api
    assert 'profiles: ["api"]' in api
