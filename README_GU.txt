SMART AGRI-MARKET AI — Android AI Backend

આ folder Render પર અલગ Web Service તરીકે deploy કરવાનું છે. Weather service અને આ AI service અલગ છે.

1) Render માં New Web Service બનાવો અને આ ai_backend folder deploy કરો.
2) Build Command: pip install -r requirements.txt
3) Start Command: uvicorn main:app --host 0.0.0.0 --port $PORT
4) Environment Variable:
   OPENAI_API_KEY = તમારી OpenAI API key (optional for rule-based agent; required for full OpenAI AI/vision)
   OPENAI_MODEL = gpt-5.6-luna
5) Deploy થયા પછી browserમાં ચેક કરો:
   https://YOUR-SERVICE.onrender.com/api/v1/health
   તેમાં ok=true અને agent_loaded=true આવવું જોઈએ.
6) Android > Settings > AI Backend URL માં:
   https://YOUR-SERVICE.onrender.com/api/v1/

Android calls:
POST /api/v1/ai/ask
POST /api/v1/ai/diagnose

મહત્વપૂર્ણ: જો Androidમાં HTTP 404 આવે તો URL ખોટો છે અથવા Render પર આ AI backend deploy થયેલું નથી. Weather Render URL અહીં ન મૂકવો.

આ backendમાં આપેલી smart_agri_agent.py નો પાક-જ્ઞાન fallback પણ જોડાયેલ છે, એટલે OPENAI key વગર પણ AI Agent પ્રશ્નોના મૂળભૂત ખેતી જવાબ આપે છે.
