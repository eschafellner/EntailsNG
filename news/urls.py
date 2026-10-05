from django.urls import path
from .views import news_detail_view, news_list_view

urlpatterns = [
    path('', news_list_view, name='news_list'),
    path('<int:pk>/', news_detail_view, name='news_detail'),
]
