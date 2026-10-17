import secrets
import requests
from django.conf import settings
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib import messages
from django.contrib.auth import login
from apps.organization.models import User
from .decorators import get_home_url_for_user

SAMPLE_GOOGLE_EMAILS = [
    "systemdeveloper@ausindia.org",
    "shivkumar.kanaje@ausindia.org",
    "harshad.thorat@ausindia.org",
    "avadhutjagtap1341@gmail.com",
    "jagtapavdhut1111@gmail.com",
]

def google_login_view(request):
    """
    Initiates Google Sign-In.
    If GOOGLE_CLIENT_ID is configured in settings, redirects to Google's OAuth2 endpoint.
    Otherwise, serves the Google Sign-In Account Selector.
    """
    if request.user.is_authenticated:
        return redirect(get_home_url_for_user(request.user))

    redirect_uri = settings.GOOGLE_OAUTH_REDIRECT_URI or request.build_absolute_uri(reverse('portal:google_callback'))

    if settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET and not request.GET.get('dev'):
        state = secrets.token_urlsafe(32)
        request.session['google_oauth_state'] = state
        auth_url = (
            "https://accounts.google.com/o/oauth2/v2/auth?"
            f"client_id={settings.GOOGLE_CLIENT_ID}&"
            f"redirect_uri={redirect_uri}&"
            "response_type=code&"
            "scope=openid%20email%20profile&"
            f"state={state}&"
            "prompt=select_account"
        )
        return redirect(auth_url)

    # In development or when credentials are not yet configured in environment:
    context = {
        'sample_emails': SAMPLE_GOOGLE_EMAILS,
        'redirect_uri': redirect_uri,
        'has_live_credentials': bool(settings.GOOGLE_CLIENT_ID),
    }
    return render(request, 'registration/google_dev_provider.html', context)

def google_callback_view(request):
    """
    Handles Google OAuth2 callback.
    Verifies identity and maps to internal user role and unit.
    """
    verified_email = None

    # Scenario A: Live Google OAuth authorization code flow
    code = request.GET.get('code')
    if code and settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET:
        redirect_uri = settings.GOOGLE_OAUTH_REDIRECT_URI or request.build_absolute_uri(reverse('portal:google_callback'))
        token_endpoint = "https://oauth2.googleapis.com/token"
        token_data = {
            'code': code,
            'client_id': settings.GOOGLE_CLIENT_ID,
            'client_secret': settings.GOOGLE_CLIENT_SECRET,
            'redirect_uri': redirect_uri,
            'grant_type': 'authorization_code',
        }
        try:
            token_resp = requests.post(token_endpoint, data=token_data, timeout=10)
            if token_resp.status_code == 200:
                access_token = token_resp.json().get('access_token')
                userinfo_resp = requests.get(
                    "https://www.googleapis.com/oauth2/v3/userinfo",
                    headers={'Authorization': f"Bearer {access_token}"},
                    timeout=10
                )
                if userinfo_resp.status_code == 200:
                    verified_email = userinfo_resp.json().get('email')
        except Exception as e:
            messages.error(request, f"Google authentication failed: {str(e)}")
            return redirect('portal:login')

    # Scenario B: Development / Test Google authentication simulation
    if not verified_email:
        verified_email = request.POST.get('email') or request.GET.get('email')

    if not verified_email:
        messages.error(request, "No verified email received from Google authentication.")
        return redirect('portal:login')

    verified_email = verified_email.strip().lower()

    # Step 2: Map verified identity to internal system users
    matching_users = User.objects.filter(email__iexact=verified_email, is_active=True).select_related('primary_unit')

    if not matching_users.exists():
        # Identity verified, but no matching user in institutional FMS
        return render(request, 'registration/google_unregistered.html', {'email': verified_email})

    if matching_users.count() == 1:
        # Exactly one user matches this email
        user = matching_users.first()
        login(request, user, backend='django.contrib.auth.backends.ModelBackend')
        messages.success(request, f"Signed in with Google as {verified_email} ({user.get_full_name() or user.username} - {user.get_role_display()})")
        return redirect(get_home_url_for_user(user))

    # Multiple user accounts share this email (due to randomized testing or shared role assignments)
    request.session['pending_google_email'] = verified_email
    context = {
        'email': verified_email,
        'users': matching_users,
    }
    return render(request, 'registration/google_account_picker.html', context)

def google_select_account_view(request):
    """
    Selects specific account when multiple staff profiles share the verified Google email.
    """
    if request.method == 'POST':
        user_id = request.POST.get('user_id')
        verified_email = request.session.get('pending_google_email')

        user = get_object_or_404(User, id=user_id, is_active=True)
        if verified_email and user.email.lower() != verified_email.lower():
            messages.error(request, "Account selection mismatch.")
            return redirect('portal:login')

        login(request, user, backend='django.contrib.auth.backends.ModelBackend')
        request.session.pop('pending_google_email', None)
        messages.success(request, f"Signed in with Google as {user.email} ({user.get_full_name() or user.username} - {user.get_role_display()})")
        return redirect(get_home_url_for_user(user))

    return redirect('portal:login')
