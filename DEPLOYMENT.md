# Deploy EduCompanion

EduCompanion runs as a Flask application behind Gunicorn, with SQLite and uploaded notes stored on disk.

> **Current blocker:** this checkout does not include the HTML templates or static assets referenced by the application. The health API can run, but login, dashboard, and other browser pages fail with `TemplateNotFound`. Restore those assets before offering the browser app to users.

## Configuration

Supply settings through your host's environment or secret manager. Never commit real credentials, local `.env` files, databases, or uploads.

| Variable | Deployment requirement |
| --- | --- |
| `FLASK_SECRET_KEY` | A private random value of at least 32 characters, shared by all workers and retained across restarts. Changing it invalidates sessions. |
| `ADMIN_USERNAME` | An explicit username of at least 3 characters for the initial admin. |
| `ADMIN_PASSWORD` | A private password of at least 12 characters for the initial admin. Set it before the first startup; do not rely on the code's development fallback. |
| `DATABASE_PATH` | An absolute path on writable persistent storage, such as `/data/student_companion.db`. |
| `UPLOAD_DIR` | A writable directory on persistent storage, such as `/data/notes`. |
| `FLASK_ENV` | Set to `production` behind HTTPS. This enables secure session cookies, so browser sessions require HTTPS. |

Admin environment variables are used only when the database has no admin. Setting them does **not** reset an existing admin's credentials. Start with a fresh database path for a new deployment; the committed database contains disposable demo records.

Keep runtime storage outside the checkout and back up both SQLite and uploaded files. Create the database's parent directory before startup and give the application process write access. A restart or redeploy must preserve this storage.

`.env.example` lists only some settings; configure the admin and storage variables above as well. If using a local `.env` file, protect it and keep it outside any Docker build context: the current Dockerfile copies the entire context into the image.

## Run with Gunicorn

From the repository root, after creating a virtual environment, installing `requirements.txt`, and supplying the variables above:

```bash
python -m pip install -r requirements.txt
mkdir -p "$(dirname "$DATABASE_PATH")" "$UPLOAD_DIR"
gunicorn --bind "0.0.0.0:${PORT:-8000}" \
  --workers 2 --timeout 120 --preload wsgi:app
```

`--preload` imports the application and initializes SQLite in the master process before forking workers, avoiding concurrent first-start initialization. Put an HTTPS reverse proxy or managed HTTPS ingress in front of Gunicorn. Use one application instance with its local persistent SQLite storage; this guide does not establish multi-host database support.

## Run with Docker

Build from a clean checkout containing no local secrets or personal data. Inject secrets at runtime through the exported variables `FLASK_SECRET_KEY`, `ADMIN_USERNAME`, and `ADMIN_PASSWORD`; the following example does not put their values in the command or image:

```bash
docker build -t educompanion .
docker volume create educompanion-data
docker run --name educompanion \
  --publish 127.0.0.1:8000:8000 \
  --mount type=volume,source=educompanion-data,target=/data \
  --env FLASK_SECRET_KEY \
  --env ADMIN_USERNAME \
  --env ADMIN_PASSWORD \
  --env FLASK_ENV=production \
  --env DATABASE_PATH=/data/student_companion.db \
  --env UPLOAD_DIR=/data/notes \
  educompanion \
  gunicorn --bind 0.0.0.0:8000 --workers 2 --timeout 120 --preload wsgi:app
```

The named volume retains the database and uploads across container replacements. Keep it when removing the container. Connect the loopback-bound port to an HTTPS reverse proxy before testing browser sessions.

## Hosting and verification

The repository includes `render.yaml`, `Dockerfile`, and `Procfile` as starting points. Configure persistent storage, private secrets, HTTPS, and the startup command above for your chosen provider. The existing launch definitions do not include `--preload`, and the Render definition does not configure a persistent disk or initial admin credentials.

Provider plans, storage costs, availability, and idle-sleep behavior depend on current terms. Check those terms before choosing a host; these files do not guarantee free hosting or continuous availability.

After startup, check the internal health endpoint:

```bash
curl --fail http://127.0.0.1:8000/api/health
```

Expected JSON: `{"app":"EduCompanion","status":"ok"}`. Then verify registration, login, authenticated `/api/summary`, and logout through HTTPS. Once the missing templates are restored, verify the browser pages and note upload/download as well. Health success alone does not establish that the full application works.
