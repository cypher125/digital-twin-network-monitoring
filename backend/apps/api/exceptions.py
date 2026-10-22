"""Every API error carries a machine-readable `code` next to the plain-language `detail`.

The dashboard uses it, for example, to ask for the password again (code
"reauthenticate") instead of showing a generic "not allowed" message.
"""
from rest_framework.views import exception_handler


def api_exception_handler(exc, context):
    response = exception_handler(exc, context)
    if response is not None and hasattr(exc, "get_codes") and isinstance(response.data, dict):
        codes = exc.get_codes()
        if isinstance(codes, str):
            response.data["code"] = codes
    return response
