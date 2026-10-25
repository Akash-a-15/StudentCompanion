# Contributing to StudentCompanion

Help make everyday coursework easier to manage. Bug reports, documentation improvements, and focused pull requests are welcome.

## Get started

Follow the [README quickstart](README.md#quickstart) to set up the Flask and SQLite application. Use a separate development database and sample accounts; avoid opening or changing the committed database during development.

The repository currently has no `templates/` or `static/` assets, so browser pages fail to render. Restoring the interface is a useful contribution. Health and summary endpoints are available for backend work; the summary requires a logged-in session.

## Choose a contribution

- **Fix a bug:** describe the problem and a minimal way to reproduce it.
- **Improve the interface:** discuss the intended screen and user flow before a large redesign.
- **Improve documentation:** check commands against a fresh setup and explain any limitations.
- **Suggest a feature:** explain who needs it and what task it would make easier.

Use the repository's issue forms to share a bug or feature idea. For a large change, open an issue first so the scope is clear.

## Send a pull request

1. Create a branch for one focused change.
2. Follow the existing Python style and keep unrelated cleanup separate.
3. Validate the behavior you changed. There is no automated test suite yet; report the commands and manual checks you ran. Add a focused test when fixing behavior that can regress.
4. Describe the problem, your change, and its validation in the pull request. Include screenshots for interface changes, using fictional data.

Keep `.env`, local databases, uploaded files, passwords, and student records out of commits, logs, screenshots, and issue reports. Use synthetic data when demonstrating a problem. A `.gitignore` rule does not remove files or sensitive data already committed to Git history.
