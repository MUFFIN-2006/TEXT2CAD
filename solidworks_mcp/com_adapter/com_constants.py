"""SolidWorks COM Constants and Enumerations.

Transcribed from SolidWorks API Type Library (swconst.tlb).
"""

# Document Types (swDocumentTypes_e)
SW_DOC_NONE = 0
SW_DOC_PART = 1
SW_DOC_ASSEMBLY = 2
SW_DOC_DRAWING = 3

# End Conditions for Extrusion / Cut (swEndConditions_e)
SW_END_COND_BLIND = 0
SW_END_COND_THROUGH_ALL = 1
SW_END_COND_THROUGH_NEXT = 2
SW_END_COND_UP_TO_SURFACE = 3
SW_END_COND_OFFSET_FROM_SURFACE = 4
SW_END_COND_MID_PLANE = 6

# Standard Views (swStandardViews_e)
SW_VIEW_FRONT = 1
SW_VIEW_BACK = 2
SW_VIEW_LEFT = 3
SW_VIEW_RIGHT = 4
SW_VIEW_TOP = 5
SW_VIEW_BOTTOM = 6
SW_VIEW_ISOMETRIC = 7
SW_VIEW_TRIMETRIC = 8
SW_VIEW_DIMETRIC = 9

# User Preference Toggles (swUserPreferenceToggle_e)
SW_EXT_REF_UPDATE_COMP_VARS = 10
SW_SHOW_DIMENSION_NAMES = 372
SW_AUTO_SAVE_INTERVAL = 520
SW_PERFORMANCE_ALWAYS_GENERATE_DRAFT_QUALITY = 642

# Plane Names (standard SolidWorks default names)
STANDARD_PLANES = {
    "front": "Front Plane",
    "top": "Top Plane",
    "right": "Right Plane",
}

# Selection Mark Constants
SEL_MARK_NONE = 0
SEL_MARK_AXIS = 1
SEL_MARK_FEATURE = 4
