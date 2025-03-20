"""Top-level package for aws-grobid."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("aws-grobid")
except PackageNotFoundError:
    __version__ = "uninstalled"

__author__ = "Eva Maxfield Brown"
__email__ = "evamaxfieldbrown@gmail.com"
