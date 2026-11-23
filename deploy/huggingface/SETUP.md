# Run the API on a Hugging Face Space

The website stays on Vercel; only the API runs on the Space. The Space starts from the
image GitHub Actions publishes for each merged commit (ghcr.io/joe254h/icpac-backend:<sha>),
so nothing is built on Hugging Face.

1. huggingface.co → New → Space. Name `icpac-api`, SDK **Docker** (blank template),
   hardware **CPU basic (free)**, public. If a free account may not create a Docker Space,
   upgrade to PRO and create it again.
2. Files → Add file → Upload: `Dockerfile` and `README.md` from this folder (replace the
   template's README).
3. Settings → Variables and secrets:
   - Secret `STAFF_CREDENTIALS`: `[{"name":"Joe254h","key":"<long random key>","roles":["admin"]}]`
   - Secret `LLM_API_KEY`: the OpenRouter key
   - Variables: `LLM_PROVIDER=openai_compatible`, `LLM_BASE_URL=https://openrouter.ai/api/v1`,
     `LLM_MODEL=openai/gpt-oss-120b`, `LLM_TOOLS=true`, `LLM_TIMEOUT_SECONDS=60`,
     `PUBLIC_SITE_URL=<the Vercel site URL>`
   - Optional secret `DATABASE_URL`: the Supabase connection string, so bulletins and records
     survive restarts. Without it they live on the Space's disk and are lost on restart.
4. Wait for "Running", then open `https://joe254h-icpac-api.hf.space/health`.
5. Vercel → the project → Settings → Environment Variables: set `API_URL` to
   `https://joe254h-icpac-api.hf.space` (Production), then Deployments → Redeploy.
6. On the website: Staff access → Operations → Run the weekly cycle (again after each
   restart of the Space, whose disk is wiped).

A free Space sleeps after about 48 hours without visitors; the next visit wakes it in a
minute or two.
