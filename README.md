# Autonomous Business Manager

نظام إدارة وأتمتة شخصي بواجهة عربية، FastAPI + SQLite + Playwright، وبطاقات موافقة بشرية.

## التشغيل
`pip install -r requirements.txt` ثم `playwright install chromium` ثم `uvicorn app.main:app --reload`

ضع `OPENAI_API_KEY` في البيئة فقط، ولا تضعه داخل GitHub. لا يوجد تجاوز CAPTCHA أو تخفٍ أو تشغيل مباشر لكود مرفوع. الإجراءات الخارجية الحساسة خلف موافقة.
