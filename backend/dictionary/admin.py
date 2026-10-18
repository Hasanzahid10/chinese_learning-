from django.contrib import admin
from .models import HSKWord, StudyProgress

@admin.register(HSKWord)
class HSKWordAdmin(admin.ModelAdmin):
    list_display = ('id', 'chinese', 'pinyin', 'english', 'bangla', 'hsk_level')
    list_filter = ('hsk_level',)
    search_fields = ('chinese', 'pinyin', 'english', 'bangla')

@admin.register(StudyProgress)
class StudyProgressAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'word', 'is_learned', 'correct_count', 'wrong_count', 'next_review')
    list_filter = ('is_learned',)
    search_fields = ('user__username', 'word__chinese')
