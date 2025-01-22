from django_cron import CronJobBase, Schedule
from django.core.cache import cache
from django.http import HttpRequest
from django.utils import timezone
from .views import news_list, article_summary
from crawling.naver_news_crawler import NaverNewsCrawler
from .utils import extract_keywords
from django.conf import settings
import logging
from news.models import Article, NewsSummary

logger = logging.getLogger('news')

class AutoSummaryCronJob(CronJobBase):
    RUN_EVERY_MINS = 30
    schedule = Schedule(run_every_mins=RUN_EVERY_MINS)
    code = 'news.auto_summary_cron'
    
    def do(self):
        try:
            logger.info("\n=== 자동 뉴스 수집 시작 ===")
            
            # 1. NaverNewsCrawler 실행
            crawler = NaverNewsCrawler()
            df = crawler.crawl_all_companies()
            
            if df.empty:
                logger.error("크롤링 결과가 없습니다.")
                return
                
            # 2. 데이터 정렬 및 변환
            df = df.sort_values(['company_name', 'rank'])
            news_items = df.to_dict('records')
            logger.info(f"수집된 뉴스: {len(news_items)}개")
            
            # 3. 키워드 추출
            all_titles = [item['title'] for item in news_items]
            keyword_rankings = extract_keywords(all_titles)
            
            # 4. 캐시 저장
            CACHE_TIMEOUT = getattr(settings, 'CACHE_TIMEOUT', 1800)
            cache.set('news_rankings', news_items, timeout=CACHE_TIMEOUT)
            cache.set('keyword_rankings', keyword_rankings, timeout=CACHE_TIMEOUT)
            cache.set('crawled_time', timezone.now(), timeout=CACHE_TIMEOUT)
            
            logger.info("뉴스 수집 및 키워드 추출 완료")
            
        except Exception as e:
            logger.error(f"자동 수집 중 오류 발생: {str(e)}")

class CleanupCronJob(CronJobBase):
    RUN_EVERY_MINS = 30  # 30분마다 실행
    
    schedule = Schedule(run_every_mins=RUN_EVERY_MINS)
    code = 'news.cleanup_cron_job'
    
    def do(self):
        Article.cleanup_old_articles()  # 30분 이전 기사 삭제
        NewsSummary.cleanup_old_summaries()  # 1시간 이전 요약 삭제

