from django.urls import path
from tournaments import views

urlpatterns = [
    # Turniere URLs
    path('', views.tournament_list, name='tournament_list'),
    path('<slug:slug>/', views.tournament_detail, name='tournament_detail'),
    path('<slug:slug>/register/', views.tournament_register, name='tournament_register'),
    path('<slug:slug>/unregister/', views.tournament_unregister, name='tournament_unregister'),
    path('<slug:slug>/generate-bracket/', views.tournament_generate_bracket, name='tournament_generate_bracket'),
    path('matches/<int:match_id>/update-score/', views.match_update_score, name='match_update_score'),
    path('matches/<int:match_id>/update-ffa-score/', views.match_update_ffa_score, name='match_update_ffa_score'),

    # Teams URLs
    path('teams/all/', views.team_list, name='team_list'),
    path('teams/create/', views.team_create, name='team_create'),
    path('teams/join-code/', views.team_join_by_code, name='team_join_by_code'),
    path('teams/<slug:slug>/', views.team_detail, name='team_detail'),
    path('teams/<slug:slug>/reactivate/', views.team_reactivate, name='team_reactivate'),
    path('teams/<slug:slug>/leave/', views.team_leave, name='team_leave'),
    path('teams/<slug:slug>/kick/<int:user_id>/', views.team_kick_member, name='team_kick_member'),
    path('teams/<slug:slug>/apply/', views.team_apply, name='team_apply'),
    path('teams/<slug:slug>/accept/<int:membership_id>/', views.team_accept_membership, name='team_accept_membership'),

]
