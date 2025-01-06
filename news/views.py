from django.core.cache import cache
from django.shortcuts import render
from crawling.naver_news_crawler import NaverNewsCrawler
from .utils import extract_keywords
from datetime import datetime
from django.conf import settings
from django.views.decorators.cache import cache_page
from functools import wraps
import threading
import re

# 크롤링 중복 방지를 위한 락
crawling_lock = threading.Lock()

def atomic_cache(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        with crawling_lock:
            result = func(*args, **kwargs)
        return result
    return wrapper

def clean_title(title):
    # 앞에 붙은 숫자와 점, 공백 제거
    # 예: "1. 제목" -> "제목"
    return re.sub(r'^\d+\.?\s*', '', title)

@atomic_cache
def news_list(request):
    cached_data = cache.get('news_data')
    last_update = cache.get('last_update')
    now = datetime.now()
    
    # 캐시 타임아웃(15분) 체크
    if cached_data and last_update and (now - last_update).seconds < 900:
        for item in cached_data['news_items']:
            item['title'] = clean_title(item['title'])
        return render(request, 'news/news_list.html', cached_data)
    
    # settings에서 캐시 타임아웃 가져오기
    CACHE_TIMEOUT = 900  # 5분(300)에서 15분(900)으로 수정
    
    news_items = cache.get('news_rankings')
    previous_keywords = cache.get('previous_keywords', [])
    last_update = datetime.now()
    
    if news_items is None:
        crawler = NaverNewsCrawler()
        df = crawler.crawl_all_companies()
        df = df.sort_values(['company_name', 'rank'])
        news_items = df.to_dict('records')
        
        # 제목에서 숫자 제거
        for item in news_items:
            item['title'] = clean_title(item['title'])
            
        all_titles = [item['title'] for item in news_items]
        current_keywords = extract_keywords(all_titles)
        
        # 하드코딩된 300 대신 settings의 TIMEOUT 사용
        cache.set('previous_keywords', current_keywords, timeout=CACHE_TIMEOUT)
        cache.set('news_rankings', news_items, timeout=CACHE_TIMEOUT)
    
    # 크롤링된 기사 수 출력
    print(f"Total news items: {len(news_items)}")
    
    # 일간 주요 뉴스 준비 (각 신문사의 1위 기사)
    daily_rankings = [
        item for item in news_items 
        if item.get('rank') == 1
    ]
    
    # 전체 기사에서 키워드 랭킹 추출
    all_titles = [item['title'] for item in news_items]
    keyword_rankings = extract_keywords(all_titles)
    
    # 디버깅용 출력도 제거
    # print("Previous keywords:", previous_keywords)
    # print("Current keywords:", keyword_rankings)
    
    context = {
        'news_items': news_items,
        'daily_rankings': daily_rankings,
        'keyword_rankings': keyword_rankings,
        'previous_keywords': previous_keywords,
        'last_update': last_update,
        'refresh_interval': settings.CACHES['default']['TIMEOUT']  # 캐시 타임아웃 전달
    }
    
    # 여기에 캐시 업데이트 추가
    cache.set('news_data', context, timeout=CACHE_TIMEOUT)
    cache.set('last_update', now, timeout=CACHE_TIMEOUT)
    
    return render(request, 'news/news_list.html', context) 