from django.urls import path
from . import views

app_name = 'news'

urlpatterns = [
    path('', views.news_list, name='news_list'),
    path('analysis/', views.keyword_analysis, name='keyword_analysis'),
    path('analysis/<str:keyword>/', views.keyword_analysis, name='keyword_detail'),
    path('keyword/<str:keyword>/', views.keyword_articles, name='keyword_articles'),
    path('top-articles/', views.top_articles, name='top_articles'),
] 