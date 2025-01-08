"""
news/utils.py - 뉴스 키워드 추출 유틸리티

전체 프로세스:
1. 패턴 정의
2. 키워드 추출 (extract_keywords 함수)
   - 코엔(KoNLPy) 형태소 분석
   - 인용구 처리
   - 뉴스 구조 분석
   - 복합명사 추출
   - 일반 명사 추출
3. 결과 처리
"""

import logging
from konlpy.tag import Okt
from eunjeon import Mecab
from collections import Counter
import re
from django.conf import settings
from langchain_openai import OpenAI
from langchain import LLMChain
from langchain.prompts import PromptTemplate

# 로거 설정
logger = logging.getLogger('news')

# 전역 Okt 객체 - 형태소 분석에 사용
okt = Okt()
mecab = Mecab()

# 공통 패턴 상수
COMMON = {
    # 직위/직책
    'POSITIONS': '장관|의원|총리|대표|위원장|차관|대통령|청장|대행|처장|경찰청장|회장|부회장|이사|사장',
    
    # 조직/기관 - 중복 제거 ('협회|연합회' 제거)
    'ORGANIZATIONS': '정부|당국|당정|위원회|대통령실|경찰청|서울경찰청|공수처|의협|공단|공사|재단',
    
    # 기업 유형
    'COMPANY_TYPES': '전자|증권|금융|화학|건설|카드|보험|통신|그룹',
    
    # 정부기관 유형 - 중복 제거 ('협회|연합회|위원회' 제거)
    'GOV_TYPES': '청|처|원|부|회|실|공사|연구원',
    
    # 행동 동사 - 중복 제거 ('찬성|반대' 제거, POLITICAL_TERMS에 있음)
    'ACTIONS': '추진|검토|결정|지정|발표|하다|되다|드러내|포착|제기|압박|고려',
    
    # 조사
    'JOSA': '이|가|은|는|을|를|의|와|과|도|만',
    
    # 인명 수식어
    'NAME_PREFIX': '전|현|신임',
    
    # 수치 단위 추가
    'UNITS': '율|량|액|개|원|%|퍼센트|건|명|인',
    
    # 정치/법률 용어 강
    'POLITICAL_TERMS': '특검|탄핵|내란|법안|표결|발의|재발의|부결|찬성|반대|쌍특검|당론|정책',
    
    # 태/결과 추가
    'STATUS': '도피|설|논란|혐의|갈등|대립',
    
    # 복합어 처리용 접미사 - 중복 제거 ('특검' 제거, POLITICAL_TERMS에 있음)
    'SUFFIXES': '설|법|론|측|당|청',
    
    # 협회/협의회 관련 패턴 유지
    'ASSOCIATION_TYPES': '''
        # 직능단체
        의사|한의사|치과의사|약사|간호사|물리치료사|
        
        # 산업단체
        무역|상공|중소기업|벤처|
        
        # 전문단체
        회계사|변호사|세무사|노무사|
        
        # 교육단체
        교원|교수|
        
        # 노동단체
        노동|노조|
        
        # 기타 직능
        기자|예술인|작가|음악인
    '''.strip().replace('\n', ''),
    
    # 단체 접미사 유지
    'ASSOCIATION_SUFFIXES': '협회|협의회|연합회|총연합회|연맹'
}

# 2. 행동-결과 패턴
ACTION_RESULT_PATTERNS = [
    # 확인/점검/일반 행동 후 결과 (하나로 통합)
    fr'(?:확인|점검|일반|조사|관찰|검사|[가-힣]+)(?:{COMMON["ACTIONS"]})?\s*(?:니|니까)\s*([가-힣]+)[.…\u2026]*'
]

# 3. 조사 패턴 정의 (통합)
JOSA_PATTERNS = [
    r'(?<=[\가-힣])(으로|로|께|에게|한테|더러|보고|같이|처럼|만큼|보다|까지|부터)(?=\s|$)',
    fr'(?<=[\가-힣])({COMMON["JOSA"]})(?=\s|$)',
    r'(?<=[\가-힣])(씨|측|님|군|양)(?=\s|$)'  # 인명 관련 특수 접미사
]

# 4. 복합 단어 패턴 (직위/직책 통합)
COMPOUND_WORD_PATTERNS = [
    fr'[가-힣]+({COMMON["COMPANY_TYPES"]})',
    fr'[가-힣]+({COMMON["GOV_TYPES"]})(?=\s|$)',
    fr'[가-힣]+({COMMON["POSITIONS"]})(?=\s|$)',
    fr'[가-힣]+({COMMON["POLITICAL_TERMS"]})',
    fr'[가-힣]+({COMMON["STATUS"]})',
    fr'[가-힣]+({COMMON["SUFFIXES"]})',
    r'(?:전국(?:광역)?시도)?(?:{COMMON["ASSOCIATION_TYPES"]})(?:{COMMON["ASSOCIATION_SUFFIXES"]})(?:장|위원장)?'
]

# 5. 뉴스 구조 패턴
NEWS_STRUCTURE_PATTERNS = [
    fr'\[(속보|단독|긴급)\]\s*([가-힣]+).*?([가-힣]+(?:{COMMON["ACTIONS"]}))',
    fr'(?:{COMMON["ORGANIZATIONS"]}|[가-힣]{{2,4}}\s*(?:{COMMON["POSITIONS"]})).*?"([^"]+)"',
    fr'([가-힣]+)(?:{COMMON["JOSA"]})?\s*(?:{COMMON["ACTIONS"]}).*?([가-힣]+)',
    fr'([가-힣]+)[은는]\s*([가-힣]+[{COMMON["UNITS"]}])',
    fr'([가-힣]+)으로\s*([가-힣]+)',
    fr'([가-힣]+)(?:{COMMON["STATUS"]})\s*(?:{COMMON["ACTIONS"]})',
    fr'([가-힣]+)(?:{COMMON["POLITICAL_TERMS"]})\s*(?:{COMMON["ACTIONS"]})'
]

# 6. 인명 관련 패턴
NAME_PATTERNS = {
    'government': [
        fr'([가-힣]{{2,4}})\s*(?:{COMMON["NAME_PREFIX"]})?\s*(?:{COMMON["POSITIONS"]})',
    ],
    'congress': [
        fr'([가-힣]{{2,4}})\s*(?:{COMMON["NAME_PREFIX"]})?\s*의원',
    ]
}

def extract_keywords(titles, limit=10, keywords_per_title=2):
    """
    뉴스 제목들에서 키워드를 추출하는 메인 함수
    - 코엔(KoNLPy)으로 형태소 분석
    - 기존 패턴으로 구조적 특징 추출
    """
    all_nouns = []
    stop_words = {
        # 기존 불용어
        '속보', '단독', '종합', '갱신', '업데이트', '확인',
        
        # 뉴스 작성 관련
        '보도', '특보', '뉴스', '기자', '취재', '인터뷰', '기사',
        '발표', '발언', '주장', '설명', '강조', '지적',
        
        # 시간 관련
        '오늘', '내일', '어제', '현재', '이번', '최근',
        
        # 상태/정도
        '완료', '예정', '검토', '진행', '추진', '계획',
        '전망', '분석', '예상', '가능',
        
        # 일반적 수식
        '공식', '긴급', '특별', '일부', '관련',
        
        # 방향/추세
        '상승', '하락', '증가', '감소',
        
        # 조사가 붙은 단어들
        '대해서', '통해서', '위해서', '따라서', '대하여', '관하여',
        
        # 동작/상태 서술어 추가
        '포착', '발견', '찬성', '추정', '등장', '제기', '모의', '압박',
        '돌아왔', '해결', '섬기는', '폐기', '통제',

        # 일반 명사 추가
        '남성', '여성', '사람', '인물', '모습',
        
        # 변동/추세 관련 단어 추가
        '상승', '하락', '증가', '감소', '급등', '급락', '상향', '하향',
        '오름', '내림', '올라', '내려', '올랐', '내렸', '상승세', '하락세',
        '늘어', '줄어', '늘었', '줄었', '증감',
        
        # 수치 관련
        '퍼센트', '%', '포인트', 'p', 'P'
    }

    for title in titles:
        title_nouns = []
        working_title = title

        # 1. 대괄호 제거 및 공백 처리
        working_title = re.sub(r'\[[^]]*\]', ' ', working_title)
        logger.info(f"처리할 제목: {working_title}")

        # 2. Mecab으로 복합명사 우선 추출 (NEW!)
        mecab_nouns = mecab.nouns(working_title)
        for noun in mecab_nouns:
            if len(noun) >= 3 and noun not in stop_words:
                if any(suffix in noun for suffix in COMMON['ASSOCIATION_SUFFIXES']):
                    title_nouns.append(noun)
                    working_title = working_title.replace(noun, '■' * len(noun))

        # 3. 기존 패턴들 그대로 유지
        # 2. 인명 패턴 (NAME_PATTERNS)
        for pattern in NAME_PATTERNS['government']:
            matches = re.finditer(pattern, working_title)
            for match in matches:
                name = match.group(1)
                if name not in stop_words:
                    title_nouns.append(name)
                    working_title = working_title.replace(match.group(0), '■' * len(match.group(0)))
                    
        # 3. 접미사 패턴으로 인명 추출 (기존 코드 유지)
        words = working_title.split()
        for word in words:
            if 2 <= len(word) <= 4:  # 접미사 포함해서 최대 4글자
                match = re.search(fr'^([가-힣]{{2,3}})(?:{COMMON["JOSA"]})(?=\s|$)', word)
                if match:
                    name = match.group(1)  # 접미사 제외한 부분
                    if name not in stop_words:
                        title_nouns.append(name)
                        working_title = working_title.replace(word, '■' * len(word))
        
        # 4. 3글자 단어 처리 - 코엔 결과와 비교
        words = working_title.split()
        for word in words:
            if len(word) == 3 and re.match(r'^[가-힣]{3}$', word):
                pos = okt.pos(word, stem=False)
                if (len(pos) == 1 and pos[0][1] == 'Noun') or \
                   (len(pos) > 1 and pos[0][1] == 'Noun'):
                    title_nouns.append(word)
                    working_title = working_title.replace(word, '■' * len(word))

        # 5. 조사 제거
        for pattern in JOSA_PATTERNS:
            working_title = re.sub(pattern, '', working_title)

        # 나머지 패턴 처리 (ACTION_RESULT_PATTERNS, COMPOUND_WORD_PATTERNS, NEWS_STRUCTURE_PATTERNS)
        # 인용구 처리, NEWS_STRUCTURE_PATTERNS 전에 추가
        for pattern in ACTION_RESULT_PATTERNS:
            matches = re.finditer(pattern, working_title)
            for match in matches:
                result = match.group(1)
                if result not in stop_words:
                    title_nouns.append(result)
        
        # 2단계: NEWS_STRUCTURE_PATTERNS 매칭
        # - 뉴스 구조에서 중요 키워드 추출
        # - excluded_words에 있는 단어는 제외
        for pattern in NEWS_STRUCTURE_PATTERNS:
            matches = re.finditer(pattern, working_title)
            for match in matches:
                for group in match.groups():
                    if group and group not in stop_words and len(group) >= 2:
                        title_nouns.append(group)
        
        # 3단계: 복합명사 우선 추출
        for pattern in COMPOUND_WORD_PATTERNS:
            matches = re.finditer(pattern, working_title)
            for match in matches:
                compound_word = match.group(0)
                if compound_word not in stop_words and len(compound_word) >= 3:
                    title_nouns.append(compound_word)
                    working_title = working_title.replace(match.group(0), '■' * len(match.group(0)))
        
        # 4. 나머지 일반 명사 추출
        # - excluded_words와 stop_words에 없는 2글자 이상 명사만 추출
        okt_nouns = okt.nouns(working_title)
        mecab_nouns = mecab.nouns(working_title)  # 남은 명사들
        nouns = list(set(okt_nouns + mecab_nouns))  # 중복 제거
        nouns = [noun for noun in nouns 
                if noun not in stop_words 
                and len(noun) >= 2]
        title_nouns.extend(nouns)
        
        # 마지막으로 형태소 분석 실행
        morphs = okt.pos(working_title)
        base_nouns = []
        for word, pos in morphs:
            if pos.startswith('N'):  # 명사류 추출
                if len(word) >= 2 and word not in stop_words:
                    base_nouns.append(word)
        
        # 중복 제거
        title_nouns = list(set(title_nouns))
        
        # 빈도수 계산
        noun_counts = Counter(title_nouns)
        top_nouns = [word for word, _ in noun_counts.most_common(keywords_per_title)]
        all_nouns.extend(top_nouns)
        
        logger.info(f"최종 추출된 키워드: {title_nouns}")
    
    keyword_count = Counter(all_nouns)
    
    # 포함 관계 처리를 위한 변수 초기화
    final_keywords = []  # 최종 키워드 목록
    counts = {}         # 키워드별 빈도수 저장
    keyword_groups = {} # 연관 키워드 그룹 저장
    
    # 빈도수 높은 순으로 키워드 처리
    for keyword, count in keyword_count.most_common():
        if len(final_keywords) >= limit:
            break
            
        added = False
        # 기존 키워드와 포함 관계 확인
        for existing in final_keywords:
            # 키워드 간 포함 관계가 있는 경우
            if keyword in existing or existing in keyword:
                # 더 긴 키워드를 대표 키워드로 선택
                main_keyword = keyword if len(keyword) > len(existing) else existing
                # 빈도수 합산
                counts[main_keyword] = counts.get(main_keyword, 0) + count
                
                # 연관 키워드 그룹에 추가
                if main_keyword not in keyword_groups:
                    keyword_groups[main_keyword] = {existing, keyword}
                else:
                    keyword_groups[main_keyword].add(keyword)
                added = True
                break
        
        # 포함 관계가 없는 새로운 키워드인 경우
        if not added:
            final_keywords.append(keyword)
            counts[keyword] = count
            keyword_groups[keyword] = {keyword}
    
    # 합산된 빈도수 기준으로 정렬하여 반환
    sorted_keywords = sorted(final_keywords, key=lambda k: counts[k], reverse=True)
    return [(k, counts[k], keyword_groups[k]) for k in sorted_keywords[:limit]]

def process_keywords(keywords_list):
    """
    키워드 리스트를 전처리하고 중복을 제거하는 함수
    
    Args:
        keywords_list: 처리할 키워드 리스트
    
    Returns:
        list: 전처리된 고유한 키워드 리스트
    """
    # 키워드 전처리 및 중복 제거
    processed_keywords = []
    seen_words = set()  # 이미 처리된 단어 추적
    
    for keyword in keywords_list:
        keyword = keyword.strip()
        
        # 1. 이미 처리된 단어면 스킵
        if keyword in seen_words:
            continue
            
        # 2. 다른 키워드의 일부인지 확인
        is_part = any(
            other != keyword and (
                keyword in other or 
                other in keyword
            )
            for other in keywords_list
        )
        
        # 3. 일부가 아닌 경우만 추가
        if not is_part:
            processed_keywords.append(keyword)
            seen_words.add(keyword)
    
    return processed_keywords

def analyze_keywords_with_llm(keywords_with_counts, titles):
    """
    키워드와 제목들을 LLM으로 분석
    
    Args:
        keywords_with_counts: (키워드, 빈도수, 연관키워드) 튜플의 리스트
        titles: 분석할 뉴스 제목들
    
    Returns:
        str: LLM의 분석 결과
    """
    # 키워드 정보 제한 (상위 10개만)
    keyword_info = [f"{k}({c}회)" for k, c, _ in keywords_with_counts[:10]]
    
    # 제목 수 제한 (최근 20개만)
    limited_titles = titles[:20]
    
    template = """
    다음 뉴스 제목들과 상위 키워드들을 간단히 분석해주세요:

    [상위 키워드]
    {keywords}

    [최근 주요 제목]
    {titles}

    간단히 답변해주세요:
    1. 주요 트렌드:
    2. 키워드 연관성:
    3. 특이사항:
    """
    
    prompt = PromptTemplate(
        input_variables=["keywords", "titles"],
        template=template
    )
    
    llm = OpenAI(
        temperature=0.3,
        openai_api_key=settings.OPENAI_API_KEY,
        max_tokens=256  # 응답 길이 제한
    )
    
    # LLMChain을 사용하여 체인 생성
    chain = LLMChain(prompt=prompt, llm=llm)
    
    response = chain.run({
        "keywords": "\n".join(keyword_info),
        "titles": "\n".join(limited_titles)
    })
    
    return response 
