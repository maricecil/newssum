"""
news/utils.py - 뉴스 키워드 추출 유틸리티

패턴 구조:
1. COMMON - 공통 패턴 상수
   - PERSON_RELATED: 직위/직책/인물 관련
   - ORGANIZATION_RELATED: 조직/기관/단체 관련
   - ACTION_STATUS: 행동/상태/결과 관련
   - PLACE_RELATED: 장소/시설 관련
   - JOSA: 조사 패턴
   - UNITS: 단위 관련

2. PARTY_NAMES - 정당명 집합
   - 주요 정당
   - 진보/좌파 계열
   - 민주당 계열
   - 보수/우파 계열
   - 종교 계열
   - 기타 정당

3. ACTION_RESULT_PATTERNS - 행동-결과 패턴
   - 확인/점검/일반 행동 후 결과

4. JOSA_PATTERNS - 조사 패턴
   - 일반 조사
   - 인명 관련 특수 접미사

5. COMPOUND_WORD_PATTERNS - 복합 단어 패턴
   - 법률/사법 관련
   - 제도/동향 관련
   - 경제/산업 관련
   - 지역+시설/사건
   - 조직/부서
   - 문서/기록 관련
   - 조사/분석 관련
   - 종교 관련

6. NEWS_STRUCTURE_PATTERNS - 뉴스 구조 패턴
   - 속보/단독/긴급 형식
   - 인용구 형식
   - 주체-행동-결과 형식
   - 기관명 관련 형식

7. NAME_PATTERNS - 인명 관련 패턴
   - 정부/공공 인명
   - 혼합 이름 (한글+영문)
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

# 1. 공통 패턴 상수 - 기본적인 패턴 매칭에 사용되는 정규식 패턴들
COMMON = {
    # 직위/직책/인물 관련 통합 - 인물 식별 및 직책 매칭에 사용
    'PERSON_RELATED': (
        # 정부/공공/기업 직책
        '장관|총리|대표|위원장|차관|대통령|청장|대행|처장|경찰청장|회장|부회장|이사|사장|대령'
        # 종교 직책 통합
        '|법사|스님|신부|목사|교무|전하|법왕|교주|대종사|종정|주교|대주교|추기경|교황'
        # 인명 수식어
        '|전|현|신임|역|정|신규|기존|임시|긴급'
        # 의원 추가
        '|의원'
    ),
    
    # 조직/기관/단체 통합 - 기관명 및 단체명 식별에 사용
    'ORGANIZATION_RELATED': (
        # 정부/공공기관
        '정부|당국|당정|위원회|대통령실|경찰청|공수처|의협|공단|공사|재단'
        # 기관 유형
        '|청|처|원|부|회|실|연구원'
        # 기업 유형
        '|전자|증권|금융|화학|건설|카드|보험|통신|그룹'
        # 협회/단체
        '|협회|협의회|연합회|총연합회|연맹'
    ),
    
    # 행동/상태/결과 통합 - 뉴스 내용의 인과관계 분석에 사용
    # 특정 행동 후의 결과를 추출하기 위한 패턴
    'ACTION_STATUS': (
        # 행동
        '추진|검토|결정|지정|드러내|고려'
        # 상태
        '|도피|혐의|갈등|대립|귀성|귀경'
        # 정치 행동
        '|특검|탄핵|내란|법안|표결|발의|재발의|부결|찬성|반대|쌍특검|당론|정책'
    ),
    
    # 장소/시설 통합 - 사건 발생 장소와 관련 시설 식별
    'PLACE_RELATED': (
        # 종교 시설
        '사찰|법당|성당|교회|수도원|절|암자|교구|수녀원|수도회|선원'
        # 기타 주요 시설
        '|청사|법원|국회|관공서|병원|학교'
    ),
    
    # 조사 패턴 - 한국어 문법 분석을 위한 조사 패턴
    'JOSA': ('이|가|은|는|을|를|의|와|과|도|만|에|으로|로|께|에게|한테|더러|보고|같이|처럼|만큼|보다|까지|부터|'
             '라|며|고|면|야|랑|든|서|대해서|통해서|위해서|따라서|대하여|관하여|에게서|마저|조차|'
             '에서|으로서|로서|으로써|로써|이라고|라고|이라는|라는|이라며|라며|이라서|라서|'
             # 동사/형용사 활용형 추가
             '하다|했다|한다|할|하고|하며|하면|하니|하게|하여|해서|했고|했지만|했는데|'
             '되다|됐다|된다|될|되고|되며|되면|되니|되게|되어|돼서|됐고|됐지만|됐는데|'
             '받다|받은|받을|받고|받아|받게|받아서|받았다|'
             '주다|준|줄|주고|주며|주면|주니|주게|주어|줘서|'
             # 특수 활용형
             '구한|찾은|얻은|만난|본|낸|된|한'),
    
    # 단위 패턴 - 수량 및 단위 표현 식별
    'UNITS': '량|액|개|원|%|퍼센트|건|명|인'
}

# 2. 정당명 집합 - 정확한 정당명 매칭을 위한 문자열 집합
# 현재 활동 중이거나 역사적으로 중요한 정당들을 포함
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

# 3. 행동-결과 패턴 - 뉴스 내용의 인과관계 분석에 사용
# 특정 행동 후의 결과를 추출하기 위한 패턴
ACTION_RESULT_PATTERNS = [
    # 확인/점검/일반 행동 후 결과 (하나로 통합)
    fr'(?:확인|점검|일반|조사|관찰|검사|[가-힣]+)(?:{COMMON["ACTION_STATUS"]})?\s*(?:니|니까)\s*([가-힣]+)[.…\u2026]*'
]

# 4. 조사 패턴 - 문장 구조 분석과 키워드 추출 정확도 향상을 위한 패턴
# 일반 조사와 인명 관련 특수 접미사를 구분하여 처리
JOSA_PATTERNS = [
    fr'(?<=[\가-힣])({COMMON["JOSA"]})(?=\s|$)',
    r'(?<=[\가-힣])(씨|측|님|군|양)(?=\s|$)'  # 인명 관련 특수 접미사
]

# 5. 복합 단어 패턴 - 여러 단어가 결합된 복합 키워드 추출
# 각 분야별로 구분된 패턴으로 전문용어 식별에 활용
COMPOUND_WORD_PATTERNS = [
    fr'[가-힣]+({COMMON["ORGANIZATION_RELATED"]})',  # 조직/기관 복합어 패턴
    fr'[가-힣]+({COMMON["PERSON_RELATED"]})(?=\s|$)',
    fr'[가-힣]+({COMMON["ACTION_STATUS"]})',
    r'\d+[가-힣]+단',
    r'(?:전국(?:광역)?시도)?(?:{COMMON["ORGANIZATION_RELATED"]})(?:장|위원장)?',
    
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
    
    # 직위/직책, 시설 관련 패턴
    fr'[가-힣]+(?:{COMMON["PERSON_RELATED"]})',  # 홍길동 장관, 건진법사, 정진스님 등
    fr'[가-힣]+(?:{COMMON["PLACE_RELATED"]})'  # 서울청사, 건진사, 정진암 등
]

# 6. 뉴스 구조 패턴 - 뉴스 텍스트의 구조적 특징을 분석
# 속보, 인용구, 주체-행동-결과 등의 뉴스 특유의 패턴 매칭
NEWS_STRUCTURE_PATTERNS = [
    fr'\[(속보|단독|긴급)\]\s*([가-힣]+).*?([가-힣]+(?:{COMMON["ACTION_STATUS"]}))',
    fr'(?:{COMMON["ORGANIZATION_RELATED"]}|[가-힣]{{2,4}}\s*(?:{COMMON["PERSON_RELATED"]})).*?"([^"]+)"',
    fr'(?:{COMMON["ORGANIZATION_RELATED"]}|[가-힣]{{2,4}}\s*(?:{COMMON["PERSON_RELATED"]})).*?["\']([^"\']+)["\']', # 둘은 다른 용도(큰,작은따옴표)
    fr'([가-힣]+)(?:{COMMON["JOSA"]})?',  # 주체 (예: "경찰")
    fr'(?:{COMMON["ACTION_STATUS"]})',     # 행동 (예: "출석")
    fr'([가-힣]+)[은는]\s*([가-힣]+[{COMMON["UNITS"]}])',
    fr'([가-힣]+)으로\s*([가-힣]+)',
    fr'(?:{COMMON["ORGANIZATION_RELATED"]}).*?"([^"]+)"',  # 기관-발언 패턴
    fr'(?:{COMMON["ORGANIZATION_RELATED"]})[이가]?\s*(?:[,.]|$)',  # 기관명으로 시작하는 경우
    fr'(?:{COMMON["ORGANIZATION_RELATED"]})\s*(?:{COMMON["ACTION_STATUS"]})',  # 기관명+행동(금융위원회 결정)
    fr'(?:{COMMON["ORGANIZATION_RELATED"]}).*?(?:{COMMON["ACTION_STATUS"]})'  # 기관-행동 패턴(금융위원회가 오후에 결정. 유연한 매칭)
]

# 7. 인명 관련 패턴 - 다양한 형태의 인명 추출
# 정부 인사와 혼합 이름(한글+영문) 패턴을 구분하여 처리
NAME_PATTERNS = {
    'government': [
        fr'([가-힣]{{2,4}})\s*(?:{COMMON["PERSON_RELATED"]})',  # PERSON_RELATED로 통합
    ],
    'mixed_name': [
        r'([A-Za-z]+)\s+([가-힣])(?=\s|$)',  
        r'([가-힣])\s+([A-Za-z]+)(?=\s|$)',  
    ]
}

def is_compound_term(word):
    """종교 시설 및 주요 공공시설 관련 용어 체크"""
    religious_pattern = fr'.*(?:{COMMON["PERSON_RELATED"]}|{COMMON["PLACE_RELATED"]})$'
    return bool(re.match(religious_pattern, word))

KEYWORDS_PER_TITLE = 2
def extract_keywords(titles, limit=10, keywords_per_title=2):
    def is_contains_hanja(text):
        """한자 포함 여부 체크"""
        return bool(re.search(r'[\u4e00-\u9fff]', text))

    
    all_nouns = []
    stop_words = {
        # 1. 뉴스 작성/형식 관련
        '속보', '단독', '종합', '업데이트', '확인', '보도', '특보', '뉴스', 
        '기자', '취재', '인터뷰', '기사',
        
        # 2. 뉴스 형식적 표현/톤
        '논란', '파문', '사태', '의혹', '스캔들', '루머', '파장', '후폭풍', 
        '여파', '후유증', '해명', '해프닝', '미스터리', '미궁', '논쟁', '공방',
        '파격', '충격', '경악', '충격적', '대혼란', '대란', '대참사', '대재앙',
        '초유', '유례없는', '전무후무', '사상최초',
        
        # 3. 동작/상태/입장 표현
        '발표', '발언', '주장', '강조', '지적', '포착', '발견', '등장', '제기', 
        '모의', '압박', '돌아왔', '해결', '섬기는', '폐기', '통제', '나선', '나섰', 
        '나서', '추월', '넘어서', '넘어감', '투입', '진화', '설득', '차단',
        '기대', '희망', '우려', '걱정', '예상', '전망', '완료', '예정', '진행',
        '분석', '가능', '만나', '만남', '느끼다', '생각하다', '판단', '생각',
        '추천', '권고', '지목', '믿다', '의심', '확신', '신뢰', '좋아', '싫어', 
        '미워', '사랑', '놀라다', '당황', '혼란',
        
        # 4. 시스템/처리 관련
        '추가', '삭제', '변경', '수정', '등록', '제거', '편집', '입력', '출력', 
        '저장', '불러오기', '확장', '축소', '이동', '복사', '시작', '개시', '착수', 
        '출발', '준비', '대기', '마무리', '종료', '선정', '지정', '선발', '임명',
        
        # 5. 평가/판단 관련
        '잘못', '잘', '못', '잘하다', '잘되다', '제대로', '올바로', '바르게', 
        '정확히', '틀리다', '틀린', '그르다', '그른', '성공', '실패', '성과', 
        '실수', '착오', '옳다', '맞다', '훌륭히', '완벽히', '부족히', '뛰어난', 
        '뒤떨어진', '앞선', '뒤처진',
        
        # 6. 설명/논리/상황 관련
        '이유', '원인', '배경', '결과', '목적', '설명', '논리', '방법', '방식', 
        '과정', '상황', '경우', '계기', '중립', '보상', '책임', '책임자',
        
        # 7. 시간/상태 관련
        '오늘', '내일', '어제', '현재', '이번', '임시', '아침', '저녁', '매일', '매주', '매월', '매년', 
        '밤', '새벽', '점심', '낮', '올해', '작년', '내년', '올', '이달', '지난',
        '이전', '이후', '전', '후', '당시', '과거', '새로운', '기존', '신규', 
        '이날', '기한', '기간', '시간', '시점', '시기', '출석', '결석', '지각', '조퇴',
        '요새', '요즘', '최근', '끝내', '마침내',
        
        # 8. 수량/정도 표현
        '공식', '긴급', '특별', '일부', '관련', '상승', '하락', '증가', '감소', 
        '급등', '급락', '상향', '하향', '오름', '내림', '올라', '내려', '올랐', 
        '내렸', '상승세', '하락세', '늘어', '줄어', '늘었', '줄었', '증감',
        '영하', '이하', '이상', '미만', '초과', '최대', '최소', '최고', '최저', 
        '최강', '최악', '최상', '최첨단', '극대', '극소', '극한', '극심', '극강', 
        '극미', '극소수', '극대수', '절반', '다수', '소수', '대부분', '대다수',
        '전체', '전부', '일부분', '수준', '정도', '가량', '매우', '너무', '아주', 
        '가장', '정말', '진짜', '상당', '다소', '약', '약간', '조금', '거의',
        '완전', '절대', '전혀',
        
        # 9. 문법 관련 (부사/접속사/대명사)
        '다시', '또', '이제', '아직', '벌써', '이미', '먼저', '나중', '드디어',
        '계속', '자주', '항상', '때때로', '가끔', '종종', '방금', '곧', '즉시', 
        '바로', '우선', '결국', '그리고', '또한', '그러나', '하지만', 
        '그래서', '따라서', '그러므로', '그런데', '그러면', '그래도', '그리하여', 
        '그러니까', '왜냐하면', '이것', '저것', '그것', '여기', '저기', '거기', 
        '이런', '저런', '그런', '이렇게', '저렇게', '그렇게', '이와', '그와', '저와',
        
        # 10. 보조용언/조동사
        '있다', '없다', '하다', '되다', '보다', '주다', '받다', '가다', '오다',
        '싶다', '말다', '버리다', '두다', '놓다', '드리다', '이다', '아니다', '같다',
        
        # 11. 상태/추상 관련
        '적합도', '명분', '압도', '격차', '근접', '급등세', '급락세', '상승폭', 
        '하락폭', '호전', '악화', '개선', '퇴보', '유리', '불리', '양호', '미흡',
        '강세', '약세', '우세', '열세', '필요', '필수', '불필요', '기능', '중요',
        '이용', '사용', '사용자', '서버', '호출', '호환', '호환성',
        
        # 12. 일반 명사/분야
        '남성', '여성', '사람', '인물', '모습', '정치', '경제', '사회', '문화', 
        '국민', '체감', '개발', '속도', '온도', '시장', '지분', '주식', '투자', 
        '배당', '자본', '주가', '주주', '주주총회', '사과', '제출', '사실', '사건'
        
        # 13. 가족 관계 용어
        '아내', '남편', '부인', '아들', '딸', '부모', '아버지', '어머니', '할머니', '쌍둥이',
        '할아버지', '가족', '동생', '언니', '오빠', '형', '누나', '조카', '형제', '자매', '남매',
        
        # 14. 행위/상태/절차 관련
        '보장', '지원', '제공', '수행', '실시', '요구', '요청', '답변', 
        '질문', 
        '문의', '처리', '처분', '조치', '대응', '대처', '확정', '결정', '판단', 
        '판결', '선고', '간병', '돌봄', '치료', '진료', '수술', '살해', '사망', 
        '부상', '상해', '사고',
        
        # 15. 반대/찬성 관련
        '반대', '찬성', '찬반', '동의', '거부', '반발', '지지', '옹호', '비판', 
        '항의', '저항', '반론', '수용', '수락', '거절', '기각', '승인', '부결',
        '찬동', '반박', '항변', '맞서', '맞불', '거짓', '거짓말', '침해', '합의',
        '거절', '철회', '취소', '취급', 
        
        # 16. 법률/수사 관련
        '수사', '조사', '심사', '심의', '감사', '점검', '검토', '진술', '증언', 
        '자백', '취조', '심문', '조서', '소환', '체포', '구속', '압수', '수색', 
        '혐의', '증거', '배상', '소송', '고소', '고발', '기소', '구형', '재판', 
        '공판', '선고', '판결', '항소', '상고', '무죄', '유죄', '손배', '손해배상', 
        '가처분', '청구', '기각', '인용',
        
        # 17. 공공/사법 직종
        '경찰', '검찰', '판사', '변호사', '검사', '순경', '소방관', '공무원', 
        '군인', '의무관', '교도관',
        
        # 18. 의견/발언 관련
        '조언', '답변', '인터뷰', '발언', '진술', '증언', '자백', '의견', '견해', 
        '주장', '해명', '설명', '언급', '논평', '제안', '건의', '문의', '질문', 
        '대답', '응답', '회신', '토론', '토의', '대화', '담화', '연설', '강연', 
        '발표', '상담', '자문', '고백', '고발', '진정', '청원', '탄원', '증언자', 
        '증언대', '증언록',
        
        # 19. 관련 동사형
        '말하다', '밝히다', '전하다', '답하다', '묻다', '설명하다', '주장하다', 
        '언급하다', '강조하다', '제기하다', '지적하다', '거론하다', '토로하다'
    }

    for title in titles:
        title_nouns = []
        working_title = title

        # 1. 전처리: 한자 및 대괄호 처리
        working_title = title
        
        # 한자가 포함된 단어는 한글로 변환 시도
        def process_hanja(text):
            if is_contains_hanja(text):
                hangul_text = re.sub(r'[一-龥]', '', text)  # 한자 제거
                return hangul_text if len(hangul_text) >= 2 else ''
            return text
            
        working_title = ' '.join(process_hanja(word) for word in working_title.split())
        
        # 대괄호 제거 및 공백 처리
        working_title = re.sub(r'\[[^]]*\]', ' ', working_title)
        logger.info(f"처리할 제목: {working_title}")

        # 기본 형태소 분석 먼저 실행
        morphs = okt.pos(working_title)
        base_nouns = []
        for word, pos in morphs:
            # words 변수를 사용하기 전에 먼저 정의
            words = [w.strip() for w in word.split() if w.strip()]
            
            if pos.startswith('NN') and len(word) >= 2:  # 명사류만
                if word not in stop_words:
                    title_nouns.append(word)
                    working_title = working_title.replace(word, '■' * len(word))
            
            for single_word in words:  # 이제 words 변수 사용 가능
                # 명사(N)만 추출, 동사(V)/형용사(A) 제외
                if pos.startswith('N'):  # Noun
                    if len(single_word) >= 2 and single_word not in stop_words:
                        base_nouns.append(single_word)
                elif pos.startswith('V') or pos.startswith('A'):  # Verb or Adjective
                    if len(single_word) >= 2:  # 의미있는 길이의 단어만 추가
                        stop_words.add(single_word)  # 동적으로 stop_words에 추가
        
        # Mecab pos 태그로 통합 명사 처리
        for word, pos in mecab.pos(working_title):
            # 품사 확인 (동사/형용사 제외)
            if pos.startswith(('VV', 'VA', 'VX', 'EP', 'EC', 'EF', 'ETN', 'ETM')):
                continue
                
            # 명사 처리 (고유명사 + 일반명사)
            if (pos == 'NNP' or pos.startswith('NN')) and len(word) >= 2:
                # 원문에서 해당 단어의 실제 형태 확인
                original_form = None
                for original_word in working_title.split():
                    # 1. 숫자+단위 패턴
                    if re.match(fr'\d+\s*(?:{COMMON["UNITS"]})', original_word):
                        rest = re.sub(fr'^\d+\s*(?:{COMMON["UNITS"]})\s*', '', original_word)
                        if rest and len(rest) >= 2 and rest not in stop_words:
                            title_nouns.append(rest)
                            working_title = working_title.replace(original_word, '■' * len(original_word))
                        continue
                    
                    # 2. 정당 이름
                    for party_name in PARTY_NAMES:
                        if party_name in original_word:
                            title_nouns.append(party_name)
                            working_title = working_title.replace(party_name, '■' * len(party_name))
                            original_form = party_name
                            break
                    if original_form:
                        break
                        
                    # 3. 복합어 패턴
                    if any(re.match(pattern, original_word) for pattern in COMPOUND_WORD_PATTERNS):
                        if original_word not in stop_words and len(original_word) >= 3:
                            title_nouns.append(original_word)
                            working_title = working_title.replace(original_word, '■' * len(original_word))
                            original_form = original_word
                            break
                    
                    # 4. 일반 단어 처리
                    if word in original_word.replace(' ', ''):
                        original_form = original_word
                        break
                
                # 원종 처리
                if not original_form:  # 아직 처리되지 않은 경우
                    if word not in stop_words:
                        title_nouns.append(word)
                        working_title = working_title.replace(word, '■' * len(word))

        # 1. Mecab으로 기본 명사 추출 및 처리
        mecab_nouns = mecab.nouns(working_title)
        for noun in mecab_nouns:
            # 1-1. 품사 재확인 (동사/형용사 제외)
            pos_tags = mecab.pos(noun)
            if any(tag[1].startswith(('VV', 'VA', 'VX', 'EP', 'EC', 'EF', 'ETN', 'ETM')) for tag in pos_tags):
                continue
            
            # 1-2. 공백 포함 단어 처리
            if ' ' in noun:
                parts = noun.split()
                for part in parts:
                    if len(part) >= 2 and part not in stop_words:
                        title_nouns.append(part)
                        working_title = working_title.replace(part, '■' * len(part))
                continue
            
            # 1-3. 복합어 패턴 체크
            is_compound = (
                any(re.match(pattern, noun) for pattern in COMPOUND_WORD_PATTERNS) or
                is_compound_term(noun)
            )
            
            # 1-4. 복합어 처리
            if is_compound and len(noun) >= 3:
                if noun not in stop_words:
                    title_nouns.append(noun)
                    working_title = working_title.replace(noun, '■' * len(noun))
            # 1-5. 긴 복합어(6자 이상) 분리 처리
            elif len(noun) >= 6:
                parts = mecab.nouns(noun)
                valid_parts = [p for p in parts if len(p) >= 2 and p not in stop_words]
                if valid_parts:
                    title_nouns.extend(valid_parts)
                    working_title = working_title.replace(noun, '■' * len(noun))
            # 1-6. 일반 명사 처리
            elif len(noun) >= 2 and noun not in stop_words:
                title_nouns.append(noun)
                working_title = working_title.replace(noun, '■' * len(noun))

        # 2. 남은 복합어 패턴 처리
        for pattern in COMPOUND_WORD_PATTERNS:
            matches = re.finditer(pattern, working_title)
            for match in matches:
                compound_word = match.group(0)
                # 2-1. 공백 포함 단어 처리
                if ' ' in compound_word:
                    parts = compound_word.split()
                    for part in parts:
                        if len(part) >= 2 and part not in stop_words:
                            title_nouns.append(part)
                            working_title = working_title.replace(part, '■' * len(part))
                # 2-2. 복합어 처리
                elif is_compound_term(compound_word):
                    if compound_word not in stop_words and len(compound_word) >= 3:
                        title_nouns.append(compound_word)
                        working_title = working_title.replace(compound_word, '■' * len(compound_word))

        # 3. 남은 연속 명사 처리
        compound_word = ''
        for word, pos in mecab.pos(working_title):
            # 조사 제외
            if pos.startswith('JK') or word in COMMON['JOSA'].split('|'):
                if compound_word and len(compound_word) >= 2:
                    if compound_word not in stop_words:
                        title_nouns.append(compound_word)
                        working_title = working_title.replace(compound_word, '■' * len(compound_word))
                compound_word = ''
                continue
                
            if pos.startswith('NN'):  # 명사류
                compound_word += word
                # 3-1. 긴 복합어 분리
                if len(compound_word) >= 6:
                    parts = mecab.nouns(compound_word)
                    valid_parts = [p for p in parts if len(p) >= 2 and p not in stop_words]
                    if valid_parts:
                        title_nouns.extend(valid_parts)
                        working_title = working_title.replace(compound_word, '■' * len(compound_word))
                    compound_word = ''
            else:
                # 3-2. 일반 복합어 처리
                if compound_word and len(compound_word) >= 2:
                    if compound_word not in stop_words:
                        title_nouns.append(compound_word)
                        working_title = working_title.replace(compound_word, '■' * len(compound_word))
                compound_word = ''

        # 3. 기존 패턴들 그대로 유지
        for pattern_type in ['government', 'mixed_name']:
            for pattern in NAME_PATTERNS[pattern_type]:
                matches = re.finditer(pattern, working_title)
                for match in matches:
                    # 1) government: 정부/공공 인사
                    #    예: "홍길동 장관" -> "홍길동"
                    #    - group(1)로 이름만 추출
                    
                    # 2) mixed_name: 한글+영문 혼합 이름
                    #    예: "젠슨 황" -> "젠슨 황"
                    #    - groups()의 모든 부분을 공백으로 결합
                    name = ' '.join(match.groups()) if pattern_type == 'mixed_name' else match.group(1)
                    
                    # 공통 처리: stop_words 체크 및 마스킹
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
        
        # 4. 3글자 단어 처리 부분
        words = working_title.split()
        for word in words:
            if len(word) == 3 and re.match(r'^[가-힣]{3}$', word):
                pos = okt.pos(word, stem=False)
                if (len(pos) == 1 and pos[0][1] == 'Noun') or \
                   (len(pos) > 1 and pos[0][1] == 'Noun'):
                    # 공백으로 분리 후 각각 처리
                    for part in word.split():
                        if len(part) >= 2 and part not in stop_words:
                            title_nouns.append(part)
                            working_title = working_title.replace(part, '■' * len(part))

        # 5. 나머지 일반 명사 추출 부분
        okt_nouns = okt.nouns(working_title)
        mecab_nouns = mecab.nouns(working_title)
        nouns = list(set(okt_nouns + mecab_nouns))  # 중복 제거
        for noun in nouns:
            # 공백으로 분리 후 각각 처리
            for part in noun.split():
                if len(part) >= 2 and part not in stop_words:
                    title_nouns.append(part)

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
                    if group and len(group) >= 2:
                        # 공백으로 분리 후 각각 처리
                        parts = group.split()
                        for part in parts:
                            if len(part) >= 2 and part not in stop_words:
                                title_nouns.append(part)
                                working_title = working_title.replace(part, '■' * len(part))

        # 중복 제거
        title_nouns = list(set(title_nouns))
        
        # 빈도수 계산
        all_nouns.extend(title_nouns)  # 바로 all_nouns에 추가
        
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
