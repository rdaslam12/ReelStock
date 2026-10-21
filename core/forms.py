from django import forms
from django.contrib.auth.models import User

from .models import UserProfile


class CompleteProfileForm(forms.Form):
    username = forms.CharField(
        max_length=150,
        required=True,
        widget=forms.TextInput(attrs={
            "class": "form-control rounded-3",
            "placeholder": "your_username",
            "autocomplete": "username",
        }),
    )
    display_name = forms.CharField(
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={
            "class": "form-control rounded-3",
            "placeholder": "Your full name",
            "autocomplete": "name",
        }),
    )

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        initial = kwargs.setdefault("initial", {})
        if user:
            initial.setdefault("username", user.username)
            initial.setdefault("display_name", user.get_full_name())
        super().__init__(*args, **kwargs)

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        qs = User.objects.filter(username__iexact=username)
        if self.user and self.user.pk:
            qs = qs.exclude(pk=self.user.pk)
        if qs.exists():
            raise forms.ValidationError("That username is already taken.")
        return username

    def save(self):
        user = self.user
        user.username = self.cleaned_data["username"]
        display_name = self.cleaned_data.get("display_name", "").strip()
        if display_name:
            parts = display_name.split(None, 1)
            user.first_name = parts[0]
            user.last_name = parts[1] if len(parts) > 1 else ""
        user.save(update_fields=["username", "first_name", "last_name"])
        profile, _ = UserProfile.objects.get_or_create(user=user)
        profile.needs_profile_completion = False
        profile.save(update_fields=["needs_profile_completion"])
        return user


class EditProfileForm(forms.ModelForm):
    first_name = forms.CharField(max_length=150, required=True)
    last_name = forms.CharField(max_length=150, required=False)
    email = forms.EmailField(max_length=254, required=True)

    class Meta:
        model = UserProfile
        fields = [
            "first_name", "last_name", "email", "bio", "location", "website",
            "x_handle", "instagram", "youtube", "tiktok",
        ]
        widgets = {
            "bio": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        if user and not self.is_bound:
            self.fields["first_name"].initial = user.first_name
            self.fields["last_name"].initial = user.last_name
            self.fields["email"].initial = user.email
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control rounded-3")

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exclude(pk=self.user.pk).exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email

    def save(self, commit=True):
        profile = super().save(commit=False)
        self.user.first_name = self.cleaned_data["first_name"].strip()
        self.user.last_name = self.cleaned_data["last_name"].strip()
        self.user.email = self.cleaned_data["email"]
        if commit:
            self.user.save(update_fields=["first_name", "last_name", "email"])
            profile.save()
        return profile
