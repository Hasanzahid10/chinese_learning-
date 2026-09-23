from django.urls import path

from .views import (
    DictionarySearchView,
    DictionaryDetailView,
    StudyCardView,
    StudyAnswerView,
    StudyProgressView,
)

urlpatterns = [
    path("", DictionarySearchView.as_view(), name="dictionary"),
    path("search/", DictionarySearchView.as_view(), name="dictionary-search"),
    path("<int:pk>/", DictionaryDetailView.as_view(), name="dictionary-detail"),
    # Study
    path(
        "study/",
        StudyCardView.as_view(),
        name="study-card",
    ),

    path(
        "study/answer/",
        StudyAnswerView.as_view(),
        name="study-answer",
    ),

    path(
        "study/progress/",
        StudyProgressView.as_view(),
        name="study-progress"),
]