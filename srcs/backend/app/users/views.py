from django.db import models
from django.db.models import Q
from django.contrib.auth import authenticate
from rest_framework import status
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.exceptions import AuthenticationFailed, NotFound
from rest_framework.generics import UpdateAPIView, RetrieveAPIView, ListAPIView
from .models import User, UserStats, Friend, BlacklistedToken
from .serializers import (UserRegistrationSerializer, UserProfileSerializer, 
                          UserProfileSearchSerializer, UserUpdateSerializer, 
                            UserStatsSerializer, FriendSerializer)
from .jwt_logic import generate_jwt, decode_jwt
from jwt.exceptions import ExpiredSignatureError, InvalidTokenError
from .session_id import generate_session_id
from django.utils import timezone
from datetime import timedelta

class UserRegistrationAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = UserRegistrationSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response({'message': 'User successfully registered.'}, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class UserLoginAPIView(APIView):
    permission_classes = [permissions.AllowAny]
    """
    Handles user authentication and returns JWT tokens upon success.
    """
    def post(self, request):
        # Extract username and password from the request
        username = request.data.get("username")
        password = request.data.get("password")

        if not username or not password:
            return Response({"error": "Username and password are required."}, status=status.HTTP_400_BAD_REQUEST)

        # Authenticate user
        user = authenticate(username=username, password=password)
        if not user:
            # Authentication failed
            return Response({"error": "Invalid credentials."}, status=status.HTTP_401_UNAUTHORIZED)
        
        # Check if the user already has an active session
        if user.active_session_id:
            # If the session is more than 10 minutes old, consider it expired
            inactivity_limit = timezone.now() - timedelta(minutes=10)
            if user.last_activity < inactivity_limit:
                # Session expired due to inactivity
                user.active_session_id = None
                user.save(update_fields=['active_session_id', 'last_activity'])
            else:
                return Response({"error": "You are already logged in on another device."}, status=status.HTTP_403_FORBIDDEN)
        
        session_id = generate_session_id()
        user.active_session_id = session_id
        user.update_last_activity()
        user.set_online()
        user.save(update_fields=['active_session_id', 'last_activity', 'online_status'])

        # Access token (15 minutes)
        access_payload = {
            "user_id": user.id,
            "username": user.username,
            "type": "access",
            "session_id": session_id
        }
        access_token = generate_jwt(access_payload, expiration_minutes=15, session_id=session_id)  # 15 minutes
        
        # Refresh token (7 days)
        refresh_payload = {
            "user_id": user.id,
            "type": "refresh",
            "session_id": session_id
        }
        refresh_token = generate_jwt(refresh_payload, expiration_minutes=7 * 24 * 60, session_id=session_id)  # 7 days
        
        return Response(
            {
                "access_token": access_token,
                "refresh_token": refresh_token
            },
            status=status.HTTP_200_OK
        )

class UserTokenRefreshAPIView(APIView):
    permission_classes = [permissions.AllowAny]
    """
    Handles refreshing of JWT tokens.
    """
    def post(self, request):
        refresh_token = request.data.get('refresh_token')
        if not refresh_token:
            return Response({"error": "Refresh token is required."}, status=status.HTTP_400_BAD_REQUEST)
        
        if BlacklistedToken.objects.filter(token=refresh_token).exists():
            return Response({"error": "This refresh token has been revoked."}, status=status.HTTP_401_UNAUTHORIZED)
    
        try:
            # Decode the refresh token
            payload = decode_jwt(refresh_token)
            if payload.get("type") != "refresh":
                return Response({"error": "Invalid token type."}, status=status.HTTP_400_BAD_REQUEST)

            # Fetch user and check the session ID
            user = User.objects.get(id=payload["user_id"])
            if user.active_session_id != payload.get("session_id"):
                return Response({"error": "Session mismatch. Please log in again."}, status=status.HTTP_400_BAD_REQUEST)

            # Generate new access token with the same session_id
            access_payload = {
                "user_id": user.id,
                "username": user.username,
                "type": "access",
                "session_id": user.active_session_id  # Use the current active session ID
            }
            access_token = generate_jwt(access_payload, expiration_minutes=15, session_id=user.active_session_id)
            
            return Response({"access_token": access_token}, status=status.HTTP_200_OK)
        except ExpiredSignatureError:
            return Response({"error": "Refresh token has expired."}, status=status.HTTP_401_UNAUTHORIZED)
        except InvalidTokenError:
            return Response({"error": "Invalid refresh token."}, status=status.HTTP_400_BAD_REQUEST)
        except User.DoesNotExist:
            return Response({"error": "User not found."}, status=status.HTTP_400_BAD_REQUEST)


# TODO: delete old revoked tokens from BlacklistedToken
class UserLogoutAPIView(APIView):
    def post(self, request):
        auth_header = request.headers.get('Authorization')
        refresh_token = request.data.get('refresh_token')

        if not auth_header:
            return Response({"error": "Access token is required."}, status=status.HTTP_400_BAD_REQUEST)
        if not refresh_token:
            return Response({"error": "Refresh token is required."}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            token_type, token = auth_header.split(' ')
            if token_type.lower() != 'bearer':
                raise AuthenticationFailed("Invalid token header format.")

            # Decode the refresh token to get user information
            payload = decode_jwt(refresh_token)
            if payload.get("type") != "refresh":
                return Response({"error": "Invalid token type."}, status=status.HTTP_400_BAD_REQUEST)

            # Get the user from the refresh token
            user = User.objects.get(id=payload["user_id"])

            # Ensure the session is still valid
            if user.active_session_id != payload.get("session_id"):
                return Response({"error": "Session mismatch. Please log in again."}, status=status.HTTP_400_BAD_REQUEST)

            # Reset the session_id and set user to offline
            user.active_session_id = None  # Reset session ID on logout
            user.set_offline()
            user.save(update_fields=['active_session_id', 'online_status'])

            # Blacklist both the access and refresh tokens
            BlacklistedToken.objects.create(token=token)
            BlacklistedToken.objects.create(token=refresh_token)

            return Response({"message": "Successfully logged out."}, status=status.HTTP_200_OK)

        except ExpiredSignatureError:
            return Response({"error": "One of the tokens has already expired."}, status=status.HTTP_400_BAD_REQUEST)
        except InvalidTokenError:
            return Response({"error": "Invalid token."}, status=status.HTTP_400_BAD_REQUEST)
        except User.DoesNotExist:
            return Response({"error": "User not found."}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

class UserSearchAPIView(ListAPIView):
    serializer_class = UserProfileSearchSerializer

    def get_queryset(self):
        current_user = self.request.user

        query = self.request.query_params.get('search', '').strip()

        if not query:
            return User.objects.none()

        return User.objects.filter(username__icontains=query).exclude(id=current_user.id)

    def list(self, request):
        queryset = self.get_queryset()

        if queryset.count() == 0 and not request.query_params.get('search', '').strip():
            return Response({"error": "Search query parameter is required."}, status=status.HTTP_400_BAD_REQUEST)

        if queryset.count() == 0:
            return Response({"error": "No users found matching the search query."}, status=status.HTTP_404_NOT_FOUND)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

class UserProfileAPIView(RetrieveAPIView):
    queryset = User.objects.all()
    serializer_class = UserProfileSerializer

    def get_serializer_context(self):
        return {'request': self.request}

    def get_object(self):
        user_id = self.kwargs.get('user_id')
        if user_id:
            try:
                return User.objects.get(id=user_id)
            except User.DoesNotExist:
                raise NotFound(detail="User not found.")
        return self.request.user

    def retrieve(self, request, *args, **kwargs):
        response = super().retrieve(request, *args, **kwargs)

        friend_id = self.kwargs.get('user_id')
        if friend_id and request.user.id != int(friend_id):
            try:
                friend_id = int(friend_id)
                friendship = Friend.objects.filter(
                    models.Q(user=request.user, friend_id=friend_id) |
                    models.Q(user_id=friend_id, friend=request.user)
                ).first()

                if friendship:
                    response.data['friendship_status'] = friendship.status
                else:
                    response.data['friendship_status'] = 'none'
            except (ValueError, Friend.DoesNotExist):
                response.data['friendship_status'] = 'none'     
        return response

class UserUpdateAPIView(UpdateAPIView):
    serializer_class = UserUpdateSerializer

    def get_object(self):
        return self.request.user

    def put(self):
        return Response({'error': 'PUT method is not allowed. Use PATCH instead.'},
            status=status.HTTP_405_METHOD_NOT_ALLOWED)

    def patch(self, request, **kwargs):
        partial = kwargs.pop('partial', True)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        return Response({"username": instance.username, 
            "avatar": instance.avatar}, status=status.HTTP_200_OK)

class UserStatsAPIView(RetrieveAPIView):
    queryset = UserStats.objects.all()
    serializer_class = UserStatsSerializer
    permission_classes = [permissions.AllowAny]

    def get_object(self):
        user_id = self.kwargs.get('user_id', None)
        if user_id:
            try:
                user = User.objects.get(id=user_id)
            except User.DoesNotExist:
                return Response({'error': 'User not found.'}, status=status.HTTP_404_NOT_FOUND)

            return user.stats
        return self.request.user.stats

class FriendListAPIView(ListAPIView):
    serializer_class = FriendSerializer

    def get_queryset(self):
        user_id = self.kwargs.get('user_id')
        if user_id:
            try:
                user = User.objects.get(id=user_id)
            except User.DoesNotExist:
                raise NotFound({'error': 'User not found.'})
        else:
            raise NotFound({'error': 'User ID is required.'})

        friendships = Friend.objects.filter((Q(user=user) | Q(friend=user)) & Q(status='accepted'))

        return [
            {'friend': friendship.friend if friendship.user == user else friendship.user}
            for friendship in friendships
        ]

class FriendshipAPIView(APIView):
    """
    API for managing friend requests and friendship statuses.
    """
    def post(self, request):
        """
        Send a friend request.
        """
        user = request.user
        friend_id = request.data.get('friend_id')

        if not friend_id:
            return Response({'error': 'Friend ID is required.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            friend = User.objects.get(id=friend_id)
        except User.DoesNotExist:
            return Response({'error': 'Friend not found.'}, status=status.HTTP_404_NOT_FOUND)

        # Check if the user is trying to add themselves as a friend
        if user == friend:
            return Response({'error': 'You cannot add yourself as a friend.'}, status=status.HTTP_400_BAD_REQUEST)

        # Check if friendship already exists in any direction (either accepted or pending)
        if Friend.objects.filter(user=user, friend=friend).exists() or Friend.objects.filter(user=friend, friend=user).exists():
            return Response({'message': 'Friendship request already exists or is already accepted.'}, status=status.HTTP_400_BAD_REQUEST)

        # Create the friendship if not exists
        friendship, created = Friend.add_friend(user, friend)
        if not created:
            return Response({'message': 'Friendship already exists or is pending.'}, status=status.HTTP_400_BAD_REQUEST)

        return Response({'message': 'Friendship request sent.'}, status=status.HTTP_201_CREATED)

    def delete(self, request, *args, **kwargs):
        """
        Delete a friend or cancel a friend request.
        """
        user = request.user
        friend_id = request.data.get('friend_id')

        if not friend_id:
            return Response({'error': 'Friend ID is required.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            friend = User.objects.get(id=friend_id)
        except User.DoesNotExist:
            return Response({'error': 'Friend not found.'}, status=status.HTTP_404_NOT_FOUND)

        # Try to delete the friendship
        try:
            friendship = Friend.objects.get((Q(user=user) & Q(friend=friend)) | 
                (Q(user=friend) & Q(friend=user)), status='accepted')
            friendship.delete()
            return Response({'message': 'Friendship deleted.'}, status=status.HTTP_200_OK)
        
        except Friend.DoesNotExist:
            return Response({'error': 'Friendship does not exist.'}, status=status.HTTP_400_BAD_REQUEST)
    
    def patch(self, request):
        """
        Accept or decline a friend request.
        """
        user = request.user
        friend_id = request.data.get('friend_id')
        action = request.data.get('action')  # 'accept' or 'decline'

        if not friend_id or not action:
            return Response({'error': 'Friend ID and action are required.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            friend = User.objects.get(id=friend_id)
        except User.DoesNotExist:
            return Response({'error': 'Friend not found.'}, status=status.HTTP_404_NOT_FOUND)

        try:
            friendship = Friend.objects.get(user=friend, friend=user, status='pending')
        except Friend.DoesNotExist:
            return Response({'error': 'Friendship request not found.'}, status=status.HTTP_404_NOT_FOUND)

        if action == 'accept':
            friendship.accept_friend()
            return Response({'message': 'Friendship request accepted.'}, status=status.HTTP_200_OK)
        elif action == 'decline':
            friendship.decline_friend()
            return Response({'message': 'Friendship request declined.'}, status=status.HTTP_200_OK)
        else:
            return Response({'error': 'Invalid action.'}, status=status.HTTP_400_BAD_REQUEST)

class FriendRequestsAPIView(ListAPIView):
    serializer_class = FriendSerializer

    def get_queryset(self):
        user = self.request.user
        return Friend.objects.filter(friend=user, status='pending')

    def list(self):
        queryset = self.get_queryset()

        if queryset.count() == 0:
            return Response({"error": "No friend requests found."}, status=status.HTTP_404_NOT_FOUND)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)