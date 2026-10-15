import os
from app import app as flask_app

app = flask_app

if __name__ == "__main__":
    host = os.environ.get("FLASK_HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", os.environ.get("FLASK_PORT", "8000")))
    app.run(host=host, port=port, debug=False)
