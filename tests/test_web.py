"""Tests for the dashboard's static site: the page and its assets are served
from the API with the right types, every page module exists, and the
vendored chart library matches its recorded checksum."""

import hashlib
import re
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "src" / "opspilot" / "api" / "static"


@pytest.mark.db
def test_root_serves_the_dashboard(client):
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "OpsPilot Control Room" in response.text


@pytest.mark.db
@pytest.mark.parametrize("path, content_type", [
    ("/static/css/app.css", "text/css"),
    ("/static/js/app.js", "javascript"),
    ("/static/vendor/echarts-5.6.0.min.js", "javascript"),
    ("/static/favicon.svg", "image/svg+xml"),
])
def test_assets_are_served_with_the_right_type(client, path, content_type):
    response = client.get(path)
    assert response.status_code == 200
    assert content_type in response.headers["content-type"]


@pytest.mark.db
def test_dashboard_routes_stay_out_of_the_api_docs(client):
    assert "/" not in client.get("/openapi.json").json()["paths"]


def test_every_asset_the_page_references_exists():
    html = (STATIC / "index.html").read_text()
    for path in re.findall(r'(?:href|src)="/static/([^"]+)"', html):
        assert (STATIC / path).is_file(), path


def test_every_page_in_the_router_has_a_module():
    app = (STATIC / "js" / "app.js").read_text()
    for module in re.findall(r'from "\./pages/([a-z]+)\.js"', app):
        assert (STATIC / "js" / "pages" / f"{module}.js").is_file(), module


def test_vendored_echarts_matches_its_recorded_checksum():
    recorded = re.search(r"`([0-9a-f]{64})`", (STATIC / "vendor" / "README.md").read_text()).group(1)
    actual = hashlib.sha256((STATIC / "vendor" / "echarts-5.6.0.min.js").read_bytes()).hexdigest()
    assert actual == recorded


def api_paths_called_by_the_scripts() -> set[str]:
    """Every path passed to getJSON or postJSON, with ${...} parts kept as placeholders."""
    pattern = re.compile(r"""(?:getJSON|postJSON)\(\s*[`"'](/[^`"'?]*)""")
    return {path for script in (STATIC / "js").rglob("*.js") for path in pattern.findall(script.read_text())}


@pytest.mark.db
def test_every_api_path_the_dashboard_calls_exists(client):
    """If an endpoint is renamed or removed, this fails instead of the page breaking silently."""
    documented = [re.compile("^" + re.sub(r"\{[^/]+\}", "[^/]+", path) + "$")
                  for path in client.get("/openapi.json").json()["paths"]]
    called = api_paths_called_by_the_scripts()
    assert {"/health", "/model"} <= called
    for path in called:
        concrete = re.sub(r"\$\{[^}]+\}", "x", path)
        assert any(route.match(concrete) for route in documented), path


def test_scripts_never_insert_html_strings():
    """Text from the API must be inserted as text, not parsed as HTML."""
    for script in (STATIC / "js").rglob("*.js"):
        source = script.read_text()
        assert "innerHTML" not in source and "outerHTML" not in source and "insertAdjacentHTML" not in source, script.name


def test_every_model_feature_has_a_plain_language_label():
    # The simulator and ticket pages explain predictions with these labels;
    # a feature added to the model without one would show its raw column name.
    from opspilot.modeling.config import FEATURES

    labelled = set(re.findall(r"^  (\w+): \{ label:", (STATIC / "js" / "features.js").read_text(), re.MULTILINE))
    assert labelled == set(FEATURES)
