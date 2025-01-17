from crewai import Agent, Task, Crew
from typing import List, Dict, Tuple
import logging
from datetime import datetime
from langchain_openai import OpenAI
from collections import Counter

logger = logging.getLogger(__name__)

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

    def create_agents(self):
        # 1. 데이터 수집가 에이전트 (기존 데이터 정리)
        collector = Agent(
            role='데이터 수집가',
            goal='언론사별 기사 데이터 분류 및 핵심 정보 추출',
            backstory="""
            당신은 뉴스 데이터를 분석하는 전문가입니다.
            주어진 기사들을 언론사별로 분류하고, 각 기사의 핵심 키워드를 추출하여
            전체적인 보도 동향을 파악합니다.
            반드시 한국어로 응답해야 합니다.
            """,
            llm=self.llm,
            verbose=True,
            language="Korean"
        )
        
        # 2. 언론사 분석가 에이전트 (관점과 경향성 분석)
        analyst = Agent(
            role='언론사 분석가',
            goal='언론사별 보도 경향과 관점 차이 분석',
            backstory="""언론사의 보도 성향과 관점 차이를 분석하는 전문가.
                     같은 사안에 대한 다른 시각과 표현 방식을 비교 분석합니다.""",
            llm=self.llm,
            verbose=True,
            language="Korean"
        )
        
        # 3. 종합 보고서 작성 에이전트 (객관적 정리)
        reporter = Agent(
            role='보고서 작성자',
            goal='분석 결과를 객관적으로 정리하여 종합 보고서 작성',
            backstory="""복잡한 분석 결과를 명확하고 이해하기 쉽게 정리하는 전문가.
                     편향 없이 객관적인 관점에서 종합적인 인사이트를 도출합니다.""",
            llm=self.llm,
            verbose=True,
            language="Korean"
        )
        
        return [collector, analyst, reporter]
    
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
    
    def run_analysis(self, news_data: List[Dict]) -> Dict:
        try:
            # ranked_keywords 추출 (news_data에서 이미 랭킹된 키워드 가져오기)
            ranked_keywords = [item['keyword'] for item in news_data[0].get('ranked_keywords', [])]
            
            agents = self.create_agents()
            tasks = self.create_tasks(agents, news_data, ranked_keywords)  # ranked_keywords 전달
            
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
        
        