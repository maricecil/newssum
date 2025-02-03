# READ.ME

## **1. 개요**

### **1.1 프로젝트 정보**

- **프로젝트명**: 뉴스 기사 분석 및 요약 서비스
    - 주요 종합신문의 최신 뉴스 기사를 비교하고, 분석하고 요약해주는 서비스를 제공합니다.
    - 10개 대표 종합 신문(경향신문, 국민일보, 동아일보, 문화일보, 서울신문, 세계일보, 조선일보, 중앙일보, 한겨례, 한국일보)의 TOP10뉴스를 1시간마다 자동으로 크롤링합니다.
    - 각 신문사의 1위 기사는 실시간 주요 뉴스에 오릅니다. 
    - 크롤링된 100개 뉴스는 빈도수 등을 고려하여 키워드 랭킹에 오릅니다. 각 키워드와 관련된 기사를 모아서 볼 수 있고, 키워드와 언론사를 필터링 선택하여 비교하고 분석할 수 있습니다.
    - 키워드 1위와 관련된 기사 모두가 요약되어 *주요기사 요약하기* 페이지에 실리고, 그것은 LLM으로 한 번 더 분석되어 관점과 쟁점, 종합분석을 돕습니다.

- **개발 기간**: 24.12.30.(월)~25.1.30(목), 30일 간
- **개발 인원**: 1명   
    
| 날짜               | 목표                                                                                         | 비고  |
|--------------------|----------------------------------------------------------------------------------------------|-------|
| 12/30(월)~1/3(금)         | - 기획 및 디자인<br>- 시장조사<br>- 문서 작성(API, 기능명세서, ERD 등) <br>- GitHub개설             | 5일   |
| 1/4(토)~1/5(일)  | - 데이터 크롤링<br>(10개 신문사 TOP10 뉴스)                                                                      | 2일   |
| 1/6(월)~1/13(월)  | - 실시간 주요 랭킹 페이지 제작<br> - 실시간 주요 뉴스 구성<br> - 키워드 랭킹 및 전처리<br> - 언론사별 실시간 랭킹 디자인                                                                     | 8일   |
| 1/14(화)~1/17(금)| - 주요기사 모아보기 페이지 제작<br>- 언론사 및 주요 키워드 필터링 기능<br>- 키워드 분석 기능<br>(트렌드, 관계, 주요 인사이트)<br>       | 4일   |
| 1/18(토)~1/21(화)         | - 주요기사 요약 페이지 제작<br>- TOP1 키워드 관련 기사 요약 및 분석<br>(보도관점, 주요쟁점, 종합분석)             | 4일   |
| 1/22(목)~1/24(금)          | - DB구축 및 서버배포(ngrok)<br>- 테스트 요청<br>- 문서 작성(만족도 설문지, READ.ME 등)                                                           | 2일   |
| 1/25(토)~1/26(일)          | - DB구축 및 서버배포(Docker,AWS2)<br> | 3일   |
| 1/27(월)~1/31(금)          | - 테스트 및 오류개선<br>- 발표 준비(영상자료, PPT 등) | 5일   |


### **1.2 프로젝트 목적**

- 사용자가 주요 헤드라인을 빠르게 확인할 수 있는 플랫폼 제공
- 선택한 언론 매체의 뉴스를 비교할 수 있는 기능 제공
- 주요 키워드에 대한 AI의 분석 및 요약 제공
- 균형 잡힌 뉴스 소비 촉진

### **1.3 기획 의도**
정보가 넘치는 오늘 날에 객관적인 사실로 균형 잡힌 관점을 유지하기란 쉽지 않습니다. 본 웹 서비스는 10대 주요 언론사의 키워드를 분석, 비교, 요약하여 주요 이슈를 빠르고 정확하게 전달합니다. 이 플랫폼은 다양한 관점을 제공해 뉴스 소비자가 비판적 사고를 통해 편향된 정보에 의존하지 않고 스스로 판단하는 것을 돕습니다. 궁극적으로 균형 잡힌 뉴스 소비를 촉진하는 것을 목표로 합니다.

## **2. 주요 기능**
### 2.1 뉴스 크롤링
- 10개 종합 신문의 TOP10 뉴스 100개를 1시간 마다 크롤링합니다. 크롤링 할 때 키워드도 함께 분석합니다. 정보는 캐시에 저장되어 한 번 요약한 API를 추가로 호출하지 않습니다. 캐시는 TIMEOUT이 되면 사라지고, **새**로운 정보를 불러옵니다. 

### 2.2 실시간 랭킹
- 각 언론사의 TOP10 뉴스는 카드디자인으로 로고와 함께 언론사 코드순으로 분류되었습니다. 언론사는 연회색 배경으로 하여 눈에 띄게 하였고, 로고는 호버링을 주어 강조했습니다. 1위,2위,3위는 다른 색을 입혀 강조해 가독성을 향상시켰습니다.

### 2.3 실시간 주요뉴스
- 실시간 주요뉴스는 각 언론사의 TOP10 뉴스 중 1위를 차지한 기사입니다. 마찬가지로 언론사 코드순으로 배열하여 언론사가 중요하게 다루는 기사를 한 눈에 볼 수 있게 하였습니다. 제목과 썸네일 이미지, 요약문, 크롤링 시간을 기록했습니다. 

### 2.4 키워드 랭킹
- 키워드는 빈도수에 따라 랭킹이 정해지는데, 랭킹에 오르기 전 한자와 숫자, 괄호 등을 제거하고, 정당, 인명, 일반명사 순으로 랭킹에 오릅니다. 분석기는 Opt.prase가 사용되었고 구단위로 분류해 형태소가 잘 지켜지는 장점이 있었습니다. 다만 5글자 이내를 필터링하고, 미처 필터링 되지 못한 접미사, 조사 등은 stop_words에 추가하여 핵심 키워드를 파악했습니다. 
- 키워드에 강조색을 두었고, 화살표를 두어 관련기사를 슬라이드함으로써 이해를 도왔습니다. 키워드를 클릭하면 관련기사를 모아 볼 수 있습니다.

### 2.5 주요기사 모아보기
- 주요기사 모아보기에는 TOP10 순위에 오른 키워드와 관련한 기사를 모아볼 수 있습니다. 키워드별 기사는 제목에 키워드가 들어간 기사를 모아서 보여주고, 언론사별 기사는 중복 없이 해당하는 기사를 보여줍니다. 
- 특별한 점은 필터링 기능을 통해 언론사는 최대 3개까지, 키워드는 5개까지 선택해 LLM에 분석을 요청할 수 있다는 점입니다. 의미있는 결과를 도출하고자 키워드와 언론사에 선택 개수에는 상한선을 두었습니다.

### 2.6 키워드 분석하기
- 키워드 랭킹에 오른 기사를 사용자는 다시 선택해 비교하고, 분석할 수 있습니다. 여기에는 언론사별 기사 개수와 표현된 단어, 키워드 간 연관성 등을 고려해 우리에게 인사이트를 전달합니다. 

### 2.7 종합 분석 및 요약
- 키워드를 기반으로 기사를 분석하고, LLM을 기반으로 요약을 제공합니다.
- OpenAI GPT API와 LangChain을 활용해 심층 분석을 제공합니다.

## **3. 기술 스택**

### **3.1 백엔드 및 API**
- Python(3.10+)
  - 주요 로직 구현
  - 데이터 처리 및 분석
  - 크롤링 및 스크래핑

- Django(5.0)
  - SQLite 데이터베이스 활용
  - Redis 캐시 시스템 연동
  - 기본 Django 인증 시스템

### **3.2 데이터 처리 및 AI**
- OpenAI GPT API + LangChain
  - 기사 요약 및 분석
  - 프롬프트 체인 관리
  - 컨텍스트 기반 응답 생성

### **3.3 프론트엔드**
- Django 템플릿
  - 서버 사이드 렌더링
  - 템플릿 상속 구조
  - 동적 컨텐츠 렌더링

- TailwindCSS
  - 유틸리티 퍼스트 CSS
  - 반응형 디자인
  - 다크모드 지원

- JavaScript
  - AJAX 비동기 통신
  - 동적 UI 업데이트
  - 사용자 인터랙션 처리

### **3.4 크롤링 및 데이터 수집**
- BeautifulSoup4
  - 정적 페이지 파싱
  - CSS 선택자 기반 데이터 추출
  - HTML 구조 분석

- Selenium
  - 동적 콘텐츠 크롤링
  - JavaScript 렌더링 처리
  - 자동화된 데이터 수집

### **3.5 성능 최적화**
- Redis 기반 캐싱 전략
  - 1시간 단위 캐시 갱신
  - 크롤링 중 기존 캐시 데이터 제공
  - JSON 형식 백업 파일 저장
- 데이터 복구 우선순위
  1. 메모리 캐시 확인
  2. 새로운 크롤링 시도
  3. 백업 데이터 활용
  4. 마지막 캐시 재사용

### **의사결정**
- **Python과 Django**: Python의 간결성과 Django의 강력한 웹 프레임워크 기능을 활용하여 MVT 아키텍처 기반의 빠른 개발이 가능합니다. 기본 인증 시스템과 ORM을 통해 보안성과 데이터베이스 관리가 편리해 선택하게 되었습니다.

- **OpenAI GPT API와 LangChain**: 자연어 처리에 특화된 GPT API와 LangChain의 프롬프트 체인 관리 기능을 통해 구조화된 기사 분석과 요약을 제공하여 선택하게 되었습니다.

- **BeautifulSoup4와 Selenium**: BeautifulSoup4의 정적 페이지 파싱 능력과 Selenium의 동적 콘텐츠 처리 기능을 결합하여 효율적인 데이터 수집이 가능해 선택하게 되었습니다.

- **Redis**: 1시간 단위 캐시 갱신과 JSON 백업을 통해 데이터 접근 속도를 최적화하고 시스템 안정성을 확보하고자 선택하게 되었습니다.

- **TailwindCSS**: 유틸리티 퍼스트 CSS 프레임워크로 반응형 디자인과 다크모드를 쉽게 구현할 수 있어 선택하게 되었습니다.

## **4. 배포 및 운영**
### **4.1 필요 환경**
- Python 3.10+
- OpenAI API 키

### **4.2 설치 및 실행**
```python
pip install -r requirements.txt
Python manage.py runserver
```

### **4.3 트러블슈팅**

#### **Frontend**
1. **키워드 필터링 UI/UX**
   - 문제: 필터 초기화 시 키워드 태그가 화면에 남아있는 현상
   - 해결: `updateKeywordTags()` 함수 호출 추가 및 태그 업데이트 로직 동기화
   ```javascript
   resetButton.addEventListener('click', function() {
       selectedCompanyList.clear();
       selectedKeywordList.clear();
       updateTags();
       updateKeywordTags();
       filterArticles();
   });
   ```

2. **필터링 사용성**
   - 문제: 키워드만 선택 시 결과가 표시되지 않는 UX 이슈
   - 해결: 사용자 안내 메시지 추가 및 선택 제한 구현
   ```javascript
   if (selectedKeywords.length > 0 && selectedCompanies.length === 0) {
       filteredContainer.innerHTML = '<p class="text-gray-500 text-center py-4">언론사를 먼저 선택해주세요.</p>';
       return;
   }
   ```

#### **Backend**
1. **키워드 추출 정확도**
   - 문제: "공수처", "공수처장"이 "공수"로 잘못 추출되는 현상
   - 해결: 복합명사 우선 추출 로직 구현
   ```python
   for pattern in COMPOUND_PATTERNS:
       matches = re.finditer(pattern, working_title)
       for match in matches:
           compound_word = match.group(0)
           if compound_word not in stop_words:
               title_nouns.append(compound_word)
   ```

2. **뉴스 제목 전처리**
   - 문제: 랭킹 숫자 제거 시 제목 내 숫자까지 제거되는 현상
   - 해결: BeautifulSoup의 decompose() 메서드로 순위 요소만 정확히 제거
   ```python
   rank_num = article.select_one('.list_ranking_num')
   if rank_num:
       rank_num.decompose()
   ```

3. **형태소 분석 성능**
   - 문제: 단일 형태소 분석기의 한계
   - 해결: Okt와 Mecab 조합 사용
   - Okt: 기본 형태소 분석
   - Mecab: 복합명사 처리

4. **키워드 중복 처리**
   - 문제: 연관 키워드 중복 집계
   - 해결: 키워드 그룹화 및 마스킹 처리
   ```python
   keyword_groups[main_keyword] = {existing, keyword}
   working_title = working_title.replace(match.group(0), '■' * len(match.group(0)))
   ```

5. **인명 추출 정확도**
   - 문제: "최상목"이 "최상" + "목"으로 잘못 분리되는 현상
   - 해결: 직책 패턴 및 조사 패턴 기반 인명 추출 로직 구현
   ```python
   NAME_PATTERNS = {
       'government': [r'([가-힣]{2,4})\s*(전|현)?\s*(차관|장관|대통령)'],
       'congress': [r'([가-힣]{2,4})\s*의원']
   }
   ```

#### **서비스 구현**
1. **요약 생성 시 토큰 제한 문제**
   - 문제: GPT API 호출 시 토큰 수 제한으로 긴 기사 요약 실패
   - 해결: 기사를 3개 단위로 배치 처리하여 요약 생성
   ```python
   def batch_summarize(articles, batch_size=3):
       summaries = []
       for i in range(0, len(articles), batch_size):
           batch = articles[i:i + batch_size]
           summary = generate_summary(batch)
           summaries.extend(summary)
       return summaries
   ```

2. **데이터 일관성 문제**
   - 문제: 캐시 키 불일치로 데이터 동기화 실패
   - 해결: 캐시 키 체계 통일 및 데이터 구조 표준화
   ```python
   CACHE_KEYS = {
       'news_data': 'news_data_{date}',
       'news_rankings': 'news_rankings_{date}',
       'keyword_rankings': 'keyword_rankings_{date}'
   }
   ```

3. **크롤링 안정성**
   - 문제: AWS 서버에서 Selenium 크롤링 실패
   - 해결: 헤드리스 브라우저 설정 및 의존성 패키지 설치
   ```python
   chrome_options = Options()
   chrome_options.add_argument('--headless')
   chrome_options.add_argument('--no-sandbox')
   chrome_options.add_argument('--disable-dev-shm-usage')
   ```

4. **성능 최적화**
   - 문제: 요약 생성 시 사용자 대기 시간 발생
   - 해결: DB와 캐시를 활용한 계층적 데이터 저장 구조 구현
   ```python
   def get_summary(article_id):
       # DB에서 30분 이내 요약 확인
       summary = Summary.objects.filter(
           article_id=article_id,
           created_at__gte=timezone.now() - timedelta(minutes=30)
       ).first()
       
       if summary:
           return summary.content
           
       # 캐시 확인
       cache_key = f'summary_{article_id}'
       cached_summary = cache.get(cache_key)
       
       if cached_summary:
           return cached_summary
           
       # 새로운 요약 생성
       new_summary = generate_new_summary(article_id)
       
       # DB와 캐시에 저장
       Summary.objects.create(article_id=article_id, content=new_summary)
       cache.set(cache_key, new_summary, timeout=1800)
       
       return new_summary
   ```

5. **배포 환경 설정**
   - 문제: 패키지 의존성 충돌로 인한 배포 실패
   - 해결: AWS Management Console을 통한 수동 배포 및 환경 설정
   ```bash
   # AWS 서버 초기 설정
   sudo apt-get update
   sudo apt-get install -y chromium-browser chromium-chromedriver
   
   # 가상환경 설정
   python -m venv venv
   source venv/bin/activate
   
   # 의존성 설치
   pip install -r requirements.txt
   ```

이러한 트러블슈팅을 통해:
1. 서비스의 안정성 향상
2. 사용자 경험 개선
3. 시스템 성능 최적화
4. 배포 프로세스 안정화

를 달성할 수 있었습니다.

## **5. 확장성 및 유지보수**
### **5.1 확장 가능한 부분**
- 뉴스 크롤링 대상 확대: 더 많은 신문방송사를 추가하여 관점을 확대함
- 평가 댓글 분석: 기사에 대한 반응을 비교하고 분석함 
- 개인화된 대시보드: 사용자 경험을 기록하고 추적하여 반대 급부의 기사를 추천함
- 공유 기능 추가: 분석이나 요약을 공유할 수 있도록 지원함
- 중요 키워드 사전: 핵심 키워드는 간단한 주석으로 이해를 도움

### **5.2 유지보수 고려사항**
- 정기적인 크롤링 시스템 점검 및 업데이트
- 모니터링(응답 시간, API 호출 횟수, 오류 발생 빈도 등)
- 사용자 피드백 수집 및 반영
- 시스템 성능 최적화(캐싱, 벡터 검색 최적화 등)
- 보안 강화(세션 타임아웃 구현, 입력값 검증 강화, 로그인 시도 제한 등)

## **6. 향후 개선 계획**
### **6.1 단기 목표**
- UI/UX 개선: 사용자 친화적인 인터페이스 제공
- 에러 처리 강화: 안정적인 서비스 제공을 위한 오류 처리 개선
- 사용자 피드백 시스템 구현: 사용자 의견을 수집하고 반영할 수 있는 시스템 구축

### **6.2 장기 목표**
- AI 모델 고도화: GPT-4 모델 적용 검토 및 분석 정확도 향상
- 실시간 협업 기능: 사용자 간의 실시간 협업 지원
- 모바일 최적화: 다양한 기기에서 최적의 사용자 경험 제공
- 데이터 분석 강화: 고급 통계 분석 및 시각화 도구 추가
- 시스템 안정성: 부하 분산 시스템 구축 및 모니터링 시스템 고도화
- 보안 강화: API 보안 강화 및 데이터 암호화
