from flask import Flask, request, jsonify, render_template, redirect, url_for, session, send_file
import openai, datetime, os
from collections import defaultdict, Counter
import matplotlib.pyplot as plt
from dotenv import load_dotenv
from pathlib import Path
from werkzeug.utils import secure_filename
from flask import request, jsonify
import smtplib, ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
import base64
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import (
    Mail, Email, To, Content,
    Attachment, FileContent, FileName, FileType, Disposition
)


load_dotenv()

app = Flask(__name__)
app.secret_key = "Test"  # Replace in production

openai.api_key = os.getenv("OPENAI_API_KEY")

ALLOWED_EXTENSIONS = {"png","jpg","jpeg","webp","svg","pdf"}
UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024  # 25 MB total

# === SendGrid settings (from environment) ===
SENDGRID_API_KEY = (os.getenv("SENDGRID_API_KEY") or "").strip()  # trim whitespace/newlines
FROM_EMAIL = (os.getenv("FROM_EMAIL", "admin@solarisai.co.uk") or "").strip()
TO_EMAIL = (os.getenv("TO_EMAIL", "admin@solarisai.co.uk") or "").strip()
SENDGRID_HOST = (os.getenv("SENDGRID_HOST", "https://api.sendgrid.com") or "").strip()

# sanity checks so we don't hit the API with bad config
if not SENDGRID_API_KEY or not SENDGRID_API_KEY.startswith("SG."):
    raise RuntimeError("SENDGRID_API_KEY is missing/invalid (doesn't start with 'SG.'). Check your .env and reload the app.")
if not FROM_EMAIL or not TO_EMAIL:
    raise RuntimeError("FROM_EMAIL or TO_EMAIL not set.")


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

# --- receiver for the brief ---
@app.route("/submit-brief", methods=["POST"])
def submit_brief():
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    base = f"brief_{ts}"

    # Save JSON
    brief_json = request.form.get("brief_json", "")
    json_path = os.path.join(app.config["UPLOAD_FOLDER"], f"{base}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        f.write(brief_json or "{}")

    # Save files
    saved_files = []
    for file in request.files.getlist("attachments"):
        if file and file.filename and allowed_file(file.filename):
            fname = secure_filename(file.filename)
            dest = os.path.join(app.config["UPLOAD_FOLDER"], f"{ts}_{fname}")
            file.save(dest)
            saved_files.append(dest)

        # --- Send email via SendGrid ---
    try:
        if not SENDGRID_API_KEY:
            raise RuntimeError("SENDGRID_API_KEY not set")

        subject = f"New Website Brief Submission — {ts}"
        body_html = f"""
        <h2>New Website Brief</h2>
        <p>Submitted at <strong>{ts}</strong></p>
        <p><strong>JSON file path (server):</strong> {json_path}</p>
        <p><strong>Uploaded files ({len(saved_files)}):</strong> {', '.join(os.path.basename(f) for f in saved_files) or 'None'}</p>
        <p>(Full JSON and files attached)</p>
        """

        message = Mail(
            from_email=Email(FROM_EMAIL),
            to_emails=[To(TO_EMAIL)],
            subject=subject,
            html_content=Content("text/html", body_html),
        )

        # Attach the JSON (always)
        with open(json_path, "rb") as jf:
            jbytes = jf.read()
        j_b64 = base64.b64encode(jbytes).decode("utf-8")
        message.add_attachment(
            Attachment(
                FileContent(j_b64),
                FileName(os.path.basename(json_path)),
                FileType("application/json"),
                Disposition("attachment"),
            )
        )

        # Attach any user files (kept small by your MAX_CONTENT_LENGTH = 25 MB)
        for fpath in saved_files:
            with open(fpath, "rb") as fh:
                content = fh.read()
            b64 = base64.b64encode(content).decode("utf-8")

            # quick mime guess
            ext = os.path.splitext(fpath)[1].lower()
            if ext in [".png", ".jpg", ".jpeg", ".gif", ".webp"]:
                mime = f"image/{'jpeg' if ext=='.jpg' else ext.lstrip('.')}"
            elif ext == ".svg":
                mime = "image/svg+xml"
            elif ext == ".pdf":
                mime = "application/pdf"
            else:
                mime = "application/octet-stream"

            message.add_attachment(
                Attachment(
                    FileContent(b64),
                    FileName(os.path.basename(fpath)),
                    FileType(mime),
                    Disposition("attachment"),
                )
            )

                # Region-aware client
        sg = SendGridAPIClient(api_key=SENDGRID_API_KEY, host=SENDGRID_HOST)
        resp = sg.send(message)

        # Better diagnostics
        if 200 <= resp.status_code < 300:
            print(f"✅ Email sent to {TO_EMAIL}")
        else:
            try:
                body_text = resp.body.decode() if isinstance(resp.body, (bytes, bytearray)) else str(resp.body)
            except Exception:
                body_text = str(resp.body)
            print(f"❌ SendGrid error: {resp.status_code} {body_text}")


        if 200 <= resp.status_code < 300:
            print(f"✅ Email sent to {TO_EMAIL}")
        else:
            print(f"❌ SendGrid error: {resp.status_code} {resp.body}")

    except Exception as e:
        print("❌ Email failed:", e)

    return jsonify({"ok": True, "json": json_path, "files": saved_files})


# Load all company .txt files
def load_company_info():
    try:
        with open("company_data/knowledge_base.txt", encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        print("❌ Error: knowledge_base.txt not found.")
        return ""

company_info = load_company_info()

# Log interactions
def log(user, bot, route="OpenAI"):
    timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with open("chat_log.txt", "a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] | Route: {route}\nUser: {user}\nBot: {bot}\n\n")

# Serve the main site:
@app.route("/")
@app.route("/index")
@app.route("/index.html")   # so /index.html also works
def home():
    return render_template("index.html")

@app.route("/test-mail")
def test_mail():
    try:
        message = Mail(
            from_email=FROM_EMAIL,
            to_emails=TO_EMAIL,
            subject="SendGrid test",
            html_content=Content("text/html", "<p>Hello from Flask test.</p>")
        )
        sg = SendGridAPIClient(api_key=SENDGRID_API_KEY, host=SENDGRID_HOST)
        resp = sg.send(message)
        body = resp.body.decode() if hasattr(resp.body, "decode") else str(resp.body)
        return {"status": resp.status_code, "body": body}
    except Exception as e:
        return {"error": str(e)}, 500


@app.route('/chatbot')
def chatbot():
    return render_template("chatbot.html")

@app.route("/brief")
def brief():
    return render_template("brief.html")

chat_history = []  # global or session-level if you want per-user memory

# Simple in-memory history (per app run, not per session)
chat_history = []  # Optional: replace with session-based history for multiple users

@app.route('/chat', methods=['POST'])
def chat():
    user_message = request.json.get("message", "").strip()

    # Blocked language filter
    blocked_words = ["idiot", "scam", "stupid"]
    if any(word in user_message.lower() for word in blocked_words):
        reply = "Let's keep things respectful — I'm here to help."
        log(user_message, reply, route="Blocked")
        return jsonify({"reply": reply})

    # Identity / meta questions
    identity_phrases = [
        "are you real", "are you human", "who are you", "what are you",
        "are you ai", "are you an ai", "is this a bot", "are you a bot"
    ]
    if any(phrase in user_message.lower() for phrase in identity_phrases):
        reply = "I'm the official chatbot for Solaris AI — here to help you with any queries."
        log(user_message, reply, route="Identity")
        return jsonify({"reply": reply})

    # Build the strict system prompt using loaded company_info
    messages = [
        {
            "role": "system",
            "content": (
                "You are the official AI chatbot for Solaris AI. "
                "You must ONLY use the information provided below to answer questions. "
                "Do NOT make up services or capabilities. Do NOT guess. Stay strictly on-topic.\n\n"
                "================== COMPANY DATA ==================\n"
                f"{company_info}\n"
                "==================================================\n\n"
                "If you don't know the answer from the data above, say:\n"
                "'I'm here to assist with questions specifically about Solaris AI and our chatbot services. Please ask about that.'"
            )
        }
    ]

    # Add last 5 exchanges from memory (if any)
    for turn in chat_history[-5:]:
        messages.append({"role": "user", "content": turn['user']})
        messages.append({"role": "assistant", "content": turn['bot']})

    # Append latest user message
    messages.append({"role": "user", "content": user_message})

    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=messages,
            temperature=0.4  # lower temperature for factual consistency
        )
        reply = response['choices'][0]['message']['content'].strip()

        # Add to memory
        chat_history.append({"user": user_message, "bot": reply})

    except Exception as e:
        reply = "Sorry, something went wrong on our side."
        print("OpenAI error:", e)

    log(user_message, reply, route="OpenAI")
    return jsonify({"reply": reply})

@app.route("/feedback", methods=["POST"])
def feedback():
    data = request.json
    rating = data.get("rating")
    comment = data.get("comment", "")
    timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with open("feedback_log.txt", "a", encoding="utf-8") as f:
        f.write(f"[{timestamp}]\nRating: {rating}\nComment: {comment}\n\n")
    return jsonify({"message": "Feedback received"})

@app.route('/admin/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form['username'] == 'Matt' and request.form['password'] == 'Sammy123':
            session['logged_in'] = True
            return redirect(url_for('admin'))
        return render_template("login.html", error="Invalid login")
    return render_template("login.html")

@app.route('/admin')
def admin():
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    logs = []
    top_questions = Counter()
    hourly = defaultdict(int)
    category_counts = defaultdict(int)

    today = datetime.datetime.now().date()
    week_ago = today - datetime.timedelta(days=7)
    month_ago = today - datetime.timedelta(days=30)

    chat_counts = {"today": 0, "week": 0, "month": 0}

    try:
        if os.path.exists("chat_log.txt"):
            with open("chat_log.txt", encoding="utf-8", errors="ignore") as f:
                entries = f.read().split("\n\n")
                for entry in entries:
                    if "User:" in entry:
                        timestamp_line = entry.split("]")[0][1:]
                        timestamp = datetime.datetime.strptime(timestamp_line, "%Y-%m-%d %H:%M:%S")
                        date_only = timestamp.date()
                        question = entry.split("User:")[1].split("\n")[0].strip().lower()
                        top_questions[question] += 1

                        if date_only == today:
                            chat_counts["today"] += 1
                        if date_only >= week_ago:
                            chat_counts["week"] += 1
                        if date_only >= month_ago:
                            chat_counts["month"] += 1

                        logs.append(entry.replace("\n", "<br>"))
                        user_msg = entry.split("User:")[1].split("<br>")[0].strip().lower()
                        top_questions[user_msg] += 1

                        hour = timestamp.hour
                        hourly[hour] += 1
                        category = classify(user_msg)
                        category_counts[category] += 1
    except Exception as e:
        logs.append(f"<i>Error loading chat logs: {e}</i>")

    top_three = top_questions.most_common(3)
    top10 = top_questions.most_common(10)

    conversion_keywords = ["quote", "cost", "pricing", "appointment", "book", "support", "install", "refund"]
    conversion_hits = 0
    total_chats = 0

    if os.path.exists("chat_log.txt"):
        with open("chat_log.txt", encoding="utf-8", errors="ignore") as f:
            entries = f.read().split("\n\n")
            for entry in entries:
                if "User:" in entry:
                    timestamp_line = entry.split("]")[0][1:]
                    timestamp = datetime.datetime.strptime(timestamp_line, "%Y-%m-%d %H:%M:%S")
                    if timestamp.date() >= month_ago:
                        total_chats += 1
                        user_text = entry.split("User:")[1].split("\n")[0].strip().lower()
                        if any(kw in user_text for kw in conversion_keywords):
                            conversion_hits += 1

    conversion_rate = round((conversion_hits / total_chats) * 100, 1) if total_chats else 0

    return render_template("admin.html",
        logs=logs,
        top_questions=top_three,
        chat_counts=chat_counts,
        conversion_rate=conversion_rate,
        route_labels=list(category_counts.keys()),
        route_data=list(category_counts.values()),
        hour_labels=list(hourly.keys()),
        hour_data=list(hourly.values()),
        top_questions_labels=[q[0] for q in top10],
        top_questions_data=[q[1] for q in top10]
    )

@app.route('/admin/logout')
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route('/admin/download')
def download_logs():
    return send_file("chat_log.txt", as_attachment=True)

@app.route('/admin/charts')
def charts():
    return redirect("/admin")

@app.route('/admin/chart-data')
def chart_data():
    counts = defaultdict(int)
    hours = defaultdict(int)
    question_counts = Counter()

    if Path("chat_log.txt").exists():
        with open("chat_log.txt", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if "User:" in line:
                    text = line.split("User:")[1].strip()
                    category = classify(text)
                    counts[category] += 1
                    question_counts[text.lower()] += 1
                if line.startswith("["):
                    time = line.split("]")[0][1:].split()[1]
                    hour = int(time.split(":")[0])
                    hours[hour] += 1

    return jsonify({
        "categories": counts,
        "hours": hours,
        "questions": dict(question_counts.most_common(10))
    })

@app.route('/admin/filter')
def admin_filter():
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    filter_type = request.args.get("type", "").lower()
    filtered_logs = []

    if os.path.exists("chat_log.txt"):
        with open("chat_log.txt", encoding="utf-8", errors="ignore") as f:
            entries = f.read().split("\n\n")
            for entry in entries:
                user_line = next((line for line in entry.splitlines() if line.lower().startswith("user:")), "")
                bot_line = next((line for line in entry.splitlines() if line.lower().startswith("bot:")), "")
                user_text = user_line.replace("User:", "").strip().lower()
                bot_text = bot_line.replace("Bot:", "").strip().lower()

                if filter_type == "quote" and any(x in user_text for x in ["quote", "price", "cost", "estimate"]):
                    filtered_logs.append(entry.replace("\n", "<br>"))

                elif filter_type == "unanswered" and (
                    "sorry" in bot_text or "not sure" in bot_text or
                    "please contact" in bot_text or
                    "feel free to ask" in bot_text or
                    len(bot_text.strip()) < 5
                ):
                    filtered_logs.append(entry.replace("\n", "<br>"))

    return render_template("admin.html", logs=filtered_logs, top_questions=[], chat_counts={"today": 0, "week": 0, "month": 0}, conversion_rate=0, route_labels=[], route_data=[], hour_labels=[], hour_data=[], top_questions_labels=[], top_questions_data=[])

def classify(text):
    text = text.lower()
    keyword_map = {
        "pricing": ["price", "quote", "cost"],
        "support": ["support", "help", "issue", "warranty"],
        "refunds": ["refund", "return"],
        "hours": ["opening", "hours", "times"],
        "contact": ["contact", "email", "phone"],
    }
    for category, keywords in keyword_map.items():
        if any(kw in text for kw in keywords):
            return category
    return "other"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=False, host="0.0.0.0", port=port)
