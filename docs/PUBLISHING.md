# Publishing the repository

Make the project easy to understand before changing its visibility. Repository visibility and running a public web app are separate operations; neither starts the other.

## Repository visibility

The owner confirmed that the committed SQLite database contains disposable demo data. A public repository exposes all committed files and their history, including this database. Do not add real accounts, student records, private notes, or credentials to future commits. Ignoring a file does not remove an already tracked file or its history.

With repository administration access, open [the repository settings](https://github.com/Akash-a-15/StudentCompanion/settings), find **Danger Zone → Change repository visibility**, and choose **Public**. Follow GitHub's confirmation prompts.

If GitHub CLI access is available, the equivalent is:

```bash
gh repo edit Akash-a-15/StudentCompanion \
  --visibility public \
  --accept-visibility-change-consequences
```

Verify the result with `gh repo view Akash-a-15/StudentCompanion --json visibility` and by opening the repository while signed out.

## Help people find it

Suggested About description:

> A Flask and SQLite companion for student attendance, class notes, and subject management.

Suggested topics: `python`, `flask`, `sqlite`, `education`, `student-management`, `attendance`, `notes`, `learning-project`.

Use the repository's **About** settings, or:

```bash
gh repo edit Akash-a-15/StudentCompanion \
  --description "A Flask and SQLite companion for student attendance, class notes, and subject management." \
  --add-topic python --add-topic flask --add-topic sqlite \
  --add-topic education --add-topic student-management \
  --add-topic attendance --add-topic notes --add-topic learning-project
```

Keep the work-in-progress status visible until the browser templates are restored. Add real screenshots and a walkthrough after that; a working demo is more useful than unverified feature claims. Choose a license before inviting others to reuse or redistribute the code.

## GitHub access from the cloud environment

Git fetch/push access does not imply permission to administer a repository through GitHub's API. API operations require network access to `api.github.com` and authentication with repository administration permission. Use the platform's existing authentication first; do not commit tokens or paste them into chat.
