from django.urls import path

from .views import (
    DictionarySearchView,
    DictionaryDetailView,
    StudyCardView,
    StudyAnswerView,
    StudyProgressView,
    AdminStatsView,
    AdminWordDetailView,
    AdminImportHSKView,
    AdminUserListView,
    AdminConversationListView,
    AdminDataFilesView,
    UserLearningStatusView,
)

urlpatterns = [
    path("", DictionarySearchView.as_view(), name="dictionary"),
    path("search/", DictionarySearchView.as_view(), name="dictionary-search"),
    path("<int:pk>/", DictionaryDetailView.as_view(), name="dictionary-detail"),
    
    # Word CRUD
    path("words/", AdminWordDetailView.as_view(), name="admin-word-create"),
    path("words/<int:pk>/", AdminWordDetailView.as_view(), name="admin-word-manage"),

    # Admin Dashboard Endpoints
    path("admin/stats/", AdminStatsView.as_view(), name="admin-stats"),
    path("admin/import/", AdminImportHSKView.as_view(), name="admin-import"),
    path("admin/users/", AdminUserListView.as_view(), name="admin-users"),
    path("admin/users/<uuid:pk>/", AdminUserListView.as_view(), name="admin-user-detail"),
    path("admin/conversations/", AdminConversationListView.as_view(), name="admin-conversations"),
    path("admin/conversations/<int:pk>/", AdminConversationListView.as_view(), name="admin-conversation-detail"),
    path("admin/data-files/", AdminDataFilesView.as_view(), name="admin-data-files"),

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
        name="study-progress",
    ),
    path(
        "user/learning-status/",
        UserLearningStatusView.as_view(),
        name="user-learning-status",
    ),
]