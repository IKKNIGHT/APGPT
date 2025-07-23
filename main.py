from dotenv import load_dotenv
load_dotenv()  # Load .env file

import discord
from discord.ext import commands
import fitz  # PyMuPDF
import os
import requests
import threading
from flask import Flask

# === ENV CONFIGURATION ===
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
PDF_FOLDER = "./resources"

# === FLASK APP FOR KOYEB ===
app = Flask(__name__)

@app.route('/health')
def health_check():
    return {"status": "healthy"}, 200

def run_flask():
    app.run(host='0.0.0.0', port=int(os.getenv("PORT", 8080)))

flask_thread = threading.Thread(target=run_flask)
flask_thread.daemon = True
flask_thread.start()

# === DISCORD BOT SETUP ===
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix=".", intents=intents) # change the prefix to whatever

# === LOAD PDF DOCUMENTS ===
def load_pdfs(folder=PDF_FOLDER):
    docs = {}
    for filename in os.listdir(folder):
        if filename.endswith(".pdf"):
            with fitz.open(os.path.join(folder, filename)) as doc:
                text = ""
                for page in doc:
                    text += page.get_text()
                docs[filename] = text
    return docs

documents = load_pdfs()

# === GET RELEVANT CONTEXT ===
def get_context(question, documents):
    question = question.lower()
    for title, content in documents.items():
        if any(word in title.lower() for word in question.split()):
            return content[:2000]  # limit context
    return "No relevant document matched. Use general AP knowledge."

# === CALL DEEPSEEK VIA OPENROUTER ===
def query_deepseek(prompt):
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
    }
    data = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "user", "content": prompt}
        ]
    }
    try:
        response = requests.post(url, headers=headers, json=data)
        return response.json()["choices"][0]["message"]["content"]
    except Exception as e:
        return f"❌ Error talking to DeepSeek: {str(e)}"

# === DISCORD COMMAND ===
@bot.command()
async def ap(ctx, *, question):
    await ctx.send("📚 Searching resources and querying DeepSeek...")

    context = get_context(question, documents)
    prompt = f"""
You are an expert AP tutor. Use the following document to answer the question.

Context:
{context}

Question: {question}
"""
    answer = query_deepseek(prompt)
    await ctx.send(f"🧠 **AP Answer:**\n{answer}")

# === START BOT ===
bot.run(DISCORD_BOT_TOKEN)
