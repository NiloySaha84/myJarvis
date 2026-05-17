from newsapi import NewsApiClient
from dotenv import load_dotenv
from datetime import datetime
import os

load_dotenv()

news_api_key = os.getenv("NEWS_API_KEY")

news_api = NewsApiClient(api_key=news_api_key)

def get_news(query: str):
    return news_api.get_everything(q=query, sort_by='relevancy', language='en', to=datetime.now().strftime('%Y-%m-%d'))