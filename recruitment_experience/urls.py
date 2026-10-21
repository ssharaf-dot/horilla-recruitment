from django.urls import path
from . import views

urlpatterns = [
    path('recruitment/workspace/', views.today, name='workspace-today'),
    path('recruitment/workspace/jobs/', views.jobs, name='workspace-jobs'),
    path('recruitment/workspace/jobs/<int:pk>/', views.job, name='workspace-job'),
    path('recruitment/workspace/candidates/', views.candidates, name='workspace-candidates'),
    path('recruitment/workspace/candidates/<int:pk>/', views.candidate, name='workspace-candidate'),
    path('recruitment/workspace/candidates/<int:pk>/stage/', views.stage, name='workspace-stage'),
    path('recruitment/workspace/candidates/<int:pk>/review/', views.review, name='workspace-review'),
    path('recruitment/workspace/reviews/<int:pk>/complete/', views.review_complete, name='workspace-review-complete'),
    path('recruitment/workspace/candidates/<int:pk>/schedule/', views.schedule, name='workspace-schedule'),
    path('recruitment/workspace/candidates/<int:pk>/cv/', views.candidate_cv, name='workspace-cv'),
    path('recruitment/workspace/interviews/', views.interviews, name='workspace-interviews'),
    path('recruitment/workspace/interviews/<int:pk>/feedback/', views.feedback, name='workspace-feedback'),
    path('recruitment/workspace/manager/', views.manager, name='workspace-manager'),
    path('recruitment/workspace/leadership/', views.ceo, name='workspace-ceo'),
    path('recruitment/workspace/hiring-requests/', views.hiring_request, name='workspace-requests'),
    path('recruitment/workspace/hiring-requests/<int:pk>/decision/', views.decide, name='workspace-decide'),
    path('recruitment/workspace/applicant-preview/<int:pk>/', views.applicant_preview, name='workspace-applicant-preview'),
    path('careers/account/', views.applicant_home, name='applicant-home'),
    path('careers/account/sign-in/', views.applicant_login, name='applicant-login'),
    path('careers/account/create/', views.applicant_register, name='applicant-register'),
    path('careers/account/sign-out/', views.applicant_logout, name='applicant-logout'),
    path('careers/account/applications/<int:pk>/', views.applicant_detail, name='applicant-detail'),
    path('careers/account/applications/<int:pk>/questionnaire/', views.applicant_questionnaire, name='applicant-questionnaire'),
    path('careers/account/applications/<int:pk>/cv/', views.applicant_cv, name='applicant-cv'),
]
