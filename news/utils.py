from konlpy.tag import Okt
from collections import Counter
import re

# 전역 Okt 객체
okt = Okt()

def extract_keywords(titles, limit=10, keywords_per_title=3):
    all_nouns = []
    stop_words = {'속보', '단독', '종합', '갱신', '업데이트'}
    
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
        
        # 1. 대괄호 제거 및 공백 처리
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
        
        # 3글자 단어 처리 로직 추가
        words = working_title.split()
        for word in words:
            if len(word) == 3 and re.match(r'^[가-힣]{3}$', word):
                pos = okt.pos(word)
                if len(pos) > 1:  # 형태소 분석 결과가 2개 이상이면
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
    for keyword in keywords_list:
        keyword = keyword.strip()
        # 완전히 동일한 단어만 중복으로 처리
        if keyword not in processed_keywords:  # 부분 문자열 체크 대신 완전 일치만 확인
            processed_keywords.append(keyword)
    
    return processed_keywords 

NAME_PATTERNS = {
    'government': [
        r'([가-힣]{2,4})\s*(전|현)?\s*(차관|장관|대통령)',  # 대통령 추가
        # "최상목 전 차관"
        # "김현수 현 장관"
        # "윤석열 대통령"    # 새로 추가된 패턴
        # "박순철 차관"      # '전/현' 없이도 매칭
    ],
    'congress': [
        r'([가-힣]{2,4})\s*의원',
    ],
    'organization': [
        r'([가-힣]{2,4})\s*(청장|위원장)',
    ]
} 