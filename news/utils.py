"""
news/utils.py - 뉴스 키워드 추출 유틸리티

주요 기능:
1. 한자 처리
2. 명사 추출 (OKT 활용)
3. 복합어 처리
4. 특수 패턴 처리 (정당명, 인명 등)
5. 키워드 빈도수 계산
6. 연관 키워드 그룹화

패턴 구조:
1. COMMON - 기본 패턴 상수
   - PERSON_RELATED: 직위/직책/인물 관련 (예: 장관, 총리, 스님)
   - ORGANIZATION_RELATED: 기관/단체 관련 (예: 정부, 위원회, 협회)
   - PLACE_RELATED: 시설/장소 관련 (예: 성당, 법원, 청사)
   - JOSA: 한국어 조사 및 어미 패턴

2. PARTY_NAMES - 정당명 집합
   - 주요 정당 (예: 국민의힘, 더불어민주당)
   - 진보/좌파 계열 (예: 정의당, 진보당)
   - 보수/우파 계열 (예: 국민통합연대, 한나라당)
   - 기타 정당 (예: 여성의당, 노인복지당)

4. COMPOUND_WORD_PATTERNS - 복합 단어 패턴
   - 기본 복합어 (COMMON 패턴 활용)
     * 기관/단체명 (예: 검찰청, 국정원)
     * 직책/직위명 (예: 검찰총장, 경찰청장)
     * 시설/장소명 (예: 서울청사, 중앙성당)
   - 특수 복합어 (뉴스 특화)
     * 법률/수사 관련 (예: 구속영장, 살인용의자)
     * 사건/사고 관련 (예: 이태원참사, 무안사고)
     * 공공기관/시설 (예: 형사기동대, 무안공항)
     * 단체/조직명 (예: 백골단, 1기동단, 구조단)

5. NAME_PATTERNS - 인명 패턴
   - 정부/공공 인사 (예: 홍길동 장관)
   - 혼합 이름 (예: John 김, 김 Smith)
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

def is_contains_hanja(text):
    """한자 포함 여부 체크"""
    return bool(re.search(r'[一-龥]', text))  # [\u4e00-\u9fff]와 동일

def remove_hanja_word(text):
    """한자가 포함된 단어는 제외"""
    return '' if is_contains_hanja(text) else text

# 1. 공통 패턴 상수 - 기본적인 패턴 매칭에 사용되는 정규식 패턴들
COMMON = {
    # 직위/직책/인물 관련 - 인물 식별 및 직책 매칭에 사용
    'PERSON_RELATED': (
        # 기본 직위
        '장|관|사|원|감|장관|차관|실장|국장|과장|부장|팀장|'
        # 고위 직책
        '총리|대통령|청장|처장|차장|위원장|원장|본부장|단장|센터장|'
        '총장|청장|의장|사장|회장|이사장|'
        # 기업 직책
        '대표|이사|부회장|상무|전무|감사|'
        # 군/경 계급
        '군|총경|경정|경감|경위|순경|대령|중령|소령|대위|중위|소위|'
        # 종교 직책
        '법사|스님|신부|목사|교무|전하|법왕|교주|대종사|종정|주교|대주교|추기경|교황|'
        # 인명 수식어
        '전|현|신임|역|정|신규|기존|임시|긴급'
    ),
    
    # 조직/기관/단체 - 기관명 및 단체명 식별에 사용
    'ORGANIZATION_RELATED': (
        # 기본 조직 단위
        '처|청|원|실|국|과|부|팀|'
        # 정부/공공기관
        '정부|당국|위원회|대통령실|경찰청|검찰청|법원|'
        '정보원|수사처|공수처|교육청|세무서|'
        # 회의 관련
        '회의|간담회|총회|대회|협의회|회담|'
        # 조직/부서
        '본부|센터|상황실|대책단|수사대|기동대|특공대|'
        '사령부|지검|고검|지청|출장소|'
        # 기업 조직
        '공사|공단|재단|연구원|연구소|'
        # 기업 유형
        '전자|증권|금융|화학|건설|카드|보험|통신|그룹|'
        # 협회/단체
        '협회|협의회|연합회|총연합회|연맹|조합|단체|'
    ),
    
    # 장소/시설 - 사건 발생 장소와 관련 시설 식별
    'PLACE_RELATED': (
        # 기본 시설
        '청사|관|원|교|실|당|소|'
        # 공공 시설
        '법원|국회|관공서|병원|학교|도서관|미술관|박물관|'
        '경찰서|소방서|우체국|보건소|주민센터|'
        # 종교 시설
        '사찰|법당|성당|교회|수도원|절|암자|교구|수녀원|수도회|선원|'
        # 교통/운송 시설
        '공항|항만|터미널|역사|정류장|'
        # 기타 시설
        '경기장|체육관|공원|광장|시장|상가|아파트'
    )
}

# 2. 정당명 집합 - 현재 활동 중이거나 역사적으로 중요한 정당들의 정확한 매칭
PARTY_NAMES = {
    # 주요 정당
    '국민의힘', '더불어민주당', '개혁신당', '조국혁신당',
    
    # 진보/좌파 계열
    '진보당', '기본소득당', '사회민주당', '정의당', 
    '노동당', '녹색당', '미래당', '민중민주당',
    
    # 민주당 계열
    '새미래민주당', '소나무당', '열린민주당', '대중민주당',
    
    # 보수/우파 계열
    '공화당', '국민통합연대', '내일로미래로', '대한국민당',
    '한국국민당', '국민대통합당', '기후민생당',
    '히시태그국민정책당', '국민연합', '새누리당',
    '우리공화당', '자유민주당', '한나라당',
    
    # 종교 계열
    '기독당', '기독대한당', '자유통일당',
    
    # 기타 정당
    '가가국민참여신당', '가락당', '국민주권당', 
    '대한민국당', '통일한국당', '한국독립당',
    '금융개혁당', '노인복지당', '대한상공인당',
    '여성의당', '한국농어민당', '한류연합당',
    '국가혁명당', '태건당', '한반도미래당', '홍익당',
    '가나반공정당코리아'
}

# 4. 복합 단어 패턴 - 전문용어 및 복합 키워드 추출
COMPOUND_WORD_PATTERNS = [
    # 기본 복합어 패턴 (COMMON 패턴 활용)
    fr'[가-힣]+(?:{COMMON["ORGANIZATION_RELATED"]})',  # 기관/단체명 (예: 검찰청, 국정원)
    fr'[가-힣]+(?:{COMMON["PERSON_RELATED"]})',       # 직책/직위명 (예: 검찰총장, 경찰청장)
    fr'[가-힣]+(?:{COMMON["PLACE_RELATED"]})',        # 시설/장소명 (예: 서울청사, 중앙성당)
    
    # 특수 복합어 패턴 (뉴스 특화)
    r'[가-힣]+(?:영장|고발|기소|구치소|교도소|용의자|피의자|범인)',  # 법률/수사 관련 (예: 구속영장, 살인용의자)
    r'[가-힣]+(?:참사|사고|재난|화재)',  # 사건/사고 관련 (예: 이태원참사, 무안사고)
    r'[가-힣]+(?:기동대|수사대|특공대|파출소|지구대|상황실|공항|항만|터미널)',  # 공공기관/시설 (예: 형사기동대, 무안공항)
    r'(?:\d+)?[가-힣]+단(?=\s|$)',  # 단체/조직명 (예: 백골단, 1기동단, 구조단)
    r'[가-힣]+량(?=\s|$)',
    r'[가-힣]+(?:기|항공기|여객기|전투기|헬기)(?=\s|$)',  # 사고기, 여객기, 전투기 등
]

# 5. 인명 패턴 - 다양한 형식의 인명 추출
NAME_PATTERNS = {
    'government': [
        fr'([가-힣]{{2,4}})\s*(?:{COMMON["PERSON_RELATED"]})',  # 홍길동 장관
    ],
    'mixed_name': [
        r'([A-Za-z]+)\s+([가-힣])(?=\s|$)',  # John 김
        r'([가-힣])\s+([A-Za-z]+)(?=\s|$)'   # 김 Smith
    ],
    'suffix_name': [
        r'^([가-힣]{2,3})(씨|군|양|님|측)(?=\s|$)'  # 인명 뒤 특수 접미사
    ]
}

stop_words = {
    # 1. 뉴스/미디어 관련
    '속보', '단독', '긴급', '종합', '업데이트', '확인', '보도', '특보', '뉴스', 
    '기자', '취재', '인터뷰', '기사', '논란', '파문', '사태', '의혹', '반복', '지속',
    '스캔들', '루머', '파장', '후폭풍', '여파', '후유증', '해명', '해프닝',
    '미스터리', '미궁', '논쟁', '공방', '대란', '대참사', '대재앙', '문제', '추정', '추측',
    'DM', '댓글', '멘션', '태그', '리트윗', '팔로우', '팔로잉', '좋아요', '구독',

    # 2. 행위/절차/상태 관련
    '발표', '발언', '주장', '지적', '발견', '등장', '제기', '자리', '위험',
    '모의', '압박', '해결', '폐기', '통제', '투입', '진화', '설득', '차단',
    '기대', '희망', '우려', '걱정', '예상', '전망', '완료', '예정', '진행',
    '분석', '판단', '만남', '생각', '추천', '권고', '지목', '신뢰', '혼란',
    '보장', '지원', '제공', '수행', '실시', '요구', '요청', '답변', '질문',
    '문의', '처리', '처분', '조치', '대응', '대처', '확정', '결정', '기록',
    '정지', '중단', '중지', '훈련', '인사', '무력', '집행', '저지', '협조', '지시',

    # 3. 시스템/관리 관련
    '추가', '삭제', '변경', '수정', '등록', '제거', '편집', '입력', '출력', 
    '저장', '확장', '축소', '이동', '복사', '시작', '개시', '착수', 
    '출발', '준비', '대기', '종료', '선정', '지정', '선발', '임명',
    '잘못', '성공', '실패', '성과', '실수', '착오',

    # 4. 상황/설명 관련
    '이유', '원인', '배경', '결과', '목적', '설명', '논리', '방법', '방식', 
    '과정', '상황', '경우', '계기', '중립', '보상', '책임', '책임자',
    '적합도', '명분', '격차', '필요', '필수', '기능', '이용', '사용',
    '사용자', '서버', '호출', '호환', '호환성', '충돌',

    # 5. 시간/수량/순서 관련
    '아침', '저녁', '매일', '매주', '매월', '매년', '밤', '새벽', '점심', 
    '낮', '올해', '작년', '내년', '이달', '당시', '과거', '신규', '이날',
    '마지막', '최종', '최후', '말기', '종반', '막바지', '종말', 
    '처음', '초기', '시초', '발단', 
    '중간', '도중', '중반', '중순',
    '이전', '이후', '순서', '순번', '차수', '회차', '단계',
    '기한', '기간', '시간', '시점', '시기',
    '이참', '이때', '이제', '이번', '저번', '요번', '요즘', '그날', '저날',

    # 6. 수치/통계 관련
    '공식', '일부', '관련', '상승', '하락', '증가', '감소', '급등', '급락', 
    '상향', '하향', '상승세', '하락세', '증감', '영하', '이하', '이상', 
    '미만', '초과', '최대', '최소', '최고', '최저', '최강', '최악', '최상', 
    '최첨단', '극대', '극소', '극한', '극강', '극미', '극소수', '극대수', 
    '절반', '다수', '소수', '대부분', '대다수', '전체', '전부', '일부분', 
    '수준', '정도', '가량',

    # 7. 법률/수사 관련
    '수사', '조사', '심사', '심의', '점검', '검토', '진술', '증언', '자백', '취조', 
    '심문', '조서', '소환', '체포', '구속', '압수', '수색', '혐의', '증거', '배상', 
    '소송', '고소', '고발', '기소', '구형', '재판', '판결',
    '흉기', '망치', '검열',
    # 집행 관련 추가
    '집행', '이행', '강제', '명령', '처분', '처벌', '제재', '단속', '규제', '통제',

    # 8. 의견/태도 관련
    '반대', '찬성', '찬반', '동의', '거부', '반발', '지지', '옹호', '비판', 
    '항의', '저항', '반론', '수용', '수락', '거절', '허락', '불응', '승인', 
    '부결', '찬동', '반박', '항변', '거짓', '거짓말', '침해', '합의', '철회', 
    '취소', '취급', '조언', '답변', '언급', '논평', '제안', '건의', '대답',
    '응답', '회신', '토론', '토의', '대화', '담화', '연설', '강연', '상담',

    # 9. 행정/지역 관련
    '시', '특별시', '광역시', '특별자치시', '특별자치도', '남도', '북도', '제주도', '도청', '시청', '군청', '구청',
    '쪽', '방향', '방면', '좌측', '우측', '양측', '왼쪽', '오른쪽', '윗쪽', '아랫쪽', '양쪽', '앞', '뒤', '위', '아래', '북', '남', '동', '서',

    # 10. 인물/주민 관련
    '인', '국인', '본인', '아인',
    '시민', '도민', '군민', '구민', '주민',

    # 11. 수량/단위/화폐
    '번째', '번', '차례', '회', '차', '개', '명', '건', '달', '해', '년', '월', '일', '시', '분', '초',
    '만원', '천만원', '억원', '조원', '천원', '백원', '십원', '원', '달러', '엔', '위안', '파운드', '유로',

    # 12. 시간/상태/정도 표현
    '오래', '계속', '항상', '늘', '자주', '이미', '아직', '벌써', '곧', '먼저', '나중',
    '오랫동안', '계속해서', '지속적', '영원히',
    '매우', '너무', '아주', '정말', '진짜', '워낙', '굉장히', '몹시', '무척', '엄청',
    '겨우', '간신히', '조금', '약간', '다소', '거의', '요새', '잇단', '직전', '가장',

    # 13. 문법 요소 (조사/어미/대명사)
    '이', '가', '은', '는', '을', '를', '의', '와', '과', '도', '만', '에', '으로', '로', '께', '에게', '한테', '더러', '보고', '같이', '처럼', '만큼', '보다', '까지', '부터',
    '라', '며', '고', '면', '야', '랑', '든', '서', '대해서', '통해서', '위해', '위해서', '따라', '따라서', '대해', '대하여', '관해', '관하여', '에게서', '마저', '조차',
    '에서', '으로서', '로서', '으로써', '로써', '이라고', '라고', '이라는', '라는', '이라며', '라며', '이라서', '라서',
    '에서의', '서의', '에서는', '서는', '에서도', '서도', '에서만', '서만',
    '이나', '나', '이야', '야', '이란', '란', '이든', '든', '이라', '라',
    '이라서', '라서', '이라도', '라도', '이라면', '라면',
    '으로써', '로써', '으로서', '로서', '으로도', '로도',
    '이라기에', '라기에', '이라기보다', '라기보다',
    '것', '듯', '때문', '때', '등', '들',  # 의존명사 추가

    # 14. 지시/대명사/부사
    '이런', '저런', '그런', '어떤', '무슨', '웬', '이러한', '저러한', '그러한',
    '이런저런', '어떠한', '이와같은', '그와같은',
    '이것', '저것', '그것', '무엇', '어디', '언제', '어떻게',
    '이곳', '저곳', '그곳', '어느곳',
    '이이', '저이', '그이', '누구',
    '스스로', '모두', '그냥', '결국',  # 부사 추가

    # 15. 동사/형용사 활용
    '하다', '하라', '하라고', '했다', '한다', '할', '하고', '해서', '하며', '하면', '하니', '하게', '하여', '했고', '했지만', '했는데',
    '되다', '되라', '돼라', '되라고', '돼라고', '됐다', '된다', '될', '되고', '되서', '되며', '되면', '되니', '되게', '되어', '돼서', '됐고', '됐지만', '됐는데',
    '받다', '받아라', '받으라고', '받은', '받을', '받고', '받아', '받게', '받아서', '받았다',
    '주다', '줘라', '주라고', '줬다', '준다', '줄', '주고', '줘서', '주며', '주면', '주니', '주게', '줬고', '줬지만', '줬는데', '주어지고', '지고',
    '였다', '여라', '였어서', '였다고', '였으면', '였지만', '였는데', '혔다',
    '어서', '다고', '으면', '지만', '는데',
    '구한', '찾은', '얻은', '만난', '낸', '된'
    '하는', '되는', '가는', '오는', '있는', '없는',
    '하게', '되게', '가게', '오게', '있게', '없게',
    '하지', '되지', '가지', '오지', '있지', '없지',
    '가라',  # 동사 활용 추가

    # 16. 종결어미
    '아요', '어요', '여요', '예요', '에요', '해요', '했어요', '하세요', '됐어요', '되요', '주세요', '세요',
    '차려요', '보세요', '드세요', '가요', '와요', '나요', '말아요', '봐요', '써요', '놓아요', '두어요',
    '습니다', '습니까', '합니다', '합니까',
    '네요', '군요', '는군요', '는데요', '더군요',

    # 17. 행정/업무 관련
    '신청', '통보', '접수', '등록', '신고', '제출', '발급', '승인', '허가',  # 추가: 행정 절차
    '취직', '퇴직', '입사', '퇴사', '이직', '전직', '복직',  # 추가: 취업 관련
    '추진', '진행', '착수', '시행', '실시', '수행', '이행',  # 추가: 업무 진행

    # 수량/단위 관련 추가
    '하나', '다섯', '여섯', '일곱', '여덟', '아홉',
    '첫째', '둘째', '셋째', '넷째', '다섯째',
    '일부', '전부', '부분', '일체', '전체',
    '몇몇', '여러', '많은', '적은', '수많은',
    '일도', '이도', '삼도', '사도',
    
    # 시간/즉시성 표현 추가
    '당장', '즉시', '곧바로', '바로', '지금', '현재',
    '방금', '금방', '이내', '순간', '잠시', '잠깐',
    '이따가', '조금', '나중', '이전', '이후',
    '오늘', '내일', '모레', '어제', '그제', '그저께',
    
    # 정도/상태 표현 추가
    '매우', '너무', '아주', '굉장히', '되게',
    '약간', '다소', '어느정도', '그다지',
    '전혀', '결코', '절대', '별로', '도저히'
}

def extract_keywords(titles, limit=10, keywords_per_title=5):
    okt = Okt()

    all_nouns = []
    for title in titles:
        title_nouns = []
        working_title = title
        
        # 1. 대괄호 제거 및 공백 처리
        working_title = re.sub(r'\[[^]]*\]', ' ', working_title)
        
        # 2. 한자가 포함된 단어 제외
        working_title = ' '.join(
            remove_hanja_word(word) for word in working_title.split()
        ).strip()
        
        logger.info(f"처리할 제목: {working_title}")

        # 3. OKT로 기본 명사 추출
        nouns = okt.nouns(working_title)
        
        # 4. 추출된 명사들을 우선순위별로 분류
        compound_nouns = []  # 복합어
        party_nouns = []     # 정당명
        name_nouns = []      # 인명
        other_nouns = []     # 기타 일반명사
        
        # 임시 저장소
        temp_nouns = []
        
        for noun in nouns:
            if len(noun) >= 2 and noun not in stop_words:
                temp_nouns.append(noun)
                
        # 각 패턴별로 분류
        for noun in temp_nouns:
            # 1순위: 복합어 패턴 체크
            is_compound = any(re.match(pattern, noun) for pattern in COMPOUND_WORD_PATTERNS)
            if is_compound:
                compound_nouns.append(noun)
                continue
                
            # 2순위: 정당 이름 체크
            if noun in PARTY_NAMES:
                party_nouns.append(noun)
                continue
                
            # 3순위: 인명 패턴 체크
            is_name = any(
                any(re.match(pattern, noun) for pattern in patterns)
                for patterns in NAME_PATTERNS.values()
            )
            if is_name:
                name_nouns.append(noun)
                continue
                
            # 4순위: 기타 일반명사
            other_nouns.append(noun)
        
        # 5. 우선순위 순서대로 title_nouns에 추가 (5개 이상일 때만)
        if len(compound_nouns) >= 5:
            title_nouns.extend(compound_nouns)
        else:
            other_nouns.extend(compound_nouns)
            
        if len(party_nouns) >= 5:
            title_nouns.extend(party_nouns)
        else:
            other_nouns.extend(party_nouns)
            
        if len(name_nouns) >= 5:
            title_nouns.extend(name_nouns)
        else:
            other_nouns.extend(name_nouns)
            
        title_nouns.extend(other_nouns)  # 나머지 일반명사 추가

        # 중복 제거 (순서 유지)
        title_nouns = list(dict.fromkeys(title_nouns))
        
        # 마스킹된 단어 필터링
        title_nouns = [re.sub(r'[\'\"…]+', '', noun) for noun in title_nouns]
        title_nouns = [noun for noun in title_nouns 
                      if not re.search(r'^[\'\"]*[■]+[.…]*[\'\"]?$', noun) and
                      not re.search(r'^[■]+[^가-힣a-zA-Z]+$', noun) and
                      not re.search(r'^[\'\"]?[■]+', noun) and
                      not re.search(r'[■]+[\'\"]?$', noun) and
                      not re.search(r'[^가-힣a-zA-Z]+[■]+[^가-힣a-zA-Z]+', noun) and
                      not re.search(r'.*[■]+.*', noun) and
                      not re.search(r'^[^가-힣a-zA-Z0-9]+$', noun) and
                      len(re.sub(r'[^가-힣a-zA-Z]', '', noun)) >= 2]

        # 제목당 키워드 제한
        title_nouns = title_nouns[:keywords_per_title]
        all_nouns.extend(title_nouns)
        
        logger.info(f"최종 추출된 키워드: {title_nouns}")

    # 빈도수 계산
    keyword_count = Counter(all_nouns)
    # 포함 관계 처리를 위한 변수 초기화
    final_keywords = []  # 최종 키워드 목록
    counts = {}         # 키워드별 빈도수 저장
    keyword_groups = {} # 연관 키워드 그룹 저장
    
    # 포함 관계 처리를 위한 변수 초기화 전에 동시 출현 빈도 계산 추가
    cooccurrence = {}
    for title in titles:
        title_keywords = set()
        for keyword, _ in keyword_count.most_common():
            if keyword in title:
                title_keywords.add(keyword)
        
        for k1 in title_keywords:
            if k1 not in cooccurrence:
                cooccurrence[k1] = {}
            for k2 in title_keywords:
                if k1 != k2:
                    cooccurrence[k1][k2] = cooccurrence[k1].get(k2, 0) + 1
    
    # 빈도수 높은 순으로 키워드 처리
    for keyword, count in keyword_count.most_common():
        if len(final_keywords) >= limit:
            break
            
        added = False
        for existing in final_keywords:
            # 여기에 동시 출현 빈도 체크 조건 추가
            if (keyword in existing or existing in keyword or
                (keyword in cooccurrence and 
                 existing in cooccurrence[keyword] and
                 cooccurrence[keyword][existing] >= min(keyword_count[keyword], keyword_count[existing]) * 0.8)):
                
                # 나머지 로직은 기존과 동일
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

def analyze_keywords_with_llm(keywords_with_counts, titles, max_tokens=150):
    """
    키워드와 제목들을 LLM으로 분석
    
    Args:
        keywords_with_counts: (키워드, 빈도수, 연관키워드) 튜플의 리스트
        titles: 분석할 뉴스 제목들
        max_tokens: 응답 토큰 제한
    """
    # 프롬프트 템플릿 분리
    ANALYSIS_TEMPLATE = """
    다음 뉴스 데이터를 분석해주세요:

    [키워드 빈도]
    {keyword_freq}

    [연관 키워드 그룹]
    {keyword_groups}

    [주요 제목]
    {titles}

    분석 요청:
    1. 핵심 트렌드 (1-2줄):
    2. 주요 키워드 간 연관성 (1-2줄):
    3. 예상되는 후속 이슈 (1줄):
    """

    try:
        # 키워드 정보 포맷팅
        keyword_freq = '\n'.join([f"- {k} ({c}회)" for k, c, _ in keywords_with_counts[:10]])
        
        # 연관 키워드 그룹 포맷팅
        keyword_groups = '\n'.join([
            f"- {k}: {', '.join(sorted(g))}" 
            for k, _, g in keywords_with_counts[:5]
        ])
        
        # 제목 포맷팅 (최근 10개)
        formatted_titles = '\n'.join([f"- {t}" for t in titles[:10]])
        
        # 프롬프트 생성
        prompt = PromptTemplate(
            template=ANALYSIS_TEMPLATE,
            input_variables=["keyword_freq", "keyword_groups", "titles"]
        )
        
        # LLM 체인 설정
        llm = OpenAI(
            temperature=0.3,
            max_tokens=max_tokens,
            model_name="gpt-3.5-turbo"
        )
        chain = LLMChain(llm=llm, prompt=prompt)
        
        # 분석 실행
        response = chain.run({
            "keyword_freq": keyword_freq,
            "keyword_groups": keyword_groups,
            "titles": formatted_titles
        })
        
        return response.strip()
        
    except Exception as e:
        logger.error(f"LLM 분석 중 오류 발생: {str(e)}")
        return "분석 중 오류가 발생했습니다." 
