import os
import re
import sqlite3
import tempfile
import unittest
from contextlib import closing
from unittest.mock import Mock

from roadmap import create_app
from roadmap.demo import DEMO_ISSUES
from roadmap.jira import JiraClient, JiraError
from roadmap.storage import get_local_issues, initialize_storage


class RoadmapAppTests(unittest.TestCase):
    def setUp(self):
        self.config = {
            "TESTING": True,
            "JIRA_BASE_URL": "https://example.atlassian.net",
            "JIRA_EMAIL": "user@example.com",
            "JIRA_API_TOKEN": "not-a-real-token",
            "JIRA_PROJECT_KEY": "ROAD",
            "JIRA_START_DATE_FIELD": "customfield_10015",
            "JIRA_END_DATE_FIELD": "duedate",
            "JIRA_DOMAIN_FIELD": "customfield_10100",
            "JIRA_SPONSOR_FIELD": "customfield_10101",
            "JIRA_JQL": 'project = "{project_key}" ORDER BY Rank ASC',
            "JIRA_TIMEOUT_SECONDS": 15,
        }
        self.data_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.data_dir.cleanup)
        self.config["ROADMAP_DATA_DIR"] = os.path.join(self.data_dir.name, "roadmap_files")
        self.config["LEGACY_ROADMAP_DATABASE"] = None

    def test_missing_configuration_shows_setup_without_calling_jira(self):
        app = create_app({
            "TESTING": True,
            "JIRA_BASE_URL": "",
            "ROADMAP_DATA_DIR": self.config["ROADMAP_DATA_DIR"],
            "LEGACY_ROADMAP_DATABASE": None,
        })

        response = app.test_client().get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Demo roadmap", response.data)
        self.assertIn(b"live project data", response.data)
        self.assertIn(b"RELEX", response.data)
        self.assertIn(b"ARBOL V7", response.data)
        self.assertIn(b"moteur de r\xc3\xa9approvisionnement automatique", response.data)
        self.assertIn(b"ANTOINE B", response.data)
        self.assertIn(b"2027-09-30", response.data)
        self.assertIn(b"2027-03-31", response.data)
        self.assertIn(b"Supply", response.data)
        self.assertIn(b"Offre", response.data)
        self.assertIn(b'data-edit-url="/issues/RELEX"', response.data)
        self.assertIn(b'name="key" placeholder="ROAD-123"', response.data)
        self.assertIn(b"issueKeyInput.readOnly = false", response.data)
        self.assertIn(b'data-delete-url="/issues/RELEX/delete"', response.data)
        self.assertIn(b'data-edit-url="/issues/ARBOL"', response.data)
        self.assertIn(b'id="issue-context-menu"', response.data)
        self.assertIn(b'id="confirm-delete-dialog"', response.data)
        self.assertIn(b'id="confirm-delete-issue">Confirmer la suppression', response.data)
        self.assertIn(b'id="cancel-delete-issue">Annuler', response.data)
        self.assertIn(b'pendingDeleteRow = row;', response.data)
        self.assertNotIn(b'class="edit-issue-button"', response.data)
        self.assertIn(b"Valentin H", response.data)
        self.assertIn(b"Alexandra C", response.data)
        self.assertIn(b'<span>Business</span>', response.data)
        self.assertNotIn(b"Business sponsor", response.data)
        self.assertIn(b'href="https://adeogroup.atlassian.net/browse/RELEX" target="_blank"', response.data)
        self.assertIn(b'href="https://adeogroup.atlassian.net/browse/ARBOL" target="_blank"', response.data)
        self.assertIn(b"domain-supply", response.data)
        self.assertIn(b"domain-offre", response.data)
        table = response.data.split(b'id="roadmap-table"', 1)[1].split(b"</table>", 1)[0]
        self.assertNotIn(b">Domain</span>", table)
        self.assertIn(b'colspan="9"', table)
        self.assertIn(b"JIRA_BASE_URL", response.data)
        self.assertNotIn(b"End date precedes start date", response.data)
        self.assertIn(b'role="tablist"', response.data)
        self.assertIn(b"Timeline", response.data)
        self.assertIn(b"oct. 2026", response.data)
        timeline = response.data.decode().split('id="timeline-panel"', 1)[1]
        self.assertNotIn('class="issue-link"', timeline)
        self.assertIn(
            'class="timeline-bar status-in-progress" href="https://adeogroup.atlassian.net/browse/RELEX"',
            timeline,
        )
        self.assertIn(b"sept. 2027", response.data)
        self.assertNotIn(b"Dates \xc3\xa0 corriger", response.data)
        self.assertIn(b'width: 49.86%"', response.data)
        self.assertIn(b"status-in-progress", response.data)
        self.assertIn(b"status-blocked", response.data)
        self.assertIn(b">Bloqu\xc3\xa9</span>", response.data)
        self.assertIn(b"RELEX \xe2\x80\x94 En cours", response.data)
        self.assertIn(b"UPGRADE", response.data)
        self.assertIn(b"ONBOARDING", response.data)
        self.assertLess(response.data.index(b"Offre"), response.data.index(b"Supply"))
        self.assertIn(b'data-sort="key" data-direction="asc">A \xe2\x86\x92 Z', response.data)
        self.assertIn(b'data-sort="start_date" data-direction="asc">Croissant', response.data)
        self.assertIn(b'data-sort="due_date" data-direction="desc">D\xc3\xa9croissant', response.data)
        self.assertIn(b'data-date-filter="start_date"', response.data)
        self.assertIn(b'data-date-filter="due_date"', response.data)
        self.assertIn(b'value="on-or-before">Avant ou le', response.data)
        self.assertIn(b'value="on-or-after">Apr\xc3\xa8s ou le', response.data)
        self.assertIn(b'data-multi-filter="status"', response.data)
        self.assertIn(b'data-multi-filter="issue_type"', response.data)
        self.assertIn(b'data-multi-filter="domain"', response.data)
        self.assertIn(b'data-sort="domain" data-direction="asc">A \xe2\x86\x92 Z', response.data)
        self.assertIn(b'data-sort="domain" data-direction="desc">Z \xe2\x86\x92 A', response.data)
        self.assertIn(b'aria-label="Filter start date">', response.data)
        self.assertIn(b'aria-label="Sort start date">', response.data)
        self.assertIn(b".column-menu:not([open]) > .column-popover { display: none; }", response.data)
        self.assertIn(b'data-direction="asc">A \xe2\x86\x92 Z', response.data)
        self.assertIn(b"01/10/2026", response.data)
        self.assertNotIn(b"class=\"dates\"", response.data)
        self.assertIn(b".roadmap-table th:nth-child(4), .roadmap-table td:nth-child(4) { width: auto; }", response.data)
        self.assertIn(b".roadmap-table th:not(:nth-child(4)), .roadmap-table td:not(:nth-child(4)) { width: 1%; white-space: nowrap; }", response.data)
        self.assertIn(b".issue-description { color: #5e6c84; font-size: .78rem;", response.data)
        self.assertIn(b'<option>Onboarding</option><option>Upgrade</option><option>Improvement</option>', response.data)
        self.assertIn(b'<option>Offre</option><option>Supply</option><option>Travaux</option>', response.data)
        self.assertIn(b'class="priority priority-high"', response.data)
        self.assertIn(b'class="priority priority-medium"', response.data)
        self.assertIn(b'class="table-group"', response.data)
        self.assertIn(b"<strong>ARBOL V7</strong>", response.data)
        timeline_issue = response.data.decode().split('id="timeline-panel"', 1)[1]
        timeline_rows = timeline_issue.split('<div class="timeline-row">')[1:]
        self.assertTrue(timeline_rows)
        self.assertTrue(all('class="issue-link"' not in row.split('<div class="timeline-track">', 1)[0] for row in timeline_rows))
        self.assertIn('class="timeline-bar status-in-progress" href="https://adeogroup.atlassian.net/browse/ARBOL"', timeline_issue)
        self.assertIn('class="timeline-bar status-in-progress" href="https://adeogroup.atlassian.net/browse/RELEX"', timeline_issue)

    def test_demo_subjects_are_seeded_and_persisted_in_markdown_files(self):
        app = create_app({
            "TESTING": True,
            "JIRA_BASE_URL": "",
            "ROADMAP_DATA_DIR": self.config["ROADMAP_DATA_DIR"],
            "LEGACY_ROADMAP_DATABASE": None,
        })

        subjects = get_local_issues(self.config["ROADMAP_DATA_DIR"])
        self.assertEqual({issue["key"] for issue in subjects}, {"ARBOL", "RELEX"})
        self.assertEqual(
            {issue["key"]: (issue["domain"], issue["business_sponsor"]) for issue in subjects},
            {"ARBOL": ("Offre", "Alexandra C"), "RELEX": ("Supply", "Valentin H")},
        )
        self.assertTrue(os.path.isfile(os.path.join(self.config["ROADMAP_DATA_DIR"], "issues", "ARBOL.md")))
        self.assertTrue(os.path.isfile(os.path.join(self.config["ROADMAP_DATA_DIR"], "issues", "RELEX.md")))
        response = create_app({
            "TESTING": True,
            "JIRA_BASE_URL": "",
            "ROADMAP_DATA_DIR": self.config["ROADMAP_DATA_DIR"],
            "LEGACY_ROADMAP_DATABASE": None,
        }).test_client().get("/")
        self.assertIn(b"ARBOL V7", response.data)
        self.assertIn(b"RELEX", response.data)

    def test_invalid_or_non_https_jira_url_is_rejected(self):
        config = dict(self.config, JIRA_BASE_URL="http://example.atlassian.net")

        response = create_app(config).test_client().get("/")

        self.assertIn(b"must be a valid HTTPS", response.data)

    def test_roadmap_renders_planning_fields_in_date_order(self):
        issue = {
            "key": "ROAD-2",
            "summary": "Ship the release",
            "issue_type": "Story",
            "status": "In Progress",
            "priority": "High",
            "assignee": "Alex",
            "start_date": "2026-06-01",
            "due_date": "2026-06-30",
            "url": "https://example.atlassian.net/browse/ROAD-2",
        }
        jira_client = Mock()
        jira_client.get_issues.return_value = [
            dict(issue, key="ROAD-3", start_date="2026-07-01"),
            issue,
        ]
        app = create_app(self.config)

        with unittest.mock.patch("roadmap.JiraClient", return_value=jira_client):
            response = app.test_client().get("/")

        body = response.data.decode()
        self.assertLess(body.index("ROAD-2"), body.index("ROAD-3"))
        self.assertIn("2026-06-30", body)
        self.assertIn("Ship the release", body)
        self.assertIn("In Progress", body)
        self.assertIn("High", body)
        self.assertIn("Alex", body)
        self.assertIn('href="https://adeogroup.atlassian.net/browse/ROAD-2" target="_blank"', body)
        timeline = body.split('id="timeline-panel"', 1)[1]
        self.assertIn(
            'class="timeline-bar status-in-progress" href="https://adeogroup.atlassian.net/browse/ROAD-2" target="_blank"',
            timeline,
        )

    def test_local_issue_is_saved_and_links_to_adeo_jira_in_new_tab(self):
        app = create_app({
            "TESTING": True,
            "JIRA_BASE_URL": "",
            "ROADMAP_DATA_DIR": self.config["ROADMAP_DATA_DIR"],
            "LEGACY_ROADMAP_DATABASE": None,
        })
        client = app.test_client()
        page = client.get("/")
        csrf_token = re.search(rb'name="csrf_token" value="([^"]+)"', page.data).group(1).decode()

        response = client.post("/issues", data={
            "csrf_token": csrf_token,
            "key": "ROAD-123",
            "summary": "New roadmap item",
            "issue_type": "Improvement",
            "business_sponsor": "Valentin H",
            "domain": "Supply",
            "start_date": "2027-01-01",
            "due_date": "2027-02-01",
        }, follow_redirects=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"New roadmap item", response.data)
        self.assertIn(b"Valentin H", response.data)
        self.assertIn(b"Improvement", response.data)
        self.assertIn(b'href="https://adeogroup.atlassian.net/browse/ROAD-123" target="_blank"', response.data)
        self.assertIn(b"Le chantier a \xc3\xa9t\xc3\xa9 ajout\xc3\xa9", response.data)

        refreshed_page = create_app({
            "TESTING": True,
            "JIRA_BASE_URL": "",
            "ROADMAP_DATA_DIR": self.config["ROADMAP_DATA_DIR"],
            "LEGACY_ROADMAP_DATABASE": None,
        }).test_client().get("/")
        self.assertIn(b"ROAD-123", refreshed_page.data)

    def test_existing_local_issue_can_be_edited_and_renamed_by_key(self):
        app = create_app({
            "TESTING": True,
            "JIRA_BASE_URL": "",
            "ROADMAP_DATA_DIR": self.config["ROADMAP_DATA_DIR"],
            "LEGACY_ROADMAP_DATABASE": None,
        })
        client = app.test_client()
        page = client.get("/")
        csrf_token = re.search(rb'name="csrf_token" value="([^"]+)"', page.data).group(1).decode()

        response = client.post("/issues/RELEX", data={
            "csrf_token": csrf_token,
            "key": "ROAD-999",
            "summary": "Updated roadmap item",
            "description": "Updated context",
            "issue_type": "Upgrade",
            "status": "Bloqué",
            "priority": "Élevée",
            "assignee": "New owner",
            "domain": "Travaux",
            "business_sponsor": "Alexandra C",
            "start_date": "2027-04-01",
            "due_date": "2027-05-01",
        }, follow_redirects=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Le chantier a \xc3\xa9t\xc3\xa9 modifi\xc3\xa9", response.data)
        self.assertIn(b"Updated roadmap item", response.data)
        self.assertIn(b"New owner", response.data)
        updated_issue = next(
            issue for issue in get_local_issues(self.config["ROADMAP_DATA_DIR"])
            if issue["file_id"] == "ROAD-999"
        )
        self.assertEqual(updated_issue["key"], "ROAD-999")
        self.assertEqual(updated_issue["description"], "Updated context")
        self.assertEqual(updated_issue["issue_type"], "Upgrade")
        self.assertEqual(updated_issue["status"], "Bloqué")
        self.assertEqual(updated_issue["domain"], "Travaux")
        self.assertEqual(updated_issue["business_sponsor"], "Alexandra C")
        self.assertEqual(updated_issue["start_date"], "2027-04-01")
        self.assertEqual(updated_issue["due_date"], "2027-05-01")
        self.assertFalse(os.path.exists(os.path.join(self.config["ROADMAP_DATA_DIR"], "issues", "RELEX.md")))
        self.assertTrue(os.path.exists(os.path.join(self.config["ROADMAP_DATA_DIR"], "issues", "ROAD-999.md")))

    def test_edit_local_issue_requires_csrf_and_valid_fields(self):
        app = create_app({
            "TESTING": True,
            "JIRA_BASE_URL": "",
            "ROADMAP_DATA_DIR": self.config["ROADMAP_DATA_DIR"],
            "LEGACY_ROADMAP_DATABASE": None,
        })
        client = app.test_client()
        page = client.get("/")
        csrf_token = re.search(rb'name="csrf_token" value="([^"]+)"', page.data).group(1).decode()
        original = next(issue for issue in get_local_issues(self.config["ROADMAP_DATA_DIR"]) if issue["key"] == "RELEX")

        missing_token = client.post("/issues/RELEX", data={"summary": "Should not save"})
        invalid_choice = client.post("/issues/RELEX", data={
            "csrf_token": csrf_token,
            "key": "RELEX",
            "summary": "Should not save",
            "issue_type": "Unknown",
            "domain": "Supply",
        }, follow_redirects=True)

        self.assertEqual(missing_token.status_code, 400)
        self.assertIn(b"Choisis un type parmi", invalid_choice.data)
        self.assertEqual(
            next(issue for issue in get_local_issues(self.config["ROADMAP_DATA_DIR"]) if issue["key"] == "RELEX"),
            original,
        )

    def test_edit_local_issue_rejects_duplicate_key(self):
        app = create_app({
            "TESTING": True,
            "JIRA_BASE_URL": "",
            "ROADMAP_DATA_DIR": self.config["ROADMAP_DATA_DIR"],
            "LEGACY_ROADMAP_DATABASE": None,
        })
        client = app.test_client()
        page = client.get("/")
        csrf_token = re.search(rb'name="csrf_token" value="([^"]+)"', page.data).group(1).decode()

        response = client.post("/issues/RELEX", data={
            "csrf_token": csrf_token,
            "key": "ARBOL",
            "summary": "Duplicate key",
            "issue_type": "Upgrade",
            "domain": "Supply",
        }, follow_redirects=True)

        self.assertIn(b"Cette cl\xc3\xa9 existe d\xc3\xa9j\xc3\xa0", response.data)
        self.assertTrue(os.path.isfile(os.path.join(self.config["ROADMAP_DATA_DIR"], "issues", "RELEX.md")))
        self.assertEqual(
            next(issue for issue in get_local_issues(self.config["ROADMAP_DATA_DIR"]) if issue["key"] == "RELEX")["summary"],
            "RELEX",
        )

    def test_local_issue_can_be_deleted_with_csrf_confirmation_flow(self):
        app = create_app({
            "TESTING": True,
            "JIRA_BASE_URL": "",
            "ROADMAP_DATA_DIR": self.config["ROADMAP_DATA_DIR"],
            "LEGACY_ROADMAP_DATABASE": None,
        })
        client = app.test_client()
        page = client.get("/")
        csrf_token = re.search(rb'name="csrf_token" value="([^"]+)"', page.data).group(1).decode()

        missing_token = client.post("/issues/RELEX/delete")
        deleted = client.post(
            "/issues/RELEX/delete",
            data={"csrf_token": csrf_token},
            follow_redirects=True,
        )

        self.assertEqual(missing_token.status_code, 400)
        self.assertEqual(deleted.status_code, 200)
        self.assertIn(b"Le chantier a \xc3\xa9t\xc3\xa9 supprim\xc3\xa9", deleted.data)
        self.assertNotIn("RELEX", {issue["key"] for issue in get_local_issues(self.config["ROADMAP_DATA_DIR"])})
        self.assertFalse(os.path.isfile(os.path.join(self.config["ROADMAP_DATA_DIR"], "issues", "RELEX.md")))
        self.assertEqual(client.post("/issues/RELEX/delete", data={"csrf_token": csrf_token}).status_code, 404)

    def test_local_issue_rejects_missing_csrf_token(self):
        app = create_app({
            "TESTING": True,
            "JIRA_BASE_URL": "",
            "ROADMAP_DATA_DIR": self.config["ROADMAP_DATA_DIR"],
            "LEGACY_ROADMAP_DATABASE": None,
        })

        response = app.test_client().post("/issues", data={"key": "ROAD-123", "summary": "No token"})

        self.assertEqual(response.status_code, 400)

    def test_local_issue_rejects_type_or_domain_outside_allowed_options(self):
        app = create_app({
            "TESTING": True,
            "JIRA_BASE_URL": "",
            "ROADMAP_DATA_DIR": self.config["ROADMAP_DATA_DIR"],
            "LEGACY_ROADMAP_DATABASE": None,
        })
        client = app.test_client()
        page = client.get("/")
        csrf_token = re.search(rb'name="csrf_token" value="([^"]+)"', page.data).group(1).decode()

        invalid_choices = [
            ("ROAD-123", "Chantier", "Offre", b"Choisis un type parmi"),
            ("ROAD-124", "Onboarding", "Unknown", b"Choisis un domaine parmi"),
        ]
        for key, issue_type, domain, message in invalid_choices:
            with self.subTest(issue_type=issue_type, domain=domain):
                response = client.post("/issues", data={
                    "csrf_token": csrf_token,
                    "key": key,
                    "summary": "Invalid options",
                    "issue_type": issue_type,
                    "domain": domain,
                }, follow_redirects=True)
                self.assertIn(message, response.data)
                self.assertNotIn(b"Invalid options", response.data)

    def test_tbd_issues_are_confirmed_in_form_and_rendered_without_jira_links(self):
        app = create_app({
            "TESTING": True,
            "JIRA_BASE_URL": "",
            "ROADMAP_DATA_DIR": self.config["ROADMAP_DATA_DIR"],
            "LEGACY_ROADMAP_DATABASE": None,
        })
        client = app.test_client()
        page = client.get("/")
        csrf_token = re.search(rb'name="csrf_token" value="([^"]+)"', page.data).group(1).decode()

        for summary in ("Unplanned item one", "Unplanned item two"):
            client.post("/issues", data={
                "csrf_token": csrf_token,
                "key": "TBD",
                "summary": summary,
                "issue_type": "Upgrade",
                "domain": "Travaux",
            })
        response = client.get("/")

        self.assertIn(b"window.confirm(", page.data)
        self.assertIn(b"Unplanned item one", response.data)
        self.assertIn(b"Unplanned item two", response.data)
        self.assertEqual(response.data.count(b'class="issue-key-placeholder">TBD</strong>'), 2)
        self.assertNotIn(b'href="https://adeogroup.atlassian.net/browse/TBD"', response.data)

    def test_existing_sqlite_data_is_migrated_to_markdown_files(self):
        database_path = os.path.join(self.data_dir.name, "legacy.sqlite3")
        data_directory = os.path.join(self.data_dir.name, "migrated_files")
        with closing(sqlite3.connect(database_path)) as connection, connection:
            connection.execute(
                """
                CREATE TABLE local_issues (
                    key TEXT PRIMARY KEY,
                    summary TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    issue_type TEXT NOT NULL DEFAULT 'Chantier',
                    status TEXT NOT NULL DEFAULT 'Backlog',
                    priority TEXT NOT NULL DEFAULT 'Moyenne',
                    assignee TEXT NOT NULL DEFAULT '',
                    domain TEXT NOT NULL DEFAULT '',
                    business_sponsor TEXT NOT NULL DEFAULT '',
                    start_date TEXT,
                    due_date TEXT
                )
                """
            )
            connection.execute(
                """
                INSERT INTO local_issues (key, summary, description, issue_type, domain)
                VALUES ('ROAD-22', 'Existing issue', '## Context\n\nDetails', 'Improvement', 'Travaux')
                """
            )

        initialize_storage(data_directory, database_path, DEMO_ISSUES)
        issues = get_local_issues(data_directory)
        migrated = next(issue for issue in issues if issue["key"] == "ROAD-22")

        self.assertEqual(migrated["summary"], "Existing issue")
        self.assertEqual(migrated["description"], "## Context\n\nDetails")
        self.assertEqual(migrated["domain"], "Travaux")
        self.assertTrue(os.path.isfile(os.path.join(data_directory, "issues", "ROAD-22.md")))
        initialize_storage(data_directory, database_path, DEMO_ISSUES)
        self.assertEqual(
            sum(issue["key"] == "ROAD-22" for issue in get_local_issues(data_directory)),
            1,
        )

    def test_migration_preserves_multiple_keyless_issues(self):
        database_path = os.path.join(self.data_dir.name, "legacy_tbd.sqlite3")
        data_directory = os.path.join(self.data_dir.name, "migrated_tbd_files")
        with closing(sqlite3.connect(database_path)) as connection, connection:
            connection.execute(
                """
                CREATE TABLE local_issues (
                    id INTEGER PRIMARY KEY,
                    key TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT ''
                )
                """
            )
            connection.executemany(
                "INSERT INTO local_issues (key, summary) VALUES ('TBD', ?)",
                (("Unplanned issue one",), ("Unplanned issue two",)),
            )

        initialize_storage(data_directory, database_path, DEMO_ISSUES)
        migrated = [issue for issue in get_local_issues(data_directory) if issue["key"] == "TBD"]

        self.assertEqual({issue["summary"] for issue in migrated}, {"Unplanned issue one", "Unplanned issue two"})
        self.assertEqual(len({issue["file_id"] for issue in migrated}), 2)
        initialize_storage(data_directory, database_path, DEMO_ISSUES)
        self.assertEqual(
            sum(issue["key"] == "TBD" for issue in get_local_issues(data_directory)),
            2,
        )

    def test_markdown_storage_keeps_long_descriptions_in_markdown_body(self):
        app = create_app({
            "TESTING": True,
            "JIRA_BASE_URL": "",
            "ROADMAP_DATA_DIR": self.config["ROADMAP_DATA_DIR"],
            "LEGACY_ROADMAP_DATABASE": None,
        })
        client = app.test_client()
        page = client.get("/")
        csrf_token = re.search(rb'name="csrf_token" value="([^"]+)"', page.data).group(1).decode()
        client.post("/issues", data={
            "csrf_token": csrf_token,
            "key": "ROAD-23",
            "summary": "Markdown content",
            "issue_type": "Improvement",
            "domain": "Travaux",
            "description": "## Context\n\nA longer description.",
        })

        issue_file = os.path.join(self.config["ROADMAP_DATA_DIR"], "issues", "ROAD-23.md")
        with open(issue_file, encoding="utf-8") as file:
            content = file.read()
        self.assertTrue(content.startswith('---\n{\n  "key": "ROAD-23"'))
        self.assertIn("## Description\n\n## Context\n\nA longer description.", content)

    def test_jira_failure_is_shown_as_a_gateway_error(self):
        jira_client = Mock()
        jira_client.get_issues.side_effect = JiraError("Could not retrieve issues from Jira.")
        app = create_app(self.config)

        with unittest.mock.patch("roadmap.JiraClient", return_value=jira_client):
            response = app.test_client().get("/")

        self.assertEqual(response.status_code, 502)
        self.assertIn(b"Jira connection failed", response.data)

    def test_timeline_shows_single_day_issue_as_a_milestone(self):
        issue = {
            "key": "ROAD-1",
            "summary": "Launch",
            "issue_type": "Milestone",
            "status": "To Do",
            "priority": "High",
            "assignee": "Alex",
            "start_date": "2026-10-01",
            "due_date": "2026-10-01",
            "url": "https://example.atlassian.net/browse/ROAD-1",
        }
        jira_client = Mock()
        jira_client.get_issues.return_value = [issue]
        app = create_app(self.config)

        with unittest.mock.patch("roadmap.JiraClient", return_value=jira_client):
            response = app.test_client().get("/")

        self.assertIn(b'class="timeline-point status-backlog"', response.data)
        self.assertIn(b"oct. 2026", response.data)
        timeline = response.data.decode().split('id="timeline-panel"', 1)[1]
        self.assertIn(
            'class="timeline-milestone status-backlog" href="https://adeogroup.atlassian.net/browse/ROAD-1" target="_blank"',
            timeline,
        )

    def test_timeline_maps_requested_statuses_to_colors(self):
        issues = [
            {"status": "Terminé"},
            {"status": "En cours"},
            {"status": "En cadrage"},
            {"status": "Backlog"},
            {"status": "Bloqué"},
            {"status": "Blocked"},
            {"status": "In Progress"},
        ]

        from roadmap import _status_color

        self.assertEqual(
            [_status_color(issue["status"]) for issue in issues],
            ["completed", "in-progress", "framing", "backlog", "blocked", "blocked", "in-progress"],
        )

    def test_priority_style_supports_jira_and_french_labels(self):
        from roadmap import _priority_style

        self.assertEqual(_priority_style("Highest"), ("↑↑", "highest"))
        self.assertEqual(_priority_style("Élevée"), ("↑", "high"))
        self.assertEqual(_priority_style("Moyenne"), ("→", "medium"))
        self.assertEqual(_priority_style("Low"), ("↓", "low"))

    def test_jira_client_paginates_and_formats_issue_data(self):
        first_response = Mock()
        first_response.json.return_value = {
            "issues": [{"key": "ROAD-1", "fields": {
                "summary": "First issue",
                "description": {
                    "type": "doc",
                    "content": [
                        {"type": "paragraph", "content": [{"type": "text", "text": "A description."}]},
                        {"type": "paragraph", "content": [{"type": "text", "text": "Second paragraph."}]},
                    ],
                },
                "issuetype": {"name": "Story"},
                "status": {"name": "To Do"},
                "priority": {"name": "Medium"},
                "assignee": None,
                "customfield_10100": {"value": "Supply"},
                "customfield_10101": {"displayName": "Valentin H"},
                "customfield_10015": "2026-01-01",
                "duedate": "2026-02-01",
            }}],
            "isLast": False,
            "nextPageToken": "page-two",
        }
        second_response = Mock()
        second_response.json.return_value = {"issues": [], "isLast": True}
        session = Mock()
        session.get.side_effect = [first_response, second_response]

        issues = JiraClient(self.config, session=session).get_issues()

        self.assertEqual(issues[0]["start_date"], "2026-01-01")
        self.assertEqual(issues[0]["due_date"], "2026-02-01")
        self.assertEqual(issues[0]["description"], "A description.\nSecond paragraph.\n")
        self.assertEqual(issues[0]["assignee"], "Unassigned")
        self.assertEqual(issues[0]["domain"], "Supply")
        self.assertEqual(issues[0]["business_sponsor"], "Valentin H")
        self.assertEqual(session.get.call_args_list[1].kwargs["params"]["nextPageToken"], "page-two")


if __name__ == "__main__":
    unittest.main()
