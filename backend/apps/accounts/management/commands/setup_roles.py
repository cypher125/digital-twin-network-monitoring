"""Create the Senior/Junior Administrator groups and the system account; optionally create a user.

    python manage.py setup_roles
    python manage.py setup_roles --create-user admin1 --role senior
"""
import getpass

from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from apps.accounts.roles import ensure_roles, ensure_system_user


class Command(BaseCommand):
    help = "Create the two administrator roles and the system account (section 3.8)."

    def add_arguments(self, parser):
        parser.add_argument("--create-user", metavar="USERNAME")
        parser.add_argument("--role", choices=["senior", "junior"], default="junior")
        parser.add_argument("--password", help="omit to be asked for it (safer)")

    def handle(self, *args, **opts):
        senior, junior = ensure_roles()
        ensure_system_user()
        self.stdout.write(self.style.SUCCESS(f"Roles ready: {senior.name}, {junior.name}"))
        username = opts["create_user"]
        if not username:
            return
        if User.objects.filter(username=username).exists():
            raise CommandError(f"user {username} already exists")
        password = opts["password"] or getpass.getpass(f"Password for {username}: ")
        user = User(username=username, is_staff=opts["role"] == "senior")
        try:
            validate_password(password, user)
        except ValidationError as exc:
            raise CommandError("; ".join(exc.messages)) from exc
        user.set_password(password)
        user.save()
        user.groups.add(senior if opts["role"] == "senior" else junior)
        self.stdout.write(self.style.SUCCESS(f"Created {opts['role']} administrator {username}"))
