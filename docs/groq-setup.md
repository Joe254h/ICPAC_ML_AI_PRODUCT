# Free Groq configuration

To use no outside AI service at all, run the Copilot's model yourself instead: see
[the self-hosted model guide](self-hosted-llm.md).

Create a free Groq account at https://console.groq.com and create an API key at
https://console.groq.com/keys. Stay on the Free plan. Qwen 3.8 27B is a preview model;
the published free quotas include 30 requests/minute, 1,000 requests/day and
200,000 tokens/day. Any request or token quota can be reached first. Check the
account's Limits page for its actual allowance.

## Azure Container Apps

1. Open the Azure portal, then **Container Apps > icpac-api** in resource group
   **icpac** (or the app/group names you chose).
2. Open **Secrets**, add a secret named **groq-api-key**, paste the key there and
   save it.
3. Open **Revisions and replicas > Create new revision** (or **Containers > Edit
   and deploy**), select the backend container and add
   these environment variables:

   | Name | Source | Value |
   | --- | --- | --- |
   | LLM_PROVIDER | Manual entry | openai_compatible |
   | LLM_BASE_URL | Manual entry | https://api.groq.com/openai/v1 |
   | LLM_MODEL | Manual entry | qwen/qwen3.8-27b |
   | LLM_REASONING_EFFORT | Manual entry | none |
   | LLM_API_KEY | Secret reference | groq-api-key |

4. Save/deploy the new revision and wait for it to become ready. These variables
   belong to the Python backend; the Vercel frontend needs only its existing API_URL.
5. Open **Forecaster Copilot**, send a question, and inspect the answer's provider.
   `openai_compatible` means the live endpoint returned an accepted outline.
   `deterministic_fallback` means the call failed or its outline was rejected; check
   the Azure backend logs and the Groq usage/limits dashboard. `mock` means the
   backend revision still has its old settings.

The backend validates the returned sentence IDs and keeps all numerical values in
Python. The model only chooses and orders validated sentences; changing the LLM does
not change the forecast context or supply missing scientific products.

## Local testing

Set the same variables in the shell that starts the backend. For example, in
PowerShell (the key below is a placeholder, not a real credential):

```powershell
$env:LLM_PROVIDER = 'openai_compatible'
$env:LLM_BASE_URL = 'https://api.groq.com/openai/v1'
$env:LLM_MODEL = 'qwen/qwen3.8-27b'
$env:LLM_REASONING_EFFORT = 'none'
$env:LLM_API_KEY = '<your Groq key>'
```

The backend deployment script preserves existing LLM settings and their secret
references when redeploying the backend image. Keep real keys out of Git.

Sources: [Groq limits](https://console.groq.com/docs/rate-limits),
[Groq compatibility](https://console.groq.com/docs/openai),
[Qwen reasoning settings](https://console.groq.com/docs/reasoning),
[Azure environment variables](https://learn.microsoft.com/en-us/azure/container-apps/environment-variables),
[Azure secrets](https://learn.microsoft.com/en-us/azure/container-apps/manage-secrets).
