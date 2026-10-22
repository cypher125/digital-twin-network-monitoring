"""Account management in the admin site, limited to the two roles (section 3.8, plan decision D7).

Senior Administrators add and change accounts here. Django's default user admin would also
let them tick "superuser", grant raw permissions, or join any group, and so give themselves
(or anyone) more than the two roles allow. Here only a superuser can do that: everyone else
can give an account the Senior or Junior Administrator role and nothing more, and cannot
change superuser accounts at all.
"""
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import Group, User

from .roles import JUNIOR, SENIOR, SYSTEM_USERNAME

ESCALATING_FIELDS = ("is_superuser", "user_permissions")


class RoleUserAdmin(UserAdmin):
    def get_queryset(self, request):
        query = super().get_queryset(request).exclude(username=SYSTEM_USERNAME)
        return query if request.user.is_superuser else query.filter(is_superuser=False)

    def get_readonly_fields(self, request, obj=None):
        fields = list(super().get_readonly_fields(request, obj))
        if not request.user.is_superuser:
            fields += [f for f in ESCALATING_FIELDS if f not in fields]
        return tuple(fields)

    def formfield_for_manytomany(self, db_field, request, **kwargs):
        if db_field.name == "groups" and not request.user.is_superuser:
            kwargs["queryset"] = Group.objects.filter(name__in=[SENIOR, JUNIOR])
        return super().formfield_for_manytomany(db_field, request, **kwargs)

    def has_change_permission(self, request, obj=None):
        if obj is not None and obj.is_superuser and not request.user.is_superuser:
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        # accounts are deactivated (Active unticked), not deleted: their history and audit trail stay
        return request.user.is_superuser and super().has_delete_permission(request, obj)


admin.site.unregister(User)
admin.site.register(User, RoleUserAdmin)
