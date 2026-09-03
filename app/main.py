from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import os

app = FastAPI(title="Autonomous Business Manager")

class LoginRequest(BaseModel):
    password: str

@app.get("/", response_class=HTMLResponse)
def read_root():
    return """
    <html>
    <head>
        <title>Autonomous Business Manager</title>
        <style>
            body { background-color: #0b192c; color: white; font-family: Tahoma, sans-serif; text-align: center; padding-top: 50px; }
            .container { max-width: 400px; margin: auto; background: #1e3e62; padding: 30px; border-radius: 15px; box-shadow: 0 4px 15px rgba(0,0,0,0.5); }
            input { width: 80%; padding: 12px; margin: 15px 0; border-radius: 8px; border: none; text-align: center; font-size: 16px; }
            button { background: #ff6584; color: white; border: none; padding: 12px 25px; border-radius: 8px; font-size: 16px; cursor: pointer; font-weight: bold; }
            button:hover { background: #ff335c; }
        </style>
    </head>
    <body>
        <div class="container">
            <div style="font-size: 50px; margin-bottom: 10px;">🧠</div>
            <h2>ارحب يا وجه النقاء</h2>
            <p style="color: #94bbe9; font-size: 14px;">أدخل كلمة المرور السرية للنظام</p>
            <input type="password" id="password" placeholder="كلمة المرور السرية">
            <br>
            <button onclick="login()">دخول</button>
        </div>
        <script>
            function login() {
                const pass = document.getElementById('password').value;
                if(pass) {
                    alert('جاري التحقق من الأمان...');
                } else {
                    alert('يرجى إدخال كلمة المرور!');
                }
            }
        </script>
    </body>
    </html>
    """

@app.get("/health")
def health_check():
    return {"status": "active", "system": "Autonomous Business Manager"}

