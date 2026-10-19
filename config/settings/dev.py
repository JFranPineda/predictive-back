import os

from .base import *  # noqa: F403

DEBUG = True

# The on-premise bench and CI sign with a throwaway key, because ours never
# leaves the issuing machine. Production settings never read this.
LICENSE_PUBLIC_KEY = os.environ.get("LICENSE_PUBLIC_KEY") or LICENSE_PUBLIC_KEY  # noqa: F405
