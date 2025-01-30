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
    logger.info("=== 뉴스 목록 조회 시작 ===")
    CACHE_TIMEOUT = getattr(settings, 'CACHE_TIMEOUT', 3600)
    
    try:
        # 1. 캐시 확인 및 유효성 검사
        cached_data = cache.get('news_data')
        if cached_data:
            last_crawled = cached_data.get('crawled_time')
            if last_crawled:
                # timezone-aware 비교를 위해 변환
                if isinstance(last_crawled, str):
                    last_crawled = timezone.datetime.fromisoformat(last_crawled)
                time_diff = (timezone.now() - last_crawled).total_seconds()
                
                # 캐시가 만료되었으면 삭제 후 새로운 크롤링 시도
                if time_diff >= CACHE_TIMEOUT:
                    logger.info("캐시 만료 - 새로운 크롤링 시도")
                    cache.delete('news_data')
                    cache.delete('news_rankings')
                    cache.delete('previous_keywords')
                    cache.delete('crawled_time')
                    cache.delete('last_update')
                    cached_data = None
                else:
                    logger.info("유효한 캐시 데이터 사용")
                    return render(request, 'news/news_list.html', cached_data)

        # 2. 크롤링 시도
        crawler = NaverNewsCrawler()
        df = crawler.crawl_all_companies()
        
        if df is not None and not df.empty:
            news_items = df.to_dict('records')
            crawled_time = timezone.now()
            
            # 3. 새로운 데이터 처리 및 캐시 설정
            context = prepare_news_context(news_items, crawled_time)
            
            # 4. 캐시 업데이트
            cache.delete('news_data')  # 기존 캐시 명시적 삭제
            cache.set('news_data', context, timeout=CACHE_TIMEOUT)
            cache.set('last_update', timezone.now(), timeout=CACHE_TIMEOUT)
            
            # 5. 백업 저장
            if hasattr(crawler, 'backup_cache'):
                backup_data = {
                    'news_items': news_items,
                    'context': context,
                    'crawled_time': crawled_time
                }
                crawler.backup_cache(backup_data)
                logger.info("새로운 데이터 백업 완료")
            
            return render(request, 'news/news_list.html', context)
            
        # 6. 크롤링 실패 시 백업 데이터 사용
        backup_data = crawler.restore_from_backup()
        if backup_data and backup_data.get('context'):
            logger.info("백업 데이터 사용")
            return render(request, 'news/news_list.html', backup_data['context'])
            
        return render(request, 'news/error.html', {'message': '뉴스를 불러올 수 없습니다.'})
        
    except Exception as e:
        logger.error(f"뉴스 목록 조회 중 오류 발생: {str(e)}")
        return render(request, 'news/error.html', {'message': '일시적인 오류가 발생했습니다.'})

def prepare_news_context(news_items, crawled_time):
    """뉴스 컨텍스트 준비 함수"""
    # 키워드 추출
    all_titles = [item['title'] for item in news_items]
    keyword_rankings = extract_keywords(all_titles)
    
    # 일간 주요 뉴스 준비
    daily_rankings = [item for item in news_items if item.get('rank') == 1]
    
    # 언론사별 뉴스 그룹화
    news_by_company = {}
    for item in news_items:
        company = item.get('company_name', '')
        if company:
            if company not in news_by_company:
                news_by_company[company] = []
            news_by_company[company].append(item)
    
    return {
        'news_items': news_items,
        'daily_rankings': daily_rankings,
        'keyword_rankings': keyword_rankings,
        'news_by_company': news_by_company,
        'crawled_time': crawled_time,
        'refresh_interval': settings.CACHES['default']['TIMEOUT']
    }

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
        'is_loading': True,  # 로딩 상태 추가
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
                다음 세 단계로 분석해주세요:

                1. 보도 관점 분석
                각 언론사의 보도 프레임을 분석하세요:
                - 어떤 사실을 전면에 내세우는가?
                - 어떤 맥락을 강조하는가?
                - 어떤 표현과 어조를 사용하는가?

                2. 주요 쟁점 분석
                핵심 쟁점별로 언론사들의 대립되는 시각을 분석하세요:
                - 쟁점 1: [언론사A]는 [프레임A]로, [언론사B]는 [프레임B]로 해석
                - 쟁점 2: [언론사C]는 [관점C]를, [언론사D]는 [관점D]를 강조

                3. 종합 분석
                전체 보도의 지형도를 그려주세요:
                - 주요 진영과 프레임은 어떻게 형성되어 있는가?
                - 각 진영의 핵심 주장과 근거는 무엇인가?
                - 이 보도들이 여론 형성에 미치는 영향은?

                ※ 구체적 사례와 표현을 인용하며 분석할 것
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
        cache.set(cache_key, basic_analysis, timeout=3600)
        
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

def article_summary(request=None):
    print("\n=== article_summary 디버깅 ===")
    
    # 1. 캐시 데이터 확인
    cached_data = cache.get('news_data', {})
    news_items = cached_data.get('news_items', [])
    keyword_rankings = cached_data.get('keyword_rankings', [])
    crawled_time = cached_data.get('crawled_time')  # 크롤링 시간 가져오기

    print(f"1. 캐시된 뉴스 개수: {len(news_items)}")
    
    if not news_items:
        print("캐시된 뉴스가 없습니다!")
        return None if request is None else redirect('news:news_list')  # request가 없는 경우 None 반환
    
    # 2. 이미 랭킹된 키워드 사용
    print(f"2. 추출된 키워드 수: {len(keyword_rankings)}")
    top_keywords = keyword_rankings[:1] if keyword_rankings else []
    print(f"1개 키워드: {top_keywords}")
    
    # 3. 기사 그룹화 및 요약
    keyword_articles = {}
    for keyword_data in top_keywords:
        keyword, article_count, _ = keyword_data
        print(f"키워드 '{keyword}'의 기사 수: {article_count}")
        
        # DB에서 최근 저장된 요약 확인
        try:
            saved_summary = NewsSummary.objects.filter(
                keyword=keyword,
                crawled_time=crawled_time
            ).first()
            
            if saved_summary:
                print(f"저장된 요약 사용 - 키워드: {keyword}")
                keyword_articles[keyword] = {
                    'articles': saved_summary.articles,
                    'count': len(saved_summary.articles),
                    'analysis': saved_summary.analysis
                }
                continue  # 저장된 데이터가 있으면 새로운 분석 건너뛰기
        except Exception as e:
            logger.error(f"저장된 요약 조회 실패: {str(e)}")
        
        # 저장된 데이터가 없는 경우에만 새로운 분석 진행
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
                다음 세 단계로 분석해주세요:

                1. 보도 관점 분석
                각 언론사의 보도 프레임을 분석하세요:
                - 어떤 사실을 전면에 내세우는가?
                - 어떤 맥락을 강조하는가?
                - 어떤 표현과 어조를 사용하는가?

                2. 주요 쟁점 분석
                핵심 쟁점별로 언론사들의 대립되는 시각을 분석하세요:
                - 쟁점 1: [언론사A]는 [프레임A]로, [언론사B]는 [프레임B]로 해석
                - 쟁점 2: [언론사C]는 [관점C]를, [언론사D]는 [관점D]를 강조

                3. 종합 분석
                전체 보도의 지형도를 그려주세요:
                - 주요 진영과 프레임은 어떻게 형성되어 있는가?
                - 각 진영의 핵심 주장과 근거는 무엇인가?
                - 이 보도들이 여론 형성에 미치는 영향은?

                ※ 구체적 사례와 표현을 인용하며 분석할 것
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
        'is_loading': True,  # 로딩 상태 추가
        'keyword_articles': keyword_articles,
        'total_count': sum(len(data['articles']) for data in keyword_articles.values()),
        'crawled_time': crawled_time,
    }
    print(f"5. 총 기사 수: {context['total_count']}")
    
    # 컨텍스트 데이터 구성 후 DB에 저장
    for keyword, data in keyword_articles.items():
        try:
            # crawled_time을 datetime으로 변환
            if isinstance(crawled_time, str):
                crawled_time_dt = timezone.datetime.fromisoformat(crawled_time.replace('Z', '+00:00'))
            else:
                crawled_time_dt = crawled_time

            NewsSummary.objects.create(
                keyword=keyword,
                crawled_time=crawled_time_dt,
                articles=data['articles'],
                analysis=data['analysis']
            )
            logger.info(f"요약 저장 성공 - 키워드: {keyword}")
        except Exception as e:
            logger.error(f"요약 저장 실패 - 키워드: {keyword}, 에러: {str(e)}")
            continue

    # 마지막 부분 수정
    if request is None:  # 크론잡에서 호출한 경우
        return keyword_articles  # 분석 결과만 반환
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