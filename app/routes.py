"""Routes: survey form, thanks page, results summary, and health check."""

import hmac
import json
import secrets
import sqlite3
from datetime import datetime, timezone

from flask import (
    Blueprint,
    current_app,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from .db import get_db

bp = Blueprint("survey", __name__)

LANGUAGES = ["Python", "R", "Julia", "JavaScript", "Other"]
EXPERIENCE_LEVELS = [1, 2, 3, 4, 5]
EXPERIENCE_LABELS = {1: "never used", 5: "use daily"}
ENVIRONMENTS = ["Laptop", "Local server", "AWS", "Azure", "Other"]
NAME_MAX = 80
COMMENTS_MAX = 500

# Passed to every template that shows the questions or their answers.
CHOICES = {
    "languages": LANGUAGES,
    "experience_levels": EXPERIENCE_LEVELS,
    "experience_labels": EXPERIENCE_LABELS,
    "environments": ENVIRONMENTS,
    "name_max": NAME_MAX,
    "comments_max": COMMENTS_MAX,
}

EMPTY_FORM = {
    "name": "",
    "language": "",
    "container_experience": "",
    "environments": [],
    "comments": "",
}


# CSRF protection: one random token per session, stored in the signed session
# cookie and repeated as a hidden form field. A POST must send both, and they
# must match.

def get_csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return session["csrf_token"]


def csrf_token_is_valid(submitted):
    expected = session.get("csrf_token")
    if not expected or not submitted:
        return False
    return hmac.compare_digest(expected.encode(), submitted.encode())


@bp.app_context_processor
def inject_csrf_token():
    return {"csrf_token": get_csrf_token}


def validate(form):
    """Return (values, errors). values echo the input so the form can be re-rendered."""
    values = {
        "name": form.get("name", "").strip(),
        "language": form.get("language", ""),
        "container_experience": form.get("container_experience", ""),
        "environments": form.getlist("environments"),
        # Browsers send newlines as \r\n but count them as one character.
        "comments": form.get("comments", "").replace("\r\n", "\n").strip(),
    }
    errors = {}

    if len(values["name"]) > NAME_MAX:
        errors["name"] = f"Name must be {NAME_MAX} characters or fewer."
    if values["language"] not in LANGUAGES:
        errors["language"] = "Choose a language from the list."
    if values["container_experience"] not in {str(level) for level in EXPERIENCE_LEVELS}:
        errors["container_experience"] = "Choose a rating from 1 to 5."
    if not values["environments"]:
        errors["environments"] = "Choose at least one environment."
    elif any(env not in ENVIRONMENTS for env in values["environments"]):
        errors["environments"] = "Choose environments from the list only."
    if len(values["comments"]) > COMMENTS_MAX:
        errors["comments"] = f"Comments must be {COMMENTS_MAX} characters or fewer."

    return values, errors


@bp.get("/")
def form():
    return render_template("form.html", values=EMPTY_FORM, errors={}, **CHOICES)


@bp.post("/")
def submit():
    values, errors = validate(request.form)
    if not csrf_token_is_valid(request.form.get("csrf_token", "")):
        errors["form"] = (
            "This form could not be verified (the page may have expired). "
            "Please submit it again."
        )
    if errors:
        return render_template("form.html", values=values, errors=errors, **CHOICES), 400

    # Store environments in the fixed list order, without duplicates.
    environments = [env for env in ENVIRONMENTS if env in values["environments"]]
    db = get_db()
    db.execute(
        "INSERT INTO submissions"
        " (created_at, name, language, container_experience, environments, comments)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
            values["name"] or None,
            values["language"],
            int(values["container_experience"]),
            json.dumps(environments),
            values["comments"] or None,
        ),
    )
    db.commit()
    # POST/redirect/GET: reloading the thanks page does not resubmit the form.
    return redirect(url_for("survey.thanks"))


@bp.get("/thanks")
def thanks():
    return render_template("thanks.html")


@bp.get("/results")
def results():
    db = get_db()
    total = db.execute("SELECT COUNT(*) FROM submissions").fetchone()[0]

    language_counts = dict.fromkeys(LANGUAGES, 0)
    for row in db.execute(
        "SELECT language, COUNT(*) AS n FROM submissions GROUP BY language"
    ):
        language_counts[row["language"]] = row["n"]

    experience_counts = dict.fromkeys(EXPERIENCE_LEVELS, 0)
    for row in db.execute(
        "SELECT container_experience AS level, COUNT(*) AS n"
        " FROM submissions GROUP BY container_experience"
    ):
        experience_counts[row["level"]] = row["n"]

    # Each row stores a JSON array; json_each turns it into one row per item.
    environment_counts = dict.fromkeys(ENVIRONMENTS, 0)
    for row in db.execute(
        "SELECT json_each.value AS environment, COUNT(*) AS n"
        " FROM submissions, json_each(submissions.environments)"
        " GROUP BY json_each.value"
    ):
        environment_counts[row["environment"]] = row["n"]

    recent = [
        {
            "created_at": row["created_at"][:19].replace("T", " "),
            "name": row["name"] or "anonymous",
            "language": row["language"],
            "container_experience": row["container_experience"],
            "environments": ", ".join(json.loads(row["environments"])),
            "comments": row["comments"] or "",
        }
        for row in db.execute(
            "SELECT created_at, name, language, container_experience, environments, comments"
            " FROM submissions ORDER BY id DESC LIMIT 10"
        )
    ]

    return render_template(
        "results.html",
        total=total,
        language_counts=language_counts,
        experience_counts=experience_counts,
        environment_counts=environment_counts,
        recent=recent,
        **CHOICES,
    )


@bp.get("/healthz")
def healthz():
    """Report healthy only if the database answers a trivial query."""
    try:
        get_db().execute("SELECT 1").fetchone()
    except sqlite3.Error as exc:
        current_app.logger.error("Health check failed: %s", exc)
        return jsonify(status="error"), 503
    return jsonify(status="ok")
