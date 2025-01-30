import logging
import requests
from bs4 import BeautifulSoup
from langchain_openai import ChatOpenAI
from langchain.schema import HumanMessage, SystemMessage
from typing import List, Dict
from datetime import datetime

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

def summarize_article(url):
    """단일 기사 요약 함수"""
    summaries = summarize_articles([url])
    return summaries.get(url, "기사 요약 중 오류가 발생했습니다.")

async def run_analysis(news_data: List[Dict], press_stats: Dict = None) -> Dict:
    """뉴스 데이터 분석 함수"""
    try:
        if not news_data:
            return {
                'success': False,
                'error': '분석할 뉴스 데이터가 없습니다.',
                'analyzed_articles': 0,
                'timestamp': datetime.now().isoformat()
            }
        
        # GPT 분석 사용
        article_list = "\n".join([
            f"제목: {article['title']}\n"
            f"언론사: {article.get('company_name', '알 수 없음')}\n"
            f"요약: {article.get('summary', '요약 없음')}\n"
            for article in news_data
        ])
        
        llm = ChatOpenAI(
            temperature=0.3,
            model_name="gpt-3.5-turbo-16k",
            max_tokens=4000,
        )
        
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
        
        response = llm.generate([messages])
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
        
        