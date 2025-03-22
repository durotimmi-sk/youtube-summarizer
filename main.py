import os
import json
import logging
import re
import time
import pickle
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from googleapiclient.discovery import build
from youtube_transcript_api import YouTubeTranscriptApi
from gtts import gTTS
from groq import Groq
from datetime import date
import uvicorn

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from dotenv import load_dotenv
load_dotenv('.env')
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
PORT = int(os.getenv("PORT", 8000))

if not YOUTUBE_API_KEY:
    raise ValueError("YOUTUBE_API_KEY is required")
if not GROQ_API_KEY:
    raise ValueError("GROQ_API_KEY is required")

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

audio_dir = "static/audio"
cache_dir = "cache"
if not os.path.exists(audio_dir):
    os.makedirs(audio_dir)
    logger.info(f"Created audio directory: {audio_dir}")
if not os.path.exists(cache_dir):
    os.makedirs(cache_dir)
    logger.info(f"Created cache directory: {cache_dir}")

client = Groq(api_key=GROQ_API_KEY)
logger.info("Groq client initialized successfully")

today = date.today().strftime("%B %d, %Y")

CACHE_VERSION = "1.10"  

class VideoInput(BaseModel):
    query: str

class ChatInput(BaseModel):
    video_id: str
    question: str

# Helper functions
def estimate_tokens(text: str) -> int:
    return len(text) // 4 + 1

def cache_summary(video_id: str, summary_data: dict):
    summary_data["cache_version"] = CACHE_VERSION
    cache_file = os.path.join(cache_dir, f"{video_id}.pkl")
    try:
        with open(cache_file, 'wb') as f:
            pickle.dump(summary_data, f)
        logger.info(f"Cached summary for video ID: {video_id}")
    except Exception as e:
        logger.error(f"Failed to cache summary: {str(e)}")

def get_cached_summary(video_id: str, query: str = None) -> dict:
    cache_file = os.path.join(cache_dir, f"{video_id}.pkl")
    if os.path.exists(cache_file):
        try:
            with open(cache_file, 'rb') as f:
                cached_data = pickle.load(f)
                if query is None or (cached_data.get("cache_version") == CACHE_VERSION and cached_data.get("query") == query):
                    return cached_data
                else:
                    logger.info(f"Cache version or query mismatch for video ID: {video_id}. Regenerating summary.")
                    os.remove(cache_file) 
        except Exception as e:
            logger.error(f"Failed to retrieve cached summary: {str(e)}")
    return None

def extract_video_id(url: str) -> str:
    regex = r"(?:v=|\/)([0-9A-Za-z_-]{11}).*"
    match = re.search(regex, url)
    return match.group(1) if match else None

def search_video(query: str) -> dict:
    try:
        youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)
        video_id = extract_video_id(query)
        if video_id:
            request = youtube.videos().list(part="snippet", id=video_id)
            response = request.execute()
            if not response["items"]:
                raise HTTPException(status_code=404, detail="Video not found with this URL")
            item = response["items"][0]
        else:
            request = youtube.search().list(part="snippet", maxResults=1, q=query, type="video")
            response = request.execute()
            if not response["items"]:
                raise HTTPException(status_code=404, detail="No videos found for this query")
            item = response["items"][0]
            video_id = item["id"]["videoId"]
        return {
            "video_id": video_id,
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "title": item["snippet"]["title"],
            "thumbnail": item["snippet"]["thumbnails"]["medium"]["url"],
            "description": item["snippet"]["description"]
        }
    except Exception as e:
        logger.error(f"Failed to search video: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Couldn’t find a video for '{query}'. Try a different query.")

def extract_transcript(video_id: str) -> str:
    try:
        ytt_api = YouTubeTranscriptApi()
        transcript = ytt_api.get_transcript(video_id)
        transcript_text = " ".join([entry["text"] for entry in transcript])
        if not transcript_text.strip():
            raise ValueError("Transcript is empty")
        transcript_text = re.sub(r'\[Music.*?\]|\(Music.*?\)|\[.*?\]', '', transcript_text, flags=re.IGNORECASE)
        return transcript_text
    except Exception as e:
        logger.warning(f"Transcript unavailable: {str(e)}")
        youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)
        request = youtube.videos().list(part="snippet", id=video_id)
        response = request.execute()
        if response["items"]:
            description = response["items"][0]["snippet"]["description"]
            if description.strip():
                description = re.sub(r'\[Music.*?\]|\(Music.*?\)|\[.*?\]', '', description, flags=re.IGNORECASE)
                return description
        raise HTTPException(status_code=400, detail="No transcript or description available for this video. Try another video.")

def get_real_time_data(video_id: str) -> dict:
    try:
        youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)
        request = youtube.videos().list(part="statistics", id=video_id)
        response = request.execute()
        stats = response["items"][0]["statistics"] if response["items"] else {}
        return {"view_count": stats.get("viewCount", "N/A")}
    except Exception as e:
        logger.error(f"Failed to fetch real-time data: {str(e)}")
        return {"view_count": "N/A"}

def analyze_sentiment(summary: str) -> str:
    try:
        system_prompt = "You are an AI that performs sentiment analysis. Classify the sentiment of the given text as 'Positive', 'Negative', or 'Neutral'. Respond only with the classification."
        user_prompt = f"Text: {summary[:1000]}" 
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=messages,
            max_tokens=10,
            temperature=0.5
        )
        
        sentiment = response.choices[0].message.content.strip()
        if sentiment not in ["Positive", "Negative", "Neutral"]:
            return "Neutral" 
        return sentiment
    except Exception as e:
        logger.error(f"Failed to analyze sentiment with Groq: {str(e)}")
        return "Neutral"

def generate_summary(transcript: str, video_id: str, title: str, description: str) -> dict:
    try:
        real_time_data = get_real_time_data(video_id)
        view_count = real_time_data["view_count"]
        
        system_prompt = f"You are an AI that summarizes YouTube videos in detail. Today is {today}."
        system_tokens = estimate_tokens(system_prompt)
        
        TPM_LIMIT = 6000
        TOKEN_BUFFER = 500
        base_user_prompt = f"Summarize this YouTube video (title: '{title}') into a 350-400 word summary. Focus on capturing specific details from the transcript, including key events, dialogues, character motivations, emotional moments, and significant plot points. Include direct references to the content, such as specific scenes, conversations, or actions taken by characters. Identify key themes, main characters (ensure names are accurate), and the emotional tone of the story. Avoid repetition and ensure the summary provides a comprehensive overview of the video's narrative. End with a sentence on the video's impact, including its view count ({view_count})."
        base_tokens = estimate_tokens(base_user_prompt)
        
        available_tokens = TPM_LIMIT - system_tokens - base_tokens - TOKEN_BUFFER
        max_chars = available_tokens * 4
        
        content = transcript if estimate_tokens(transcript) <= available_tokens else description
        content = content[:max_chars] if estimate_tokens(content) > available_tokens else content
        
        user_prompt = f"{base_user_prompt} Content: {content}"
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=messages,
            max_tokens=800,
            temperature=0.7
        )
        
        summary = response.choices[0].message.content.strip()
        summary = re.sub(r'\[Music.*?\]|\(Music.*?\)|\[.*?\]', '', summary, flags=re.IGNORECASE)
        summary = re.sub(r'^-.*?\n', '', summary, flags=re.MULTILINE)
        sentiment = analyze_sentiment(summary)
        
        return {"summary": summary, "sentiment": sentiment}
    except Exception as e:
        logger.error(f"Failed to generate summary: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to generate summary: {str(e)}")

def generate_conversational_audio_script(summary: str, video_id: str, title: str) -> str:
    try:
        clean_summary = re.sub(r'\[Music.*?\]|\(Music.*?\)|\[.*?\]', '', summary, flags=re.IGNORECASE)
        
        system_prompt = "You are an AI creating a conversational audio script discussing a YouTube video summary. Use a natural, engaging tone. Do not mention 'Speaker 1', 'Speaker 2', 'Host A', 'Host B', or any speaker names; instead, write the script as a seamless conversation between two unnamed speakers, alternating perspectives without labeling them. Break into 2-3 sentence segments per speaker. Cover the core message, key themes, characters, and impact."
        user_prompt = f"Create a script for this summary (title: '{title}'): {clean_summary}"
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        response = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=messages,
            max_tokens=600,
            temperature=0.7
        )
        
        script = response.choices[0].message.content.strip()
        script = re.sub(r'\[Music.*?\]|\(Music.*?\)|\[.*?\]', '', script, flags=re.IGNORECASE)
        return script
    except Exception as e:
        logger.error(f"Failed to generate script: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to generate audio script: {str(e)}")

def text_to_speech_conversational(script: str, video_id: str) -> str:
    filename = f"audio_overview_{video_id}.mp3"
    audio_path = os.path.join(audio_dir, filename)
    try:
        clean_script = re.sub(r'[^\x00-\x7F]+', ' ', script)
        tts = gTTS(text=clean_script, lang="en", slow=False)
        tts.save(audio_path)
        return f"/static/audio/{filename}?t={int(time.time())}"
    except Exception as e:
        logger.error(f"Failed to generate audio: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to generate audio: {str(e)}")

@app.post("/summarize")
async def summarize_video(video: VideoInput):
    try:
        video_data = search_video(video.query)
        video_id = video_data["video_id"]
        
        cached_summary = get_cached_summary(video_id, video.query)
        if cached_summary:
            return {
                "title": video_data["title"],
                "thumbnail": video_data["thumbnail"],
                "summary": cached_summary["summary"],
                "sentiment": cached_summary["sentiment"],
                "url": video_data["url"],
                "video_id": video_id
            }
        
        transcript = extract_transcript(video_id)
        summary_data = generate_summary(transcript, video_id, video_data["title"], video_data["description"])
        response_data = {
            "title": video_data["title"],
            "thumbnail": video_data["thumbnail"],
            "summary": summary_data["summary"],
            "sentiment": summary_data["sentiment"],
            "url": video_data["url"],
            "video_id": video_id,
            "query": video.query  
        }
        cache_summary(video_id, response_data)
        return response_data
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing request: {str(e)}")

@app.get("/audio-overview/{video_id}", response_class=HTMLResponse)
async def audio_overview_page(request: Request, video_id: str):
    try:
        cached_summary = get_cached_summary(video_id) 
        if not cached_summary:
            raise HTTPException(status_code=404, detail="Summary not found for this video ID")

        return templates.TemplateResponse("audio-overview.html", {
            "request": request,
            "title": cached_summary["title"],
            "video_id": video_id
        })
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error loading audio overview page: {str(e)}")

@app.get("/generate-audio/{video_id}")
async def generate_audio(video_id: str):
    try:
        cached_summary = get_cached_summary(video_id) 
        if not cached_summary:
            raise HTTPException(status_code=404, detail="Summary not found for this video ID")

        audio_path_key = "audio_overview"
        if audio_path_key in cached_summary and os.path.exists(cached_summary[audio_path_key].split('?')[0].lstrip('/')):
            return {"audio_path": cached_summary[audio_path_key]}

        script = generate_conversational_audio_script(cached_summary["summary"], video_id, cached_summary["title"])
        audio_path = text_to_speech_conversational(script, video_id)
        cached_summary[audio_path_key] = audio_path
        cache_summary(video_id, cached_summary)
        return {"audio_path": audio_path}
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating audio: {str(e)}")

@app.post("/chat")
async def chat_with_summary(chat_input: ChatInput):
    try:
        cached_summary = get_cached_summary(chat_input.video_id)  
        if not cached_summary:
            raise HTTPException(status_code=404, detail="No summary found for this video")
        
        try:
            transcript = extract_transcript(chat_input.video_id)
        except Exception as e:
            logger.error(f"Failed to extract transcript for video ID {chat_input.video_id}: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Failed to extract transcript: {str(e)}")

        system_prompt = "You are an AI answering questions about a YouTube video in a natural, conversational tone. Be concise and accurate. Prioritize details from the transcript to answer the question, using the summary only for context (e.g., to identify the speaker's gender or main themes). If the user makes a typo (e.g., 'parcer' instead of 'PACER'), correct it and answer accordingly. Use the summary to identify the speaker's gender and use the correct pronouns (e.g., 'she' for a female speaker, 'he' for a male speaker). Do not mention the transcript, summary, or any source of information in your response; simply answer the question as if you know the content directly."
        user_prompt = f"Summary: {cached_summary['summary'][:1000]}\nTranscript: {transcript[:4000]}\nQuestion: {chat_input.question}"  # Increased transcript limit for more details
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        try:
            response = client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=messages,
                max_tokens=300,
                temperature=0.7
            )
            return {"answer": response.choices[0].message.content.strip()}
        except Exception as e:
            logger.error(f"Failed to generate chat response for video ID {chat_input.video_id}: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Failed to generate chat response: {str(e)}")
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Unexpected error in chat endpoint: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")

@app.get("/", response_class=HTMLResponse)
async def get_ui(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/static/audio/{filename}")
async def get_audio(filename: str, t: str = None):
    return FileResponse(f"static/audio/{filename}")

@app.get("/favicon.ico")
async def favicon():
    return FileResponse("static/favicon.ico") if os.path.exists("static/favicon.ico") else {"status": "no favicon"}

@app.get("/health")
async def health_check():
    return {"status": "ok"}

if __name__ == "__main__":
    logger.info(f"Starting YouNote on http://0.0.0.0:{PORT}")
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, reload=False)