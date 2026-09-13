#!/usr/bin/python3 -I
"""Read-only status; the installed helper does not open the camera in this mode."""
import os
os.execv('/usr/bin/python3', ['/usr/bin/python3', '-I', '/usr/lib/omarchy-face-auth/backend.py', 'status'])
