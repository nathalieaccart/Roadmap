import os
import re
import secrets
from datetime import date
from unicodedata import combining, normalize
from urllib.parse import urljoin, urlparse

from dotenv import load_dotenv
from flask import Flask, abort, flash, redirect, render_template, request, session, url_for

from roadmap.demo import DEMO_ISSUES
from roadmap.jira import JiraClient, JiraError
from roadmap.storage import (
    JIRA_BROWSE_BASE_URL,
    RoadmapStorageError,
    add_local_issue,
    delete_local_issue,
    get_local_issues,
    initialize_storage,
    update_local_issue,
)


load_dotenv()

PROJECT_KEY_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")
ISSUE_KEY_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*-\d+$")
ISSUE_TYPES = {"Onboarding", "Upgrade", "Improvement"}
DOMAINS = {"Offre", "Supply", "Travaux"}


def create_app(config=None):
    app = Flask(__name__)
    app.config.from_mapping(
        JIRA_BASE_URL=os.getenv("JIRA_BASE_URL", "").strip().rstrip("/"),
        JIRA_EMAIL=os.getenv("JIRA_EMAIL", "").strip(),
        JIRA_API_TOKEN=os.getenv("JIRA_API_TOKEN", ""),
        JIRA_PROJECT_KEY=os.getenv("JIRA_PROJECT_KEY", "").strip().upper(),
        JIRA_START_DATE_FIELD=os.getenv("JIRA_START_DATE_FIELD", "customfield_10015").strip(),
        JIRA_END_DATE_FIELD=os.getenv("JIRA_END_DATE_FIELD", "duedate").strip(),
        JIRA_DOMAIN_FIELD=os.getenv("JIRA_DOMAIN_FIELD", "").strip(),
        JIRA_SPONSOR_FIELD=os.getenv("JIRA_SPONSOR_FIELD", "").strip(),
        ROADMAP_DATA_DIR=os.getenv("ROADMAP_DATA_DIR", os.path.join(app.instance_path, "roadmap_files")),
        LEGACY_ROADMAP_DATABASE=os.getenv(
            "LEGACY_ROADMAP_DATABASE",
            os.path.join(app.instance_path, "roadmap.sqlite3"),
        ),
        JIRA_JQL=os.getenv(
            "JIRA_JQL",
            'project = "{project_key}" AND issuetype != Sub-task ORDER BY Rank ASC',
        ),
        JIRA_TIMEOUT_SECONDS=float(os.getenv("JIRA_TIMEOUT_SECONDS", "15")),
    )
    if config:
        app.config.update(config)
    app.secret_key = os.getenv("FLASK_SECRET_KEY") or secrets.token_hex(32)
    app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")
    initialize_storage(
        app.config["ROADMAP_DATA_DIR"],
        app.config["LEGACY_ROADMAP_DATABASE"],
        DEMO_ISSUES,
    )

    @app.context_processor
    def inject_csrf_token():
        if "csrf_token" not in session:
            session["csrf_token"] = secrets.token_urlsafe(32)
        return {"csrf_token": session["csrf_token"]}

    @app.get("/")
    def index():
        setup_error = _configuration_error(app.config)
        local_issues = get_local_issues(app.config["ROADMAP_DATA_DIR"])
        if setup_error:
            issues = local_issues
            demo_mode = True
            error = None
        else:
            try:
                issues = JiraClient(app.config).get_issues()
            except JiraError as exc:
                return render_template("index.html", error=str(exc)), 502
            demo_mode = False
            error = None

        existing_keys = {issue["key"] for issue in issues}
        issues.extend(issue for issue in local_issues if issue["key"] not in existing_keys)
        for issue in issues:
            issue.setdefault("domain", "")
            issue.setdefault("business_sponsor", "")
            issue["url"] = (
                urljoin(JIRA_BROWSE_BASE_URL, "browse/" + issue["key"])
                if issue["key"] != "TBD" else None
            )
        _add_schedule_warnings(issues)
        issues.sort(key=_roadmap_sort_key)
        timeline = _prepare_timeline(issues)
        return render_template(
            "index.html",
            setup_error=setup_error,
            issues=issues,
            timeline=timeline,
            demo_mode=demo_mode,
            error=error,
        )

    @app.post("/issues")
    def add_issue():
        expected_token = session.get("csrf_token", "")
        submitted_token = request.form.get("csrf_token", "")
        if not expected_token or not secrets.compare_digest(expected_token, submitted_token):
            abort(400)

        issue = _issue_from_form(request.form)
        validation_error = _issue_validation_error(issue)
        if validation_error:
            flash(validation_error, "error")
        elif not add_local_issue(app.config["ROADMAP_DATA_DIR"], issue):
            flash("Cette clé existe déjà dans les chantiers ajoutés localement.", "error")
        else:
            flash("Le chantier a été ajouté à cette roadmap locale.", "success")
        return redirect(url_for("index"))

    @app.post("/issues/<file_id>")
    def edit_issue(file_id):
        expected_token = session.get("csrf_token", "")
        submitted_token = request.form.get("csrf_token", "")
        if not expected_token or not secrets.compare_digest(expected_token, submitted_token):
            abort(400)

        local_issues = get_local_issues(app.config["ROADMAP_DATA_DIR"])
        existing_issue = next((item for item in local_issues if item["file_id"] == file_id), None)
        if existing_issue is None:
            abort(404)

        issue = _issue_from_form(request.form)
        validation_error = _issue_validation_error(
            issue,
            accepted_keys={item["key"] for item in local_issues},
        )
        if validation_error:
            flash(validation_error, "error")
        elif issue["key"] != "TBD" and any(
            item["key"] == issue["key"] and item["file_id"] != file_id
            for item in local_issues
        ):
            flash("Cette clé existe déjà dans les chantiers ajoutés localement.", "error")
        elif not update_local_issue(app.config["ROADMAP_DATA_DIR"], file_id, issue):
            abort(404)
        else:
            flash("Le chantier a été modifié dans cette roadmap locale.", "success")
        return redirect(url_for("index"))

    @app.post("/issues/<file_id>/delete")
    def delete_issue(file_id):
        expected_token = session.get("csrf_token", "")
        submitted_token = request.form.get("csrf_token", "")
        if not expected_token or not secrets.compare_digest(expected_token, submitted_token):
            abort(400)

        if not delete_local_issue(app.config["ROADMAP_DATA_DIR"], file_id):
            abort(404)
        flash("Le chantier a été supprimé de cette roadmap locale.", "success")
        return redirect(url_for("index"))

    @app.errorhandler(RoadmapStorageError)
    def storage_error(exc):
        app.logger.exception("Local roadmap file storage failed", exc_info=exc)
        return render_template("index.html", error=str(exc)), 500

    return app


def _configuration_error(config):
    required = {
        "JIRA_BASE_URL": config["JIRA_BASE_URL"],
        "JIRA_EMAIL": config["JIRA_EMAIL"],
        "JIRA_API_TOKEN": config["JIRA_API_TOKEN"],
        "JIRA_PROJECT_KEY": config["JIRA_PROJECT_KEY"],
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        return "Configure " + ", ".join(missing) + " in your local .env file."

    parsed_url = urlparse(config["JIRA_BASE_URL"])
    if parsed_url.scheme != "https" or not parsed_url.netloc:
        return "JIRA_BASE_URL must be a valid HTTPS Jira Cloud URL."
    if not PROJECT_KEY_PATTERN.fullmatch(config["JIRA_PROJECT_KEY"]):
        return "JIRA_PROJECT_KEY must be a valid Jira project key (for example, ROAD)."
    return None


def _issue_from_form(form):
    return {
        "key": form.get("key", "").strip().upper(),
        "summary": form.get("summary", "").strip(),
        "description": form.get("description", "").strip(),
        "issue_type": form.get("issue_type", "").strip(),
        "status": form.get("status", "").strip() or "Backlog",
        "priority": form.get("priority", "").strip() or "Moyenne",
        "assignee": form.get("assignee", "").strip(),
        "domain": form.get("domain", "").strip(),
        "business_sponsor": form.get("business_sponsor", "").strip(),
        "start_date": _form_date(form.get("start_date", "")),
        "due_date": _form_date(form.get("due_date", "")),
    }


def _issue_validation_error(issue, accepted_keys=None):
    if (
        issue["key"] != "TBD"
        and issue["key"] not in (accepted_keys or set())
        and not ISSUE_KEY_PATTERN.fullmatch(issue["key"])
    ):
        return "Saisis une clé Jira valide, par exemple ROAD-123, ou laisse le champ vide."
    if not issue["summary"]:
        return "Le résumé du chantier est obligatoire."
    if issue["issue_type"] not in ISSUE_TYPES:
        return "Choisis un type parmi Onboarding, Upgrade et Improvement."
    if issue["domain"] not in DOMAINS:
        return "Choisis un domaine parmi Offre, Supply et Travaux."
    if issue["start_date"] is False or issue["due_date"] is False:
        return "Les dates doivent être valides."
    return None


def _roadmap_sort_key(issue):
    return (issue["start_date"] or issue["due_date"] or "9999-12-31", issue["key"])


def _add_schedule_warnings(issues):
    for issue in issues:
        issue["date_conflict"] = bool(
            issue["start_date"] and issue["due_date"] and issue["due_date"] < issue["start_date"]
        )
        issue["status_color"] = _status_color(issue["status"])
        issue["domain_color"] = _domain_color(issue.get("domain"))
        issue["priority_icon"], issue["priority_color"] = _priority_style(issue.get("priority"))


def _status_color(status):
    normalized = normalize("NFKD", status.casefold())
    normalized = "".join(char for char in normalized if not combining(char))
    normalized = normalized.strip()
    if normalized in {"termine", "done", "complete", "completed", "closed"}:
        return "completed"
    if normalized in {"en cours", "in progress", "in-progress"}:
        return "in-progress"
    if normalized in {"en cadrage", "cadrage", "scoping", "discovery"}:
        return "framing"
    if normalized in {"bloque", "blocked"}:
        return "blocked"
    return "backlog"


def _domain_color(domain):
    normalized = (domain or "").strip().casefold()
    if normalized == "offre":
        return "offre"
    if normalized == "supply":
        return "supply"
    return "default"


def _priority_style(priority):
    normalized = normalize("NFKD", (priority or "").casefold())
    normalized = "".join(char for char in normalized if not combining(char)).strip()
    styles = {
        "highest": ("↑↑", "highest"),
        "blocker": ("↑↑", "highest"),
        "tres elevee": ("↑↑", "highest"),
        "tres haute": ("↑↑", "highest"),
        "high": ("↑", "high"),
        "elevee": ("↑", "high"),
        "haute": ("↑", "high"),
        "medium": ("→", "medium"),
        "normal": ("→", "medium"),
        "moyenne": ("→", "medium"),
        "low": ("↓", "low"),
        "basse": ("↓", "low"),
        "lowest": ("↓↓", "lowest"),
        "tres basse": ("↓↓", "lowest"),
    }
    return styles.get(normalized, ("•", "default"))


def _form_date(value):
    if not value:
        return None
    return value if _parse_date(value) else False


def _prepare_timeline(issues):
    groups_by_domain = {}
    for issue in issues:
        domain = issue.get("domain") or ""
        if domain not in groups_by_domain:
            groups_by_domain[domain] = {
                "domain": domain or "Sans domaine",
                "domain_color": _domain_color(domain),
                "issues": [],
            }
        groups_by_domain[domain]["issues"].append(issue)
    groups = sorted(
        groups_by_domain.values(),
        key=lambda group: (group["domain"] == "Sans domaine", group["domain"].casefold()),
    )

    scheduled = []
    for issue in issues:
        start = _parse_date(issue["start_date"])
        end = _parse_date(issue["due_date"])
        if start and end and end < start:
            issue["timeline_left"] = None
            issue["timeline_width"] = None
            continue

        issue_start = start or end
        issue_end = end or start
        if issue_start:
            scheduled.append((issue, issue_start, issue_end))

    if not scheduled:
        return {"months": [], "groups": groups}

    first_month = min(start for _, start, _ in scheduled).replace(day=1)
    last_date = max(end for _, _, end in scheduled)
    axis_end = _next_month(last_date.replace(day=1))
    total_days = (axis_end - first_month).days
    months = []
    month = first_month
    while month < axis_end:
        months.append({
            "label": _MONTH_NAMES[month.month - 1] + " " + str(month.year),
            "left": _percentage((month - first_month).days, total_days),
        })
        month = _next_month(month)

    for issue, start, end in scheduled:
        issue["timeline_left"] = _percentage((start - first_month).days, total_days)
        issue["timeline_width"] = (
            "0" if start == end else _percentage((end - start).days + 1, total_days)
        )

    return {"months": months, "groups": groups}


_MONTH_NAMES = (
    "janv.", "févr.", "mars", "avr.", "mai", "juin",
    "juil.", "août", "sept.", "oct.", "nov.", "déc.",
)


def _parse_date(value):
    try:
        return date.fromisoformat(value) if value else None
    except (TypeError, ValueError):
        return None


def _next_month(value):
    if value.month == 12:
        return date(value.year + 1, 1, 1)
    return date(value.year, value.month + 1, 1)


def _percentage(part, whole):
    return f"{part / whole * 100:.2f}".rstrip("0").rstrip(".")
