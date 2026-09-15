Smart Agri Market AI - Render Backend (Groq enabled)

Files:
- main.py
- smart_agri_agent.py
- requirements.txt
- render.yaml
- README_GU.txt

Render:
Build: pip install -r requirements.txt
Start: uvicorn main:app --host 0.0.0.0 --port $PORT
Root Directory: blank

Environment variables:
GROQ_API_KEY = your Groq API key (keep secret)
GROQ_TEXT_MODEL = openai/gpt-oss-20b
GROQ_VISION_MODEL = qwen/qwen3.6-27b

Optional fallback:
OPENAI_API_KEY
OPENAI_MODEL = gpt-5.6-luna

Behavior:
- Text AI prefers Groq, then optional OpenAI, then the supplied local agent.
- Photo diagnosis prefers Groq vision, then optional OpenAI vision.
- Android API paths remain unchanged:
  /api/v1/health
  /api/v1/ai/ask
  /api/v1/ai/diagnose

Do not put API keys in GitHub files or the Android APK. Store them in Render Environment Variables.
