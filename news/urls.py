from django.urls import path
from . import views

app_name = 'news'

urlpatterns = [
    path('', views.news_list, name='news_list'),
    path('summary/', views.news_summary, name='news_summary'),
    path('top/', views.top_articles, name='top_articles'),
    path('keyword/<str:keyword>/', views.keyword_articles, name='keyword_articles'),
    path('analysis/<str:keyword>/', views.keyword_analysis, name='keyword_analysis'),
    # 아래 URL 패턴을 주석 처리하거나 제거
    # path('api/news/analyze/', views.analyze_news_api, name='analyze_news_api'),
    path('analyze/trends/', views.analyze_trends, name='analyze_trends'),
    # path('api/analyze-filtered/', views.analyze_filtered_news, name='analyze_filtered_news'),
] 