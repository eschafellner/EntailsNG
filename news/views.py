from django.shortcuts import get_object_or_404, render
from .models import NewsArticle


def news_list_view(request):
    articles = NewsArticle.objects.filter(is_published=True).select_related('author')
    return render(request, 'news/news_list.html', {'articles': articles})


def news_detail_view(request, pk):
    article = get_object_or_404(
        NewsArticle.objects.select_related('author'), pk=pk, is_published=True,
    )
    return render(request, 'news/news_detail.html', {'article': article})
