from django.urls import path, include
from django.shortcuts import redirect

def redirect_to_news(request):
    return redirect('news:news_list')

urlpatterns = [
    path('', redirect_to_news, name='home'),  # 루트 URL을 news로 리다이렉트
    path('news/', include('news.urls')),
] 