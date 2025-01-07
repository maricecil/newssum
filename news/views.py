from django.core.cache import cache
from django.shortcuts import render, redirect
from crawling.naver_news_crawler import NaverNewsCrawler
from .utils import extract_keywords, analyze_keywords_with_llm
from datetime import datetime
from django.conf import settings
from django.views.decorators.cache import cache_page
from functools import wraps
import threading
import re
from django.db.models import Q
from .models import Article
from django.utils import timezone

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
    
    # LLM 분석 추가
    llm_analysis = analyze_keywords_with_llm(
        keywords_with_counts=keyword_rankings,
        titles=all_titles
    )
    
    context = {
        'news_items': news_items,
        'daily_rankings': daily_rankings,
        'keyword_rankings': keyword_rankings,
        'previous_keywords': previous_keywords,
        'last_update': last_update,
        'refresh_interval': settings.CACHES['default']['TIMEOUT'],  # 캐시 타임아웃 전달
        'llm_analysis': llm_analysis,  # LLM 분석 결과 추가
    }
    
    # 언론사별 키워드 분석 추가
    company_keyword_stats = {}
    for item in news_items:
        company = item['company_name']
        if company not in company_keyword_stats:
            company_keyword_stats[company] = {'total': 0, 'keywords': {}}
            
        # 각 기사의 제목에서 키워드 매칭
        for keyword, count, _ in keyword_rankings:
            if keyword in item['title']:
                company_keyword_stats[company]['total'] += 1
                if keyword not in company_keyword_stats[company]['keywords']:
                    company_keyword_stats[company]['keywords'][keyword] = 0
                company_keyword_stats[company]['keywords'][keyword] += 1
    
    context.update({
        'company_keyword_stats': company_keyword_stats,
    })
    
    # 여기에 캐시 업데이트 추가
    cache.set('news_data', context, timeout=CACHE_TIMEOUT)
    cache.set('last_update', now, timeout=CACHE_TIMEOUT)
    
    return render(request, 'news/news_list.html', context)

def keyword_analysis(request, keyword=None):
    if keyword:
        # 캐시에서 전체 뉴스 데이터 가져오기
        cached_data = cache.get('news_data', {})
        news_items = cached_data.get('news_items', [])
        
        # 키워드가 포함된 기사 필터링 (부분 일치로 수정)
        filtered_articles = [
            item for item in news_items 
            if keyword in item['title'].replace(' ', '')  # 공백 제거 후 검색
        ]
        
        context = {
            'keyword': keyword,
            'articles': filtered_articles,
            'article_count': len(filtered_articles),
            'news_items': [],
            'daily_rankings': [],
            'keyword_rankings': []
        }
        
        return render(request, 'news/news_list.html', context)
    
    return redirect('news:news_list') 

def keyword_articles(request, keyword):
    # 캐시에서 전체 뉴스 데이터 가져오기
    cached_data = cache.get('news_data', {})
    news_items = cached_data.get('news_items', [])
    
    # 키워드가 포함된 기사 필터링
    filtered_articles = [
        item for item in news_items 
        if keyword in item['title']
    ]
    
    # keyword_rankings 형식에 맞춰서 데이터 전달
    keyword_rankings = [(keyword, len(filtered_articles), filtered_articles)]
    
    context = {
        'keyword': keyword,
        'articles': filtered_articles,
        'article_count': len(filtered_articles),
        # news_list.html의 다른 섹션들을 숨기기 위해 빈 리스트 전달
        'news_items': [],
        'daily_rankings': [],
        'keyword_rankings': []
    }
    
    return render(request, 'news/news_list.html', context) 

def top_articles(request):
    cached_data = cache.get('news_data', {})
    news_items = cached_data.get('news_items', [])
    keyword_rankings = cached_data.get('keyword_rankings', [])
    daily_rankings = cached_data.get('daily_rankings', [])
    
    # 디버깅을 위한 출력 추가
    print("news_items count:", len(news_items))
    print("keyword_rankings:", keyword_rankings)
    
    # TOP 10 키워드 관련 기사만 필터링
    top_keywords = [keyword for keyword, _, _ in keyword_rankings]
    top_articles = [
        item for item in news_items 
        if any(keyword in item['title'] for keyword in top_keywords)
    ]
    
    # 디버깅을 위한 출력 추가
    print("filtered articles count:", len(top_articles))
    
    # 언론사별로 기사 그룹화
    news_by_company = {}
    for item in top_articles:
        company = item['company_name']
        if company not in news_by_company:
            news_by_company[company] = []
        news_by_company[company].append(item)
    
    # 각 언론사의 기사를 순위순으로 정렬
    for articles in news_by_company.values():
        articles.sort(key=lambda x: x.get('rank', 999))
    
    # 키워드별로 기사 그룹화할 때도 전체 키워드 사용
    keyword_articles = {}
    for keyword, count, _ in keyword_rankings:  # count 정보도 함께 사용
        related_articles = [
            item for item in top_articles
            if keyword in item['title']
        ]
        if related_articles:
            keyword_articles[keyword] = related_articles
    
    # 전체 기사 수 계산
    total_articles = sum(len(articles) for articles in keyword_articles.values())
    
    context = {
        'keyword': "주요 기사 모아보기",
        'news_by_company': news_by_company,
        'articles': top_articles,
        'article_count': len(top_articles),
        'news_items': news_items,
        'daily_rankings': daily_rankings,
        'keyword_rankings': keyword_rankings,
        'keyword_articles': keyword_articles,
        'total_keyword_articles': total_articles,
        'last_update': cached_data.get('last_update')
    }
    
    return render(request, 'news/news_list.html', context) 