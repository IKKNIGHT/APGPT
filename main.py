from dotenv import load_dotenv
load_dotenv()

import discord
from discord.ext import commands
import fitz  # PyMuPDF
import os
import threading
import re
from flask import Flask
from openai import OpenAI
from collections import defaultdict

# === ENV CONFIG ===
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
PDF_FOLDER = "./resources"

# === Flask for health check ===
app = Flask(__name__)

@app.route('/health')
def health_check():
    return {"status": "healthy"}, 200

def run_flask():
    app.run(host='0.0.0.0', port=int(os.getenv("PORT", 8080)))

flask_thread = threading.Thread(target=run_flask)
flask_thread.daemon = True
flask_thread.start()

# === Discord Bot Setup ===
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix=".", intents=intents)

# === PDF Loader ===
def load_pdfs(folder=PDF_FOLDER):
    docs = {}
    for filename in os.listdir(folder):
        if filename.endswith(".pdf"):
            with fitz.open(os.path.join(folder, filename)) as doc:
                text = "".join(page.get_text() for page in doc)
                docs[filename] = text
    return docs

documents = load_pdfs()

# === Chunking and Indexing ===
def tokenize(text):
    return set(re.findall(r'\b\w+\b', text.lower()))

def chunk_document(text, chunk_size=1000, overlap=200):
    words = text.split()
    chunks = []
    for i in range(0, len(words), chunk_size - overlap):
        chunk = " ".join(words[i:i + chunk_size])
        if chunk.strip():
            chunks.append(chunk)
    return chunks

def build_chunk_index(documents):
    index = defaultdict(set)
    token_cache = []
    chunk_lookup = {}

    for title, content in documents.items():
        doc_chunks = chunk_document(content)
        for i, chunk in enumerate(doc_chunks):
            chunk_id = f"{title}::chunk_{i}"
            tokens = tokenize(chunk)
            token_cache.append((chunk_id, chunk, tokens))
            for token in tokens:
                index[token].add(chunk_id)
            chunk_lookup[chunk_id] = chunk

    return index, token_cache, chunk_lookup

inverted_index, token_cache, chunk_lookup = build_chunk_index(documents)

# === Fast Chunk Search ===
def get_context(question, token_cache, inverted_index, chunk_lookup, max_chunks=3):
    q_tokens = tokenize(question)
    chunk_scores = defaultdict(int)

    for token in q_tokens:
        for chunk_id in inverted_index.get(token, []):
            chunk_scores[chunk_id] += 1

    top_chunks = sorted(chunk_scores.items(), key=lambda x: x[1], reverse=True)[:max_chunks]
    if not top_chunks:
        return None

    return "\n\n---\n\n".join(chunk_lookup[chunk_id] for chunk_id, _ in top_chunks)

# === OpenRouter Client ===
client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
)

def query_deepseek(prompt):
    try:
        completion = client.chat.completions.create(
            model="deepseek/deepseek-r1-0528:free",
            messages=[{"role": "user", "content": prompt}]
        )
        return completion.choices[0].message.content
    except Exception as e:
        return f"❌ Error from OpenRouter: {str(e)}"

# === .ap Command ===
@bot.command()
async def ap(ctx, *, question):
    await ctx.send("📚 Searching resources and querying DeepSeek...  (You will be DM'D ETA (15s))")

    context = get_context(question, token_cache, inverted_index, chunk_lookup)

    if context:
        prompt = f"""You are an expert AP tutor. Use the following document to answer the question. If the document is not related to the query/prompt please ignore the context given below, and use general AP knowledge. But don't mention anything about the document being wrong.

Context:
{context}

Question: {question}
"""
    else:
        prompt = f"""You are an expert AP tutor. The user asked a question, but no matching documents were found.
Answer it based on your general AP knowledge.

Question: {question}
"""

    answer = query_deepseek(prompt)

    try:
        # DM the user in 2000-character chunks
        for i in range(0, len(answer), 2000):
            await ctx.author.send(answer[i:i+2000])
        await ctx.send("📬 Sent you a DM with the AP answer!")
    except discord.Forbidden:
        await ctx.send("❌ I couldn't DM you. Please enable DMs from server members.")

# === Run Bot ===
bot.run(DISCORD_BOT_TOKEN)
