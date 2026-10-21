from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.contrib import messages
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.http import Http404
from django.shortcuts import render, redirect, get_object_or_404
from django.utils.http import url_has_allowed_host_and_scheme

from .forms import CompleteProfileForm, EditProfileForm
from .models import UserProfile, GeneratedImage, GeneratedVideo, BlogPost, FeaturedAsset


# ── Auth ──────────────────────────────────────────────────────────────

def _safe_next_url(request, value, fallback='home'):
    if value and url_has_allowed_host_and_scheme(
        value,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return value
    return fallback

def login_view(request):
    if request.user.is_authenticated:
        return redirect('home')
    if request.method == 'POST':
        email_or_user = request.POST.get('email', '').strip()
        password = request.POST.get('password', '')
        # Allow login with email OR username
        user = None
        if '@' in email_or_user:
            matching_users = User.objects.filter(email__iexact=email_or_user).order_by('id')
            for u in matching_users:
                if not u.is_active and u.check_password(password):
                    return redirect('account_restricted')
                user = authenticate(request, username=u.username, password=password)
                if user is not None:
                    break
        else:
            try:
                u = User.objects.get(username__iexact=email_or_user)
                if not u.is_active and u.check_password(password):
                    return redirect('account_restricted')
            except User.DoesNotExist:
                pass
            user = authenticate(request, username=email_or_user, password=password)

        if user is not None:
            login(request, user)
            next_url = request.POST.get('next') or request.GET.get('next')
            return redirect(_safe_next_url(request, next_url))
        else:
            messages.error(request, 'Invalid email/username or password.')
    return render(request, 'core/login.html')


def logout_view(request):
    logout(request)
    return redirect('home')


def social_login_start(request, provider):
    if provider != 'google':
        raise Http404("Unknown social provider")
    try:
        from allauth.socialaccount.models import SocialApp
        has_app = SocialApp.objects.filter(
            provider=provider,
            sites__id=getattr(settings, 'SITE_ID', 1),
        ).exists()
    except Exception:
        has_app = False
    if not has_app:
        messages.error(request, 'Google sign-in is temporarily unavailable. Please use email and password instead.')
        return redirect('login')
    return redirect(f'/accounts/{provider}/login/')


def register_view(request):
    if request.user.is_authenticated:
        return redirect('home')
    if request.method == 'POST':
        first_name = request.POST.get('first_name', '').strip()
        last_name  = request.POST.get('last_name', '').strip()
        email      = request.POST.get('email', '').strip()
        password   = request.POST.get('password', '')
        password2  = request.POST.get('password2', '')

        validation_error = None
        try:
            validate_email(email)
            validate_password(password)
        except ValidationError as exc:
            validation_error = ' '.join(exc.messages)

        if not first_name or not email or not password:
            messages.error(request, 'First name, email and password are required.')
        elif len(first_name) > 150 or len(last_name) > 150:
            messages.error(request, 'First and last names must be 150 characters or fewer.')
        elif validation_error:
            messages.error(request, validation_error)
        elif password != password2:
            messages.error(request, 'Passwords do not match.')
        elif User.objects.filter(email__iexact=email).exists():
            messages.error(request, 'An account with this email already exists.')
        else:
            # derive username from email prefix, ensure uniqueness
            import re
            base = (re.sub(r'[^a-z0-9_]+', '_', email.split('@')[0].lower()).strip('_') or 'creator')[:140]
            username = base
            n = 1
            while User.objects.filter(username=username).exists():
                username = f"{base}{n}"
                n += 1
            user = User.objects.create_user(
                username=username, email=email, password=password,
                first_name=first_name, last_name=last_name,
            )
            profile, _ = UserProfile.objects.get_or_create(user=user)
            profile.needs_profile_completion = False
            profile.save(update_fields=['needs_profile_completion'])
            login(request, user)
            messages.success(request, f'Welcome to ReelStock, {first_name}!')
            return redirect('home')
    return render(request, 'core/register.html')


def account_restricted(request):
    admin_email = getattr(settings, 'ADMIN_CONTACT_EMAIL', None) or getattr(settings, 'DEFAULT_FROM_EMAIL', '')
    return render(request, 'core/account_restricted.html', {
        'admin_email': admin_email,
        'subject': 'Account Dispute',
    })


@login_required
def complete_profile(request):
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if request.method == 'POST':
        form = CompleteProfileForm(request.POST, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, 'Profile completed. Welcome in.')
            return redirect(_safe_next_url(request, request.GET.get('next')))
    else:
        form = CompleteProfileForm(user=request.user)
    return render(request, 'core/complete_profile.html', {
        'form': form,
        'profile': profile,
    })


# ── Pages ─────────────────────────────────────────────────────────────

def home(request):
    featured = []
    for item in FeaturedAsset.objects.select_related('image__user', 'video__user'):
        asset = item.get_asset()
        if not asset:
            continue
        if item.asset_type == FeaturedAsset.ASSET_IMAGE and asset.is_published:
            featured.append(item)
        elif (
            item.asset_type == FeaturedAsset.ASSET_VIDEO
            and asset.is_published
            and asset.status == GeneratedVideo.STATUS_DONE
        ):
            featured.append(item)
        if len(featured) >= 6:
            break
    blog_posts = BlogPost.objects.filter(is_published=True, show_on_home=True).order_by('home_order', '-created_at')[:3]
    return render(request, 'core/home.html', {
        'featured': featured,
        'blog_posts': blog_posts,
    })


def blog_list(request):
    posts = BlogPost.objects.filter(is_published=True)
    return render(request, 'core/blog_list.html', {'posts': posts})


def blog_detail(request, slug):
    post = get_object_or_404(BlogPost, slug=slug, is_published=True)
    return render(request, 'core/blog_detail.html', {'post': post})


@login_required
def account_page(request):
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    images = GeneratedImage.objects.filter(user=request.user, is_saved=True)
    videos = GeneratedVideo.objects.filter(user=request.user, is_saved=True, status='done')
    total_images = images.count()
    total_videos = videos.count()

    tab = request.GET.get('tab', 'all')
    if tab == 'images':
        recent_images = list(images[:8])
        recent_videos = []
    elif tab == 'videos':
        recent_images = []
        recent_videos = list(videos[:8])
    else:
        recent_images = list(images[:4])
        recent_videos = list(videos[:4])

    return render(request, 'core/account.html', {
        'profile': profile,
        'recent_images': recent_images,
        'recent_videos': recent_videos,
        'total_images': total_images,
        'total_videos': total_videos,
        'total_assets': total_images + total_videos,
        'active_tab': tab,
    })


@login_required
def edit_profile(request):
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if request.method == 'POST':
        form = EditProfileForm(request.POST, instance=profile, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, 'Profile updated.')
            return redirect('account')
    else:
        form = EditProfileForm(instance=profile, user=request.user)
    return render(request, 'core/edit_profile.html', {'profile': profile, 'form': form})
