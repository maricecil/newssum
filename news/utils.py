from konlpy.tag import Okt
from collections import Counter
import re
from django.conf import settings
from langchain_community.llms import OpenAI
from langchain.chains import LLMChain
from langchain.prompts import PromptTemplate

# 전역 Okt 객체
okt = Okt()

# 전역 Okt 객체 아래에 조사 패턴 정의 추가
JOSA_PATTERNS = [
    r'(?<=[\가-힣])(으로|로|께|에게|한테|더러|보고|같이|처럼|만큼|보다|까지|부터)(?=\s|$)',
    r'(?<=[\가-힣])(이|가|은|는|을|를|의|와|과|도|만|에|야|아|여)(?=\s|$)'
]

def extract_keywords(titles, limit=10, keywords_per_title=3):
    all_nouns = []
    stop_words = {
        # 기존
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
        
        # 조사가 붙은 단어들 추가
        '대해서', '통해서', '위해서', '따라서', '대하여', '관하여'
    }
    
    # 인명 뒤에 자주 나오는 접미사 패턴
    NAME_SUFFIXES = [
        r'[이가](?=\s|$)',  # 주격 조사
        r'[은는](?=\s|$)',  # 주제 조사
        r'[을를](?=\s|$)',  # 목적격 조사
        r'의(?=\s|$)',      # 소유격 조사
        r'에게(?=\s|$)',    # 여격 조사
        r'[과와](?=\s|$)',  # 공동격 조사
        r'도(?=\s|$)',      # 포함 조사
        r'만(?=\s|$)',      # 한정 조사
        r'씨(?=\s|$)',      # 호칭
        r'측(?=\s|$)'       # 관련 집단
    ]
    NAME_SUFFIX_PATTERN = '(' + '|'.join(NAME_SUFFIXES) + ')'
    
    for title in titles:
        title_nouns = []
        working_title = title
        
        # 조사 제거 전처리 추가 (기존 대괄호 제거 전)
        for pattern in JOSA_PATTERNS:
            working_title = re.sub(pattern, '', working_title)
        
        # 1. 대괄호 제거 및 공백 처리 (기존 코드)
        working_title = re.sub(r'\[[^]]*\]', ' ', working_title)
        
        # 2. 직책이 있는 인명 추출
        for pattern in NAME_PATTERNS['government']:
            matches = re.finditer(pattern, working_title)
            for match in matches:
                name = match.group(1)
                if name not in stop_words:
                    title_nouns.append(name)
                    working_title = working_title.replace(match.group(0), '■' * len(match.group(0)))
        
        # 3. 접미사 패턴으로 인명 추출
        words = working_title.split()
        for word in words:
            # 2-3글자 + 접미사 패턴
            if 2 <= len(word) <= 4:  # 접미사 포함해서 최대 4글자
                match = re.search(f'^([가-힣]{2,3}){NAME_SUFFIX_PATTERN}', word)
                if match:
                    name = match.group(1)  # 접미사 제외한 부분
                    if name not in stop_words:
                        title_nouns.append(name)
                        working_title = working_title.replace(word, '■' * len(word))
        
        # 3글자 단어 처리 수정
        words = working_title.split()
        for word in words:
            if len(word) == 3 and re.match(r'^[가-힣]{3}$', word):
                pos = okt.pos(word, stem=False)
                # 하나의 명사로 인식되거나
                # 분리되어도 앞부분이 명사인 경우만 추가
                if (len(pos) == 1 and pos[0][1] == 'Noun') or \
                   (len(pos) > 1 and pos[0][1] == 'Noun'):
                    title_nouns.append(word)
                    working_title = working_title.replace(word, '■' * len(word))
        
        # 4. 나머지 일반 명사 추출
        nouns = okt.nouns(working_title)
        nouns = [noun for noun in nouns if len(noun) >= 2 and noun not in stop_words]
        title_nouns.extend(nouns)
        
        # 빈도수 계산
        noun_counts = Counter(title_nouns)
        top_nouns = [word for word, _ in noun_counts.most_common(keywords_per_title)]
        all_nouns.extend(top_nouns)
    
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

NAME_PATTERNS = {
    'government': [
        r'([가-힣]{2,4})\s*(전|현|신임)?\s*(차관|장관|대통령|청장|위원장|대행|처장)',
        # 직책 패턴 통합: 전/현/신임 수식어 + 모든 직책
    ],
    'congress': [
        r'([가-힣]{2,4})\s*(전|현)?\s*의원',  # 전/현 의원 포함
    ],
    'quotes': [
        r'["""]([가-힣]{2,4})[이가은는을를의]?[\s,]',  # 인용구 시작
        r'([가-힣]{2,4})[이가은는을를의]?\s*["""]',    # 인용구 끝
        r'["""][^"""]+["""]\s*([가-힣]{2,4})[이가은는을를의]?\s*["""]'  # 인용구 사이
    ],
    'context': [
        r'([가-힣]{2,4})[이가은는을를의](?=\s|$)',  # 조사
        r'(전|현|신임)\s*([가-힣]{2,4})',           # 수식어
        r'([가-힣]{2,4})\s*(씨|측)(?=\s|$)'        # 호칭
    ]
} 

def analyze_keywords_with_llm(keywords_with_counts, titles):
    """
    키워드와 제목들을 LLM으로 분석
    """
    # 키워드와 빈도수 정보 포맷팅
    keyword_info = [f"{k}({c}회)" for k, c, _ in keywords_with_counts]
    
    template = """
    다음 뉴스 제목들과 추출된 키워드들을 분석해주세요:

    [키워드 (빈도수)]
    {keywords}

    [뉴스 제목들]
    {titles}

    다음 형식으로 간단히 답변해주세요:
    1. 주요 트렌드:
    2. 키워드 간 연관성:
    3. 특이사항:
    """
    
    prompt = PromptTemplate(
        input_variables=["keywords", "titles"],
        template=template
    )
    
    llm = OpenAI(
        temperature=0.3,
        openai_api_key=settings.OPENAI_API_KEY
    )
    chain = LLMChain(llm=llm, prompt=prompt)
    
    response = chain.run({
        "keywords": "\n".join(keyword_info),
        "titles": "\n".join(titles)
    })
    
    return response 