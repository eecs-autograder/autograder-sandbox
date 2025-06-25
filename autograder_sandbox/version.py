from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version(str(__package__))
except PackageNotFoundError:
    __version__ = "0.0.0"
