from crewai import Agent, Task, Crew
from typing import List, Dict, Tuple
import logging
from datetime import datetime
from langchain_openai import ChatOpenAI
from collections import Counter
from langchain.schema import HumanMessage, SystemMessage
import requests
from bs4 import BeautifulSoup
import os
from langchain_community.chat_models import ChatOpenAI
from pprint import pformat  # 복잡한 객체를 보기 좋게 출력하기 위해 추가
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export import ConsoleSpanExporter

logger = logging.getLogger(__name__)

def summarize_articles(urls, batch_size=5):
    """여러 기사를 배치로 나누어 요약하는 함수"""
    try:
        # 1. URL 목록을 배치로 나누기
        batches = [urls[i:i + batch_size] for i in range(0, len(urls), batch_size)]
        all_summaries = {}
        
        # 2. 각 배치별로 기존 summarize_article 로직 실행
        for batch_urls in batches:
            batch_content = []
            
            # 2.1 배치 내 각 URL의 내용 수집
            for url in batch_urls:
                response = requests.get(url)
                soup = BeautifulSoup(response.text, 'html.parser')
                article_body = soup.select_one('#dic_area')
                
                if article_body:
                    content = article_body.get_text().strip()
                    batch_content.append(f"{content[:2000]}")
            
            # 2.2 배치 내용 한번에 요약
            llm = ChatOpenAI(
                model_name="gpt-3.5-turbo-16k",
                temperature=0.5,
                max_tokens=300
            )
            
            system_message = """
            당신은 뉴스 기사를 간단명료하게 요약하는 전문가입니다.
            주어진 뉴스 기사를 3줄로 요약해주세요.(180자 이내)
            핵심 내용만 추출하여 객관적으로 작성해주세요.
            """
            
            messages = [
                SystemMessage(content=system_message),
                HumanMessage(content="\n".join(batch_content))
            ]
            
            response = llm.generate([messages])
            summaries = response.generations[0][0].text.split("\n\n")
            
            # 2.3 URL과 요약 매핑
            for url, summary in zip(batch_urls, summaries):
                all_summaries[url] = summary.strip()
        
        return all_summaries
        
    except Exception as e:
        logger.error(f"요약 중 오류 발생: {str(e)}")
        return {}

# 기존 함수는 유지하고 배치 처리 함수 호출
def summarize_article(url):
    summaries = summarize_articles([url])
    return summaries.get(url, "기사 요약 중 오류가 발생했습니다.")

class NewsAnalysisCrew:
    def __init__(self, agents=None, tasks=None, verbose=False):
        # OpenTelemetry 설정 비활성화
        os.environ["OTEL_PYTHON_DISABLED"] = "true"
        
        self.llm = ChatOpenAI(
            temperature=0.3,
            model_name="gpt-3.5-turbo-16k",  # 16k 컨텍스트 윈도우를 가진 모델로 변경
            max_tokens=4000,  # 토큰 제한 증가
        )
        # CrewOutput 초기화 시 기본 구조 확보
        self.output = {
            "0": None,  # 기본값 설정
            "final": None
        }
        self.agents = agents or []
        self.tasks = tasks or []
        self.verbose = verbose
    
    def get_top_keywords(self, news_data: List[Dict], limit: int = 10) -> List[Tuple[str, int]]:
        """뉴스 데이터에서 상위 키워드와 출현 빈도를 추출"""
        keyword_counter = Counter()
        
        for item in news_data:
            # 제목과 내용에서 키워드 추출
            title_keywords = item.get('keywords', [])
            content_keywords = item.get('content_keywords', [])
            
            # 키워드 카운트 업데이트
            keyword_counter.update(title_keywords)
            keyword_counter.update(content_keywords)
        
        # 상위 N개 키워드 반환 (키워드, 빈도수)
        return keyword_counter.most_common(limit)

    def format_keyword_analysis(self, top_keywords: List[Tuple[str, int]]) -> str:
        """키워드 분석 결과를 포맷팅"""
        keywords_str = '\n'.join([
            f"- {keyword}: {count}건" 
            for keyword, count in top_keywords
        ])
        return f"주요 키워드 (Top {len(top_keywords)}):\n{keywords_str}"

    def create_agents(self, press_stats=None):
        try:
            logger.info("=== Agent 생성 시작 ===")
            
            # press_stats 정보는 그대로 유지
            press_stats_info = ""
            if press_stats:
                press_stats_info = f"""
                언론사별 통계 정보:
                - 총 기사 수: {press_stats.get('total_articles', 0)}
                - 참여 언론사: {', '.join(press_stats.get('companies', []))}
                - 주요 키워드: {', '.join(press_stats.get('keywords', []))}
                """
            
            classifier = Agent(
                role='뉴스 분류 전문가',
                goal='GPT가 요약한 기사들을 관점별로 분류',
                backstory=f"""
                당신은 GPT가 1차 요약한 뉴스 기사들을 다시 분석하여 분류하는 전문가입니다.
                1. 각 그룹의 주요 프레임 파악
                2. 보도 논조별 분류 (비판적/중립적/우호적)
                3. 각 분류별 대표적 특징 정리
                {press_stats_info}
                """,
                llm=self.llm,
                verbose=True,
                language="Korean"
            )
            
            # 3. 관점 비교 분석가
            comparator = Agent(
                role='관점 비교 분석가',
                goal='언론사별 보도 관점 비교 분석',
                backstory="""
                당신은 같은 사안에 대한 언론사별 보도 관점을 비교 분석하는 전문가입니다.
                1. 언론사별 보도 프레임 차이점 분석
                2. 사용된 표현과 어조의 특징 파악
                3. 중점적으로 다루는 측면과 생략된 부분 비교
                """,
                llm=self.llm,
                verbose=True,
                language="Korean"
            )
            
            # 4. 통합 요약 작성자
            summarizer = Agent(
                role='통합 요약 전문가',
                goal='분석 결과를 종합하여 최종 요약 작성',
                backstory="""
                분류와 비교 분석 결과를 종합하여 최종 요약을 작성하는 전문가입니다.
                1. 객관적 사실 정리 (200자)
                2. 주요 쟁점 요약 (200자)
                3. 전체 보도 경향 분석 (200자)
                """,
                llm=self.llm,
                verbose=True,
                language="Korean"
            )
            
            agents = [classifier, comparator, summarizer]
            logger.info(f"생성된 Agent 수: {len(agents)}")
            
            # Agent와 Task 생성 함수를 함께 반환
            return {
                'agents': agents,
                'create_task': self.create_task
            }
            
        except Exception as e:
            logger.error("=== Agent 생성 중 오류 발생 ===")
            logger.error(f"오류 메시지: {str(e)}")
            logger.error(f"오류 타입: {type(e)}")
            import traceback
            logger.error(f"상세 오류: {traceback.format_exc()}")
            raise

    def create_task(self, agent, articles, task_type='classification'):
        """Task를 생성하는 헬퍼 메서드"""
        task_descriptions = {
            'classification': """
                모든 기사를 종합적으로 분석하여 관점별로 분류해주세요:
                1. 보도 관점 (긍정/부정/중립)
                2. 주요 프레임과 각 프레임별 대표 기사
                3. 핵심 쟁점과 관련 기사
            """,
            'comparison': """
                모든 기사의 언론사별 보도 관점을 비교 분석해주세요:
                1. 언론사별 프레임 차이와 구체적 사례
                2. 표현과 어조의 특징 및 대표적 예시
                3. 중점적으로 다루는 측면과 생략된 부분 비교
            """,
            'summary': """
                전체 기사를 종합적으로 분석하여 요약해주세요:
                1. 객관적 사실 정리 (300자)
                2. 주요 쟁점과 대립점 요약 (300자)
                3. 전체 보도 경향과 시사점 (300자)
            """
        }

        article_list = "\n".join([
            f"제목: {article['title']}\n"
            f"언론사: {article.get('source', '알 수 없음')}\n"
            f"요약: {article.get('summary', '요약 없음')}\n"
            for article in articles  # 기사 수 제한 제거
        ])

        return Task(
            description=f"{task_descriptions.get(task_type)}\n\n분석할 기사:\n{article_list}",
            agent=agent,
            expected_output=f"{task_type} 분석 결과"
        )

    async def run_analysis(self, news_data: List[Dict], press_stats: Dict = None) -> Dict:
        try:
            if not news_data:
                return {
                    'success': False,
                    'error': '분석할 뉴스 데이터가 없습니다.',
                    'analyzed_articles': 0,
                    'timestamp': datetime.now().isoformat()
                }
            
            # CrewAI 대신 직접 GPT 분석 사용
            article_list = "\n".join([
                f"제목: {article['title']}\n"
                f"언론사: {article.get('company_name', '알 수 없음')}\n"
                f"요약: {article.get('summary', '요약 없음')}\n"
                for article in news_data
            ])
            
            system_prompt = """
            모든 참여 언론사의 기사를 빠짐없이 분석하여 다음 형식으로 정리해주세요:

            보도 관점 분석
            - [언론사명] 구체적 보도 프레임과 사용된 표현 분석
            - 예시) "조선일보는 'A정책 실패' 강조, 한겨레는 'B정책 성과' 부각"

            주요 쟁점 분석
            - 언론사별 대립되는 시각과 근거
            - 예시) "동아일보와 경향신문은 [특정 사안]에 대해 상반된 입장"

            종합 분석
            - 전체 보도 경향의 특징
            - 각 언론사의 관점 차이가 두드러진 부분
            - 독자들이 균형있게 볼 수 있는 관점 제시

            ※ 언론사 이름을 구체적으로 명시하고, 실제 사용된 표현을 인용하여 분석해주세요.
            ※ 중립적이고 객관적인 톤으로 작성해주세요.
            ※ 언론사는 중복 없이 분석해주세요.
            """
            
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=article_list)
            ]
            
            response = self.llm.generate([messages])
            result = response.generations[0][0].text
            parts = result.split('\n\n', 2)
            
            return {
                'success': True,
                'classification': parts[0] if len(parts) > 0 else '분류 결과 없음',
                'comparison': parts[1] if len(parts) > 1 else '비교 분석 결과 없음',
                'summary': parts[2] if len(parts) > 2 else '요약 결과 없음',
                'analyzed_articles': len(news_data),
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"뉴스 분석 중 오류 발생: {str(e)}")
            return {
                'success': False,
                'error': '분석 중 오류가 발생했습니다.',
                'detail': str(e),
                'analyzed_articles': len(news_data),
                'timestamp': datetime.now().isoformat()
            } 
        
        