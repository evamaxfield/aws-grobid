"""Top-level package for aws-grobid."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("aws-grobid")
except PackageNotFoundError:
    __version__ = "uninstalled"

__author__ = "Eva Maxfield Brown"
__email__ = "evamaxfieldbrown@gmail.com"

from .core import deploy_and_wait_for_ready, terminate_instance

__all__ = [
    "deploy_and_wait_for_ready",
    "terminate_instance",
    "__version__",
    "__author__",
    "__email__",
]
