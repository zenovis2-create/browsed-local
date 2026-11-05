# Third-party dependencies

This repository contains the browsed-local controller and orchestration source. It does not vendor third-party binaries, driver packages, or third-party source trees.

| Project | Tested reference | License / source |
| --- | --- | --- |
| Voxl | v0.3.3, commit `47bb94ec4d253638c1470eb81906676e1bef4b00` | MIT, [upstream license](https://github.com/tembo/voxl/blob/47bb94ec4d253638c1470eb81906676e1bef4b00/LICENSE) |
| Virtual Display Driver | 25.7.23 | MIT, [upstream repository](https://github.com/VirtualDrivers/Virtual-Display-Driver), [release](https://github.com/VirtualDrivers/Virtual-Display-Driver/releases/tag/25.7.23) |
| Python / Tcl/Tk | Python 3.13 with Tkinter | Installed separately; see the Python installation's license notices |
| PowerShell | 7.x | Installed separately; [upstream](https://github.com/PowerShell/PowerShell) |

Voxl builds link additional libraries, including x264, libyuv, and Opus. The upstream project's source license does not replace the obligations of those dependencies when redistributing a compiled executable. Obtain/build these dependencies separately following upstream instructions.
