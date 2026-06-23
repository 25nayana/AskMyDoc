from flask import Flask, render_template, request, flash, redirect, session
from logging.handlers import RotatingFileHandler
from datetime import timedelta
from dotenv import load_dotenv
from pymongo import MongoClient
import requests
import logging
from datetime import datetime
import os

handler = RotatingFileHandler('myapp.log', maxBytes=5*1024*1024, backupCount=2)
formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
handler.setFormatter(formatter)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logger.addHandler(handler)

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY")
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=10)

mongo_uri = os.getenv("MONGO_URI")
client = MongoClient(mongo_uri)
db = client["chat_db"]
chat_collection = db["chat_history"]

BASE_URL = "http://localhost:8000"

@app.before_request
def set_session_expiry():
    session.permanent = True  

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user_id = request.form.get("user_id")
        if not user_id:
            flash("Please enter a user ID")
            return redirect("/login")
        session["user_id"] = user_id
        logger.info(f"User {user_id} logged in at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        return redirect("/")
    return render_template("login.html")

@app.route("/")
def index():
    user_id = session.get("user_id")
    if not user_id:
        return redirect("/login")
    
    chat_data = chat_collection.find_one({"user_id": user_id})
    chat = chat_data["chat"] if chat_data else []
    return render_template("index.html", chat=chat)

@app.route("/upload", methods=["POST"])
def upload():
    files = request.files.getlist("files")  
    user_id = session.get("user_id")

    if not files:
        flash("No files selected.")
        return redirect("/")

    success = True
    for file in files:
        if file.filename == '':
            continue

        ext = file.filename.split('.')[-1].lower()
        if ext not in ['pdf', 'docx']:
            flash(f"{file.filename} is not a supported file type.")
            success = False
            continue

        send_file = {
            "file": (file.filename, file.stream, file.mimetype),
            "user_id": (None, user_id)
        }

        response = requests.post(f"{BASE_URL}/get", files=send_file)

        if response.status_code != 200:
            flash(f"Error processing {file.filename}")
            success = False
        else:
            flash(f"{file.filename} uploaded and processed successfully!")

    if success:
        flash("All files processed successfully!")

    return redirect("/")

@app.route("/ask", methods=["POST"])
def ask():
    user_id = session.get("user_id")
    question = request.form['question']

    logger.info(f"Question asked by user {user_id} at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    response = requests.post(f"{BASE_URL}/chat", json={"question": question, "user_id": user_id})
    # answer = response.json().get("answer")
    
    logger.info(f"Answer received by user {user_id} at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    return redirect("/")  # reload page to show updated chat

if __name__ == "__main__":
    app.run(port=5000, debug=True)