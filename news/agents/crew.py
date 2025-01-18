from crewai import Agent, Task, Crew
from typing import List, Dict, Tuple
import logging
from datetime import datetime
from langchain_openai import OpenAI
from collections import Counter
from langchain.schema import HumanMessage, SystemMessage
import requests
from bs4 import BeautifulSoup
import os
from langchain_community.chat_models import ChatOpenAI

logger = logging.getLogger(__name__)

def summarize_article(url):
    """
    뉴스 기사 URL을 받아서 내용을 요약하는 함수
    """
    try:
        # 1. URL에서 기사 내용 가져오기
        response = requests.get(url)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # 네이버 뉴스 기사 본문 찾기
        article_body = soup.select_one('#dic_area')
        if not article_body:
            return "기사 내용을 찾을 수 없습니다."
        
        content = article_body.get_text().strip()
        
        # 2. GPT를 사용하여 요약
        llm = ChatOpenAI(
            model_name="gpt-3.5-turbo",
            temperature=0.5,
            max_tokens=300
        )
        
        system_message = """
        당신은 뉴스 기사를 간단명료하게 요약하는 전문가입니다.
        주어진 뉴스 기사를 3줄로 요약해주세요.
        핵심 내용만 추출하여 객관적으로 작성해주세요.
        """
        
        messages = [
            SystemMessage(content=system_message),
            HumanMessage(content=f"다음 뉴스 기사를 요약해주세요:\n\n{content[:2000]}")  # 첫 2000자만 사용
        ]
        
        response = llm.invoke(messages)
        summary = response.content
        
        return summary
        
    except Exception as e:
        print(f"요약 중 오류 발생: {str(e)}")
        return "기사 요약 중 오류가 발생했습니다."

class NewsAnalysisCrew:
    def __init__(self):
        self.llm = OpenAI(
            temperature=0.3,
            model_name="gpt-3.5-turbo",
            max_tokens=1000,
        )
    
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
        # 1. 뉴스 분류 에이전트
        classifier = Agent(
            role='뉴스 분류 전문가',
            goal='유사한 관점과 내용의 뉴스를 그룹화하고 분류',
            backstory=f"""
            당신은 뉴스 기사들의 관점과 내용을 분석하여 그룹화하는 전문가입니다.
            1. 유사한 관점을 가진 기사들을 그룹화
            2. 각 그룹의 대표적 특징 파악
            3. 시간순으로 사건 흐름 정리
            4. 중복된 내용 필터링
            반드시 한국어로 응답해야 합니다.
            """,
            llm=self.llm,
            verbose=True,
            language="Korean"
        )
        
        # 2. 관점 비교 분석가
        comparator = Agent(
            role='관점 비교 분석가',
            goal='각 언론사의 보도 관점 차이와 특징 분석',
            backstory=f"""
            서로 다른 관점을 가진 보도들을 비교 분석하는 전문가입니다.
            1. 같은 사건에 대한 다른 시각 비교
            2. 각 언론사의 강조점 파악
            3. 보도 논조의 차이점 분석
            4. 객관적 사실과 주관적 해석 구분
            현재 분석 대상: {", ".join(press_stats.keys()) if press_stats else "전체 언론사"}
            """,
            llm=self.llm,
            verbose=True,
            language="Korean"
        )
        
        # 3. 통합 요약 작성자
        summarizer = Agent(
            role='통합 요약 전문가',
            goal='다양한 관점을 통합하여 균형잡힌 요약 작성',
            backstory="""
            여러 관점의 뉴스를 통합하여 균형잡힌 요약을 만드는 전문가입니다.
            1. 핵심 사실 중심의 요약
            2. 상반된 관점들의 균형있는 통합
            3. 시간순 사건 전개 정리
            4. 중복 내용 제거 및 간결한 정리
            편향되지 않은 객관적인 시각을 유지합니다.
            """,
            llm=self.llm,
            verbose=True,
            language="Korean"
        )
        
        return [classifier, comparator, summarizer]
    
    def create_tasks(self, agents: List[Agent], news_data: List[Dict], ranked_keywords: List[str]) -> List[Task]:
        """
        이미 랭킹된 키워드와 기사들을 기반으로 분석 태스크 생성
        
        Args:
            ranked_keywords: 이미 집계된 상위 10개 키워드 리스트
            news_data: 각 언론사별 주요 기사 데이터
        """
        news_summary = {
            'total_articles': len(news_data),
            'companies': list(set(item['company_name'] for item in news_data)),
            'ranked_keywords': ranked_keywords
        }
        
        # 1. 데이터 수집 및 분류 태스크
        collection_task = Task(
            description=f"""
            다음 주요 키워드에 대한 언론사별 보도 경향을 분석해주세요:
            
            분석 대상:
            - 주요 키워드: {', '.join(news_summary['ranked_keywords'])}
            - 분석 대상 언론사: {', '.join(news_summary['companies'])}
            
            분석 요구사항:
            1. 각 키워드별 언론사들의 관점 차이 분석
            2. 언론사별 주요 관심사와 보도 특징 요약
            
            결과는 다음 형식으로 반환:
            {{
                "키워드_분석": {{
                    "키워드명": {{
                        "주요_보도_언론사": ["언론사1", "언론사2"],
                        "관점_차이": "해당 키워드를 바라보는 언론사별 시각과 관점 차이"
                    }}
                }}
            }}
            """,
            expected_output="키워드별 언론사의 관점 차이가 포함된 분석 결과",
            agent=agents[0]
        )
        
        # 2. 언론사별 보도 경향 분석 태스크
        analysis_task = Task(
            description="""
            1. 각 언론사의 보도 관점과 논조 분석
            2. 같은 사안에 대한 언론사별 시각 차이 비교
            3. 사용된 표현과 어조의 특징 분석
            4. 중점적으로 다루는 측면과 생략된 부분 파악
            
            분석 결과를 구체적인 예시와 함께 설명해주세요.
            """,
            expected_output="언론사별 보도 경향과 관점 차이에 대한 상세 분석 결과",
            agent=agents[1]
        )
        
        # 3. 종합 보고서 작성 태스크
        report_task = Task(
            description="""
            1. 데이터 수집 결과와 분석 내용을 종합
            2. 주요 발견 사항을 객관적으로 정리
            3. 언론사별 특징과 차이점을 중립적 관점에서 서술
            4. 전체적인 보도 동향에 대한 인사이트 도출
            
            최종 보고서 형태로 작성해주세요.
            """,
            expected_output="객관적인 관점에서 작성된 종합 분석 보고서",
            agent=agents[2]
        )
        
        return [collection_task, analysis_task, report_task]
    
    async def run_analysis(self, news_data: List[Dict], press_stats: Dict = None) -> Dict:
        try:
            # press_stats 정보를 agents에 전달
            agents = self.create_agents(press_stats)
            tasks = self.create_tasks(agents, news_data, press_stats)
            
            crew = Crew(
                agents=agents,
                tasks=tasks,
                verbose=True,
                max_iterations=3
            )
            
            result = crew.kickoff()
            
            # 결과가 잘린 경우 재시도 로직
            def retry_with_shorter_prompt(result):
                if isinstance(result, str) and len(result) >= 3500:
                    shorter_news_data = news_data[:5]
                    agents = self.create_agents()
                    tasks = self.create_tasks(agents, shorter_news_data)
                    crew = Crew(agents=agents, tasks=tasks, verbose=True)
                    return crew.kickoff()
                return result

            # 첫 시도에서 잘린 경우 재시도
            if isinstance(result, str) and len(result) >= 3500:
                result = retry_with_shorter_prompt(result)
            
            # 결과 처리 - 항상 일관된 형식 반환
            response = {
                'success': True,
                'analysis': {
                    'summary': str(result) if isinstance(result, (str, dict)) else '',
                    'analyzed_articles': len(news_data),
                    'timestamp': datetime.now().isoformat()
                }
            }
            
            return response
            
        except Exception as e:
            logger.error(f"CrewAI 분석 중 오류 발생: {str(e)}")
            return {
                'success': False,
                'error': '분석 중 오류가 발생했습니다.',
                'detail': str(e),
                'analyzed_articles': len(news_data),
                'timestamp': datetime.now().isoformat()
            } 
        
        