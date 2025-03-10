from django.urls import path
from .views import (UserRegistrationAPIView, UserLoginAPIView,
    UserLogoutAPIView, UserProfileAPIView, UserUpdateAPIView,
    UserStatsAPIView, FriendshipAPIView, FriendListAPIView,
    UserSearchAPIView, UserTokenRefreshAPIView, FriendRequestsAPIView)
from .two_factor_auth.TwoFA_views import (TwoFA_ActivateAPIView, TwoFA_DeactivateAPIView, 
                                          TwoFA_VerifyAPIView, TwoFA_VerifyDeactivateAPIView, 
                                          LoginWith2FA_APIView, Is2FAEnabled)

from .gdpr_views import UserDataExport, UserDeleteAccount, UserResetPassword, UserForgotPassword, UserVerifyResetCode

urlpatterns = [
    path('register/', UserRegistrationAPIView.as_view(), name='register'),
    path('login/', UserLoginAPIView.as_view(), name='login'),
    path('token-refresh/', UserTokenRefreshAPIView.as_view(), name='token-refresh'),
    path('logout/', UserLogoutAPIView.as_view(), name='logout'),
    path('search-profile/', UserSearchAPIView.as_view(), name='user-search'),
    path('profile/<int:user_id>/', UserProfileAPIView.as_view(), name='view-profile'),
    path('stats/<int:user_id>/', UserStatsAPIView.as_view(), name='view-user-stats'),
    path('update/', UserUpdateAPIView.as_view(), name='update'),
    path('friends/<int:user_id>/', FriendListAPIView.as_view(), name='friends-list'),
    path('friendship/', FriendshipAPIView.as_view(), name='friendship'),
    path('friendship-requests/', FriendRequestsAPIView.as_view(), name='friend-requests'),
    path('2fa/setup/', TwoFA_ActivateAPIView.as_view(), name='2fa-activate'),
    path('2fa/remove/', TwoFA_DeactivateAPIView.as_view(), name='2fa-deactivate'),
    path('2fa/verify/', TwoFA_VerifyAPIView.as_view(), name='2fa-verify'),
    path('2fa/verify-remove/', TwoFA_VerifyDeactivateAPIView.as_view(), name='2fa-verify-deactivate'),
    path('login/with-2fa/', LoginWith2FA_APIView.as_view(), name='2fa-login'),

    path('data-export/', UserDataExport.as_view(), name='data-export'),
    path('delete-account/', UserDeleteAccount.as_view(), name='delete-account'),
    
    path('forgot-password/', UserForgotPassword.as_view(), name='forgot-password'),
    path('verify-reset-code/', UserVerifyResetCode.as_view(), name='verify-reset-code'),
    path('reset-password/', UserResetPassword.as_view(), name='reset-password'),
    path('is-2fa-enabled/', Is2FAEnabled.as_view(), name='is-2fa-enabled'),
]
