from django.http import Http404
from django.shortcuts import get_object_or_404, render
from .models import NewsArticle


def can_preview_news(user):
    return user.is_staff and (user.has_perm('news.view_newsarticle') or user.has_perm('news.change_newsarticle'))


def news_list_view(request):
    articles = NewsArticle.objects.visible().select_related('author')
    return render(request, 'news/news_list.html', {'articles': articles})


def news_detail_view(request, pk):
    article = get_object_or_404(
        NewsArticle.objects.select_related('author'), pk=pk, is_published=True,
    )
    is_preview = article.is_scheduled
    if is_preview and not can_preview_news(request.user):
        raise Http404
    response = render(request, 'news/news_detail.html', {'article': article, 'is_preview': is_preview})
    if is_preview:
        response['Cache-Control'] = 'private, no-store'
    return response
