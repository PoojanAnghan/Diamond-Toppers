# VDB Diamond Scraper System

A full-stack monorepo system containing a **Next.js Web Frontend** and a **Django REST API Backend** to upload, enrich, and scrape diamond listings, automatically storing results in a **Supabase PostgreSQL** database and syncing files to **Google Drive**.

---

## Directory Structure

```text
untitled folder/
├── vdb_backend/       # Django Ninja REST API (Python 3.9)
└── vdb_frontend/      # Next.js Web Dashboard (React & TypeScript)
```

---

## 🚀 Getting Started

### 1. Backend Setup (`vdb_backend`)
The backend is powered by **Django Ninja**, using **Supabase PostgreSQL** as its primary database.

1. **Navigate to the backend directory**:
   ```bash
   cd vdb_backend
   ```
2. **Set up the virtual environment**:
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   ```
3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```
4. **Configure your environment variables**:
   Create a `.env` file in `vdb_backend/` (refer to `.env.example` or the setup guides) with your Supabase `DATABASE_URL` and Google API credentials.
5. **Run database migrations**:
   ```bash
   python manage.py migrate
   ```
6. **Start the development server**:
   ```bash
   python manage.py runserver
   ```
   The backend will be available at **`http://127.0.0.1:8000/`**. You can access the interactive Swagger API documentation at **`http://127.0.0.1:8000/api/docs`**.

---

### 2. Frontend Setup (`vdb_frontend`)
The frontend is a modern **Next.js** application.

1. **Navigate to the frontend directory**:
   ```bash
   cd vdb_frontend
   ```
2. **Install node dependencies**:
   ```bash
   npm install
   ```
3. **Configure environment variables**:
   Create a `.env.local` file with the URL of the Django backend:
   ```env
   NEXT_PUBLIC_API_URL=http://localhost:8000
   ```
4. **Start the development server**:
   ```bash
   npm run dev
   ```
   The frontend dashboard will be available at **`http://localhost:3000/`**.

---

## 🔐 Database & Storage Integration
* **Database**: Hosted on **Supabase PostgreSQL** using the Supavisor connection pooler (IPv4-compatible port `5432`/`6543`).
* **File Storage**: Uploaded files and enriched results are synced directly to **Google Drive** using Google OAuth 2.0 and Google Service Account credentials configured in `.env`.
* **CORS & CSRF**: Backend is fully configured to permit cross-origin requests from the `http://localhost:3000` frontend, bypassing session cookie checks in favor of Bearer Token authentication.

---

## 🌐 Production Deployment
* **Backend**: Optimized for deployment on **Render** (via standard `build.sh` script and `gunicorn` runner). Static assets are served via `whitenoise`. Refer to `RENDER_DEPLOYMENT_GUIDE.md` inside `vdb_backend/` for setup details.
* **Frontend**: Can be deployed on **Vercel** or **Render** by linking your Next.js repository.
