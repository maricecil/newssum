from django.core.cache import cache
from django.shortcuts import render, redirect
from crawling.naver_news_crawler import NaverNewsCrawler
from .utils import extract_keywords, analyze_keywords_with_llm_sync
from datetime import datetime
from django.conf import settings
from django.views.decorators.cache import cache_page
from functools import wraps
import threading
import re
from django.db.models import Q
from .models import Article, Keyword
from django.db.models import Count
from django.utils import timezone
import logging
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
import json
from openai import OpenAI
from asgiref.sync import sync_to_async
from .agents.crew import NewsAnalysisCrew, summarize_article
from langchain_community.llms import OpenAI

logger = logging.getLogger('news')  # Django 설정의 'news' 로거 사용

# 크롤링 중복 방지를 위한 락
crawling_lock = threading.Lock()

def atomic_cache(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        with crawling_lock:
            result = func(*args, **kwargs)
        return result
    return wrapper

@atomic_cache
def news_list(request):
    print("=== 뉴스 목록 조회 시작 ===")  # 일단 print로 확인
    # 캐시 타임아웃을 settings에서 가져오기
    CACHE_TIMEOUT = getattr(settings, 'CACHE_TIMEOUT', 900)  # 기본값 15분
    
    # 캐시된 데이터 확인 시 타임아웃도 함께 체크
    cached_data = cache.get('news_data')
    last_update = cache.get('last_update')
    now = timezone.now()  # timezone 사용
    
    # 캐시 타임아웃 체크 (15분)
    if cached_data and last_update and (now - last_update).seconds < CACHE_TIMEOUT:
        return render(request, 'news/news_list.html', cached_data)
    
    news_items = cache.get('news_rankings')
    previous_keywords = cache.get('previous_keywords', [])
    last_update = datetime.now()
    
    if news_items is None:
        print("크롤링 시작")  # 크롤링 시작 확인
        crawler = NaverNewsCrawler()
        df = crawler.crawl_all_companies()
        df = df.sort_values(['company_name', 'rank'])
        news_items = df.to_dict('records')
        print(f"크롤링 완료: {len(news_items)}개 기사")  # 크롤링 결과 확인
        
        all_titles = [item['title'] for item in news_items]
        current_keywords = extract_keywords(all_titles)
        
        # 하드코딩된 300 대신 settings의 TIMEOUT 사용
        cache.set('previous_keywords', current_keywords, timeout=CACHE_TIMEOUT)
        cache.set('news_rankings', news_items, timeout=CACHE_TIMEOUT)
    
    # 크롤링된 기사 수 출력
    logger.info(f"Total news items: {len(news_items)}")
    
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
    
    # LLM 분석 (동기 버전 사용)
    llm_analysis = analyze_keywords_with_llm_sync(
        keywords_with_counts=keyword_rankings,
        titles=news_items  # 전체 기사 데이터 전달
    )
    
    # news_by_company 딕셔너리 생성 추가
    news_by_company = {}
    for item in news_items:
        company = item['company_name']
        if company not in news_by_company:
            news_by_company[company] = []
        news_by_company[company].append(item)
    
    context = {
        'news_items': news_items,
        'daily_rankings': daily_rankings,
        'keyword_rankings': keyword_rankings,
        'previous_keywords': previous_keywords,
        'last_update': last_update,
        'refresh_interval': settings.CACHES['default']['TIMEOUT'],
        'llm_analysis': llm_analysis,
        'news_by_company': news_by_company,
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
    
    if request.resolver_match.url_name == 'top_articles':
        # 제목 리스트 추출
        titles = []
        for company, articles in news_by_company.items():
            titles.extend([article.title for article in articles])
        
        # LLM 분석 추가
        llm_analysis = analyze_keywords_with_llm_sync(
            keywords_with_counts=keyword_rankings,
            titles=news_items
        )
        
        context.update({
            'llm_analysis': llm_analysis,
        })

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
    
    # news_by_company 딕셔너리 생성
    news_by_company = {}
    for item in filtered_articles:
        company = item['company_name']
        if company not in news_by_company:
            news_by_company[company] = []
        news_by_company[company].append(item)
    
    # keyword_rankings 형식 유지
    keyword_rankings = [(keyword, len(filtered_articles), filtered_articles)]
    
    context = {
        'keyword': keyword,
        'articles': filtered_articles,
        'article_count': len(filtered_articles),
        # news_list.html의 다른 섹션들을 숨기기 위해 빈 리스트 전달
        'news_items': [],
        'daily_rankings': [],
        'news_by_company': news_by_company,
        'keyword_rankings': keyword_rankings
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
    for keyword, count, _ in keyword_rankings[:10]:  # 상위 10개 키워드만
        related_articles = [
            item for item in top_articles
            if keyword in item['title']
        ]
        if related_articles:
            keyword_articles[keyword] = related_articles
    
    # CrewAI 분석 실행
    top_ranked_articles = []
    for articles in keyword_articles.values():
        if articles:  # 각 키워드당 첫 번째 기사만 선택
            top_ranked_articles.append(articles[0])
    
    crew = NewsAnalysisCrew()
    crew_analysis = crew.run_analysis(top_ranked_articles)
    
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
        'last_update': cached_data.get('last_update'),
        'crew_analysis': crew_analysis  # CrewAI 분석 결과 추가
    }
    
    return render(request, 'news/news_list.html', context)

def news_summary(request):
    articles = Article.objects.filter(
        created_at__gte=timezone.now() - timezone.timedelta(hours=24)
    ).order_by('-created_at')
    
    # Article 모델의 데이터를 딕셔너리로 변환
    articles_data = [{
        'title': article.title,
        'company_name': article.press_name,  # DB의 press_name 필드 사용
        'rank': article.rank
    } for article in articles]
    
    # 키워드 추출 (titles 리스트 사용)
    titles = [article.title for article in articles]
    keyword_rankings = extract_keywords(titles, limit=10)
    
    # LLM 분석 시 전체 기사 데이터 전달
    llm_analysis = analyze_keywords_with_llm_sync(
        keywords_with_counts=keyword_rankings,
        titles=articles_data  # 딕셔너리 형태의 데이터 전달
    )
    
    context = {
        'articles': articles,
        'keyword_rankings': keyword_rankings,
        'llm_analysis': llm_analysis,
    }
    
    return render(request, 'news/news_summary.html', context) 

@require_http_methods(["POST"])
def analyze_trends(request):
    """AI 트렌드 분석 결과를 반환하는 뷰"""
    try:
        # POST 데이터 파싱
        data = json.loads(request.body)
        selected_companies = data.get('companies', [])
        selected_keywords = data.get('keywords', [])
        analysis_type = data.get('analysis_type', 'basic')  # 기본값은 'basic'

        # 캐시된 데이터 가져오기
        cached_data = cache.get('news_data', {})
        news_items = cached_data.get('news_items', [])
        
        # 선택된 언론사/키워드로 필터링
        filtered_items = [
            item for item in news_items
            if (not selected_companies or item['company_name'] in selected_companies) and
               (not selected_keywords or any(k in item['title'] for k in selected_keywords))
        ]

        # 언론사별 분포 분석
        press_distribution = {}
        for item in filtered_items:
            company = item['company_name']
            press_distribution[company] = press_distribution.get(company, 0) + 1

        # 필터링된 기사의 제목만 추출
        titles = [item['title'] for item in filtered_items]
        
        # 키워드 추출 및 분석
        keyword_rankings = [
            {'keyword': k, 'count': c, 'articles': list(a)}  # set을 list로 변환
            for k, c, a in extract_keywords(titles)
        ]
        
        # 기본 LLM 분석
        llm_analysis = analyze_keywords_with_llm_sync(
            keywords_with_counts=keyword_rankings,
            titles=filtered_items
        )
        
        # 기본 분석 결과 구성
        basic_analysis = {
            'llm_analysis': llm_analysis,
            'press_distribution': press_distribution,
            'filtered_count': len(filtered_items),
            'keyword_rankings': keyword_rankings
        }
        
        # 상세 분석 요청시 CrewAI 분석 추가
        if analysis_type == 'detailed':
            try:
                crew = NewsAnalysisCrew()
                crew_analysis = crew.run_analysis(filtered_items)
                # CrewOutput을 dictionary로 변환
                basic_analysis['crew_analysis'] = {
                    'summary': str(crew_analysis.summary),  # 문자열로 변환
                    'analyzed_articles': crew_analysis.analyzed_articles,
                    'timestamp': crew_analysis.timestamp.isoformat()  # ISO 형식 문자열로 변환
                }
                logger.info("CrewAI 분석 완료")
            except Exception as crew_error:
                logger.error(f"CrewAI 분석 중 오류 발생: {str(crew_error)}")
                basic_analysis['crew_analysis_error'] = "상세 분석 중 오류가 발생했습니다."
        
        # 분석 결과 캐싱 (30분)
        cache_key = f"analysis_{analysis_type}_{'-'.join(selected_companies)}_{'-'.join(selected_keywords)}"
        cache.set(cache_key, basic_analysis, timeout=1800)
        
        return JsonResponse({
            'success': True,
            'analysis': basic_analysis,
            'cache_key': cache_key
        }, json_dumps_params={'ensure_ascii': False})
        
    except Exception as e:
        logger.error(f"트렌드 분석 중 오류 발생: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': '분석 중 오류가 발생했습니다.'
        }, status=500)

def article_summary(request):
    print("\n=== article_summary 디버깅 ===")
    
    # 1. 캐시 데이터 확인
    news_items = cache.get('news_rankings', [])
    print(f"1. 캐시된 뉴스 개수: {len(news_items)}")
    
    if not news_items:
        print("캐시된 뉴스가 없습니다!")
        return redirect('news:news_list')
    
    # 2. 키워드 추출 확인
    all_titles = [item['title'] for item in news_items]
    keyword_rankings = extract_keywords(all_titles)
    print(f"2. 추출된 키워드 수: {len(keyword_rankings)}")
    print(f"상위 5개 키워드: {keyword_rankings[:5]}")
    
    # 3. 기사 그룹화 및 요약
    keyword_articles = {}
    for keyword, count, _ in keyword_rankings[:5]:
        related_articles = []
        for item in news_items:
            if keyword in item['title']:
                # 캐시에서 요약 확인
                cache_key = f"summary_{item['url']}"
                summary = cache.get(cache_key)
                
                if not summary:
                    try:
                        # 요약이 없으면 새로 생성
                        summary = summarize_article(item['url'])
                        # 요약 결과 캐시에 저장 (1시간)
                        cache.set(cache_key, summary, 3600)
                    except Exception as e:
                        print(f"요약 생성 실패: {str(e)}")
                        summary = "요약을 생성할 수 없습니다."
                
                article_data = {
                    'title': item['title'],
                    'source': item['company_name'],
                    'url': item['url'],
                    'published_at': datetime.now(),
                    'summary': summary
                }
                related_articles.append(article_data)
                
        if related_articles:
            keyword_articles[keyword] = related_articles
            print(f"3. 키워드 '{keyword}'에 대한 기사 수: {len(related_articles)}")
    
    # 4. 컨텍스트 데이터 확인
    context = {
        'keyword_articles': keyword_articles,
        'total_count': sum(len(articles) for articles in keyword_articles.values())
    }
    print(f"4. 총 기사 수: {context['total_count']}")
    
    return render(request, 'news/news_summary.html', context)

def get_top_keyword_articles():
    print("\n=== get_top_keyword_articles 함수 시작 ===")
    
    # news_rankings에서 직접 뉴스 아이템 가져오기
    news_items = cache.get('news_rankings', [])
    print(f"뉴스 아이템 수: {len(news_items)}")
    
    # 전체 기사에서 키워드 랭킹 추출
    all_titles = [item['title'] for item in news_items]
    keyword_rankings = extract_keywords(all_titles)
    print(f"키워드 랭킹 수: {len(keyword_rankings)}")
    
    # 키워드 랭킹이 없으면 빈 딕셔너리 반환
    if not keyword_rankings:
        print("키워드 랭킹이 없습니다.")
        return {'keyword': '', 'articles': [], 'total_count': 0}
    
    # 1위 키워드 가져오기
    top_keyword = keyword_rankings[0][0]
    print(f"1위 키워드: {top_keyword}")
    
    # 1위 키워드가 포함된 기사 필터링
    top_articles = [
        {
            'title': item['title'],
            'url': item['url'],
            'company_name': item['company_name'],
            'rank': item.get('rank', 0)
        }
        for item in news_items 
        if top_keyword in item['title']
    ]
    print(f"필터링된 기사 수: {len(top_articles)}")
    
    # 랭킹순으로 정렬
    top_articles.sort(key=lambda x: x['rank'])
    
    return {
        'keyword': top_keyword,
        'articles': top_articles,
        'total_count': len(top_articles)
    }