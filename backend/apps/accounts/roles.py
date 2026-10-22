"""The two levels of administrative access (section 3.8, plan decision D7)."""
from django.contrib.auth.models import Group, Permission, User

SENIOR = "Senior Administrator"
JUNIOR = "Junior Administrator"
SYSTEM_USERNAME = "dt-system"   # owns automatically generated recommendation scenarios

TWIN_MODELS = ["networkdevice", "networklink", "monitoringrecord", "prediction",
               "simulationscenario", "simulationresult"]


def ensure_roles() -> tuple[Group, Group]:
    senior, _ = Group.objects.get_or_create(name=SENIOR)
    junior, _ = Group.objects.get_or_create(name=JUNIOR)
    twin = Permission.objects.filter(content_type__app_label="twin", content_type__model__in=TWIN_MODELS)
    users = Permission.objects.filter(content_type__app_label="auth", content_type__model="user",
                                      codename__in=["add_user", "change_user", "view_user"])
    senior.permissions.set(list(twin.exclude(codename__startswith="delete_")) + list(users))
    junior.permissions.set(list(twin.filter(codename__startswith="view_")))
    return senior, junior


def ensure_system_user() -> User:
    user, created = User.objects.get_or_create(
        username=SYSTEM_USERNAME, defaults={"first_name": "Digital twin", "last_name": "(system)"})
    if created or user.has_usable_password():
        user.set_unusable_password()
        user.is_active = False      # cannot log in; used only as the owner of generated scenarios
        user.save()
    return user


def is_senior(user) -> bool:
    return bool(user and user.is_authenticated and user.is_active
                and (user.is_superuser or user.groups.filter(name=SENIOR).exists()))


def role_of(user) -> str:
    if is_senior(user):
        return "senior"
    if user and user.is_authenticated and user.groups.filter(name=JUNIOR).exists():
        return "junior"
    return "none"
