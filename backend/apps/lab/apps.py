from django.apps import AppConfig


class LabConfig(AppConfig):
    """Test-harness tools. They drive the emulator's lab interface; the digital twin itself never does."""

    name = "apps.lab"
    label = "lab"
    verbose_name = "Test harness (emulator lab tools)"
