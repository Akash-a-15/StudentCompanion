# EduCompanion - Free Internet Deployment Guide

This guide explains how to make your **EduCompanion** app accessible over the internet from anywhere, 100% for free.

---

## Option 1: 24/7 Cloud Hosting on Render (Recommended)

[Render](https://render.com) offers a free Web Service tier that includes automatic HTTPS, a public URL (`https://educompanion.onrender.com`), and continuous deployment from GitHub.

### Steps:
1. **Push your code to GitHub**:
   - Create a repository named `studentcompanion` on [GitHub](https://github.com).
   - Commit and push your project files (`app.py`, `wsgi.py`, `requirements.txt`, `templates/`, `static/`).
2. **Sign up on Render**:
   - Go to [render.com](https://render.com) and create a free account (sign in with GitHub).
3. **Create a New Web Service**:
   - Click **New +** -> **Web Service**.
   - Select your `studentcompanion` repository.
4. **Configure Settings**:
   - **Environment**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn wsgi:app`
   - **Instance Type**: `Free`
5. **Set Environment Variables**:
   - Click **Environment Variables** -> **Add Environment Variable**:
     - `FLASK_SECRET_KEY`: Enter a 32+ character random string.
     - `PYTHON_VERSION`: `3.11.0`
6. **Deploy**:
   - Click **Create Web Service**. Within 2 minutes, your app will be live on the internet!

*Note on Free Tier*: Free Render instances enter sleep mode after 15 minutes of inactivity; the first visitor after idle will experience a ~30-50 second cold start.

---

## Option 2: Free Hosting on PythonAnywhere (Persistent SQLite)

[PythonAnywhere](https://www.pythonanywhere.com) is built specifically for Python and allows your SQLite database to remain persistent on disk without any external database service.

### Steps:
1. Register for a free "Beginner" account at [pythonanywhere.com](https://www.pythonanywhere.com).
2. Go to the **Web** tab and click **Add a new web app**.
3. Select **Flask** and **Python 3.10** (or manual configuration).
4. In the **Files** tab, upload your project files or clone your GitHub repository into your home directory (`/home/yourusername/studentcompanion`).
5. Open the **WSGI configuration file** (linked under the Web tab) and point it to your app:
   ```python
   import sys
   import os

   project_home = '/home/yourusername/studentcompanion'
   if project_home not in sys.path:
       sys.path.insert(0, project_home)

   os.environ['FLASK_SECRET_KEY'] = 'your-secret-key-at-least-32-chars-long'
   from app import app as application
   ```
6. Click **Reload yourusername.pythonanywhere.com**. Your app is live at `https://yourusername.pythonanywhere.com`!

---

## Option 3: Instant Public Access via Cloudflare Tunnel (Zero Cloud Setup)

If you have the app running on your computer and want to instantly share a public HTTPS link with friends, teachers, or test devices anywhere in the world:

1. Download the free [Cloudflare Tunnel utility (cloudflared)](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/).
2. Run your Flask app locally:
   ```bash
   python app.py
   ```
3. Open a second terminal window and run:
   ```bash
   cloudflared tunnel --url http://127.0.0.1:5000
   ```
4. Cloudflare outputs a free secure link:
   ```
   https://random-words-1234.trycloudflare.com
   ```
Anyone anywhere in the world can open that URL on their mobile phone or laptop and use your app directly.
