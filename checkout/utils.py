

def import_from_string(to_import):
    u"""
    Import a object (variable, method, class ...) with a string.
    Example: "myapp.models.FooModel"
    """
    if not "." in to_import:
        raise ImportError("No \".\" in %r" % to_import)
    idx = to_import.rindex(".")
    module_name = to_import[:idx]
    attr = to_import[idx + 1:]
    module = __import__(module_name, {}, {}, [attr])
    something = getattr(module, attr, None)
    if not something:
        raise ImportError("module %s has no attribute %r" % (module_name, attr))
    return something