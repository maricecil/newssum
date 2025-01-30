from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup
import pandas as pd
from datetime import datetime
import time
import logging
from django.core.cache import cache
from django.utils import timezone
import platform
import json
from pathlib import Path

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
        # 백업 파일 경로 설정
        self.backup_dir = Path('cache_backup')
        self.backup_file = self.backup_dir / 'news_cache_backup.json'
        self._ensure_backup_dir()
        
    def _ensure_backup_dir(self):
        """백업 디렉토리 생성"""
        try:
            self.backup_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.error(f"백업 디렉토리 생성 실패: {str(e)}")

    def backup_cache(self, data):
        """캐시 데이터를 파일로 백업"""
        try:
            # datetime 객체를 문자열로 변환
            serializable_data = self._prepare_for_json(data)
            
            with open(self.backup_file, 'w', encoding='utf-8') as f:
                json.dump(serializable_data, f, ensure_ascii=False)
            logger.info("캐시 백업 완료")
        except Exception as e:
            logger.error(f"캐시 백업 실패: {str(e)}")

    def _prepare_for_json(self, data):
        """JSON 직렬화를 위해 데이터 전처리"""
        if isinstance(data, dict):
            return {k: self._prepare_for_json(v) for k, v in data.items()}
        elif isinstance(data, (list, tuple, set)):
            return [self._prepare_for_json(item) for item in data]
        elif isinstance(data, (pd.Timestamp, datetime)):
            return data.isoformat()
        elif hasattr(data, 'tolist'):  # numpy array 처리
            return data.tolist()
        elif hasattr(data, '__dict__'):  # 객체 처리
            return self._prepare_for_json(data.__dict__)
        return data

    def restore_from_backup(self):
        """백업 파일에서 데이터 복구"""
        try:
            if self.backup_file.exists():
                with open(self.backup_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    logger.info("백업에서 데이터 복구 완료")
                    return data
        except Exception as e:
            logger.error(f"백업 복구 실패: {str(e)}")
        return None

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
                    # 기존 이미지 처리 유지
                    img_container = article.select_one('div.list_img')
                    image_url = None
                    if img_container:
                        img_elem = img_container.select_one('img')
                        if img_elem and 'src' in img_elem.attrs:
                            image_url = img_elem['src']
                    
                    # 제목과 링크 가져오기
                    link = article.select_one('a._es_pc_link, a.list_img')
                    title_elem = article.select_one('strong.list_title, strong.list_text')
                    
                    if title_elem and link:
                        title = title_elem.get_text(strip=True)
                        url = link['href']
                        if not url.startswith('http'):
                            url = f"https://n.news.naver.com{url}"
                        
                        # 1위 기사만 본문 크롤링
                        summary = ''
                        if idx == 1:
                            driver.get(url)
                            time.sleep(2)
                            
                            try:
                                # 본문 이미지 찾기 (기존 코드 유지)
                                try:
                                    main_img = driver.find_element(By.CSS_SELECTOR, '.end_photo_org img')
                                    if main_img:
                                        high_quality_url = main_img.get_attribute('src')
                                        if high_quality_url:
                                            image_url = high_quality_url
                                except:
                                    pass
                                
                                # 본문 크롤링 및 길이 제한
                                content_elem = driver.find_element(By.ID, 'dic_area')
                                if content_elem:
                                    content = content_elem.text.strip()
                                    # 250자로 제한하고 ... 추가
                                    summary = content[:250].strip()
                                    if len(content) > 250:
                                        summary += '...'
                                
                            except Exception as e:
                                logger.error(f"본문 크롤링 실패: {str(e)}")
                            
                            # 랭킹 페이지로 돌아가기
                            driver.get(f"https://media.naver.com/press/{company_code}/ranking")
                            time.sleep(2)
                        
                        news_items.append({
                            'company_code': company_code,
                            'company_name': self.news_companies[company_code],
                            'title': title,
                            'url': url,
                            'rank': idx,
                            'image_url': image_url,
                            'summary': summary,
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
            # 캐시 확인 및 유효성 검사 수정
            cached_data = cache.get('news_data')
            if cached_data:
                last_crawled = cached_data.get('crawled_time')
                if last_crawled:
                    # timezone-aware 비교를 위해 변환
                    if isinstance(last_crawled, str):
                        last_crawled = timezone.datetime.fromisoformat(last_crawled)
                    time_diff = (timezone.now() - last_crawled).total_seconds()
                    
                    # 캐시가 만료되었으면 None 처리
                    if time_diff >= self.CACHE_TIMEOUT:
                        cache.delete('news_data')
                        cached_data = None
                    else:
                        logger.info("캐시된 데이터 사용")
                        return pd.DataFrame(cached_data.get('news_items', []))

            # 크롤링 락 확인
            if cache.get('crawling_in_progress'):
                logger.info("다른 크롤링이 진행 중")
                if cached_data:
                    logger.info("이전 캐시 데이터 사용")
                    return pd.DataFrame(cached_data.get('news_items', []))
                # 캐시가 없는 경우 백업에서 복구 시도
                backup_data = self.restore_from_backup()
                if backup_data:
                    logger.info("백업 데이터 사용")
                    return pd.DataFrame(backup_data.get('news_items', []))
                return pd.DataFrame([])

            # 크롤링 락 설정 (타임아웃 시간 조정)
            cache.set('crawling_in_progress', True, timeout=600)  # 10분으로 연장

            try:
                # 현재 캐시 백업
                if cached_data:
                    self.backup_cache(cached_data)

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
                    new_cache_data = {
                        'news_items': all_news,
                        'crawled_time': timezone.now()
                    }
                    # 새 데이터 캐시에 저장 전 기존 캐시 삭제
                    cache.delete('news_data')
                    cache.set('news_data', new_cache_data, timeout=self.CACHE_TIMEOUT)
                    # 새 데이터 백업
                    self.backup_cache(new_cache_data)
                    return pd.DataFrame(all_news)

                # 크롤링 실패 시 백업 데이터 사용
                backup_data = self.restore_from_backup()
                if backup_data:
                    return pd.DataFrame(backup_data.get('news_items', []))
                return pd.DataFrame([])

            finally:
                # 크롤링 락 해제
                cache.delete('crawling_in_progress')

        except Exception as e:
            logger.error(f"크롤링 중 오류 발생: {str(e)}")
            # 에러 발생 시 백업 데이터 사용
            backup_data = self.restore_from_backup()
            if backup_data:
                return pd.DataFrame(backup_data.get('news_items', []))
            return pd.DataFrame([])

        finally:
            if driver:
                driver.quit()
    
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