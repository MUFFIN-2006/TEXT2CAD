"""Search and invoke commands from the installed SOLIDWORKS command type library."""

from functools import lru_cache
from pathlib import Path
import re

from .com_adapter.base import CADResult


@lru_cache(maxsize=1)
def _catalog():
    import winreg
    import pythoncom

    clsid = winreg.QueryValue(winreg.HKEY_CLASSES_ROOT, r"SldWorks.Application\CLSID")
    server = winreg.QueryValue(winreg.HKEY_CLASSES_ROOT, rf"CLSID\{clsid}\LocalServer32")
    exe = re.match(r'^\s*"?(.+?\.exe)(?:"|\s|$)', server, re.I)
    if not exe:
        raise ValueError("Cannot locate the registered SolidWorks executable.")
    library = pythoncom.LoadTypeLib(str(Path(exe[1]).with_name("swcommands.tlb")))
    for index in range(library.GetTypeInfoCount()):
        if library.GetDocumentation(index)[0] != "swCommands_e":
            continue
        info = library.GetTypeInfo(index)
        commands = {}
        for slot in range(info.GetTypeAttr().cVars):
            value = info.GetVarDesc(slot)
            name = info.GetDocumentation(value.memid)[0].removeprefix("swCommands_")
            if value.value > 0:
                commands[name] = value.value
        return commands
    raise ValueError("The installed type library does not contain swCommands_e.")


def _key(text):
    return re.sub(r"[^a-z0-9]", "", text.lower().removeprefix("swcommands_"))


def find_commands(query="", offset=0, limit=20):
    if offset < 0 or not 1 <= limit <= 100:
        return CADResult(success=False, message="Use a nonnegative offset and a limit from 1 to 100.")
    try:
        catalog = _catalog()
    except Exception as exc:
        return CADResult(success=False, message=f"Cannot read the installed SolidWorks command catalog: {exc}")
    words = [_key(word) for word in query.split()]
    matches = [name for name in catalog if all(word in _key(name) for word in words)]
    matches.sort(key=lambda name: (_key(name) != _key(query), len(name), name))
    return CADResult(success=True, message=f"{len(matches)} matching SolidWorks commands.",
                     data={"commands": matches[offset:offset + limit], "total": len(matches), "offset": offset})


def start_command(adapter, name):
    try:
        matches = [(label, value) for label, value in _catalog().items() if _key(label) == _key(name)]
    except Exception as exc:
        return CADResult(success=False, message=f"Cannot read the installed SolidWorks command catalog: {exc}")
    if len(matches) != 1:
        return CADResult(success=False, message=f"Use 'find command {name}' and enter one exact command name.")
    label, value = matches[0]
    return adapter.run_native_command(value, label)
