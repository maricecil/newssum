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
    # 직위/직책 - '의원' 제거 (NAME_PATTERNS에서 별도 처리)
    'POSITIONS': '장관|총리|대표|위원장|차관|대통령|청장|대행|처장|경찰청장|회장|부회장|이사|사장|대령|처장|교주',
    
    # 조직/기관 
    'ORGANIZATIONS': '정부|당국|당정|위원회|대통령실|경찰청|서울경찰청|공수처|의협|공단|공사|재단',
    
    # 기업 유형
    'COMPANY_TYPES': '전자|증권|금융|화학|건설|카드|보험|통신|그룹',
    
    # 정부기관 유형 - 중복 제거 ('협회|연합회|위원회' 제거)
    'GOV_TYPES': '청|처|원|부|회|실|공사|연구원',
    
    # 행동 동사 - 중복 제거 ('찬성|반대' 제거, POLITICAL_TERMS에 있음)
    'ACTIONS': '추진|검토|결정|지정|하다|되다|드러내|고려',
    
    # 조사 확장
    'JOSA': ('이|가|은|는|을|를|의|와|과|도|만|에|으로|로|께|에게|한테|더러|보고|같이|처럼|만큼|보다|까지|부터|'
             '라|며|고|면|야|랑|든|서|대해서|통해서|위해서|따라서|대하여|관하여|에게서|마저|조차|'
             '에서|으로서|로서|으로써|로써|이라고|라고|이라는|라는|이라며|라며|이라서|라서'),
    
    # 인명 수식어
    'NAME_PREFIX': '전|현|신임|역|정|신규|기존|임시|긴급',
    
    # 수치 단위 추가
    'UNITS': '량|액|개|원|%|퍼센트|건|명|인',
    
    # 정치/법률 용어
    'POLITICAL_TERMS': '특검|탄핵|내란|법안|표결|발의|재발의|부결|찬성|반대|쌍특검|당론|정책',
    
    # 태/결과 추가
    'STATUS': '도피|설|논란|혐의|갈등|대립|귀성|귀경',
    
    # 복합어 처리용 접미사 - 중복 제거 ('특검' 제거, POLITICAL_TERMS에 있음)
    'SUFFIXES': '설|법|론|측|당|청|용|편|특별',
    
    # 협회/협의회 관련 패턴
    'ASSOCIATION_TYPES': '의사|한의사|치과의사|약사|간호사|물리치료사|무역|상공|중소기업|벤처|회계사|변호사|세무사|노무사|교원|교수|노동|노조|기자|예술인|작가|음악인',
    
    # 단체 접미사
    'ASSOCIATION_SUFFIXES': '협회|협의회|연합회|총연합회|연맹'
}

# 정당명 상수 추가
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

# 2. 행동-결과 패턴
ACTION_RESULT_PATTERNS = [
    # 확인/점검/일반 행동 후 결과 (하나로 통합)
    fr'(?:확인|점검|일반|조사|관찰|검사|[가-힣]+)(?:{COMMON["ACTIONS"]})?\s*(?:니|니까)\s*([가-힣]+)[.…\u2026]*'
]

# 3. 조사 패턴 정의
JOSA_PATTERNS = [
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
    r'\d+[가-힣]+단',
    r'(?:전국(?:광역)?시도)?(?:{COMMON["ASSOCIATION_TYPES"]})(?:{COMMON["ASSOCIATION_SUFFIXES"]})(?:장|위원장)?',
    
    # 1. 법률/사법 관련
    r'[가-힣]+(?:영장|고발|기소)',          # 구속영장, 체포영장, 형사고발
    r'[가-힣]+(?:구치소|교도소)',           # 서울구치소, 안양교도소
    r'[가-힣]+(?:용의자|피의자|범인)',      # 살인용의자, 방화피의자
    
    # 2. 제도/동향 관련
    r'[가-힣]+(?:제도|대책)',              # 연금제도, 민생대책
    r'[가-힣]+동향',                      # 민심동향, 시장동향
    
    # 3. 경제/산업 관련
    r'[가-힣]+(?:물가|임금|수당)',         # 소비자물가, 최저임금
    r'[가-힣]+(?:대출|금리|예금)',         # 주택대출, 기준금리
    r'[가-힣]+(?:주가|증시|환율)',         # 종합주가, 코스피증시
    r'[가-힣]+(?:단지|아파트)',           # 산업단지, 재건축아파트
    
    # 4. 지역+시설/사건 패턴
    r'[가-힣]+(?:공항|항만|터미널)',       # 무안공항, 인천공항, 부산항만
    r'[가-힣]+(?:참사|사고|재난|화재)',    # 무안참사, 이태원참사
    
    # 5. 조직/부서 패턴
    r'[가-힣]+(?:기동대|수사대|특공대)',   # 형사기동대, 광역수사대
    r'[가-힣]+(?:파출소|지구대|상황실)',    # 종로파출소, 남대문지구대
    
    # 6. 문서/기록 관련
    r'[가-힣]+(?:편지|성명서|보도자료|입장문)',  # 옥중편지, 공개편지
    
    # 7. 조사/분석 관련 패턴
    r'[가-힣]+(?:조사|설문|통계|분석)',  # 여론조사, 실태조사, 설문조사
    r'[가-힣]+(?:지지율|순위|점수|등급)',  # 대통령지지율, 정당지지율
]

# 5. 뉴스 구조 패턴
NEWS_STRUCTURE_PATTERNS = [
    fr'\[(속보|단독|긴급)\]\s*([가-힣]+).*?([가-힣]+(?:{COMMON["ACTIONS"]}))',
    fr'(?:{COMMON["ORGANIZATIONS"]}|[가-힣]{{2,4}}\s*(?:{COMMON["POSITIONS"]})).*?"([^"]+)"',
    fr'([가-힣]+)(?:{COMMON["JOSA"]})?\s*(?:{COMMON["ACTIONS"]}).*?([가-힣]+)',
    fr'([가-힣]+)[은는]\s*([가-힣]+[{COMMON["UNITS"]}])',
    fr'([가-힣]+)으로\s*([가-힣]+)',
    fr'([가-힣]+)(?:{COMMON["STATUS"]})\s*(?:{COMMON["ACTIONS"]})',
    fr'([가-힣]+)(?:{COMMON["POLITICAL_TERMS"]})\s*(?:{COMMON["ACTIONS"]})',
    fr'(?:{COMMON["ORGANIZATIONS"]})[이가]?\s*(?:[,.]|$)',  # 기관명으로 시작하는 경우
    fr'(?:{COMMON["ORGANIZATIONS"]})\s*(?:{COMMON["ACTIONS"]})',  # 기관명+행동
    fr'(?:{COMMON["ORGANIZATIONS"]}|[가-힣]{{2,4}}\s*(?:{COMMON["POSITIONS"]})).*?["\']([^"\']+)["\']',
]

# 6. 인명 관련 패턴
NAME_PATTERNS = {
    'government': [
        fr'([가-힣]{{2,4}})\s*(?:{COMMON["NAME_PREFIX"]})?\s*(?:{COMMON["POSITIONS"]})',
    ],
    'congress': [
        fr'([가-힣]{{2,4}})\s*(?:{COMMON["NAME_PREFIX"]})?\s*의원',
    ],
    'mixed_name': [
        # 영문이름 + 한글성 패턴
        r'([A-Za-z]+)\s+([가-힣])(?=\s|$)',  # 예: "젠슨 황"
        
        # 한글성 + 영문이름 패턴도 추가
        r'([가-힣])\s+([A-Za-z]+)(?=\s|$)',  # 예: "황 젠슨"
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
        # 뉴스 작성/형식 관련
        '속보', '단독', '종합', '업데이트', '확인',
        '보도', '특보', '뉴스', '기자', '취재', '인터뷰', '기사',
        
        # 뉴스 형식적 표현/톤
        '논란', '파문', '사태', '의혹', '스캔들', '루머',  # 이슈/의혹 관련
        '파장', '후폭풍', '여파', '후유증',  # 영향/결과 관련
        '해명', '반박', '항변', '해프닝',  # 대응/해명 관련
        '미스터리', '미궁', '논쟁', '공방',  # 상황/전개 관련
        '파격', '충격', '경악', '충격적',  # 감정/반응 관련 (여기만 유지)
        '대혼란', '대란', '대참사', '대재앙',  # 과장/강조 관련
        '초유', '유례없는', '전무후무', '사상최초',  # 특이성 강조
        
        # 동작/상태/입장 표현
        '발표', '발언', '주장', '강조', '지적',
        '포착', '발견', '등장', '제기', '모의', '압박',
        '돌아왔', '해결', '섬기는', '폐기', '통제',
        '나선', '나섰', '나서',
        '추월', '넘어서', '넘어감', '투입',
        '진화', '설득', '차단', '조사',
        '동의', '반발', '항의', '저항', '승인', '기권',
        '기대', '희망', '우려', '걱정', '예상', '전망',
        '완료', '예정', '진행',
        '분석', '가능', '만나', '만남',
        '느끼다', '생각하다', '판단', '생각', '검토',
        '추천', '권고', '지목',
        '믿다', '의심', '확신', '신뢰',
        '좋아', '싫어', '미워', '사랑',
        '놀라다', '당황', '혼란',
        '추가', '삭제', '변경', '수정',     
        '등록', '제거', '편집',             
        '입력', '출력', '저장', '불러오기', 
        '확장', '축소', '이동', '복사',     
        '시작', '개시', '착수', '출발',     
        '준비', '대기', '마무리', '종료',   
        '선정', '지정', '선발', '임명',     
        '잘못', '잘', '못', '잘하다', '잘되다',
        '제대로', '올바로', '바르게', '정확히',
        '틀리다', '틀린', '그르다', '그른',
        '성공', '실패', '성과', '실수', '착오',
        '옳다', '그르다', '맞다', '틀리다',
        '훌륭히', '완벽히', '부족히',  # '미흡히' 제거
        '뛰어난', '뒤떨어진', '앞선', '뒤처진',
        # 설명/논리/상황/방식 관련 단어 (통합)
        '이유', '원인', '배경', '결과', '목적', '설명', '논리',
        '방법', '방식', '과정', '상황', '경우',
        
        # 시간/상태/수식어
        '오늘', '내일', '어제', '현재', '이번', '최근',
        '아침', '저녁', '밤', '새벽', '점심', '낮',
        '올해', '작년', '내년', '올', '이달', '지난',
        '공식', '긴급', '특별', '일부', '관련',
        '상승', '하락', '증가', '감소', '급등', '급락', '상향', '하향',
        '오름', '내림', '올라', '내려', '올랐', '내렸', '상승세', '하락세',
        '늘어', '줄어', '늘었', '줄었', '증감',
        '영하', '이하', '이상', '미만', '초과', '이전',
        '최대', '최소', '최고', '최저', '최강', '최악', '최상', '최첨단',
        '극대', '극소', '극한', '극심', '극강', '극미', '극소수', '극대수',
        '절반', '다수', '소수', '대부분', '대다수',
        '전체', '전부', '일부분',
        '수준', '정도', '가량',
        '매우', '너무', '아주', '가장', '정말', '진짜',
        '상당', '다소', '약', '약간', '조금', '거의',
        '완전', '절대', '전혀',

        # 부사어/접속어 (NEW)
        '다시', '또', '이제', '아직', '벌써', '이미', '먼저', '나중', '드디어',
        '계속', '자주', '항상', '때때로', '가끔', '종종',
        '방금', '곧', '즉시', '바로', '우선', '결국', '마침내',
        '그리고', '또한', '그러나', '하지만', '그래서', '따라서', '그러므로',
        '그런데', '그러면', '그래도', '그리하여', '그러니까', '왜냐하면',
        
        # 지시/대명사 (NEW)
        '이것', '저것', '그것', '여기', '저기', '거기', '이런', '저런', '그런',
        '이렇게', '저렇게', '그렇게', '이와', '그와', '저와',
        
        # 보조용언/조동사 (NEW)
        '있다', '없다', '하다', '되다', '보다', '주다', '받다', '가다', '오다',
        '싶다', '말다', '버리다', '두다', '놓다', '드리다', '이다', '아니다', '같다',

        # 새로운 상태/추상 단어 추가
        '적합도', '명분', '압도', '격차', '근접',  
        '급등세', '급락세', '상승폭', '하락폭',
        '호전', '악화', '개선', '퇴보',
        '유리', '불리', '양호', '미흡' 
        '강세', '약세', '우세', '열세',
        '필요', '필수', '불필요', '기능','중요',

        # 일반 명사/분야
        '남성', '여성', '사람', '인물', '모습',
        '정치', '경제', '사회', '문화', '국민' 
        '체감', '개발', '속도', '온도', '시장'
    }

    for title in titles:
        title_nouns = []
        working_title = title

        # 1. 대괄호 제거 및 공백 처리
        working_title = re.sub(r'\[[^]]*\]', ' ', working_title)
        logger.info(f"처리할 제목: {working_title}")

        # [NEW] 복합어 패턴 먼저 처리
        for pattern in COMPOUND_WORD_PATTERNS:
            matches = re.finditer(pattern, working_title)
            for match in matches:
                compound_word = match.group(0)
                if compound_word not in stop_words and len(compound_word) >= 3:
                    title_nouns.append(compound_word)
                    working_title = working_title.replace(compound_word, '■' * len(compound_word))

        # [추가] Mecab pos 태그로 고유명사 우선 처리
        for word, pos in mecab.pos(working_title):
            if pos == 'NNP' and len(word) >= 2:  # 고유명사
                # 관형어와 stop_words 동시 체크
                is_modifier = any(
                    re.match(fr'^(?:{COMMON[pattern]}).*$', word)
                    for pattern in ['NAME_PREFIX', 'SUFFIXES']  # STATUS 제거
                ) or word in COMMON['STATUS'].split('|')  # STATUS는 완전일치 검사
                
                if not is_modifier and word not in stop_words:
                    title_nouns.append(word)
                    working_title = working_title.replace(word, '■' * len(word))

        # 2. 기존 Mecab 복합명사 처리 유지
        mecab_nouns = mecab.nouns(working_title)
        for noun in mecab_nouns:
            # 정당명 보존
            if noun in PARTY_NAMES:
                title_nouns.append(noun)
                working_title = working_title.replace(noun, '■' * len(noun))
                continue
            
            # 자주 등장하는 단어 체크 (기존 로직)
            if sum(noun in title for title in titles) >= 2:
                if noun not in stop_words and len(noun) >= 2:
                    title_nouns.append(noun)
                    working_title = working_title.replace(noun, '■' * len(noun))
        
        # 기존 복합명사 처리 로직 유지
        compound_word = ''
        for word, pos in mecab.pos(working_title):
            if pos.startswith('NN'):  # 명사류
                # 6자 이상인 경우 분리 시도
                if len(compound_word + word) >= 6:
                    parts = mecab.nouns(compound_word + word)
                    # 분리된 각 부분이 2자 이상인 경우만 채택
                    valid_parts = [p for p in parts if len(p) >= 2 and p not in stop_words]
                    if valid_parts:
                        title_nouns.extend(valid_parts)
                        working_title = working_title.replace(compound_word + word, '■' * len(compound_word + word))
                        compound_word = ''
                        continue
                compound_word += word
            else:
                if compound_word and len(compound_word) >= 2:
                    if compound_word not in stop_words:
                        title_nouns.append(compound_word)
                    working_title = working_title.replace(compound_word, '■' * len(compound_word))
                compound_word = ''
                
        # 마지막 복합명사 처리
        if compound_word and len(compound_word) >= 2 and compound_word not in stop_words:
            title_nouns.append(compound_word)
            working_title = working_title.replace(compound_word, '■' * len(compound_word))

        # 3. 기존 패턴들 그대로 유지
        # 2. 인명 패턴 (NAME_PATTERNS)
        for pattern_type in ['government', 'congress', 'mixed_name']:  # mixed_name 추가
            for pattern in NAME_PATTERNS[pattern_type]:
                matches = re.finditer(pattern, working_title)
                for match in matches:
                    # mixed_name의 경우 groups()가 2개를 반환하므로 처리 방식 변경
                    if pattern_type == 'mixed_name':
                        name = ' '.join(match.groups())  # 예: "젠슨 황"
                    else:
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
            # 명사(N)만 추출, 동사(V)/형용사(A) 제외
            if pos.startswith('N'):  # Noun
                if len(word) >= 2 and word not in stop_words:
                    base_nouns.append(word)
            elif pos.startswith('V') or pos.startswith('A'):  # Verb or Adjective
                stop_words.add(word)  # 동적으로 stop_words에 추가
        
        # 중복 제거
        title_nouns = list(set(title_nouns))
        
        # 빈도수 계산
        all_nouns.extend(title_nouns)  # 바로 all_nouns에 추가
        
        logger.info(f"최종 추출된 키워드: {title_nouns}")
    
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
