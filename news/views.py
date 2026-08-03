from django.shortcuts import render
from .models import NewsArticle


def news_list_view(request):
    articles = NewsArticle.objects.filter(is_published=True)
    return render(request, 'news/news_list.html', {'articles': articles})
