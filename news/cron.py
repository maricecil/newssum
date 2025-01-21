from django_cron import CronJobBase, Schedule
from django.core.cache import cache
from django.http import HttpRequest
from django.utils import timezone
from .views import news_list, article_summary
from crawling.naver_news_crawler import NaverNewsCrawler
from .utils import extract_keywords
from django.conf import settings
import logging

logger = logging.getLogger('news')

class AutoSummaryCronJob(CronJobBase):
    RUN_EVERY_MINS = 30
    
    schedule = Schedule(run_every_mins=RUN_EVERY_MINS)
    code = 'news.auto_summary_cron'
    
    def do(self):
        try:
            logger.info("\n=== 자동 뉴스 수집 시작 ===")
            
            # 1. 크롤링 실행 (DataFrame 반환)
            crawler = NaverNewsCrawler()
            request = HttpRequest()
            news_list(request)

            df = crawler.crawl_all_companies()
            if df.empty:
                logger.error("크롤링 결과가 없습니다.")
                return
            
            news_items = cache.get('news_rankings')
            if not news_items:
                logger.error("크롤링된 뉴스가 없습니다")
                return

            logger.info(f"크롤링된 뉴스: {len(news_items)}개")

            all_titles = [item['title'] for item in news_items]
            keyword_rankings = extract_keywords(all_titles)

            cache_data = {
                'news_items': news_items,
                'keyword_rankings': keyword_rankings,
                'crawled_time': timezone.now()
            }

            cache.set('news_data', cache_data)
            logger.info(f"분석용 캐시 저장 완료: {len(news_items)}개 기사")

            # 4. article_summary 실행
            from .views import article_summary
            article_summary(request)
            logger.info("뉴스 분석 완료")
            
        except Exception as e:
            print(f"자동 분석 중 오류 발생: {str(e)}")

