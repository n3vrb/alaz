# Contributing

Thanks for helping! ROG Control has only been tested on one laptop (Intel Zephyrus, see README),
so reports and fixes from **other models — especially AMD** — are very welcome.

## Before you start
- Read [`CLAUDE.md`](CLAUDE.md) (hard rules — each one was learned on real hardware) and
  [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). The backlog is in [`docs/TODO.md`](docs/TODO.md).
- Never switch the GPU live (`supergfxctl -m` / supergfxd `SetMode`), never block the GUI thread,
  never wake the dGPU just for monitoring, and keep tests away from the real system.

## Workflow
1. Fork, create a branch, make your change.
2. Run the whole suite: `QT_QPA_PLATFORM=offscreen python3 -m pytest tests -q` (needs `python3-pyqt6`, `python3-psutil`, `pytest-qt`).
3. For UI changes, render the windows (`tools/screenshot_windows.py --lang en <dir>`) and attach before/after screenshots.
4. New user-visible strings go through `rog_control.i18n.tr()` with an English entry in `rog_control/i18n_en.py`.
5. Open a pull request describing your **model, CPU, distro** and how you tested on real hardware.

Using an AI assistant (e.g. Claude Code) is fine — `CLAUDE.md` gives it the project context. Please review its
changes yourself and say what you verified on real hardware.
