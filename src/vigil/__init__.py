from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("vigil")
except PackageNotFoundError:
    __version__ = "unknown"
