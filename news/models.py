from django.db import models
from django.utils import timezone
from datetime import timedelta

class Keyword(models.Model):
    name = models.CharField(max_length=100, unique=True, verbose_name='키워드')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='생성일')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='수정일')

    class Meta:
        verbose_name = '키워드'
        verbose_name_plural = '키워드 목록'
        ordering = ['-created_at']

    def __str__(self):
        return self.name

class Article(models.Model):
    title = models.CharField(max_length=200, verbose_name='제목')
    url = models.URLField(verbose_name='기사 링크')
    source = models.CharField(max_length=50, verbose_name='언론사')
    published_at = models.DateTimeField(verbose_name='발행일')
    summary = models.TextField(null=True, blank=True, verbose_name='요약')
    content = models.TextField(null=True, blank=True, verbose_name='본문')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='생성일')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='수정일')
    keywords = models.ManyToManyField(Keyword, related_name='articles', verbose_name='키워드')

    class Meta:
        verbose_name = '기사'
        verbose_name_plural = '기사 목록'
        ordering = ['-published_at']
        indexes = [
            models.Index(fields=['-published_at']),
            models.Index(fields=['title']),
        ]

    def __str__(self):
        return self.title

    @classmethod
    def cleanup_old_articles(cls):
        threshold = timezone.now() - timedelta(minutes=30)
        cls.objects.filter(created_at__lt=threshold).delete()

class NewsSummary(models.Model):
    keyword = models.CharField(max_length=100)
    crawled_time = models.DateTimeField()
    created_at = models.DateTimeField(default=timezone.now)
    articles = models.JSONField()  # 관련 기사 데이터
    analysis = models.JSONField()  # 분석 결과 데이터
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['keyword']),
            models.Index(fields=['created_at']),
        ]
    
    def __str__(self):
        return f"{self.keyword} - {self.created_at.strftime('%Y-%m-%d %H:%M')}" 

    @classmethod
    def cleanup_old_summaries(cls):
        threshold = timezone.now() - timedelta(minutes=30)
        cls.objects.filter(created_at__lt=threshold).delete()