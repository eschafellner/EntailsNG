# news/services.py
from .models import NewsArticle


def get_latest_news(limit=3):
    """Liefert die neuesten veröffentlichten News-Beiträge."""
    return list(
        NewsArticle.objects.filter(is_published=True).order_by('-id')[:limit]
    )


def get_pinned_news():
    """Liefert die wichtigste angepinnte Ankündigung für das Dashboard."""
    return NewsArticle.objects.filter(
        is_published=True, is_pinned=True
    ).first()


def get_all_published_news():
    """Liefert alle veröffentlichten News für die News-Übersicht."""
    return NewsArticle.objects.filter(is_published=True).order_by(
        '-is_pinned', '-created_at'
    )
