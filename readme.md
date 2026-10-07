# SD RAWR

<p align="center">
  <img src="SHOWCASE.png" alt="sd rawr int">
</p>

SD RAWR is a Windows utility for creating, splitting, combining, and mounting virtual SD card RAW images, mainly to be used with RiftWii, Dolphin and also Smash Brawl Mods

## Features

- Create FAT16/FAT32 `.raw` virtual SD card images from a folder
- Automatically choose the smallest supported SD card size that fits the source data
- Copy the selected folder's contents directly into the root of the virtual SD card
- Split RAW images into 4000 MiB parts such as `.raw.001`, `.raw.002`, and so on
- Split existing premade `.raw` files
- Combine split RAW parts back into the original `.raw` image
- Mount and unmount RAW images with ImDisk
- Read-only mounting by default, with optional read/write mounting
- Detect duplicate mounts of the same RAW image
- Show currently mounted ImDisk virtual drives
- Open mounted drives directly in Windows Explorer
- Live `logs.txt` file beside `SDRAWR.exe`
- Always requests administrator privileges when the packaged EXE starts
- Custom SD RAWR branding and Windows EXE icon

## Supported Virtual SD Sizes

128 MB, 256 MB, 512 MB, 1 GB, 2 GB, 4 GB, 8 GB, 16 GB, and 32 GB.

## Notes

ImDisk is required for mounting RAW images and is not bundled with SD RAWR.

The SD RAWR interface is in English. Build-script messages and runtime logs are in Japanese.


# Credits

### SD RAWR

Application design, source code, UI, RAW creation/splitting/combining workflow, and Windows packaging.

The SD RAWR logo included with the project was supplied by the project owner and is used for the application window icon, executable icon, and in-app branding.

### pyfatfs

Used to create and work with FAT12/FAT16/FAT32 filesystems.

- Project: `pyfatfs`
- Author/project maintainers: Nathan Hi and contributors
- License: MIT
- Source: https://github.com/nathanhi/pyfatfs

### PyFilesystem2

Filesystem abstraction used by `pyfatfs`.

- Project: `PyFilesystem2`
- License: MIT
- Source: https://github.com/PyFilesystem/pyfilesystem2

### PyInstaller

Used to package SD RAWR into a standalone Windows executable.

- Project: `PyInstaller`
- License: GPL-2.0 with the PyInstaller exception, with some files under Apache-2.0
- The PyInstaller exception permits executables produced by PyInstaller to be distributed under the application's own license, subject to the licenses of bundled dependencies.
- Source: https://pyinstaller.org/

### ImDisk Virtual Disk Driver

Used as an **optional external dependency** for mounting and unmounting RAW images.

- Project: `ImDisk Virtual Disk Driver`
- Original author: Olof Lagerkvist
- Current source/project: LTR Data
- Source: https://github.com/LTRData/ImDisk

ImDisk is **not included in the SD RAWR distribution**. Users install it separately.

ImDisk contains code under multiple license terms. Its main source includes a permissive MIT-style license, while the project also contains GPL-licensed components and other third-party code. Refer to the ImDisk repository's `LICENSE.md` and source notices for the exact terms that apply to the version you install.

## SD RAWR License

SD RAWR itself is released under the **MIT License**.

Copyright (c) 2026 SD RAWR contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## Third-Party Licensing

The MIT license above applies to **SD RAWR's own source code only**.

Third-party libraries and external tools keep their own licenses. Distributing
SD RAWR does not relicense `pyfatfs`, `PyFilesystem2`, `PyInstaller`, ImDisk,
or any other third-party component.

If you redistribute a build containing third-party components, keep the
required copyright notices and license terms for those components.
