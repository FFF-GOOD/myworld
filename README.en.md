# myworld

A local dual-pane PDF workspace for Windows: read the original next to an editable copy, annotate, redact, add text and keep illustrated notes.

Formerly StudyPDF. Version 0.6.2 adds viewport-aware PDF drag-and-drop and a working-copy Save as PDF button, preserving .pdfwork projects.

[中文 README](README.md) · [User guide (Chinese)](docs/USER_GUIDE.md)

## Download

Open this repository's Releases → v0.6.2 → Assets. Download **myworld_0.6.2_Windows_x64.zip**, extract everything and run **Start_myworld.bat**.

Windows 10/11 x64. The portable ZIP includes dependencies. Automatic Source code archives do not.

## Features

Synchronized scrolling, page, zoom and rotation; swap panes; highlight, underline, strikeout, ink and text boxes; undoable redaction in the working copy; movable persistent comments; rich-text notes, quotes, screenshots, image paste and resizing; compact linked projects and separate original save.

## Development and license

Python 3.12, requirements-dev.txt, app.py. See docs/DEVELOPMENT.md for tests and builds.

Application: GNU AGPL-3.0-only, see LICENSE. Dependencies keep their own licenses and source directions in THIRD_PARTY_NOTICES.md.

Public preview, not comprehensively tested on real Windows devices. OCR, arbitrary existing-text reflow and electronic signatures are not implemented. Complex intersecting vector objects may be removed as whole objects during redaction. Local processing, no application upload, telemetry or cloud synchronization.
