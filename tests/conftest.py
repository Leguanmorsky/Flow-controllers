import os

# Qt tests run without a visible window (and without a display).
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
