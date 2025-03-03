## Introduction

Simply, the script is a GUI written in Python using GTK3 that allows users to easily create QEMU KVM virtual machines and manage them without much need for configuration or troubleshooting. This script is based on stability and simple design, providing a "just works" solution that's fast and includes everything a user might need.

## Why you should use this program

You should use this program if you want to manage virtual machines with QEMU KVM quickly, easily, and simply it's designed to work with everything you need out of the box.

## How to use the program

- The program starts with a simple GUI window that has a plus button at the top bar. If you click it, a window opens.
- The opened window will ask you for an ISO installation image. You can either click the big plus symbol at the top or drag and drop an ISO into the bottom part of the window.
- The next window is a configuration menu for the VM:

  - **VM Name** = Here you can name the VM whatever you want.
  - **VM Directory** = Here you can click the "browse" button to choose a path where the VM will be stored with all its configuration files.
  - **CPU Cores** = Here you can type how many vCPUs you want to add to your VM. You can base it on your CPU's threads for maximum use, and in percentage, you can calculate the cores by how many system resources you allocate to the VM. I recommend a maximum of 6 cores because, for most scenarios, you don't need more (default is 2).
  - **RAM (MiB)** = Here you can set the amount of memory or RAM you want to add to the VM. Never add more than your system resources allow, it's recommended to leave a 2GB gap between it. In MiB, you can multiply the amount of RAM in GB by 1024 to get the correct amount.
  - **Disk Size (GB)** = Here you can set the size of the VM's disk in GB. On QCOW2 (the default QEMU disk image), the disk will be expandable and will not use the whole space, it will only use the space the VM is using. The raw format will always use the size you give to the disk, which makes your VM about 2% faster, but it's not really recommended.
  - **Firmware** = You can change between firmware options:
    - **BIOS** is the older, more compatible option that should work with everything except Windows 11.
    - **UEFI** is the newest firmware with faster speeds and newer technologies. It's the most recommended firmware to use in a VM and even on real PCs.
    - **UEFI + Secure Boot** is UEFI firmware together with Secure Boot. Secure Boot is a boot technology you can look up, but it’s needed for Windows 11 without passthrough.
  - **TPM** = TPM (Trusted Platform Module) 2.0 is required by Windows 11.
  - **Displays**:
    - **GTK** = The default display with the best 3D acceleration support, recommended on everything except Windows.
    - **Virtio** = Uses the SDL display combined with Virtio implementation for Windows operating systems.
    - **Spice (Virtio)** = Uses the Spice display combined with Virtio.
    - **QEMU** = Uses the default QEMU display by removing the -display switch on launch; this is the slowest display option.
  - **3D Acceleration** = 3D acceleration adds graphic acceleration support to the VM instead of software rendering, enabling smoother animations and a better experience.

- After you hit "Create," the VM will appear as a list item in your main menu with a settings button and a play button to boot the VM.
- You can right click the VM to start it, go to its settings, clone it, or delete it.
- In the settings, you can change anything that was previously configured.
- You need to disable the ISO in the settings to boot your OS properly after a fresh install.

![nqg main](https://github.com/user-attachments/assets/6a910865-18cd-465e-8896-4651bb1f221b)

![nqg create vm](https://github.com/user-attachments/assets/498fce03-6119-4345-b916-b73bff64e53c)

![nqg vm settings](https://github.com/user-attachments/assets/09ce9b3b-ded8-4824-9b2b-975966fa0275)


## Requirements:

- Enabled IOMMU and virtualization in your BIOS
- Minimum 8GB of RAM
- Minimum 4-Core CPU

Needed packages:

```
sudo pacman -S edk2-ovmf python qemu-full
```

## How to install on Arch-based Systems:

First, clone the repo:

```
git clone https://github.com/Nico-Shock/QemuGUI-nqg-.git
```

Then go into the directory:

```
cd QemuGUI-nqg-
```

After that, build the package:

```
makepkg -si
```

Then launch the program:

```
nqg
```

### How to run it on other OSes:

Run it via Python:

In the directory of the nqg.py file, run this:

```
python nqg.py
```

## Known issues:

- The right click menu only shows up when you right click on the settings icon.
- Sometimes UEFI files won’t copy correctly.
- Auto installation and setups for UEFI files currently only work properly on Arch based systems.


| ToDo                                          | Status  |
|-----------------------------------------------|---------|
| Support Secure Boot                           | ❌      |
| Change Virtio Display to SDL with Virtio support | ✅  |
| Add TPM support                               | ❌      |
| Add snapshot support                          | ❌      |
| Add VM Name configuration                     | ✅      |
| Add support for Debian | ❌      |
| Add support for Fedora | ❌      |
| Add support for SerpentOS | ❌      |
| Change the main window to use full space without borders | ❌  |
| Change window name                            | ❌      |
| Simplify text                                 | ✅      |
| Change title to "Nicos Qemu GUI"              | ✅      |
| Add support for Windows             | ❌      |
