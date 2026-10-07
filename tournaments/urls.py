from django.urls import path
from tournaments import views
from tournaments import team_views

urlpatterns = [
    # Turniere URLs
    path('', views.tournament_list, name='tournament_list'),
    path('<slug:slug>/', views.tournament_detail, name='tournament_detail'),
    path('<slug:slug>/open-registration/', views.tournament_open_registration, name='tournament_open_registration'),
    path('<slug:slug>/close-registration/', views.tournament_close_registration, name='tournament_close_registration'),
    path('<slug:slug>/confirm-results/', views.tournament_confirm_results, name='tournament_confirm_results'),
    path('<slug:slug>/release-playoffs/', views.tournament_release_playoffs, name='tournament_release_playoffs'),
    path('<slug:slug>/register/', views.tournament_register, name='tournament_register'),
    path('<slug:slug>/unregister/', views.tournament_unregister, name='tournament_unregister'),
    path('<slug:slug>/generate-bracket/', views.tournament_generate_bracket, name='tournament_generate_bracket'),
    path('<slug:slug>/swiss/preview/', views.tournament_swiss_preview, name='tournament_swiss_preview'),
    path('<slug:slug>/swiss/publish/', views.tournament_swiss_publish, name='tournament_swiss_publish'),
    path('<slug:slug>/swiss/withdraw/<int:team_id>/', views.tournament_swiss_withdraw, name='tournament_swiss_withdraw'),
    path('matches/<int:match_id>/update-score/', views.match_update_score, name='match_update_score'),
    path('matches/<int:match_id>/start/', views.match_start, name='match_start'),
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
    path('teams/<slug:slug>/add-clan/', team_views.team_add_clan_members, name='team_add_clan_members'),
    path('teams/<slug:slug>/recruit/', team_views.team_recruit_player, name='team_recruit_player'),
    path('teams/<slug:slug>/invitations/<int:invitation_id>/accept/', team_views.team_accept_invitation, name='team_accept_invitation'),
    path('teams/<slug:slug>/invitations/<int:invitation_id>/decline/', team_views.team_decline_invitation, name='team_decline_invitation'),
    path('teams/<slug:slug>/invitations/<int:invitation_id>/withdraw/', team_views.team_withdraw_invitation, name='team_withdraw_invitation'),
    path('teams/<slug:slug>/reject/<int:membership_id>/', team_views.team_reject_application, name='team_reject_application'),

]
