from urllib.parse import urljoin

import requests


class JiraError(Exception):
    pass


class JiraClient:
    PAGE_SIZE = 100

    def __init__(self, config, session=None):
        self.base_url = config["JIRA_BASE_URL"].rstrip("/") + "/"
        self.email = config["JIRA_EMAIL"]
        self.api_token = config["JIRA_API_TOKEN"]
        self.project_key = config["JIRA_PROJECT_KEY"]
        self.start_date_field = config["JIRA_START_DATE_FIELD"]
        self.end_date_field = config["JIRA_END_DATE_FIELD"]
        self.domain_field = config["JIRA_DOMAIN_FIELD"]
        self.sponsor_field = config["JIRA_SPONSOR_FIELD"]
        self.jql = config["JIRA_JQL"].replace("{project_key}", self.project_key)
        self.timeout = config["JIRA_TIMEOUT_SECONDS"]
        self.session = session or requests.Session()

    def get_issues(self):
        fields = ["summary", "description", "status", "priority", "issuetype", "assignee"]
        for field in (self.start_date_field, self.end_date_field, self.domain_field, self.sponsor_field):
            if field and field not in fields:
                fields.append(field)

        issues = []
        next_page_token = None
        while True:
            params = {
                "jql": self.jql,
                "fields": ",".join(fields),
                "maxResults": self.PAGE_SIZE,
            }
            if next_page_token:
                params["nextPageToken"] = next_page_token

            try:
                response = self.session.get(
                    urljoin(self.base_url, "rest/api/3/search/jql"),
                    params=params,
                    auth=(self.email, self.api_token),
                    timeout=self.timeout,
                )
                response.raise_for_status()
            except requests.RequestException as exc:
                raise JiraError("Could not retrieve issues from Jira. Check your connection and Jira settings.") from exc

            try:
                result = response.json()
            except ValueError as exc:
                raise JiraError("Jira returned an unreadable response.") from exc

            issues.extend(self._format_issue(issue) for issue in result.get("issues", []))
            if result.get("isLast", True):
                break
            next_page_token = result.get("nextPageToken")
            if not next_page_token:
                raise JiraError("Jira returned an incomplete page of issues.")

        return issues

    def _format_issue(self, issue):
        fields = issue.get("fields", {})
        assignee = fields.get("assignee") or {}
        return {
            "key": issue.get("key", ""),
            "summary": fields.get("summary", ""),
            "description": _description_text(fields.get("description")),
            "issue_type": _display_name(fields.get("issuetype")),
            "status": _display_name(fields.get("status")),
            "priority": _display_name(fields.get("priority")),
            "assignee": assignee.get("displayName", "Unassigned"),
            "domain": _domain_value(fields.get(self.domain_field)) if self.domain_field else "",
            "business_sponsor": _domain_value(fields.get(self.sponsor_field)) if self.sponsor_field else "",
            "start_date": _date_value(fields.get(self.start_date_field)) if self.start_date_field else None,
            "due_date": _date_value(fields.get(self.end_date_field)) if self.end_date_field else None,
            "url": urljoin(self.base_url, "browse/" + issue.get("key", "")),
        }


def _display_name(value):
    return value.get("name", "—") if value else "—"


def _domain_value(value):
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return value.get("value") or value.get("name") or value.get("displayName") or ""
    if isinstance(value, list):
        return ", ".join(filter(None, (_domain_value(item) for item in value)))
    return ""


def _date_value(value):
    return value[:10] if isinstance(value, str) and value else None


def _description_text(value):
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(_description_text(child) for child in value)
    if not isinstance(value, dict):
        return ""

    if value.get("type") == "text":
        return value.get("text", "")

    content = _description_text(value.get("content", []))
    if value.get("type") in {"paragraph", "heading", "listItem"} and content:
        return content + "\n"
    return content
