"""
Management command to create an API token for a user.

Usage:
    python manage.py create_api_token <username> [--name "My Token"]
"""

from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model
from app.models import APIToken

User = get_user_model()


class Command(BaseCommand):
    help = "Create a new API token for the specified user."

    def add_arguments(self, parser):
        parser.add_argument("username", type=str, help="Username to create the token for")
        parser.add_argument(
            "--name",
            type=str,
            default="",
            help="Optional label for the token (e.g. 'Postman', 'Frontend')",
        )

    def handle(self, *args, **options):
        username = options["username"]
        name = options["name"]

        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            raise CommandError(f"User '{username}' does not exist.")

        token = APIToken.objects.create(user=user, name=name)

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("✅ API Token created successfully!"))
        self.stdout.write(f"   User:  {user.username}")
        self.stdout.write(f"   Name:  {name or '(none)'}")
        self.stdout.write(f"   Token: {token.token}")
        self.stdout.write("")
        self.stdout.write(self.style.WARNING("⚠️  Save this token now — it won't be shown again."))
        self.stdout.write(f"   Usage: Authorization: Bearer {token.token}")
        self.stdout.write("")
