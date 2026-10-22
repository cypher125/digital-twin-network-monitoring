"""Password hashing (write-up section 3.8: strong hash, unique salt per user)."""
from django.contrib.auth.hashers import Argon2PasswordHasher


class TunedArgon2PasswordHasher(Argon2PasswordHasher):
    """Argon2id at OWASP's minimum: 19 MiB memory, 2 passes, 1 lane (plan decision D8).

    Django's default uses 100 MiB per login, which is heavy on a 4 GB laptop. The
    algorithm name is unchanged, so existing Argon2 hashes still verify and are
    upgraded to these parameters on the next login.
    """

    time_cost = 2
    memory_cost = 19456
    parallelism = 1
