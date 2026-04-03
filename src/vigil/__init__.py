def __getattr__(name: str) -> str:
    if name == "__version__":
        from importlib.metadata import PackageNotFoundError, version

        try:
            return version("vigil")
        except PackageNotFoundError:
            return "unknown"
    raise AttributeError(name)
