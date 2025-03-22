# YouNote - YouTube Video Summarizer and Chat Interface

YouNote is a web application that summarizes YouTube videos, generates audio overviews, and provides a chat interface to ask questions about the video content. Built with FastAPI, it leverages APIs like YouTube Data API, YouTube Transcript API, and Groq for natural language processing.

## Features
- **Video Summarization**: Enter a YouTube video URL or search query to get a detailed 350-400 word summary of the video, including key events, dialogues, and themes.
- **Sentiment Analysis**: Analyzes the sentiment of the summary (Positive, Negative, or Neutral).
- **Audio Overview**: Generates a conversational audio script summarizing the video and converts it to speech using gTTS.
- **Chat Interface**: Ask questions about the video, with answers based on the transcript and summary. The chat interface features alternating white/black bubbles for user messages.
- **Theme Toggle**: Switch between light and dark themes by clicking the "YouNote" logo.
- **Language Support**: Toggle between English (EN) and French (FR) for the search placeholder.
- **Responsive Design**: The UI is centered and responsive, with a clean layout for the search bar, summary, and chat interface.

## Screenshots
![Untitled11](https://github.com/user-attachments/assets/1219a59c-f8f8-486c-9fd3-bf6b482a87b1)


## Setup Instructions

### Prerequisites
- Python 3.8+
- A YouTube Data API key (v3) from [Google Cloud Console](https://console.cloud.google.com/)
- A Groq API key from [Groq](https://groq.com/)
- (Optional) An ngrok auth token for public URL exposure

### Installation
1. **Clone the Repository**:
   ```bash
   git clone https://github.com/durotimmi-sk/youtube-summarizer.git
   cd YouNote
