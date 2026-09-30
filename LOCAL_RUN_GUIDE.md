# ProjectGuard Local Run Guide

This guide explains how to start the backend and frontend locally, open the student and mentor portals, and create/login to accounts.

## What runs where

- **Backend/API:** FastAPI with Uvicorn at `http://127.0.0.1:8000`.
  - The frontend calls this server for signup, login, project data, plagiarism checks, and Axiom chatbot responses.
  - API documentation is available at `http://127.0.0.1:8000/docs` while the backend is running.
- **Frontend:** Static HTML, CSS, and JavaScript files in the `Frontend/` folder.
  - This project does not define a separate frontend framework or frontend server.
  - Serve the folder with Python's built-in HTTP server at `http://127.0.0.1:5500`.
- **Database:** PostgreSQL with the pgvector extension. The backend requires `DATABASE_URL`; it no longer falls back to SQLite.
- **Axiom chatbot:** Uses Groq via the backend. The Groq key remains in the root `.env`; it is never needed in the frontend.

## One-time setup

Run these commands from the project root (the directory containing `main.py` and `requirements.txt`):

```bash
source venv/bin/activate
python -m pip install -r requirements.txt
```

Keep the virtual environment activated for both servers. If this is a fresh setup and no `venv` exists, create one first:

```bash
python3 -m venv venv
source venv/bin/activate
python -m pip install -r requirements.txt
```

The root `.env` should contain `DATABASE_URL` with a PostgreSQL connection URL and the Groq API key. The current code accepts the existing `API_key` name; `GROQ_API_KEY` is also supported. The PostgreSQL server must have pgvector installed and the configured database user must be allowed to enable the `vector` extension. Do not put API keys in frontend files or share them publicly.

## Start the application

Open two terminal windows, and run both commands from the project root.

### Terminal 1: backend API

```bash
cd "Project_Guard"
source venv/bin/activate
python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

Leave this terminal running. You should see Uvicorn report that it is running on `http://127.0.0.1:8000`.

### Terminal 2: frontend static server

```bash
cd "Project_Guard"
python3 -m http.server 5500 --directory Frontend --bind 127.0.0.1
```

Leave this terminal running too. You can stop either server with `Control+C` in its terminal.

## Open the portals

- Student sign in/sign up: [http://127.0.0.1:5500/auth.html](http://127.0.0.1:5500/auth.html)
- Student portal: [http://127.0.0.1:5500/index.html](http://127.0.0.1:5500/index.html)
- Mentor sign in/sign up: [http://127.0.0.1:5500/mentor_auth.html](http://127.0.0.1:5500/mentor_auth.html)
- Mentor portal: [http://127.0.0.1:5500/mentor_index.html](http://127.0.0.1:5500/mentor_index.html)
- Backend API docs: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

Open the sign-in pages first. The dashboard pages redirect to the corresponding sign-in page if the browser has no saved login.

## Create an account and sign in

### Student

1. Open `http://127.0.0.1:5500/auth.html`.
2. Select **Sign Up**.
3. Enter a roll number, year, and password; confirm the password.
4. After account creation, return to **Login**.
5. Sign in with the same roll number and password. The student dashboard opens.

### Mentor

1. Open `http://127.0.0.1:5500/mentor_auth.html`.
2. Select **Sign Up**.
3. Enter a mentor name and password; confirm the password.
4. After account creation, return to **Login**.
5. Sign in with the same mentor name and password. The mentor dashboard opens.

Accounts are stored in the configured PostgreSQL database; signup is required unless an account already exists in that database. Successful login is remembered in browser `localStorage`. Use **Logout** in the portal to clear that browser login.

## PostgreSQL and vector search

Set `DATABASE_URL` in the root `.env` to the PostgreSQL connection URL. Backend startup enables pgvector before creating tables, creates the mentor roster and app tables in PostgreSQL, and adds the nullable `projects.embedding vector(1024)` column. A database administrator may need to install pgvector on the server first and grant extension privileges.

If you need to move existing records from the old local `DB/training_data.db`, run `python migrate_sqlite_to_postgres.py` once after setting `DATABASE_URL`. The SQLite file is only a read-only migration source; the running app reads and writes PostgreSQL. The importer also copies mentor roster rows if that legacy database contains them. To prepare project vectors later, set `CLOUDFLARE_ACCOUNT_ID` and `CLOUDFLARE_API_TOKEN` in the backend environment, then run:

```bash
python -m Models.scripts.index_postgres_vectors
```

This fills missing project embeddings using Cloudflare Workers AI and stores each vector alongside its project ID and metadata in PostgreSQL. `embeddings.project_vectors.find_similar_projects(title, abstract, top_k)` performs cosine-similarity search. The existing SBERT plagiarism checker remains unchanged and continues using its current local index until you explicitly switch its scoring path.

## Common issues

- **`zsh: command not found: uvicorn`:** Activate the environment with `source venv/bin/activate`, then use `python -m uvicorn ...` as above.
- **Frontend loads but API requests fail:** Confirm Terminal 1 is still running on port 8000. Both frontend scripts call `localhost:8000` or `127.0.0.1:8000`.
- **Port already in use:** Stop the older server with `Control+C`, or use another port and update frontend API URLs to match.
- **Axiom reports an AI service error:** Check that the Groq key exists in the root `.env`, then restart the backend.
- **Frontend page not found:** Confirm the static server was started with `--directory Frontend` from the project root and visit one of the URLs above.
