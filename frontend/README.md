# Parametric Screw Generator — Frontend

Next.js frontend deployed on Vercel. Proxies API calls to the Python/CadQuery backend on Railway.

## Local Development

1. Start the Python backend (from the project root):
   ```
   python run_web.py
   ```

2. Install frontend dependencies and start dev server:
   ```
   cd frontend
   npm install
   npm run dev
   ```

3. Visit http://localhost:3000

For local dev, auth is configured with placeholder values in `.env.local`.

## Deployment

### 1. Deploy Python Backend to Railway

1. Go to [railway.com](https://railway.com) and create a new project
2. Connect your GitHub repo
3. Railway will auto-detect the `Dockerfile` and build
4. Set environment variables:
   - `PORT` = `8000`
   - `HOST` = `0.0.0.0`
   - `BACKEND_API_KEY` = (generate a random secret, e.g. `openssl rand -hex 32`)
   - `GEMINI_API_KEY` = (optional, for image-based screw detection)
5. Deploy — note the Railway URL (e.g. `https://your-app.up.railway.app`)

### 2. Set Up Google OAuth

1. Go to [Google Cloud Console](https://console.cloud.google.com/apis/credentials)
2. Create an OAuth 2.0 Client ID (Web application)
3. Add authorized redirect URI: `https://your-app.vercel.app/api/auth/callback/google`
4. Set the OAuth consent screen to **Internal** (restricts to your Google Workspace org)
5. Note the Client ID and Client Secret

### 3. Deploy Frontend to Vercel

1. Go to [vercel.com](https://vercel.com) and import your GitHub repo
2. Set the **Root Directory** to `frontend`
3. Set environment variables:
   - `BACKEND_URL` = your Railway URL (e.g. `https://your-app.up.railway.app`)
   - `BACKEND_API_KEY` = same secret you set on Railway
   - `GOOGLE_CLIENT_ID` = from Google Cloud Console
   - `GOOGLE_CLIENT_SECRET` = from Google Cloud Console
   - `AUTH_SECRET` = (generate with `openssl rand -base64 32`)
4. Deploy
