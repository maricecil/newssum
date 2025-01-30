from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup
import pandas as pd
from datetime import datetime
import time
import logging
from news.models import Article, NewsSummary
from django.core.cache import cache
from django.utils import timezone
import tempfile
import os
import shutil
import platform


logger = logging.getLogger('crawling')  # Django 설정의 'crawling' 로거 사용

class NaverNewsCrawler:
    def __init__(self):
        self.news_companies = {
            '005': '국민일보',
            '023': '조선일보',
            '020': '동아일보',
            '081': '서울신문',
            '025': '중앙일보',
            '028': '한겨레',
            '032': '경향신문',
            '021': '문화일보',
            '022': '세계일보',
            '469': '한국일보'
        }
        self.CACHE_TIMEOUT = 1800  # 30분
        
    def setup_driver(self):
        chrome_options = Options()
        chrome_options.add_argument('--headless=new')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        
        # 공통 옵션
        chrome_options.add_argument('--lang=ko_KR')
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--ignore-certificate-errors')
        chrome_options.add_argument('--disable-popup-blocking')
        chrome_options.add_argument('--disable-extensions')
        chrome_options.add_argument('--disable-dev-tools')
        chrome_options.add_argument('--blink-settings=imagesEnabled=false')
        chrome_options.add_argument('--window-size=1920,1080')
        
        # OS별 옵션 분리
        if platform.system() == 'Windows':
            # Windows 전용 옵션
            chrome_options.add_argument('--disable-gpu')  # Windows에서 필수
            service = Service(ChromeDriverManager().install())
        else:
            # Linux 전용 옵션
            chrome_options.add_argument('--single-process')
            chrome_options.add_argument('--disable-application-cache')
            service = Service('/usr/bin/chromedriver')
        
        try:
            driver = webdriver.Chrome(service=service, options=chrome_options)
            driver.implicitly_wait(10)
            return driver
            
        except Exception as e:
            logger.error(f"Chrome Driver 초기화 실패: {e}")
            raise
            
    def crawl_news_ranking(self, company_code, driver):
        try:
            logger.info(f"크롤링 시작: {self.news_companies[company_code]}")
            started_at = datetime.now()
            
            url = f"https://media.naver.com/press/{company_code}/ranking"
            driver.get(url)
            time.sleep(3)
            
            wait = WebDriverWait(driver, 10)
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, '.press_ranking_list')))
            
            soup = BeautifulSoup(driver.page_source, 'html.parser')
            news_items = []
            
            ranking_list = soup.select_one('.press_ranking_list')
            if not ranking_list:
                logger.error("랭킹 리스트를 찾을 수 없습니다.")
                return None
            
            articles = ranking_list.select('li')[:10]
            
            for idx, article in enumerate(articles, 1):
                try:
                    # 이미지가 있는 기사와 없는 기사 모두 처리
                    link = article.select_one('a._es_pc_link, a.list_img')
                    title_elem = article.select_one('strong.list_title, strong.list_text')
                    
                    # 이미지 요소 찾기 (여러 클래스 패턴 고려)
                    img_elem = article.select_one('img.list_img, img.thumb')
                    image_url = None
                    if img_elem and 'src' in img_elem.attrs:
                        image_url = img_elem['src']
                        # 이미지 URL이 상대 경로인 경우 처리
                        if not image_url.startswith('http'):
                            image_url = f"https:{image_url}"
                        # 이미지 URL에서 크기 파라미터 조정 (더 큰 이미지로)
                        image_url = image_url.replace('type=nf106_72', 'type=nf240_150')
                    
                    if title_elem and link:
                        title = title_elem.get_text(strip=True)
                        url = link['href']
                        
                        news_items.append({
                            'company_code': company_code,
                            'company_name': self.news_companies[company_code],
                            'title': title,
                            'url': url if url.startswith('http') else f"https://n.news.naver.com{url}",
                            'rank': idx,
                            'image_url': image_url,  # 이미지 URL 추가
                            'crawled_at': datetime.now()
                        })
                        
                except Exception as e:
                    logger.error(f"기사 파싱 중 오류 발생: {str(e)}")
                    continue
            
            logger.info(f"수집 완료: {len(news_items)}건")
            return news_items
            
        except Exception as e:
            logger.error(f"크롤링 중 오류 발생: {str(e)}")
            return None
            
    def crawl_all_companies(self):
        driver = None
        try:
            # 캐시 확인
            cached_data = cache.get('news_data')
            if cached_data:
                last_crawled = cached_data.get('crawled_time')
                if last_crawled and (timezone.now() - last_crawled).seconds < self.CACHE_TIMEOUT:
                    logger.info("캐시된 데이터 사용")
                    return pd.DataFrame(cached_data.get('news_items', []))
            
            # 크롤링 락 확인
            if cache.get('crawling_in_progress'):
                logger.info("다른 크롤링이 진행 중, 이전 캐시 사용")
                return pd.DataFrame(cached_data.get('news_items', [])) if cached_data else pd.DataFrame([])
            
            # 크롤링 락 설정
            cache.set('crawling_in_progress', True, timeout=300)  # 5분 타임아웃
            
            try:
                # 새로운 크롤링 시작
                logger.info("새로운 크롤링 시작")
                all_news = []
                driver = self.setup_driver()
                for code in self.news_companies.keys():
                    try:
                        news_items = self.crawl_news_ranking(code, driver)
                        if news_items:
                            all_news.extend(news_items)
                        time.sleep(2)
                    except Exception as e:
                        logger.error(f"신문사 크롤링 실패 ({code}): {str(e)}")
                        continue
                    
                if all_news:
                    df = pd.DataFrame(all_news)
                    cache.set('news_data', {
                        'news_items': all_news,
                        'crawled_time': timezone.now()
                    }, timeout=self.CACHE_TIMEOUT)
                    return df
                    
                return pd.DataFrame([])
                
            finally:
                # 크롤링 락 해제
                cache.delete('crawling_in_progress')
            
        except Exception as e:
            logger.error(f"크롤링 중 오류 발생: {str(e)}")
            return pd.DataFrame([])
    
    def crawl_content(self, url):
        driver = None
        try:
            driver = self.setup_driver()
            driver.get(url)
            time.sleep(2)  # 페이지 로딩 대기
            
            # 페이지 로딩 대기
            wait = WebDriverWait(driver, 10)
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, '#dic_area')))
            
            # HTML 파싱
            soup = BeautifulSoup(driver.page_source, 'html.parser')
            
            # 기사 본문 찾기 (네이버 뉴스 본문 영역의 ID: dic_area)
            content_element = soup.select_one('#dic_area')
            if content_element:
                # 불필요한 요소 제거
                for tag in content_element.select('script, style, iframe'):
                    tag.decompose()
                    
                # 본문 텍스트 추출 및 정제
                content = content_element.get_text(strip=True)
                content = ' '.join(line.strip() for line in content.split('\n') if line.strip())
                return content
                
            return "기사 내용을 찾을 수 없습니다."
            
        except Exception as e:
            logger.error(f"기사 내용 크롤링 중 오류 발생: {str(e)}")
            return f"기사 내용을 가져오는 중 오류가 발생했습니다: {str(e)}"
            
        finally:
            if driver:
                driver.quit()

if __name__ == "__main__":
    crawler = NaverNewsCrawler()
    # 전체 대신 하나의 신문사만 테스트 (예: 국민일보 '005')
    result = crawler.crawl_news_ranking('005', None)
    if result:
        print("\n=== 크롤링 결과 ===")
        print(f"총 {len(result)}개의 뉴스를 수집했습니다.")
        print("\n상위 5개 뉴스:")
        for item in result[:5]:
            print(f"[{item['rank']}위] {item['title']}") 