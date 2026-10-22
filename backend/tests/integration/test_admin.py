"""Account management in the admin site stays inside the two roles (section 3.8, D7)."""
import pytest
from django.contrib import admin
from django.contrib.auth.models import Group, User
from django.test import Client, RequestFactory

from apps.accounts.admin import RoleUserAdmin
from apps.accounts.roles import JUNIOR, SENIOR, SYSTEM_USERNAME, ensure_roles, ensure_system_user

pytestmark = pytest.mark.django_db
PASSWORD = "a-long-password-123"


def make(username, role=None, **extra):
    ensure_roles()
    user = User.objects.create_user(username, password=PASSWORD, **extra)
    if role:
        user.groups.add(Group.objects.get(name=role))
    return user


def request_by(user):
    request = RequestFactory().get("/admin/auth/user/")
    request.user = user
    return request


def test_a_senior_manages_accounts_but_cannot_grant_superuser_or_extra_groups():
    senior = make("senior1", SENIOR, is_staff=True)
    junior = make("junior1", JUNIOR)
    root = make("root", is_staff=True, is_superuser=True)
    ensure_system_user()
    Group.objects.create(name="Everything")
    user_admin = admin.site._registry[User]
    assert isinstance(user_admin, RoleUserAdmin)
    request = request_by(senior)

    assert {"is_superuser", "user_permissions"} <= set(user_admin.get_readonly_fields(request, junior))
    form = user_admin.get_form(request, junior)
    assert "is_superuser" not in form.base_fields and "user_permissions" not in form.base_fields
    assert set(form.base_fields["groups"].queryset.values_list("name", flat=True)) == {SENIOR, JUNIOR}
    visible = set(user_admin.get_queryset(request).values_list("username", flat=True))
    assert visible == {"senior1", "junior1"}                       # no superusers, no system account
    assert user_admin.has_change_permission(request, junior) is True
    assert user_admin.has_change_permission(request, root) is False
    assert user_admin.has_delete_permission(request, junior) is False   # deactivate instead

    superuser_form = user_admin.get_form(request_by(root), junior)
    assert "is_superuser" in superuser_form.base_fields                # a superuser keeps full control
    assert SYSTEM_USERNAME not in set(user_admin.get_queryset(request_by(root)).values_list("username", flat=True))


def test_the_account_page_works_for_a_senior():
    senior = make("senior1", SENIOR, is_staff=True)
    junior = make("junior1", JUNIOR)
    client = Client()
    client.force_login(senior)
    page = client.get(f"/admin/auth/user/{junior.pk}/change/")
    assert page.status_code == 200
    html = page.content.decode()
    assert 'name="groups"' in html and 'name="is_superuser"' not in html
