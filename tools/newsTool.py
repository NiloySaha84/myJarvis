from newsapi import NewsApiClient
from dotenv import load_dotenv
from datetime import datetime
import os
from collections import defaultdict

load_dotenv()

news_api_key = os.getenv("NEWS_API_KEY")

news_api = NewsApiClient(api_key=news_api_key)
news_metrics = defaultdict(int)


def get_news_metrics():
    return dict(news_metrics)

def get_news(query: str):
    news_metrics["calls_total"] += 1
    if not query or not query.strip():
        news_metrics["validation_errors_total"] += 1
        return {"status": "error", "message": "Please provide a valid news query."}
    try:
        result = news_api.get_everything(
            q=query,
            sort_by='relevancy',
            language='en',
            to=datetime.now().strftime('%Y-%m-%d'),
        )
        news_metrics["success_total"] += 1
        articles = result.get("articles", []) if isinstance(result, dict) else []
        news_metrics["articles_returned_total"] += len(articles)
        return result
    except Exception as exc:
        news_metrics["errors_total"] += 1
        return {"status": "error", "message": f"News API request failed: {exc}"}