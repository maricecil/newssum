from django import template
import re

register = template.Library()

@register.simple_tag
def is_duplicate(title, shown_titles):
    """단순 중복 체크"""
    if not shown_titles:  # 첫 번째 항목이면 중복 아님
        return False
        
    # 현재 제목과 이전에 표시된 제목들을 비교
    titles_list = shown_titles.split('|||')
    
    # 완전 일치만 검사
    return title in titles_list 