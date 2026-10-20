# Jira project roadmap

A small local Flask app that reads Jira Cloud issues and displays their available schedule, description, status, priority, type, assignee, Business, and domain in table and timeline views. The table groups issues by domain, separates the key, summary, start and end dates, and uses tags for issue type plus Jira-style priority arrows. Filter domains from the toolbar above the table; use the filter icon in a column header for other filters and the sort icon to choose ascending or descending order. Date comparisons include the selected day; status, type, and domain filters support multiple selections. The plus button adds a roadmap-only chantier to editable Markdown files; it does not create or synchronize a Jira issue. Its Jira key links to `https://adeogroup.atlassian.net/browse/KEY` in a new tab. The timeline groups issues by domain, uses the summary as the issue title, shows the type as a tag, and labels each bar with its issue key and status. Timeline bars are colored by status (green for completed, blue for in progress, orange for framing, gray for backlog, and red for blocked). Jira credentials are used only by the server and are never sent to the browser. Until Jira is configured, the app shows the sample RELEX and ARBOL issues supplied for the roadmap; this makes the UI usable without an account or token.

Rows backed by local Markdown files have a context menu on right-click (or the keyboard context-menu key) to edit or delete them. Editing can change the Jira key and renames the local Markdown file accordingly; this does not rename or update a Jira issue. Deleting asks for confirmation and removes only the local Markdown file. Jira-sourced rows remain read-only in the roadmap.

## Run locally

1. Use Python 3.10 or later.
2. Create and activate a virtual environment, then install dependencies:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```

3. Copy `.env.example` to `.env` and set your Jira Cloud site URL, account email, API token, and project key. Create an API token in your Atlassian account security settings; do not commit `.env` or share the token.
4. Start the app and open `http://127.0.0.1:5000`:

   ```powershell
   py -m roadmap
   ```

If a chantier is submitted without a Jira key, the app asks for confirmation and stores it with the placeholder key `TBD`, shown in red without a Jira link. Multiple `TBD` chantiers are allowed. New subjects must use one of the types Onboarding, Upgrade, Improvement and one of the domains Offre, Supply, Travaux. Each subject is stored as an individual `issues/<KEY>.md` file: JSON front matter holds structured roadmap fields, and the Markdown body holds the long description. Multiple keyless subjects get unique `TBD-<id>.md` names. This format can be opened, copied, synced, and edited in a drive or used directly as AI context. RELEX and ARBOL are initialized as files if they are not already present. `ROADMAP_DATA_DIR` controls the folder; by default it is `instance/roadmap_files` in the project. To use a synced Drive folder, uncomment `ROADMAP_DATA_DIR` in `.env.example` when copying it to `.env`, then replace the example with the absolute path to that folder. If you have already added subjects in the default folder, copy the full `instance/roadmap_files` directory to the Drive folder before changing the setting. The app imports existing subjects from the previous SQLite file once into Markdown files; the SQLite file is not used for ongoing storage and is left untouched as a backup.

The app binds to localhost only. Do not expose it to a network or deploy it publicly without adding user authentication and appropriate access controls.

## Configuration

`JIRA_BASE_URL` must be an HTTPS Jira Cloud site URL. `JIRA_PROJECT_KEY` scopes the default JQL query to one project and excludes subtasks. Set `JIRA_JQL` to customize the query; `{project_key}` is replaced with the configured project key. The app retrieves all matching issues using Jira's paginated search endpoint.

The default start date field is `customfield_10015`, commonly used for Jira Software's Start date. Set `JIRA_START_DATE_FIELD` to the field ID used by your Jira site, or leave it empty to omit start dates. `JIRA_END_DATE_FIELD` defaults to Jira's `duedate` field and can also be set to a custom field ID. Fields unavailable to the Jira account or project may cause Jira to reject the search; verify the field IDs in your Jira site.

Set `JIRA_DOMAIN_FIELD` to the custom-field ID that holds the domain (for example, `customfield_10100`) to show domain tags for live issues. It is optional; without it, sample issues still show their demo domains.

Set `JIRA_SPONSOR_FIELD` to your Jira custom-field ID for Business to populate that column from live issues. The demo entries have Business values prefilled (Valentin H for RELEX and Alexandra C for ARBOL). Demo and locally added chantiers are stored in the configured roadmap files folder. When Jira is connected, live Jira issues are displayed in preference to stored entries with the same key.

The demo data uses a start date of 1 October 2026 and an end date of 31 March 2027 for ARBOL. The timeline uses the earliest and latest valid dates to create its monthly scale. Issues with reversed or missing dates remain visible and are flagged, but do not receive a misleading bar.

## Tests

Run the test suite with:

```powershell
py -m unittest discover -s tests
```
