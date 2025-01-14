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

3. STOP_WORDS - 불용어 집합
   - 뉴스/미디어 관련 용어
   - 행위/절차/업무 관련 용어
   - 문법 요소 (조사/어미/대명사)
   - 기타 일반 명사

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
   - 접미사 포함 이름 (예: 홍길동씨, 김철수군)
"""

import logging
from konlpy.tag import Okt
from collections import Counter
import re
from asgiref.sync import sync_to_async
import asyncio
from openai import AsyncOpenAI
import json

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
        '총리|대통령|처장|차장|위원장|원장|본부장|단장|센터장|'
        '총장|의장|사장|부사장|회장|이사장|'
        # 사법부 직책
        '재판관|헌법재판관|헌재소장|헌법재판소장|수석재판관|'
        # 기관장 직책
        '경찰청장|국세청장|관세청장|조달청장|통계청장|검찰청장|기상청장|경호차장|'
        '소방청장|산림청장|특허청장|국방장관|국무총리|'
        # 기업 직책
        '대표|이사|부회장|상무|전무|감사|'
        # 군/경 계급
        '군|총경|경정|경감|경위|순경|대령|중령|소령|대위|중위|소위|'
        # 종교 직책
        '법사|스님|신부|목사|교무|전하|법왕|교주|대종사|종정|주교|대주교|추기경|교황|'
        # 인명 수식어
        '전|현|신임|역|정|신규|기존|임시|권한대행|긴급'
    ),
    
    # 조직/기관/단체 - 기관명 및 단체명 식별에 사용
    'ORGANIZATION_RELATED': (
        # 기본 조직 단위
        '처|청|원|실|국|과|부|팀|'
        # 정부/공공기관
        '정부|당국|위원회|대통령실|경찰청|검찰청|법원|'
        '정보원|수사처|공수처|경호처|교육청|세무서|'
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
    '사망', '부상', '사상', '희생', '희생자', '피해', '피해자', '정신',
    '변사', '타계', '별세', '운명', '서거', '사인', '장례', '추모', '거품', '품위',
    '가짜', '사실', '허위', '진실', '실제', '메시지', '공문', '이름', '명칭',
    '측', '씨', '분들', '여러분', '맹공', '맞불', '설전', '폭로', '특종',
    '삶', '여정', '자결', '자살', '죽음', '왜곡', '들통', '치명', '줄줄이',
    '정계', '천상계', 

    # 2. 행위/절차/업무 관련
    '발표', '발언', '주장', '지적', '발견', '등장', '제기', '자리', '위험',
    '파견', '훈육', '일임',  '임시',
    '모의', '압박', '해결', '폐기', '통제', '투입', '진화', '설득', '차단',
    '기대', '희망', '우려', '걱정', '예상', '전망', '완료', '예정', '진행',
    '분석', '판단', '만남', '생각', '추천', '권고', '지목', '신뢰', '혼란',
    '보장', '지원', '제공', '실시', '요구', '요청', '질문',
    '문의', '처리', '처분', '조치', '대응', '대처', '확정', '결정', '기록',
    '정지', '중단', '중지', '훈련', '인사', '무력', '저지', '협조', 
    '신청', '통보', '접수', '등록', '신고', '제출', '발급', '승인', '허가',  
    '취직', '퇴직', '입사', '퇴사', '이직', '전직', '복직', '기피',
    '추진', '시행', '수행', '이행', '경쟁', '위로', '답게',
    '방문', '발송', '교환', '불참', '참석', '초청', '초대', '완성', 
    '경영', '자제', '저격', '구입', '심부름', '제보', '통과', '강화',
    '결제', '유지', '방해', '흡수', '배출', '확산', '임박',

    # 3. 시스템/관리 관련
    '추가', '삭제', '변경', '수정', '제거', '편집', '입력', '출력', 
    '저장', '확장', '축소', '이동', '복사', '시작', '개시', '착수', 
    '출발', '준비', '대기', '종료', '선정', '지정', '선발', '임명',
    '잘못', '성공', '실패', '성과', '실수', '착오', '간부',
    '마련', '제시', '휴대', '해제', '먹통', '고장', 

    # 4. 상황/설명 관련
    '이유', '원인', '배경', '결과', '목적', '설명', '논리', '방법', '방식', 
    '과정', '상황', '경우', '계기', '중립', '보상', '책임', '책임자',
    '적합도', '명분', '격차', '필요', '필수', '기능', '이용', '사용',
    '사용자', '서버', '호출', '호환', '호환성', '충돌', '헛심', '심',
    '황당', '환심', '사려', '경고', '울분', '오판', '유감', '사과', '용서', 
    '안정', '부당', '이익', '불이익', '요소', '정가', '가격',
    '가능성', '기능성', '진의', '상당', '상대', '여부', '조건', '조건부',

    # 5. 감정/심리 표현 추가
    '분노', '후회', '기쁨', '슬픔', '행복', '불안', '두려움',
    '공포', '놀람', '충격', '당황', '혼란', '불만', '만족', '실망',
    '괴로움', '고통', '즐거움', '기대', '희망', '절망', '환희',
    '흥분', '짜증', '답답', '서운', '억울', '부끄러움', '창피',
    '질투', '시기', '미움', '증오', '원망', '한탄', '후련',
    '아쉬움', '그리움', '외로움', '허전', '허탈', '우울',
    '초조', '긴장', '불편', '편안', '걱정',
    '선택', '일반', '미래', '수치', '양심', '조바심',
    '얼굴', '심신', '미약', '꿀꺽', '감정', '압도', '싸가지',

    # 6. 시간/수량/통계 관련
    '아침', '저녁', '매일', '매주', '매월', '매년', '밤', '새벽', '점심', 
    '낮', '올해', '작년', '내년', '이달', '당시', '과거', '신규', '이날',
    '마지막', '최종', '최후', '말기', '종반', '막바지', '종말', 
    '처음', '초기', '시초', '발단', '중간', '도중', '중반', '중순',
    '이전', '이후', '순서', '순번', '차수', '회차', '단계',
    '기한', '기간', '시간', '시점', '시기',
    '이참', '이때', '이제', '이번', '저번', '요번', '요즘', '그날', '저날',
    '끝내', '해당', '대박', '고음',
    '공식', '일부', '관련', '상승', '하락', '증가', '감소', '급등', '급락', 
    '상향', '하향', '상승세', '하락세', '증감', '영하', '이하', '이상', 
    '미만', '초과', '최대', '최소', '최고', '최저', '최강', '최악', '최상', 
    '최첨단', '극대', '극소', '극한', '극강', '극미', '극소수', '극대수', 
    '절반', '다수', '소수', '대부분', '대다수', '전체', '전부', '일부분', 
    '수준', '정도', '가량', '최대폭', '제일', '액수', '원금',
    '하위', '중하위', '상위', '중상위', '최상위', '최하위',
    '한가지', '두가지', '세가지', '네가지', '하필',
    '급증', '지난해', '분산', '숫자', '확률',

    # 7. 법률/수사 관련
    '수사', '조사', '심사', '심의', '점검', '검토', '진술', '증언', '자백', '취조', '심판',
    '심문', '조서', '소환', '체포', '구속', '압수', '수색', '혐의', '증거', '배상', 
    '소송', '고소', '고발', '기소', '구형', '재판', '판결', 
    '흉기', '둔기', '무기', '총', '칼', '망치', '톱', '소총', '화살', '촉', '검열', '나랏돈', '눈먼돈', '거래', '원금', '액수',
    '집행', '대행', '이행', '강제', '명령', '처분', '처벌', '제재', '단속', '규제', '통제',
    '정족수', '호송', '조력자', '범인', '외압성',

    # 8. 의견/태도 관련
    '반대', '찬성', '찬반', '동의', '거부', '반발', '지지', '옹호', '비판', 
    '항의', '저항', '반론', '수용', '수락', '거절', '허락', '불응', '승인', 
    '부결', '찬동', '반박', '항변', '거짓', '거짓말', '침해', '합의', '철회', 
    '취소', '취급', '조언', '답변', '언급', '논평', '제안', '건의', '대답',
    '응답', '회신', '토론', '토의', '대화', '담화', '연설', '강연', '상담', '퍼주면',
    '최선', '지원', '제의', '공개', '지시', '방침', '어른', '어르신', '소년', '소녀',
    '더더', '판하', '독촉', '인정', '멍청이', '반격', '무산', '결집', '방어',

    # 9. 행정/지역 관련
    '시', '특별시', '광역시', '특별자치시', '특별자치도', '남도', '북도', '제주도', '도청', '시청', '군청', '구청',
    '쪽', '방향', '방면', '좌측', '우측', '양측', '왼쪽', '오른쪽', '윗쪽', '아랫쪽', '양쪽', '앞', '뒤', '위', '아래', '북', '남', '동', '서',
    '지자체', '교민', '정치', '번지',

    # 10. 인물/주민 관련
    '인', '국인', '본인', '아인',
    '시민', '도민', '군민', '구민', '주민',
    '국민', '민간인', '민족', '유가족', '유족',
    '엄마', '아빠', '부모', '아버지', '어머니', 
    '할머니', '할아버지', '손자', '손녀',
    '삼촌', '이모', '고모', '외삼촌',
    '조카', '사촌', '형', '누나', '오빠', '언니',
    '동생', '남매', '자매', '형제', '쌍둥이',
    '시어머니', '시아버지', '장인', '장모',
    '며느리', '사위', '시댁', '처가', 
    '왕', '왕비', '공주', '왕자', '황제', '황후',
    '귀족', '공작', '백작', '후작', '남작', '군주',
    '전하', '마마', '대비', '세자', '세자빈', '대군', '공',
    '직원', '사원', '근로자', '노동자', '종업원', '근무자', '담당자',
    '실무자', '관리자', '주임', '임원', '비정규직', '정규직',
    '창시자', '부부', '남성', '여성', '상사', '남편', '아내', '운전자',
    '출신', '새내기주',

    # 11. 수량/단위/화폐
    '번', '차례', '회', '차', '개', '명', '건', '달', '해', '년', '월', '일', '시', '분', '초', '무더기',
    '만원', '천만원', '억원', '조원', '천원', '백원', '십원', '원', '달러', '엔', '위안', '파운드', '유로',

    # 12. 시간/상태/정도 표현
    '오래', '계속', '항상', '늘', '자주', '이미', '아직', '벌써', '곧', '먼저', 
    '오랫동안', '계속해서', '지속적', '영원히',
    '매우', '너무', '아주', '정말', '진짜', '워낙', '굉장히', '몹시', '무척', '척', '엄청',
    '겨우', '간신히', '조금', '약간', '다소', '거의', '요새', '잇단', '직전', '가장',
    '어느정도', '그다지', '전혀', '결코', '절대', '별로', '도저히',
    '강경', '동시', '우선', '직접', '똑바로', '갑자기',
    '자기', '얘기', '고시', '비교', '면전', '홀로', '멀쩡', '동안', '다시', '혼자',
    '당장', '즉시', '곧바로', '바로', '지금', '현재',
    '방금', '금방', '이내', '순간', '잠시', '잠깐',
    '이따가', '나중', '이전', '이후',
    '오늘', '내일', '모레', '어제', '그제', '그저께',
    '그때', '번째', '첫번째', '두번째', '세번째', '네번째', '다섯번째', '여섯번째', '일곱번째', '여덟번째', '아홉번째', '열번째',
    '하나', '다섯', '여섯', '일곱', '여덟', '아홉',
    '첫째', '둘째', '셋째', '넷째', '다섯째',
    '부분', '일체', '몇몇', '여러', '많은', '적은', '수많은',
    '일도', '이도', '삼도', '사도', '물속', '여기', '저기', '거기',
    '안', '밖', '속', '바깥', '하늘', '얼마나',
    '하루', '이틀', '사흘', '나흘', '열흘', '일주일', '한달', '일년',
    '일', '일일', '이일', '삼일', '사일', '오일', '육일', '칠일', '팔일', '구일', '십일',

    # 13. 문법 요소 (조사/어미/대명사)
    '이', '가', '은', '는', '을', '를', '의', '와', '과', '도', '만', '에', '으로', '로', '께', '에게', '한테', '더러', '보고', '같이', '처럼', '만큼', '보다', '까지', '부터',
    '라', '며', '고', '면', '야', '랑', '든', '서', '대해서', '통해서', '위해', '위해서', '따라', '따라서', '대해', '대하여', '관해', '관하여', '에게서', '마저', '조차',
    '에서', '으로서', '로서', '으로써', '로써', '이라고', '라고', '이라는', '라는', '이라며', '라며', '이라서', '라서',
    '구해', '구해서', '구해서는', '구해서도', '구해서만', '가면', '가면서',
    '에서의', '서의', '에서는', '서는', '에서도', '서도', '에서만', '서만',
    '이나', '나', '이야', '야', '이란', '란', '이든', '든', '물든', '이라', '라',
    '이라도', '라도', '이라면', '라면', '으로도', '로도',
    '이라기에', '라기에', '이라기보다', '라기보다',
    '것', '듯', '때문', '때', '등', '들', '달라', '이', '일이', '일이나', '이나', 

    # 14. 지시/대명사/부사
    '이런', '저런', '그런', '어떤', '무슨', '웬', '이러한', '저러한', '그러한',
    '이런저런', '어떠한', '이와같은', '그와같은',
    '이것', '저것', '그것', '무엇', '어디', '언제', '어떻게',
    '이곳', '저곳', '그곳', '어느곳',
    '이이', '저이', '그이', '누구',
    '스스로', '모두', '그냥', '결국',

    # 15. 동사/형용사 활용
    '하다', '하라', '하라고', '했다', '한다', '할', '하고', '해서', '하며', '하면', '하니', '하게', '하여', '했고', '했지만', '했는데', '하는', '하게', '하지', 
    '되다', '되라', '돼라', '되라고', '돼라고', '됐다', '된다', '될', '되고', '되서', '되며', '되면', '되니', '되어', '돼서', '됐고', '됐지만', '됐는데', '되는', '되지', '되게', 
    '받다', '받아라', '받으라고', '받은', '받을', '받고', '받아', '받게', '받아서', '받았다',
    '주다', '줘라', '주라고', '줬다', '준다', '줄', '주고', '줘서', '주며', '주면', '주니', '주게', '줬고', '줬지만', '줬는데', '주어지고', '지고',
    '였다', '여라', '였어서', '였다고', '였으면', '였지만', '였는데', '오지', '있지', '없지', '오게', '있게', '없게', '오는', '있는', '없는', '혔다',
    '어서', '다고', '으면', '지만', '는데', '구한', '찾은', '얻은', '만난', '낸', '된', '가는', '가게', '가지', '가라', '퍼뜨린', '자고', '자고로', '밀면', '건가',
    '분다', '온', 

    # 16. 종결어미
    '아요', '어요', '여요', '예요', '에요', '해요', '했어요', '하세요', '됐어요', '되요', '주세요', '세요',
    '차려요', '보세요', '드세요', '가요', '와요', '나요', '말아요', '봐요', '써요', '놓아요', '두어요',
    '습니다', '습니까', '합니다', '합니까',
    '네요', '군요', '는군요', '는데요', '더군요',
    # 형태소 분석 오류 방지용 음절
    '렌스', '스키', '프스', '브스', '드스', 

    # 17. 기타 명사
    '생활', '호화', '놀이', '생일', '추억', '명문', '제동', '말꼬리', '꼬리', '안건', '당위', '범위', '오차', '록스', '추방', '사진', '매립', '갑부', 
    '서면', '마크', '잡지', '팼다', '발목', '기주', '명의', '시대', '비번', '기적', '전기', '전화', '수석', '조수석', '유보', '헬멧', '배낭', '인형', '지호',
    '외치', '미기', '에르', '도부', '핏대', '임신',  '지층', '내자', '자체', '대신', '우리', '회원', '소문', '발사', '초교', '중교', '고교', '박찬', '차장',
    '초래', '중재', '정쟁', '주도', '대표', '간식', '친구', '사람', '본부장', '동요', '방청', '장관', '국방', '외면', '독려', '현직', '숙소', '공관', '집합', 
    '재시', '재시도', '시도', '관측', '예측', '도로', '지지자', '유력', '표현', '일종', '최소한', '수상한', '고백', '비단', '간다', '산책', '자진', '출도', '관람',
    '극성', '하자마자', '집결', '정체'  
}

def extract_keywords(titles, limit=10, keywords_per_title=4):
    """
    뉴스 제목들에서 주요 키워드를 추출하는 함수
    
    처리 흐름:
    1. 전처리 단계
       - 대괄호 제거 및 공백 정리
       - 한자 제거
       - OKT를 사용한 명사 추출
       - 불용어(stop_words) 1차 필터링
    
    2. 키워드 분류 단계
       - 복합어 (1순위): COMPOUND_WORD_PATTERNS 매칭
       - 정당명 (2순위): PARTY_NAMES 매칭
       - 인명 (3순위): NAME_PATTERNS 매칭
       - 일반명사 (4순위): 위 패턴에 해당하지 않는 나머지
    
    3. 우선순위 처리 단계
       - 각 카테고리별로 5개 이상 시 독립 처리
       - 5개 미만 시 일반명사로 통합
       - 중복 제거 (순서 유지)
    
    4. 후처리 단계
       - 마스킹된 단어 필터링 (■ 등 특수문자 처리)
       - 불용어 2차 필터링
       - 제목당 키워드 수 제한
    
    5. 키워드 빈도 분석 단계
       - 전체 키워드 빈도수 계산
       - 동시 출현 빈도 계산
       - 포함 관계 처리
       - 연관 키워드 그룹화
    
    6. 결과 정렬 및 반환
       - 빈도수 기준 내림차순 정렬
       - limit 개수만큼 상위 키워드 반환
       - (키워드, 빈도수, 연관키워드 그룹) 형태로 반환
    
    Args:
        titles (list): 분석할 뉴스 제목 리스트
        limit (int): 반환할 최대 키워드 수 (기본값: 10)
        keywords_per_title (int): 제목당 추출할 최대 키워드 수 (기본값: 4)
    
    Returns:
        list: (키워드, 빈도수, 연관키워드 집합) 튜플의 리스트
    """
    okt = Okt()
    
    logger.info(f"Stop words count: {len(stop_words)}")
    
    all_nouns = []
    for title in titles:
        title_nouns = []
        working_title = title
        
        logger.info(f"\n원본 제목: {title}")
        
        # 1. 대괄호 제거 및 공백 처리 후
        working_title = re.sub(r'\[[^]]*\]', ' ', working_title)

        # 2. 한자 제거 후
        working_title = ' '.join(
            remove_hanja_word(word) for word in working_title.split()
        ).strip()
        
        # 3. OKT 명사 추출 후
        nouns = okt.nouns(working_title)
        logger.info(f"명사 추출: {nouns}")
        
        # 4. stop_words 필터링 (첫 번째 필터링 - 유지)
        temp_nouns = [noun for noun in nouns if len(noun) >= 2 and noun not in stop_words]
        logger.info(f"필터링: {temp_nouns}")
        
        # 5. 추출된 명사들을 우선순위별로 분류
        compound_nouns = []  # 복합어 # 예: "경호처", "체포영장"
        party_nouns = []     # 정당명 # 예: "민주당", "국민의당"
        name_nouns = []      # 인명 # 예: "이재명", "윤건영"
        other_nouns = []     # 기타 일반명사 # 예: "산불", "내란"
        
        # 필터링된 명사들에 대해서만 패턴 매칭 수행
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
                
            # 4순위: 기타 일반명사 (stop_words 체크 제거)
            other_nouns.append(noun)  # 여기 수정
        
        # 5. 우선순위 순서대로 title_nouns에 추가 (5개 이상일 때만)
        # 각 카테고리별로 5개 이상 출현 시 독립적으로 처리하고,
        # 그렇지 않은 경우 일반명사로 통합하여 처리
        if len(compound_nouns) >= 5:
            title_nouns.extend(compound_nouns) # 독립적으로 추가
        else:
            other_nouns.extend(compound_nouns) # 일반명사로 통합
            
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
        title_nouns = list(dict.fromkeys(title_nouns)) # 모든 일반명사와 통합된 키워드 추가
        
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
        
        # 마스킹 필터링 후 stop_words 체크 (두 번째 필터링 - 안전장치로 유지)
        title_nouns = [noun for noun in title_nouns if noun not in stop_words]

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
            # stop_words 체크 추가
            if keyword in title and keyword not in stop_words:
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
    keywords_with_groups = [(k, counts[k], keyword_groups[k]) for k in sorted_keywords[:limit]]
    
    # 실제 기사 건수로 재정렬
    article_counts = {}
    for keyword, _, _ in keywords_with_groups:
        # 해당 키워드가 직접 포함된 기사 수 카운트
        article_count = sum(1 for title in titles if keyword in title)
        article_counts[keyword] = article_count
    
    # 기사 건수 기준으로 재정렬 (동일 건수는 키워드 사전순)
    final_sorted = sorted(
        keywords_with_groups,
        key=lambda x: (-article_counts[x[0]], x[0])
    )
    
    # 기사 건수로 업데이트하여 반환
    return [(k, article_counts[k], group) for k, _, group in final_sorted]

def process_keywords(keywords_list):
    """
    키워드 리스트를 전처리하고 중복을 제거하는 함수
    
    처리 흐름:
    1. 전처리 단계
       - 각 키워드의 앞뒤 공백 제거
       - 이미 처리된 단어 추적을 위한 set 생성
    
    2. 중복 및 포함 관계 처리
       - 이미 처리된 단어 스킵
       - 다른 키워드의 부분 문자열인지 확인
       - 독립적인 키워드만 선택
    
    3. 결과 반환
       - 전처리된 고유 키워드 리스트 반환
    
    Args:
        keywords_list (list): 처리할 키워드 리스트
    
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

# 동기 함수들을 비동기로 변환
extract_keywords_async = sync_to_async(extract_keywords)
process_keywords_async = sync_to_async(process_keywords)

async def analyze_keywords_with_llm(keywords_with_counts, titles, max_tokens=300):
    """
    키워드와 제목들을 LLM으로 분석 (비동기)
    """
    try:
        # 데이터 준비 (동기 작업)
        keyword_freq = '\n'.join([f"- {k} ({c}회)" for k, c, _ in keywords_with_counts[:10]])
        keyword_groups = '\n'.join([
            f"- {k}: {', '.join(sorted(g))}" 
            for k, _, g in keywords_with_counts[:5]
        ])
        formatted_titles = '\n'.join([f"- {t}" for t in titles[:10]])
        
        analysis_prompt = f'''
        다음 뉴스 데이터를 분석해주세요. 각 항목을 반드시 모두 작성해주세요:

        ===== 분석할 데이터 =====
        [키워드 빈도]
        {keyword_freq}

        [연관 키워드 그룹]
        {keyword_groups}

        [주요 제목]
        {formatted_titles}

        ===== 분석 요청 =====
        아래 세 가지 항목을 반드시 순서대로 모두 완성해주세요.
    각 항목은 100자 이내로 간단명료하게 작성해주세요.

        1. 핵심 트렌드:
        (뉴스의 주요 흐름을 설명해주세요)

        2. 주요 키워드 간 연관성:
        (키워드들이 어떻게 연결되어 있는지 설명해주세요)

        3. 주요 인사이트:
        (이 뉴스들이 시사하는 바를 설명해주세요)

        모든 항목을 빠짐없이 작성해주시기 바랍니다.
'''

        # GPT 응답을 비동기로 처리
        response = await _get_gpt_response(
            analysis_prompt, 
            temperature=0.3, 
            max_tokens=max_tokens,
            split_sections=True
        )
        
        # 디버깅을 위해 원본 응답 출력
        logger.info(f"=== GPT 원본 응답 ===\n{response}\n===================")
        
        # 응답 구조 단순화
        if isinstance(response, dict):
            if response.get('success'):
                analysis = response.get('analysis', {})
                if isinstance(analysis, dict):
                    return {
                        'trends': analysis.get('trends', '분석 결과가 없습니다.'),
                        'relations': analysis.get('relations', '분석 결과가 없습니다.'),
                        'insights': analysis.get('insights', '분석 결과가 없습니다.')
                    }
        
        # 응답 구조가 잘못된 경우
        logger.error(f"잘못된 응답 구조: {response}")
        return {
            'trends': '분석 결과 형식이 잘못되었습니다.',
            'relations': '분석 결과 형식이 잘못되었습니다.',
            'insights': '분석 결과 형식이 잘못되었습니다.'
        }
            
    except Exception as e:
        logger.error(f"키워드 분석 중 오류 발생: {str(e)}")
        return {
            'trends': '분석 중 오류가 발생했습니다.',
            'relations': '분석 중 오류가 발생했습니다.',
            'insights': '분석 중 오류가 발생했습니다.'
        }

async def _get_gpt_response(prompt, temperature=0.7, max_tokens=300, split_sections=False):
    """
    GPT API를 비동기로 호출하는 내부 유틸리티 함수
    """
    try:
        client = AsyncOpenAI()
        response = await client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "당신은 뉴스 분석 전문가입니다. 주어진 뉴스들을 객관적이고 간단명료하게 분석해주세요."},
                {"role": "user", "content": prompt}
            ],
            temperature=temperature,
            max_tokens=max_tokens,
            # 추가할 파라미터들
            presence_penalty=0.0,    # 반복을 피하기 위한 페널티
            frequency_penalty=0.0,   # 같은 단어 반복을 피하기 위한 페널티
            stop=None,              # 강제로 멈추지 않도록 설정
            top_p=1.0               # 다양한 응답을 위한 설정
        )
        content = response.choices[0].message.content
        
        # finish_reason 체크 추가
        finish_reason = response.choices[0].finish_reason
        if finish_reason != "stop":
            logger.warning(f"GPT 응답이 비정상적으로 종료됨: {finish_reason}")
            # 재시도 로직 추가 가능
        
        # 디버깅을 위해 원본 응답 출력
        logger.info(f"=== GPT 원본 응답 ===\n{content}\n===================")
        
        if split_sections:
            sections = {}
            content_lines = content.split('\n')
            current_section = None
            current_text = []
            
            for line in content_lines:
                line = line.strip()
                if not line:
                    continue
                
                lower_line = line.lower()
                
                # 1. 직접적인 섹션 매칭
                if '1.' in line or '핵심 트렌드:' in line:
                    if current_section and current_text:
                        sections[current_section] = ' '.join(current_text)
                    current_section = 'trends'
                    current_text = [line.split(':', 1)[-1].strip() if ':' in line else line]
                
                elif '2.' in line or '주요 키워드 간 연관성:' in line:
                    if current_section and current_text:
                        sections[current_section] = ' '.join(current_text)
                    current_section = 'relations'
                    current_text = [line.split(':', 1)[-1].strip() if ':' in line else line]
                
                elif '3.' in line or '주요 인사이트:' in line:
                    if current_section and current_text:
                        sections[current_section] = ' '.join(current_text)
                    current_section = 'insights'
                    current_text = [line.split(':', 1)[-1].strip() if ':' in line else line]
                
                # 2. 일반 텍스트 라인 처리
                elif current_section:
                    # 숫자나 불필요한 마커 제거
                    cleaned_line = line
                    if cleaned_line.startswith(('1.', '2.', '3.')):
                        cleaned_line = cleaned_line.split('.', 1)[-1].strip()
                    current_text.append(cleaned_line)

            # 마지막 섹션 처리
            if current_section and current_text:
                sections[current_section] = ' '.join(current_text)

            # 빈 응답 체크
            if not any(sections.values()):
                logger.warning("파싱된 내용이 없습니다. 원본 응답을 전체 텍스트로 처리합니다.")
                return {
                    'success': True,
                    'analysis': {
                        'trends': content.strip(),
                        'relations': '',
                        'insights': ''
                    }
                }

            # 디버깅
            logger.info("=== 파싱된 섹션 ===")
            for section, text in sections.items():
                logger.info(f"{section}: {text}")
            logger.info("===================")

            return {
                'success': True,
                'analysis': {
                    'trends': sections.get('trends', '트렌드 분석 결과가 없습니다.'),
                    'relations': sections.get('relations', '관계 분석 결과가 없습니다.'),
                    'insights': sections.get('insights', '주요 인사이트가 없습니다.')
                }
            }
        else:
            # 여기가 누락되어 있었음! 응답이 반환되지 않았을 것
            return {
                'success': True,
                'analysis': content.strip()
            }
            
    except Exception as e:
        logger.error(f"GPT 분석 중 오류 발생: {str(e)}")
        error_response = {
            'success': False,
            'analysis': {
                'trends': '분석 중 오류가 발생했습니다.',
                'relations': '분석 중 오류가 발생했습니다.',
                'insights': '분석 중 오류가 발생했습니다.'
            }
        }
        return error_response

async def analyze_news_with_gpt(article_text, max_tokens=150):
    """
    뉴스 기사 내용을 GPT로 분석하는 함수
    """
    try:
        analysis_prompt = f"""
        다음 뉴스 기사를 분석해주세요:

        {article_text}

        분석 요청:
        1. 핵심 내용 요약 (2-3줄):
        2. 주요 키워드 (콤마로 구분):
        3. 기사의 관점/톤 (1줄):
        """

        return await _get_gpt_response(
            analysis_prompt,
            temperature=0.3,
            max_tokens=max_tokens,
            split_sections=True
        )

    except Exception as e:
        logger.error(f"뉴스 분석 중 오류 발생: {str(e)}")
        return {
            'summary': '분석 중 오류가 발생했습니다.',
            'keywords': '분석 중 오류가 발생했습니다.',
            'perspective': '분석 중 오류가 발생했습니다.'
        }

def analyze_keywords_with_llm_sync(keywords_with_counts, titles, max_tokens=150):
    """동기 버전의 키워드 분석 함수"""
    return asyncio.run(analyze_keywords_with_llm(
        keywords_with_counts=keywords_with_counts,
        titles=titles,
        max_tokens=max_tokens
    ))
