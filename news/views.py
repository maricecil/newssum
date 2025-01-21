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
from .models import Article, Keyword, NewsSummary
from django.db.models import Count
from django.utils import timezone
import logging
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
import json
from openai import OpenAI
from asgiref.sync import sync_to_async, async_to_sync
from .agents.crew import NewsAnalysisCrew, summarize_article
from langchain_community.llms import OpenAI
from crewai.crew import Crew
from langchain_community.chat_models import ChatOpenAI
from langchain.schema import SystemMessage, HumanMessage
from django.utils import timezone

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
    CACHE_TIMEOUT = getattr(settings, 'CACHE_TIMEOUT', 1800)  # 기본값 30분
    
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
        crawled_time = timezone.now()  # 크롤링 시간 저장
        
        all_titles = [item['title'] for item in news_items]
        current_keywords = extract_keywords(all_titles)
        
        # 하드코딩된 300 대신 settings의 TIMEOUT 사용
        cache.set('previous_keywords', current_keywords, timeout=CACHE_TIMEOUT)
        cache.set('news_rankings', news_items, timeout=CACHE_TIMEOUT)
        cache.set('crawled_time', crawled_time, timeout=CACHE_TIMEOUT)
    else:
        # 캐시된 크롤링 시간 가져오기
        crawled_time = cache.get('crawled_time')
    
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
    
    # news_by_company 딕셔너리 생성 수정
    news_by_company = {}
    for item in news_items:
        company = item.get('company_name', '')  # get 메서드로 안전하게 접근
        if company:  # company가 존재할 때만 처리
            if company not in news_by_company:
                news_by_company[company] = []
            news_by_company[company].append(item)
    
    context = {
        'news_items': news_items,
        'daily_rankings': daily_rankings,
        'keyword_rankings': keyword_rankings,
        'previous_keywords': previous_keywords,
        'crawled_time': crawled_time,  # 크롤링 시간 추가
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
        'crawled_time': cached_data.get('crawled_time'),
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
                # CrewAI 대신 GPT로 종합 분석
                summaries_text = "\n\n".join([
                    f"제목: {article['title']}\n"
                    f"언론사: {article['company_name']}\n"
                    f"요약: {article['summary']}"
                    for article in filtered_items
                ])
                
                llm = ChatOpenAI(
                    model_name="gpt-3.5-turbo-16k",
                    temperature=0.3,
                    max_tokens=4000
                )
                
                system_prompt = """
                모든 언론사의 기사를 반드시 빠짐없이 분석하여 다음 형식으로 정리해주세요:

                보도 관점 분석(800자 이내)
                - [언론사명] (각 언론사별로 반드시 분석)
                - 주요 보도 프레임과 논조 (예시-"조선일보는 'A정책 실패' 강조, 한겨레는 'B정책 성과' 부각")
                - 구체적인 표현과 인용구 포함
                - 다룬 주요 이슈와 강조점

                주요 쟁점 분석
                - 언론사별 대립되는 시각과 근거(예시-"동아일보와 경향신문은 [특정 사안]에 대해 상반된 입장")

                종합 분석
                - 전체 언론사의 보도 경향성 요약
                - 각 언론사별 차별화된 시각과 의미
                - 독자들이 고려해야 할 다양한 관점
                
                ※ 주의사항
                - 보도 관점 분석, 주요 쟁점 분석, 종합 분석의 구분을 명확히 할 것
                - 기사가 하나일지라도 모든 언론사를 빠짐없이 포함하여 누락되지 않게 할 것
                - 반드시 언론사가 중복되지 않게 할 것
                - 구체적인 기사 내용과 표현을 인용하여 분석할 것
                - 중립적인 톤으로 작성할 것
                """
                
                messages = [
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=summaries_text)
                ]
                
                response = llm.generate([messages])
                result = response.generations[0][0].text
                parts = result.split('\n\n', 2)
                
                analysis_results = {
                    'classification': parts[0] if len(parts) > 0 else '분류 결과 없음',
                    'comparison': parts[1] if len(parts) > 1 else '비교 분석 결과 없음',
                    'summary': parts[2] if len(parts) > 2 else '요약 결과 없음'
                }
                
                analysis_results['press_distribution'] = press_distribution
                analysis_results['filtered_count'] = len(filtered_items)
                analysis_results['keyword_rankings'] = keyword_rankings
                basic_analysis['crew_analysis'] = analysis_results
                logger.info("GPT 분석 완료")
            except Exception as gpt_error:
                logger.error(f"GPT 분석 중 오류 발생: {str(gpt_error)}")
                basic_analysis['gpt_analysis_error'] = "종합 분석 중 오류가 발생했습니다."
        
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
    cached_data = cache.get('news_data', {})
    news_items = cached_data.get('news_items', [])
    keyword_rankings = cached_data.get('keyword_rankings', [])
    crawled_time = cached_data.get('crawled_time')  # 크롤링 시간 가져오기

    print(f"1. 캐시된 뉴스 개수: {len(news_items)}")
    
    if not news_items:
        print("캐시된 뉴스가 없습니다!")
        return redirect('news:news_list')
    
    # 2. 이미 랭킹된 키워드 사용
    print(f"2. 추출된 키워드 수: {len(keyword_rankings)}")
    top_keywords = keyword_rankings[:1] if keyword_rankings else []
    print(f"1개 키워드: {top_keywords}")
    
    # 3. 기사 그룹화 및 요약
    keyword_articles = {}
    for keyword_data in top_keywords:
        keyword, article_count, _ = keyword_data  # 사용하지 않는 articles는 _로 표시
        print(f"키워드 '{keyword}'의 기사 수: {article_count}")
        
        related_articles = []
        for item in news_items:
            if keyword in item['title']:
                # 캐시에서 요약 확인
                cache_key = f"summary_{item['url']}"
                summary = cache.get(cache_key)
                
                if not summary:
                    try:
                        summary = summarize_article(item['url'])
                        cache.set(cache_key, summary, 3600)
                    except Exception as e:
                        logger.error(f"요약 생성 실패: {str(e)}")
                        summary = "요약을 생성할 수 없습니다."
                
                article_data = {
                    'title': item['title'],
                    'source': item['company_name'],
                    'url': item['url'],
                    'summary': summary,
                    'rank': item.get('rank', 0)
                }
                related_articles.append(article_data)
        
        if related_articles:
            # 순위순으로 정렬
            related_articles.sort(key=lambda x: x['rank'])
            
            # CrewAI 분석 실행 - 중복 분석 제거
            try:
                # CrewAI 대신 GPT로 종합 분석
                summaries_text = "\n\n".join([
                    f"제목: {article['title']}\n"
                    f"언론사: {article['source']}\n"
                    f"요약: {article['summary']}"
                    for article in related_articles
                ])
                
                llm = ChatOpenAI(
                    model_name="gpt-3.5-turbo-16k",
                    temperature=0.3,
                    max_tokens=4000
                )
                
                system_prompt = """
                모든 언론사의 기사를 반드시 빠짐없이 분석하여 다음 형식으로 정리해주세요:

                보도 관점 분석(800자 이내)
                - [언론사명] (각 언론사별로 반드시 분석)
                - 주요 보도 프레임과 논조 (예시-"조선일보는 'A정책 실패' 강조, 한겨레는 'B정책 성과' 부각")
                - 구체적인 표현과 인용구 포함
                - 다룬 주요 이슈와 강조점

                주요 쟁점 분석
                - 언론사별 대립되는 시각과 근거(예시-"동아일보와 경향신문은 [특정 사안]에 대해 상반된 입장")

                종합 분석
                - 전체 언론사의 보도 경향성 요약
                - 각 언론사별 차별화된 시각과 의미
                - 독자들이 고려해야 할 다양한 관점
                
                ※ 주의사항
                - 보도 관점 분석, 주요 쟁점 분석, 종합 분석의 구분을 명확히 할 것
                - 기사가 하나일지라도 모든 언론사를 빠짐없이 포함하여 누락되지 않게 할 것
                - 반드시 언론사가 중복되지 않게 할 것
                - 구체적인 기사 내용과 표현을 인용하여 분석할 것
                - 중립적인 톤으로 작성할 것
                """
                
                messages = [
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=summaries_text)
                ]
                
                response = llm.generate([messages])
                result = response.generations[0][0].text
                parts = result.split('\n\n', 2)
                
                analysis_results = {
                    'classification': parts[0] if len(parts) > 0 else '분류 결과 없음',
                    'comparison': parts[1] if len(parts) > 1 else '비교 분석 결과 없음',
                    'summary': parts[2] if len(parts) > 2 else '요약 결과 없음'
                }
                
                # press_stats에서 직접 가져오는 대신 results에서 가져오기
                keyword_articles[keyword] = {
                    'articles': related_articles,
                    'count': article_count,
                    'analysis': analysis_results
                }
                
            except Exception as e:
                logger.error(f"GPT 분석 중 오류 발생: {str(e)}")
                keyword_articles[keyword] = {
                    'articles': related_articles,
                    'count': article_count,
                    'analysis': {
                        'classification': '분석 중 오류 발생',
                        'comparison': '분석 중 오류 발생',
                        'summary': '분석 중 오류 발생'
                    }
                }
    
    # 5. 컨텍스트 데이터 구성
    context = {
        'keyword_articles': keyword_articles,
        'total_count': sum(len(data['articles']) for data in keyword_articles.values()),
        'crawled_time': crawled_time,
    }
    print(f"5. 총 기사 수: {context['total_count']}")
    
    # 컨텍스트 데이터 구성 후 DB에 저장
    for keyword, data in keyword_articles.items():
        try:
            NewsSummary.objects.create(
                keyword=keyword,
                crawled_time=crawled_time,
                articles=data['articles'],
                analysis=data['analysis']
            )
        except Exception as e:
            logger.error(f"요약 저장 실패 - 키워드: {keyword}, 에러: {str(e)}")
            continue
    
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

def view_saved_summaries(request):
    # 최근 24시간 내의 요약만 조회
    recent_summary = NewsSummary.objects.filter(
        created_at__gte=timezone.now() - timezone.timedelta(days=3)
    ).order_by('-created_at').first()
    
    if recent_summary:
        context = {
            'keyword_articles': {
                recent_summary.keyword: {
                    'articles': recent_summary.articles,
                    'analysis': recent_summary.analysis
                }
            },
            'crawled_time': recent_summary.crawled_time,
        }
    else:
        context = {
            'keyword_articles': {},
            'crawled_time': None,
        }
    
    return render(request, 'news/news_summary.html', context)