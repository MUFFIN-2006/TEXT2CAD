"""Verify live connection to SolidWorks on this machine."""

import sys
import win32com.client

print("=" * 60)
print(" SOLIDWORKS LIVE CONNECTION PROBE")
print("=" * 60)

try:
    print("[1/3] Checking for active running SolidWorks instance...")
    swApp = win32com.client.GetActiveObject("SldWorks.Application")
    try:
        revision = swApp.RevisionNumber()
    except TypeError:
        revision = swApp.RevisionNumber
    print(f"      Connected to running SolidWorks! Revision: {revision}")
except Exception as e:
    print(f"      No active instance found ({e}).")
    print("[2/3] Attempting to launch/dispatch SolidWorks...")
    try:
        swApp = win32com.client.Dispatch("SldWorks.Application")
        swApp.Visible = True
        try:
            revision = swApp.RevisionNumber()
        except TypeError:
            revision = swApp.RevisionNumber
        print(f"      Successfully launched SolidWorks! Revision: {revision}")
    except Exception as e2:
        print(f"      Failed to dispatch SolidWorks: {e2}")
        print("\nPlease make sure SolidWorks is open on your Windows desktop and try again.")
        sys.exit(1)

print("[3/3] Testing COM API calls...")
try:
    swApp.Visible = True
    swApp.UserControl = True
    active_doc = swApp.ActiveDoc
    if active_doc:
        try:
            title = active_doc.GetTitle()
        except TypeError:
            title = active_doc.GetTitle
        print(f"      Active document open: '{title}'")
    else:
        print("      No document currently open (SolidWorks is idle and ready for new parts).")
    print("\nSUCCESS: SolidWorks COM bridge is fully working and ready for live AI design!")
except Exception as e3:
    print(f"      Error querying SolidWorks state: {e3}")
