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
        
    def setup_driver(self):
        chrome_options = Options()
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--disable-software-rasterizer')
        chrome_options.add_argument('--ignore-certificate-errors')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option('useAutomationExtension', False)
        chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        chrome_options.add_argument('--headless=new')  # 새로운 헤드리스 모드
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--window-size=1920,1080')
        chrome_options.add_argument("--disable-extensions")
        chrome_options.add_argument('--allow-running-insecure-content')
        chrome_options.add_argument("--disable-setuid-sandbox")
        chrome_options.add_argument('--lang=ko_KR')
        chrome_options.add_argument('--remote-debugging-port=9222')  # 디버깅 포트 추가

        try:
            service = ChromeService()
            driver = webdriver.Chrome(service=service, options=chrome_options)
        except Exception as e:
            logger.error(f"ChromeDriver 초기화 실패: {e}")
            raise

        return driver
    
    def crawl_news_ranking(self, company_code):
        driver = None
        try:
            logger.info(f"크롤링 시작: {self.news_companies[company_code]}")
            started_at = datetime.now()
            
            driver = self.setup_driver()
            url = f"https://media.naver.com/press/{company_code}/ranking"
            driver.get(url)
            time.sleep(3)
            
            # 페이지 로딩 대기 및 CSS 선택자 수정
            wait = WebDriverWait(driver, 10)
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, 'a[href*="/article/"]')))
            
            # HTML 파싱
            soup = BeautifulSoup(driver.page_source, 'html.parser')
            news_items = []
            
            # 뉴스 아이템 추출 (CSS 선택자 수정)
            articles = soup.select('a[href*="/article/"]')[:10]  # 상위 10개만 추출
            
            for idx, article in enumerate(articles, 1):
                try:
                    # 순위 요소 찾기
                    rank_num = article.select_one('.list_ranking_num')
                    if rank_num:
                        rank_num.decompose()  # 순위 텍스트 제거
                    
                    title = article.get_text(strip=True)
                    url = article['href']
                    
                    # 제목에서 조회수 부분 제거
                    if '조회수' in title:
                        title = title.split('조회수')[0].strip()
                            
                    if title and url:
                        news_items.append({
                            'company_code': company_code,
                            'company_name': self.news_companies[company_code],
                            'title': title,
                            'url': url if url.startswith('http') else f"https://n.news.naver.com{url}",
                            'rank': idx,
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
            
        finally:
            if driver:
                driver.quit()
    
    def crawl_all_companies(self):
        # 크롤링 전 이전 데이터 정리
        Article.cleanup_old_articles()
        NewsSummary.cleanup_old_summaries()
        
        all_news = []
        for code in self.news_companies.keys():
            try:
                news_items = self.crawl_news_ranking(code)
                if news_items:
                    all_news.extend(news_items)
                time.sleep(2)  # 신문사 간 딜레이
            except Exception as e:
                logger.error(f"신문사 크롤링 실패 ({code}): {str(e)}")
                continue
        
        return pd.DataFrame(all_news)
    
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
    result = crawler.crawl_news_ranking('005')
    if result:
        print("\n=== 크롤링 결과 ===")
        print(f"총 {len(result)}개의 뉴스를 수집했습니다.")
        print("\n상위 5개 뉴스:")
        for item in result[:5]:
            print(f"[{item['rank']}위] {item['title']}") 