"""Top-level package for aws-grobid."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("aws-grobid")
except PackageNotFoundError:
    __version__ = "uninstalled"

__author__ = "Eva Maxfield Brown"
__email__ = "evamaxfieldbrown@gmail.com"

from .core import (
    GROBIDDeploymentConfig,
    GROBIDDeploymentConfigs,
    deploy_and_wait_for_ready,
    terminate_instance,
)

__all__ = [
    "deploy_and_wait_for_ready",
    "terminate_instance",
    "GROBIDDeploymentConfig",
    "GROBIDDeploymentConfigs",
    "__version__",
    "__author__",
    "__email__",
]
