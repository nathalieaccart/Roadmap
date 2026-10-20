import json
import os
import re
import sqlite3
import uuid
from contextlib import closing


JIRA_BROWSE_BASE_URL = "https://adeogroup.atlassian.net/"
ISSUE_FIELDS = (
    "key",
    "summary",
    "issue_type",
    "status",
    "priority",
    "assignee",
    "domain",
    "business_sponsor",
    "start_date",
    "due_date",
)
MIGRATION_MARKER = ".sqlite-migration-v1.done"


class RoadmapStorageError(Exception):
    pass


def initialize_storage(data_directory, legacy_database_path, demo_issues):
    issues_directory = os.path.join(data_directory, "issues")
    os.makedirs(issues_directory, exist_ok=True)
    migration_marker = os.path.join(data_directory, MIGRATION_MARKER)

    if not os.path.exists(migration_marker):
        if legacy_database_path and os.path.isfile(legacy_database_path):
            _import_legacy_database(issues_directory, legacy_database_path)
        for issue in demo_issues:
            if not _has_issue_key(issues_directory, issue["key"]):
                _write_issue(issues_directory, issue, _file_id(issue["key"]))
        with open(migration_marker, "w", encoding="utf-8") as marker:
            marker.write("Markdown issue files are the active roadmap storage.\n")


def get_local_issues(data_directory):
    issues_directory = os.path.join(data_directory, "issues")
    issues = [_read_issue(path) for path in _issue_paths(issues_directory)]
    return sorted(issues, key=lambda issue: (issue["key"], issue["file_id"]))


def add_local_issue(data_directory, issue):
    issues_directory = os.path.join(data_directory, "issues")
    os.makedirs(issues_directory, exist_ok=True)
    if issue["key"] != "TBD" and _has_issue_key(issues_directory, issue["key"]):
        return False

    file_id = _file_id(issue["key"])
    if issue["key"] == "TBD":
        file_id += "-" + uuid.uuid4().hex
    _write_issue(issues_directory, issue, file_id)
    return True


def update_local_issue(data_directory, file_id, issue):
    issues_directory = os.path.join(data_directory, "issues")
    path = next(
        (
            candidate
            for candidate in _issue_paths(issues_directory)
            if os.path.splitext(os.path.basename(candidate))[0] == file_id
        ),
        None,
    )
    if path is None:
        return False

    current_issue = _read_issue(path)
    current_file_id = current_issue["file_id"]
    updated_issue = dict(issue)
    if updated_issue["key"] == "TBD" and current_issue["key"] != "TBD":
        updated_file_id = _file_id("TBD") + "-" + uuid.uuid4().hex
    elif updated_issue["key"] == current_issue["key"]:
        updated_file_id = current_file_id
    else:
        updated_file_id = _file_id(updated_issue["key"])
    updated_path = os.path.join(issues_directory, updated_file_id + ".md")
    if updated_path != path and os.path.exists(updated_path):
        raise RoadmapStorageError(f"Roadmap issue file already exists: {updated_path}")

    temporary_path = updated_path + "." + uuid.uuid4().hex + ".tmp"
    try:
        with open(temporary_path, "x", encoding="utf-8", newline="\n") as issue_file:
            issue_file.write(_issue_content(updated_issue))
        if updated_path == path:
            os.replace(temporary_path, path)
        else:
            os.rename(temporary_path, updated_path)
            os.remove(path)
    except OSError as exc:
        raise RoadmapStorageError(f"Could not update roadmap issue file: {path}") from exc
    finally:
        try:
            os.remove(temporary_path)
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise RoadmapStorageError(f"Could not clean up temporary roadmap issue file: {temporary_path}") from exc
    return True


def delete_local_issue(data_directory, file_id):
    path = next(
        (
            candidate
            for candidate in _issue_paths(os.path.join(data_directory, "issues"))
            if os.path.splitext(os.path.basename(candidate))[0] == file_id
        ),
        None,
    )
    if path is None:
        return False
    try:
        os.remove(path)
    except OSError as exc:
        raise RoadmapStorageError(f"Could not delete roadmap issue file: {path}") from exc
    return True


def _import_legacy_database(issues_directory, database_path):
    try:
        with closing(sqlite3.connect(database_path)) as connection:
            connection.row_factory = sqlite3.Row
            table_exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'local_issues'"
            ).fetchone()
            if not table_exists:
                return
            rows = connection.execute("SELECT * FROM local_issues ORDER BY key, rowid").fetchall()
    except sqlite3.Error as exc:
        raise RoadmapStorageError("Could not import the existing local roadmap data.") from exc

    for row in rows:
        issue = {field: row[field] for field in ISSUE_FIELDS if field in row.keys()}
        issue["description"] = row["description"] if "description" in row.keys() else ""
        for field in ISSUE_FIELDS:
            issue.setdefault(field, None if field in {"start_date", "due_date"} else "")
        if issue["key"] != "TBD" and _has_issue_key(issues_directory, issue["key"]):
            continue
        file_id = _file_id(issue["key"])
        if issue["key"] == "TBD":
            file_id += "-" + uuid.uuid4().hex
        _write_issue(issues_directory, issue, file_id)


def _has_issue_key(issues_directory, key):
    return any(issue["key"] == key for issue in (_read_issue(path) for path in _issue_paths(issues_directory)))


def _issue_paths(issues_directory):
    if not os.path.isdir(issues_directory):
        return []
    return [
        os.path.join(issues_directory, name)
        for name in sorted(os.listdir(issues_directory))
        if name.endswith(".md")
    ]


def _file_id(key):
    safe_key = re.sub(r"[^A-Za-z0-9_-]", "-", key).strip("-")
    return safe_key or uuid.uuid4().hex


def _write_issue(issues_directory, issue, file_id):
    path = os.path.join(issues_directory, file_id + ".md")
    try:
        with open(path, "x", encoding="utf-8", newline="\n") as issue_file:
            issue_file.write(_issue_content(issue))
    except FileExistsError:
        raise RoadmapStorageError(f"Roadmap issue file already exists: {path}")
    except OSError as exc:
        raise RoadmapStorageError(f"Could not save roadmap issue file: {path}") from exc


def _issue_content(issue):
    document = {field: issue.get(field) for field in ISSUE_FIELDS}
    metadata = json.dumps(document, ensure_ascii=False, indent=2)
    description = issue.get("description") or ""
    return f"---\n{metadata}\n---\n\n## Description\n\n{description}\n"


def _read_issue(path):
    try:
        with open(path, "r", encoding="utf-8") as issue_file:
            content = issue_file.read()
        if not content.startswith("---\n"):
            raise ValueError("Missing JSON front matter.")
        _, metadata_text, markdown_body = content.split("---\n", 2)
        metadata = json.loads(metadata_text)
        markdown_body = markdown_body.lstrip("\n")
        description_heading = "## Description\n\n"
        if not markdown_body.startswith(description_heading):
            raise ValueError("Missing Markdown description section.")
        description = markdown_body[len(description_heading):].rstrip("\n")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise RoadmapStorageError(f"Could not read roadmap issue file: {path}") from exc

    for field in ISSUE_FIELDS:
        metadata.setdefault(field, None if field in {"start_date", "due_date"} else "")
    metadata["description"] = description
    metadata["file_id"] = os.path.splitext(os.path.basename(path))[0]
    return metadata
