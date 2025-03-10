from urllib.parse import parse_qs
from jwt.exceptions import ExpiredSignatureError, InvalidTokenError
from django.contrib.auth.models import AnonymousUser
from channels.middleware import BaseMiddleware
from django.http import JsonResponse
from .models import User
from channels.db import database_sync_to_async
from .jwt_logic import decode_jwt
import logging

logger = logging.getLogger(__name__)

class TokenAuthMiddleware(BaseMiddleware):
    """
    Middleware for authentication via JWT token in WebSocket.
    """
    async def __call__(self, scope, receive, send):
        query_string = parse_qs(scope["query_string"].decode())
        token = query_string.get("token", [None])[0]

        if token:
            try:
                decoded_payload = decode_jwt(token)
                user_id = decoded_payload.get("user_id")
                if user_id:
                    user = await database_sync_to_async(User.objects.get)(id=user_id)
                    scope["user"] = user
                else:
                    scope["user"] = AnonymousUser()
            except (ExpiredSignatureError, InvalidTokenError):
                scope["user"] = AnonymousUser()
        else:
            scope["user"] = AnonymousUser()

        return await super().__call__(scope, receive, send)

class UpdateLastActivityMiddleware:
    """
    Middleware to update user's last activity and check online status.
    """
    EXEMPT_PATHS = [
        '/api/users/login/',
        '/api/users/register/',
        '/api/users/refresh-token/',
        '/api/users/forgot-password/',
        '/api/users/verify-reset-code/',
        '/api/users/reset-password/',
        '/api/games/match/start/',
        '/api/games/match/finish/',
        '/api/games/tournament/round/create-match/',
        '/api/games/tournament/update-status/',
        '/api/games/check-active-match/',
        '/api/games/check-active-tournament/',
    ]

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        response_check_online_status = self.handle_authenticated_user(request)

        if response_check_online_status:
            return response_check_online_status

        return response

    def handle_authenticated_user(self, request):
        """Checks the online status and updates the user's activity."""
        if request.path not in self.EXEMPT_PATHS:
            if request.user.is_authenticated:
                if not getattr(request.user, 'online_status', False):
                    return JsonResponse(
                        {"detail": "Network error. Please try again later."},
                        status=403
                    )
                request.user.update_last_activity()
        return None


