"""Tests for the survey app. Run them in the dev container:

    docker compose -f docker-compose.dev.yml run --rm app pytest
"""

import re

import pytest

from app import create_app
from app.db import connect


@pytest.fixture
def app(tmp_path):
    return create_app(
        {
            "TESTING": True,
            "FLASK_ENV": "production",
            "SECRET_KEY": "test-secret-key",
            "DATABASE_PATH": str(tmp_path / "test.db"),
        }
    )


@pytest.fixture
def client(app):
    return app.test_client()


def csrf_token(client):
    """Load the form the way a browser would and return its CSRF token."""
    html = client.get("/").get_data(as_text=True)
    return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)


def valid_form(client, **overrides):
    data = {
        "csrf_token": csrf_token(client),
        "name": "Ada",
        "language": "Python",
        "container_experience": "4",
        "environments": ["Laptop", "AWS"],
        "comments": "Containers are neat.",
    }
    data.update(overrides)
    return data


def count_submissions(app):
    conn = connect(app.config["DATABASE_PATH"])
    try:
        return conn.execute("SELECT COUNT(*) FROM submissions").fetchone()[0]
    finally:
        conn.close()


def test_healthz_ok(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def test_healthz_reports_unreachable_database(app, client, tmp_path):
    app.config["DATABASE_PATH"] = str(tmp_path / "no-such-dir" / "test.db")
    assert client.get("/healthz").status_code == 503


def test_form_renders(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"Primary language you use at work" in response.data


def test_valid_submission_is_saved_and_redirects(app, client):
    response = client.post("/", data=valid_form(client))
    assert response.status_code == 302
    assert response.headers["Location"] == "/thanks"
    assert count_submissions(app) == 1
    assert client.get("/thanks").status_code == 200


@pytest.mark.parametrize(
    "overrides",
    [
        {"language": "COBOL"},
        {"language": ""},
        {"container_experience": "0"},
        {"container_experience": "6"},
        {"container_experience": "abc"},
        {"environments": []},
        {"environments": ["Laptop", "Mars"]},
        {"name": "x" * 81},
        {"comments": "x" * 501},
    ],
    ids=[
        "bad-language",
        "missing-language",
        "rating-too-low",
        "rating-too-high",
        "rating-not-a-number",
        "no-environment",
        "unknown-environment",
        "oversize-name",
        "oversize-comment",
    ],
)
def test_invalid_submission_is_rejected(app, client, overrides):
    response = client.post("/", data=valid_form(client, **overrides))
    assert response.status_code == 400
    assert b'class="error"' in response.data
    assert count_submissions(app) == 0


def test_rejected_form_keeps_user_input(client):
    response = client.post("/", data=valid_form(client, container_experience="9"))
    html = response.get_data(as_text=True)
    assert response.status_code == 400
    assert 'value="Ada"' in html
    assert '<option value="Python" selected>' in html
    assert re.search(r'value="AWS"\s+checked', html)
    assert "Containers are neat." in html


def test_missing_csrf_token_is_rejected(app, client):
    data = valid_form(client)
    del data["csrf_token"]
    response = client.post("/", data=data)
    assert response.status_code == 400
    assert b"could not be verified" in response.data
    assert count_submissions(app) == 0


def test_wrong_csrf_token_is_rejected(app, client):
    response = client.post("/", data=valid_form(client, csrf_token="forged"))
    assert response.status_code == 400
    assert count_submissions(app) == 0


def test_results_show_saved_submission(client):
    client.post("/", data=valid_form(client))
    client.post("/", data=valid_form(client, name="", language="R", comments=""))
    html = client.get("/results").get_data(as_text=True)
    assert re.search(r'class="total">2<', html)
    assert "Ada" in html
    assert "anonymous" in html
    assert "Containers are neat." in html
    assert "Laptop, AWS" in html


def test_results_escape_html(client):
    client.post("/", data=valid_form(client, name="<script>alert(1)</script>"))
    html = client.get("/results").get_data(as_text=True)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


@pytest.mark.parametrize("secret_key", [None, "change-me"], ids=["missing", "placeholder"])
def test_production_refuses_to_start_without_real_secret_key(monkeypatch, tmp_path, secret_key):
    monkeypatch.setenv("FLASK_ENV", "production")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    if secret_key is None:
        monkeypatch.delenv("SECRET_KEY", raising=False)
    else:
        monkeypatch.setenv("SECRET_KEY", secret_key)
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        create_app()
