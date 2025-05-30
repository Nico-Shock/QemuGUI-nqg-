#!/usr/bin/env python3
import os, json, subprocess, shutil, threading, urllib.parse
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk, GLib
import webbrowser

CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".nqg")
if not os.path.exists(CONFIG_DIR):
    os.makedirs(CONFIG_DIR)
CONFIG_FILE = os.path.join(CONFIG_DIR, "vms_index.json")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def get_host_os():
    if os.path.exists("/etc/arch-release"):
        return "arch"
    elif os.path.exists("/etc/debian_version"):
        return "debian"
    elif os.path.exists("/etc/fedora-release"):
        return "fedora"
    elif os.path.exists("/etc/serpentos-release"):
        return "serpentos"
    else:
        return "other"

def copy_uefi_files(config, parent_window=None):
    host = get_host_os()
    ovmf_dir = os.path.join(config["path"], "ovmf")
    os.makedirs(ovmf_dir, exist_ok=True)
    if host in ["arch", "serpentos"]:
        src_dir = "/usr/share/edk2/x64"
    elif host == "fedora":
        src_dir = "/usr/share/OVMF"
    elif host == "debian":
        src_dir = "/usr/share/ovmf"
    else:
        src_dir = "/usr/share/edk2/x64"
    if config["firmware"] == "UEFI":
        files = ["OVMF.4m.fd", "OVMF_VARS.4m.fd"]
    elif config["firmware"] == "UEFI+Secure Boot":
        files = ["OVMF_CODE.4m.fd", "OVMF_VARS.4m.fd"]
    else:
        return True
    success = True
    copied_count = 0
    for f in files:
        src = os.path.join(src_dir, f)
        dst = os.path.join(ovmf_dir, f)
        if os.path.exists(src):
            try:
                shutil.copy(src, dst)
                copied_count += 1
            except Exception as e:
                sudo_pwd = prompt_sudo_password(parent_window)
                if sudo_pwd is not None:
                    full_cmd = f"echo {sudo_pwd} | sudo -S cp '{src}' '{dst}'"
                    try:
                        subprocess.run(full_cmd, shell=True, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        copied_count += 1
                    except subprocess.CalledProcessError as e_sudo:
                        show_detailed_error_dialog(f"Error with Sudo: {str(e_sudo)}\nCheck password and permissions.", str(e_sudo), parent_window)
                        success = False
                    except Exception as e_sudo_other:
                        show_detailed_error_dialog(f"Unexpected error with Sudo: {str(e_sudo_other)}\nCheck setup.", str(e_sudo_other), parent_window)
                        success = False
                else:
                    show_detailed_error_dialog("Need Sudo password to copy files.", "Sudo password not provided.", parent_window)
                    success = False
        else:
            show_detailed_error_dialog(f"Source file {src} does not exist.", "Check OVMF installation.", parent_window)
            success = False
    if config["firmware"] == "UEFI":
        config["ovmf_bios"] = os.path.join(ovmf_dir, "OVMF.4m.fd")
    elif config["firmware"] == "UEFI+Secure Boot":
        config["ovmf_code_secure"] = os.path.join(ovmf_dir, "OVMF_CODE.4m.fd")
        config["ovmf_vars_secure"] = os.path.join(ovmf_dir, "OVMF_VARS.4m.fd")
    if copied_count == 0 and config["firmware"] in ["UEFI", "UEFI+Secure Boot"]:
        show_detailed_error_dialog(f"No files found in {src_dir}.", "Install appropriate OVMF package.", parent_window)
        success = False
    return success

def delete_ovmf_dir(config):
    ovmf_dir = os.path.join(config["path"], "ovmf")
    if os.path.exists(ovmf_dir):
        try:
            shutil.rmtree(ovmf_dir)
        except Exception as e:
            show_detailed_error_dialog(f"Error deleting OVMF folder: {e}", str(e), None)
            return False
    return True

def build_launch_command(config):
    host = get_host_os()
    if host in ["arch", "serpentos"]:
        qemu = shutil.which("qemu-kvm") or shutil.which("qemu-system-x86_64")
    elif host in ["fedora", "debian"]:
        qemu = shutil.which("qemu-system-x86_64")
    else:
        qemu = shutil.which("qemu-system-x86_64") or shutil.which("qemu-kvm")
    if not qemu:
        show_detailed_error_dialog("QEMU not found!", "Please install QEMU.", None)
        return None
    cmd = [
        qemu, "-enable-kvm", "-cpu", "host",
        "-smp", str(config["cpu"]),
        "-m", str(config["ram"]),
        "-drive", f"file={config['disk_image']},format={config['disk_type']},if=virtio",
        "-boot", "order=dc,menu=off",
        "-usb", "-device", "usb-tablet",
        "-netdev", "user,id=net0", "-device", "virtio-net-pci,netdev=net0",
    ]
    if config.get("3d_acceleration", False):
        cmd.extend(["-vga", "none", "-device", "virtio-vga-gl"])
    else:
        cmd.extend(["-vga", "virtio"])
    disp = config["display"].lower()
    if disp == "gtk (default)":
        cmd.extend(["-display", "gtk,gl=on" if config.get("3d_acceleration", False) else "gtk"])
    elif disp == "sdl":
        cmd.extend(["-display", "sdl,gl=on" if config.get("3d_acceleration", False) else "sdl"])
    elif disp == "spice (virtio)":
        cmd.extend(["-display", "spice-app"])
        if config.get("3d_acceleration", False):
            cmd.extend(["-spice", "gl=on"])
    elif disp == "virtio":
        cmd.extend(["-display", "egl-headless,gl=on"])
    elif disp == "qemu":
        pass
    if config.get("iso_enabled") and config.get("iso"):
        iso_path = urllib.parse.unquote(config["iso"])
        cmd.extend(["-cdrom", iso_path])
    if config["firmware"] == "UEFI":
        if config.get("ovmf_bios"):
            cmd.extend(["-bios", config["ovmf_bios"]])
    elif config["firmware"] == "UEFI+Secure Boot":
        ovmf_code_secure = os.path.join(config["path"], "ovmf", "OVMF_CODE.4m.fd")
        ovmf_vars_secure = os.path.join(config["path"], "ovmf", "OVMF_VARS.4m.fd")
        if os.path.exists(ovmf_code_secure) and os.path.exists(ovmf_vars_secure):
            cmd.extend([
                "-drive", f"if=pflash,format=raw,readonly=on,file={ovmf_code_secure}",
                "-drive", f"if=pflash,format=raw,file={ovmf_vars_secure}"
            ])
        else:
            show_detailed_error_dialog("Secure Boot files missing!", "OVMF files not found.", None)
    if config.get("tpm_enabled", False):
        tpm_dir = os.path.join(config["path"], "tpm")
        os.makedirs(tpm_dir, exist_ok=True)
        tpm_sock_path = os.path.join(tpm_dir, "tpm0.sock")
        if os.path.exists(tpm_sock_path):
            os.remove(tpm_sock_path)
        cmd.extend([
            "-chardev", f"socket,id=chrtpm,server=on,wait=off,path={tpm_sock_path}",
            "-tpmdev", f"emulator,id=tpm0,chardev=chrtpm",
            "-device", "tpm-crb,tpmdev=tpm0"
        ])
    return cmd

def list_snapshots(vm):
    qemu_img = shutil.which("qemu-img")
    if not qemu_img:
        return []
    try:
        output = subprocess.check_output([qemu_img, "snapshot", "-l", vm["disk_image"]], universal_newlines=True)
        lines = output.splitlines()
        snaps = []
        for line in lines:
            parts = line.split()
            if len(parts) >= 2 and parts[0].isdigit():
                snaps.append(parts[1])
        return snaps
    except Exception:
        return []

def create_snapshot_cmd(vm, snap_name):
    qemu_img = shutil.which("qemu-img")
    if not qemu_img:
        return False
    try:
        subprocess.run([qemu_img, "snapshot", "-c", snap_name, vm["disk_image"]], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False

def restore_snapshot(vm, snap_name):
    qemu_img = shutil.which("qemu-img")
    if not qemu_img:
        return False
    try:
        subprocess.run([qemu_img, "snapshot", "-a", snap_name, vm["disk_image"]], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False

def delete_snapshot(vm, snap_name):
    qemu_img = shutil.which("qemu-img")
    if not qemu_img:
        return False
    try:
        subprocess.run([qemu_img, "snapshot", "-d", snap_name, vm["disk_image"]], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False

def load_vm_index():
    if os.path.exists(CONFIG_FILE) and os.path.getsize(CONFIG_FILE) > 0:
        try:
            with open(CONFIG_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def save_vm_index(index):
    with open(CONFIG_FILE, "w") as f:
        json.dump(index, f, indent=4)

def load_all_vm_configs():
    index = load_vm_index()
    configs = []
    for vm_path in index:
        try:
            for fname in os.listdir(vm_path):
                if fname.endswith(".json"):
                    with open(os.path.join(vm_path, fname), "r") as f:
                        configs.append(json.load(f))
                    break
        except Exception as e:
            show_detailed_error_dialog(f"Error loading config from {vm_path}: {e}", str(e), None)
    return configs

def save_vm_config(config):
    conf_file = os.path.join(config["path"], f"{config['name']}.json")
    try:
        with open(conf_file, "w") as f:
            json.dump(config, f, indent=4)
    except Exception as e:
        show_detailed_error_dialog("Error saving VM config.", str(e), None)
        raise

def prompt_sudo_password(parent):
    d = Gtk.Dialog(title="Sudo Password", transient_for=parent, flags=0)
    d.add_buttons("OK", Gtk.ResponseType.OK, "Cancel", Gtk.ResponseType.CANCEL)
    box = d.get_content_area()
    box.add(Gtk.Label(label="Enter Sudo password:"))
    entry = Gtk.Entry()
    entry.set_visibility(False)
    box.add(entry)
    d.show_all()
    resp = d.run()
    pwd = entry.get_text() if resp == Gtk.ResponseType.OK else None
    d.destroy()
    return pwd

class LoadingDialog(Gtk.Dialog):
    def __init__(self, parent, msg="Installing OVMF Files..."):
        super().__init__(title="Wait", transient_for=parent)
        self.set_modal(True)
        self.set_default_size(300,100)
        box = self.get_content_area()
        box.add(Gtk.Label(label=msg))
        self.progress = Gtk.ProgressBar()
        self.progress.set_show_text(False)
        box.add(self.progress)
        self.show_all()
        self.timeout_id = GLib.timeout_add(100, self.on_timeout)
    def on_timeout(self):
        self.progress.pulse()
        return True
    def destroy(self):
        GLib.source_remove(self.timeout_id)
        super().destroy()

class ProgressDialog(Gtk.Dialog):
    def __init__(self, parent, msg="Processing..."):
        super().__init__(title="Progress", transient_for=parent)
        self.set_modal(True)
        self.set_default_size(300, 100)
        box = self.get_content_area()
        self.percent_label = Gtk.Label(label="0%")
        self.percent_label.set_halign(Gtk.Align.CENTER)
        box.add(self.percent_label)
        self.progress = Gtk.ProgressBar()
        self.progress.set_show_text(False)
        box.add(self.progress)
        self.show_all()
        self.progress_value = 0
        self.timeout_id = GLib.timeout_add(100, self.on_timeout)
    def on_timeout(self):
        self.progress.pulse()
        self.progress_value += 10
        if self.progress_value > 100:
            self.progress_value = 100
        self.percent_label.set_text(f"{self.progress_value}%")
        return self.progress_value < 100
    def destroy(self):
        GLib.source_remove(self.timeout_id)
        super().destroy()

class ISOSelectDialog(Gtk.Window):
    def __init__(self, parent):
        super().__init__(title="Select ISO for Virtual Machine", transient_for=parent)
        self.parent = parent
        self.set_default_size(400,300)
        self.set_position(Gtk.WindowPosition.CENTER)
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        vbox.set_margin_top(20)
        vbox.set_margin_bottom(20)
        vbox.set_margin_start(20)
        vbox.set_margin_end(20)
        btn = Gtk.Button(label="+")
        btn.set_size_request(150,150)
        btn.connect("clicked", self.on_plus_clicked)
        vbox.pack_start(btn, False, False, 0)
        drop = Gtk.EventBox()
        drop.set_size_request(300,150)
        drop.get_style_context().add_class("iso-drop-area")
        drop.connect("drag-data-received", self.on_drag_received)
        drop.drag_dest_set(Gtk.DestDefaults.ALL, [], Gdk.DragAction.COPY)
        target = Gtk.TargetEntry.new("text/uri-list", 0, 0)
        drop.drag_dest_set_target_list(Gtk.TargetList.new([target]))
        vbox.pack_start(drop, True, True, 0)
        vbox.pack_start(Gtk.Label(label="Drag ISO here or click '+'"), False, False, 0)
        skip_btn = Gtk.Button(label="Skip")
        skip_btn.connect("clicked", self.on_skip_clicked)
        vbox.pack_start(skip_btn, False, False, 0)
        self.add(vbox)
    def on_plus_clicked(self, w):
        d = Gtk.FileChooserDialog(title="Select ISO File", parent=self,
                                                        action=Gtk.FileChooserAction.OPEN)
        d.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OPEN, Gtk.ResponseType.OK)
        f = Gtk.FileFilter()
        f.set_name("ISO Files")
        f.add_pattern("*.iso")
        d.add_filter(f)
        if d.run() == Gtk.ResponseType.OK:
            self.iso_chosen(d.get_filename())
        d.destroy()
    def on_drag_received(self, w, dc, x, y, data, info, time):
        uris = data.get_uris()
        if uris:
            self.iso_chosen(uris[0].replace("file://", "").strip())
    def on_skip_clicked(self, w):
        self.destroy()
        d = VMCreateDialog(self.parent)
        if d.run() == Gtk.ResponseType.OK:
            self.parent.add_vm(d.get_vm_config())
        d.destroy()
    def iso_chosen(self, iso_path):
        self.destroy()
        d = VMCreateDialog(self.parent, iso_path)
        if d.run() == Gtk.ResponseType.OK:
            self.parent.add_vm(d.get_vm_config())
        d.destroy()

class VMCreateDialog(Gtk.Dialog):
    def __init__(self, parent, iso_path=None):
        super().__init__(title="New Virtual Machine Configuration", transient_for=parent)
        self.set_default_size(500,500)
        self.iso_path = iso_path
        box = self.get_content_area()
        grid = Gtk.Grid(column_spacing=10, row_spacing=10)
        grid.set_margin_top(10)
        grid.set_margin_bottom(10)
        grid.set_margin_start(10)
        grid.set_margin_end(10)
        grid.attach(Gtk.Label(label="Virtual Machine Name:"), 0, 0, 1, 1)
        self.entry_name = Gtk.Entry()
        grid.attach(self.entry_name, 1, 0, 2, 1)
        grid.attach(Gtk.Label(label="Virtual Machine Directory:"), 0, 1, 1, 1)
        self.entry_path = Gtk.Entry()
        btn = Gtk.Button(label="Browse")
        btn.connect("clicked", self.on_browse)
        grid.attach(self.entry_path, 1, 1, 1, 1)
        grid.attach(btn, 2, 1, 1, 1)
        grid.attach(Gtk.Label(label="CPU Cores:"), 0, 2, 1, 1)
        self.spin_cpu = Gtk.SpinButton.new_with_range(1, os.cpu_count(), 1)
        self.spin_cpu.set_value(2)
        grid.attach(self.spin_cpu, 1, 2, 2, 1)
        grid.attach(Gtk.Label(label=f"Max: {os.cpu_count()}"), 3, 2, 1, 1)
        grid.attach(Gtk.Label(label="RAM (MiB):"), 0, 3, 1, 1)
        self.spin_ram = Gtk.SpinButton.new_with_range(256, 131072, 256)
        self.spin_ram.set_value(4096)
        grid.attach(self.spin_ram, 1, 3, 2, 1)
        grid.attach(Gtk.Label(label="Max: 131072 MiB"), 3, 3, 1, 1)
        grid.attach(Gtk.Label(label="Disk Size (GB):"), 0, 4, 1, 1)
        self.spin_disk = Gtk.SpinButton.new_with_range(1, 128, 1)
        self.spin_disk.set_value(40)
        grid.attach(self.spin_disk, 1, 4, 2, 1)
        grid.attach(Gtk.Label(label="Disk Type:"), 0, 5, 1, 1)
        self.radio_qcow2 = Gtk.RadioButton.new_with_label_from_widget(None, "qcow2 (Recommended)")
        self.radio_raw = Gtk.RadioButton.new_with_label_from_widget(self.radio_qcow2, "raw (Full)")
        grid.attach(self.radio_qcow2, 1, 5, 1, 1)
        grid.attach(self.radio_raw, 2, 5, 1, 1)
        grid.attach(Gtk.Label(label="Firmware:"), 0, 6, 1, 1)
        fw_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        self.radio_bios = Gtk.RadioButton.new_with_label_from_widget(None, "BIOS")
        self.radio_uefi = Gtk.RadioButton.new_with_label_from_widget(self.radio_bios, "UEFI")
        self.radio_secure = Gtk.RadioButton.new_with_label_from_widget(self.radio_bios, "UEFI+Secure Boot")
        fw_box.pack_start(self.radio_bios, False, False, 0)
        fw_box.pack_start(self.radio_uefi, False, False, 0)
        fw_box.pack_start(self.radio_secure, False, False, 0)
        grid.attach(fw_box, 1, 6, 2, 1)
        grid.attach(Gtk.Label(label="Enable TPM:"), 0, 7, 1, 1)
        self.check_tpm = Gtk.CheckButton()
        grid.attach(self.check_tpm, 1, 7, 2, 1)
        grid.attach(Gtk.Label(label="Display:"), 0, 8, 1, 1)
        self.combo_disp = Gtk.ComboBoxText()
        for opt in ["gtk (default)", "sdl", "spice (virtio)", "virtio", "qemu"]:
            self.combo_disp.append_text(opt)
        self.combo_disp.set_active(0)
        grid.attach(self.combo_disp, 1, 8, 2, 1)
        self.recommend_label = Gtk.Label()
        grid.attach(self.recommend_label, 3, 8, 1, 1)
        self.combo_disp.connect("changed", self.on_display_changed)
        grid.attach(Gtk.Label(label="3D Acceleration:"), 0, 9, 1, 1)
        self.check_3d = Gtk.CheckButton()
        grid.attach(self.check_3d, 1, 9, 2, 1)
        box.add(grid)
        self.add_button("Cancel", Gtk.ResponseType.CANCEL)
        self.add_button("Create", Gtk.ResponseType.OK)
        self.show_all()
        self.on_display_changed(self.combo_disp)  # Verschoben nach Initialisierung von check_3d
        self.initial_firmware = "BIOS"
        if self.radio_uefi.get_active():
            self.initial_firmware = "UEFI"
        elif self.radio_secure.get_active():
            self.initial_firmware = "UEFI+Secure Boot"

    def on_display_changed(self, combo):
        selected = combo.get_active_text()
        if selected == "gtk (default)":
            self.recommend_label.set_text("Recommended for Linux")
            self.check_3d.set_sensitive(True)
        elif selected == "sdl":
            self.recommend_label.set_text("Recommended for Linux")
            self.check_3d.set_sensitive(True)
        elif selected == "spice (virtio)":
            self.recommend_label.set_text("Recommended for Windows")
            self.check_3d.set_sensitive(True)  # 3D-Beschleunigung aktiviert
        elif selected == "virtio":
            self.recommend_label.set_text("Optimized for Windows with 3D")
            self.check_3d.set_sensitive(True)  # Neue Option für Windows mit 3D
        elif selected == "qemu":
            self.recommend_label.set_text("")
            self.check_3d.set_sensitive(False)

    def on_browse(self, w):
        d = Gtk.FileChooserDialog(title="Select Folder", parent=self,
                                                        action=Gtk.FileChooserAction.SELECT_FOLDER)
        d.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, "Select", Gtk.ResponseType.OK)
        if d.run() == Gtk.ResponseType.OK:
            self.entry_path.set_text(d.get_filename())
        d.destroy()

    def get_vm_config(self):
        firmware = "BIOS"
        if self.radio_uefi.get_active():
            firmware = "UEFI"
        elif self.radio_secure.get_active():
            firmware = "UEFI+Secure Boot"
        config = {
            "name": self.entry_name.get_text(),
            "path": self.entry_path.get_text(),
            "cpu": self.spin_cpu.get_value_as_int(),
            "ram": self.spin_ram.get_value_as_int(),
            "disk": self.spin_disk.get_value_as_int(),
            "disk_type": "qcow2" if self.radio_qcow2.get_active() else "raw",
            "firmware": firmware,
            "display": self.combo_disp.get_active_text(),
            "iso": self.iso_path if self.iso_path else "",
            "iso_enabled": True if self.iso_path else False,
            "3d_acceleration": self.check_3d.get_active(),
            "disk_image": os.path.join(self.entry_path.get_text(), self.entry_name.get_text() + ".img"),
            "tpm_enabled": self.check_tpm.get_active()
        }
        if not os.path.exists(config["disk_image"]):
            qemu_img = shutil.which("qemu-img")
            if qemu_img:
                try:
                    subprocess.run([qemu_img, "create", "-f", config["disk_type"],
                                                                    config["disk_image"], f"{config['disk']}G"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except Exception as e_img_create:
                    show_detailed_error_dialog(f"Error creating disk: {e_img_create}", str(e_img_create), self)
                    return None

        if config["firmware"] in ["UEFI", "UEFI+Secure Boot"]:
            ovmf_dir = os.path.join(config["path"], "ovmf")
            os.makedirs(ovmf_dir, exist_ok=True)
            if self.initial_firmware == "BIOS":
                if not copy_uefi_files(config, self):
                    return None
        elif self.initial_firmware in ["UEFI", "UEFI+Secure Boot"]:
            delete_ovmf_dir(config)
        config["launch_cmd"] = build_launch_command(config)
        return config

class VMSettingsDialog(Gtk.Dialog):
    def __init__(self, parent, config):
        super().__init__(title="Edit Virtual Machine Settings", transient_for=parent)
        self.set_default_size(500,450)
        self.config = config.copy()
        self.original_name = config["name"]
        box = self.get_content_area()
        grid = Gtk.Grid(column_spacing=10, row_spacing=10)
        grid.set_margin_top(10)
        grid.set_margin_bottom(10)
        grid.set_margin_start(10)
        grid.set_margin_end(10)

        grid.attach(Gtk.Label(label="Virtual Machine Name:"), 0, 0, 1, 1)
        self.entry_name = Gtk.Entry()
        self.entry_name.set_text(self.config.get("name", ""))
        grid.attach(self.entry_name, 1, 0, 2, 1)

        self.check_iso_enable = Gtk.CheckButton()
        self.check_iso_enable.set_active(self.config.get("iso_enabled", False))
        self.check_iso_enable.connect("toggled", self.on_iso_enabled_toggled_settings)
        grid.attach(Gtk.Label(label="ISO Path:"), 0, 1, 1, 1)
        self.entry_iso = Gtk.Entry(text=self.config.get("iso", ""))
        grid.attach(self.entry_iso, 1, 1, 1, 1)
        self.btn_iso_browse = Gtk.Button(label="Browse")
        self.btn_iso_browse.connect("clicked", self.on_iso_browse)
        grid.attach(self.btn_iso_browse, 2, 1, 1, 1)
        grid.attach(self.check_iso_enable, 3, 1, 1, 1)

        grid.attach(Gtk.Label(label="CPU Cores:"), 0, 2, 1, 1)
        self.spin_cpu = Gtk.SpinButton.new_with_range(1, os.cpu_count(), 1)
        self.spin_cpu.set_value(self.config.get("cpu", 2))
        grid.attach(self.spin_cpu, 1, 2, 2, 1)
        grid.attach(Gtk.Label(label=f"Max: {os.cpu_count()}"), 3, 2, 1, 1)
        grid.attach(Gtk.Label(label="RAM (MiB):"), 0, 3, 1, 1)
        self.spin_ram = Gtk.SpinButton.new_with_range(256, 131072, 256)
        self.spin_ram.set_value(self.config.get("ram", 4096))
        grid.attach(self.spin_ram, 1, 3, 2, 1)
        grid.attach(Gtk.Label(label="Max: 131072 MiB"), 3, 3, 1, 1)
        grid.attach(Gtk.Label(label="Firmware:"), 0, 4, 1, 1)
        fw_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        self.radio_bios = Gtk.RadioButton.new_with_label_from_widget(None, "BIOS")
        self.radio_uefi = Gtk.RadioButton.new_with_label_from_widget(self.radio_bios, "UEFI")
        self.radio_secure = Gtk.RadioButton.new_with_label_from_widget(self.radio_bios, "UEFI+Secure Boot")
        fw_box.pack_start(self.radio_bios, False, False, 0)
        fw_box.pack_start(self.radio_uefi, False, False, 0)
        fw_box.pack_start(self.radio_secure, False, False, 0)
        if self.config.get("firmware", "BIOS") == "UEFI":
            self.radio_uefi.set_active(True)
        elif self.config.get("firmware") == "UEFI+Secure Boot":
            self.radio_secure.set_active(True)
        else:
            self.radio_bios.set_active(True)
        grid.attach(fw_box, 1, 4, 2, 1)
        grid.attach(Gtk.Label(label="Enable TPM:"), 0, 5, 1, 1)
        self.check_tpm = Gtk.CheckButton()
        self.check_tpm.set_active(self.config.get("tpm_enabled", False))
        grid.attach(self.check_tpm, 1, 5, 2, 1)
        grid.attach(Gtk.Label(label="Display:"), 0, 6, 1, 1)
        self.combo_disp = Gtk.ComboBoxText()
        for opt in ["gtk (default)", "sdl", "spice (virtio)", "virtio", "qemu"]:
            self.combo_disp.append_text(opt)
        self.combo_disp.set_active(0)
        if self.config.get("display") in ["gtk (default)", "sdl", "spice (virtio)", "virtio", "qemu"]:
            self.combo_disp.set_active(["gtk (default)", "sdl", "spice (virtio)", "virtio", "qemu"].index(self.config.get("display")))
        grid.attach(self.combo_disp, 1, 6, 2, 1)
        self.recommend_label = Gtk.Label()
        grid.attach(self.recommend_label, 3, 6, 1, 1)
        self.combo_disp.connect("changed", self.on_display_changed)
        grid.attach(Gtk.Label(label="3D Acceleration:"), 0, 7, 1, 1)
        self.check_3d = Gtk.CheckButton()
        self.check_3d.set_active(self.config.get("3d_acceleration", False))
        grid.attach(self.check_3d, 1, 7, 2, 1)
        box.add(grid)
        self.add_button("Cancel", Gtk.ResponseType.CANCEL)
        self.add_button("Apply", Gtk.ResponseType.OK)
        self.show_all()
        self.on_display_changed(self.combo_disp)  # Verschoben nach Initialisierung von check_3d
        self.initial_firmware = self.config.get("firmware", "BIOS")
        self.update_iso_entry_sensitivity_settings()

    def on_display_changed(self, combo):
        selected = combo.get_active_text()
        if selected == "gtk (default)":
            self.recommend_label.set_text("Recommended for Linux")
            self.check_3d.set_sensitive(True)
        elif selected == "sdl":
            self.recommend_label.set_text("Recommended for Linux")
            self.check_3d.set_sensitive(True)
        elif selected == "spice (virtio)":
            self.recommend_label.set_text("Recommended for Windows")
            self.check_3d.set_sensitive(True)  # 3D-Beschleunigung aktiviert
        elif selected == "virtio":
            self.recommend_label.set_text("Optimized for Windows with 3D")
            self.check_3d.set_sensitive(True)  # Neue Option für Windows mit 3D
        elif selected == "qemu":
            self.recommend_label.set_text("")
            self.check_3d.set_sensitive(False)

    def on_iso_enabled_toggled_settings(self, check):
        self.update_iso_entry_sensitivity_settings()

    def update_iso_entry_sensitivity_settings(self):
        is_enabled = self.check_iso_enable.get_active()
        self.entry_iso.set_sensitive(is_enabled)
        self.btn_iso_browse.set_sensitive(is_enabled)

    def on_iso_browse(self, w):
        d = Gtk.FileChooserDialog(title="Select ISO File", parent=self,
                                                        action=Gtk.FileChooserAction.OPEN)
        d.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OPEN, Gtk.ResponseType.OK)
        f = Gtk.FileFilter()
        f.set_name("ISO Files")
        f.add_pattern("*.iso")
        d.add_filter(f)
        if d.run() == Gtk.ResponseType.OK:
            self.entry_iso.set_text(d.get_filename())
        d.destroy()

    def get_updated_config(self):
        new_name = self.entry_name.get_text()
        firmware = "BIOS"
        if self.radio_uefi.get_active():
            firmware = "UEFI"
        elif self.radio_secure.get_active():
            firmware = "UEFI+Secure Boot"

        if new_name != self.original_name:
            old_conf_file = os.path.join(self.config["path"], f"{self.original_name}.json")
            new_conf_file = os.path.join(self.config["path"], f"{new_name}.json")
            old_disk_image = self.config["disk_image"]
            new_disk_image = os.path.join(self.config["path"], f"{new_name}.img")

            try:
                if os.path.exists(old_conf_file):
                    os.rename(old_conf_file, new_conf_file)
                if os.path.exists(old_disk_image):
                    os.rename(old_disk_image, new_disk_image)
                self.config["disk_image"] = new_disk_image
                self.config["name"] = new_name
            except Exception as e:
                show_detailed_error_dialog(f"Error renaming files: {e}", str(e), self)
                return None

        self.config["iso"] = urllib.parse.unquote(self.entry_iso.get_text()) if self.check_iso_enable.get_active() else ""
        self.config["iso_enabled"] = self.check_iso_enable.get_active()
        self.config["cpu"] = self.spin_cpu.get_value_as_int()
        self.config["ram"] = self.spin_ram.get_value_as_int()
        if self.config["firmware"] != firmware:
            if firmware in ["UEFI", "UEFI+Secure Boot"]:
                if not copy_uefi_files(self.config, self):
                    show_detailed_error_dialog("Error copying UEFI files.", "Failed to copy OVMF files.", self)
                    return None
            else:
                delete_ovmf_dir(self.config)
        self.config["firmware"] = firmware
        self.config["display"] = self.combo_disp.get_active_text()
        self.config["3d_acceleration"] = self.check_3d.get_active()
        self.config["tpm_enabled"] = self.check_tpm.get_active()
        self.config["launch_cmd"] = build_launch_command(self.config)
        return self.config

class VMCloneDialog(Gtk.Dialog):
    def __init__(self, parent, vm_config):
        super().__init__(title="Clone Virtual Machine", transient_for=parent)
        self.set_default_size(400,200)
        self.original_vm = vm_config
        box = self.get_content_area()
        grid = Gtk.Grid(column_spacing=10, row_spacing=10)
        grid.set_margin_top(10)
        grid.set_margin_bottom(10)
        grid.set_margin_start(10)
        grid.set_margin_end(10)
        grid.attach(Gtk.Label(label="New Virtual Machine Name:"), 0, 0, 1, 1)
        self.entry_new_name = Gtk.Entry(text=self.original_vm["name"] + "_clone")
        grid.attach(self.entry_new_name, 1, 0, 2, 1)
        grid.attach(Gtk.Label(label="New Folder:"), 0, 1, 1, 1)
        self.entry_new_path = Gtk.Entry()
        btn = Gtk.Button(label="Browse")
        btn.connect("clicked", self.on_browse)
        grid.attach(self.entry_new_path, 1, 1, 1, 1)
        grid.attach(btn, 2, 1, 1, 1)
        box.add(grid)
        self.add_button("Cancel", Gtk.ResponseType.CANCEL)
        self.add_button("Clone", Gtk.ResponseType.OK)
        self.show_all()
    def on_browse(self, w):
        d = Gtk.FileChooserDialog(title="Select Folder", parent=self,
                                                        action=Gtk.FileChooserAction.SELECT_FOLDER)
        d.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, "Select", Gtk.ResponseType.OK)
        if d.run() == Gtk.ResponseType.OK:
            self.entry_new_path.set_text(d.get_filename())
        d.destroy()
    def get_clone_info(self):
        return {"new_name": self.entry_new_name.get_text(), "new_path": self.entry_new_path.get_text()}

class ManageSnapshotsDialog(Gtk.Dialog):
    def __init__(self, parent, vm):
        super().__init__(title="Manage Snapshots", transient_for=parent)
        self.set_default_size(600, 400)
        self.vm = vm
        self.notebook = Gtk.Notebook()
        self.create_tab = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.create_tab.set_border_width(10)
        self.create_entry = Gtk.Entry()
        create_btn = Gtk.Button(label="Create Snapshot")
        create_btn.connect("clicked", self.on_create)
        self.create_list = Gtk.ListBox()
        self.create_tab.pack_start(self.create_entry, False, False, 0)
        self.create_tab.pack_start(create_btn, False, False, 0)
        self.create_tab.pack_start(self.create_list, True, True, 0)
        self.restore_tab = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.restore_tab.set_border_width(10)
        self.restore_list = Gtk.ListBox()
        self.restore_list.connect("row-activated", self.on_restore)
        self.restore_tab.pack_start(self.restore_list, True, True, 0)
        self.delete_tab = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.delete_tab.set_border_width(10)
        self.delete_list = Gtk.ListBox()
        self.delete_list.connect("button-press-event", self.on_delete)
        self.delete_tab.pack_start(self.delete_list, True, True, 0)
        self.notebook.append_page(self.create_tab, Gtk.Label(label="Create"))
        self.notebook.append_page(self.restore_tab, Gtk.Label(label="Restore"))
        self.notebook.append_page(self.delete_tab, Gtk.Label(label="Delete"))
        self.get_content_area().add(self.notebook)
        self.add_button("Close", Gtk.ResponseType.CLOSE)
        self.notebook.connect("switch-page", self.on_switch)
        self.refresh_all()
        self.show_all()
    def on_switch(self, notebook, page, page_num):
        self.refresh_all()
    def refresh_all(self):
        self.refresh_list(self.create_list)
        self.refresh_list(self.restore_list)
        self.refresh_list(self.delete_list)
    def refresh_list(self, listbox):
        for child in listbox.get_children():
            listbox.remove(child)
        snaps = list_snapshots(self.vm)
        for snap in snaps:
            row = Gtk.ListBoxRow()
            label = Gtk.Label(label=snap)
            row.add(label)
            listbox.add(row)
            row.show_all()
        listbox.show_all()
    def on_create(self, button):
        snap_name = self.create_entry.get_text()
        if snap_name:
            if create_snapshot_cmd(self.vm, snap_name):
                self.refresh_all()
            else:
                show_detailed_error_dialog("Failed to create snapshot.", "Check qemu-img and disk image.", self)
    def on_restore(self, listbox, row):
        snap = row.get_child().get_text()
        if restore_snapshot(self.vm, snap):
            show_detailed_error_dialog(f"Restored snapshot '{snap}'.", "", self)
        else:
            show_detailed_error_dialog("Failed to restore snapshot.", "Check qemu-img and disk image.", self)
    def on_delete(self, widget, event):
        if event.type == Gdk.EventType.BUTTON_PRESS and event.button == 3:
            row = widget.get_selected_row()
            if row is None:
                for child in widget.get_children():
                    alloc = child.get_allocation()
                    if event.x >= alloc.x and event.x <= alloc.x + alloc.width and event.y >= alloc.y and event.y <= alloc.y + alloc.height:
                        row = child
                        break
            if row:
                snap = row.get_child().get_text()
                menu = Gtk.Menu()
                item = Gtk.MenuItem(label="Delete Snapshot")
                item.connect("activate", lambda w: self.confirm_delete(snap))
                menu.append(item)
                menu.show_all()
                menu.popup_at_pointer(event)
            return True
    def confirm_delete(self, snap):
        d = Gtk.MessageDialog(transient_for=self, flags=0, message_type=Gtk.MessageType.QUESTION, buttons=Gtk.ButtonsType.YES_NO, text=f"Delete snapshot '{snap}'?")
        response = d.run()
        d.destroy()
        if response == Gtk.ResponseType.YES:
            if delete_snapshot(self.vm, snap):
                self.refresh_all()
            else:
                show_detailed_error_dialog("Failed to delete snapshot.", "Check qemu-img and disk image.", self)

class QEMUManagerMain(Gtk.Window):
    def __init__(self):
        super().__init__(title="Nicos Qemu GUI")
        self.set_default_size(1000,700)
        self.vm_configs = load_all_vm_configs()
        self.build_ui()
        self.apply_css()
    def build_ui(self):
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        vbox.set_margin_top(10)
        vbox.set_margin_bottom(10)
        vbox.set_margin_start(10)
        vbox.set_margin_end(10)
        header = Gtk.HeaderBar()
        header.set_show_close_button(True)
        self.set_titlebar(header)
        btn_add = Gtk.Button(label="+")
        btn_add.connect("clicked", self.on_add_vm)
        header.pack_end(btn_add)
        self.listbox = Gtk.ListBox()
        self.listbox.set_selection_mode(Gtk.SelectionMode.NONE)
        self.listbox.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        scrolled = Gtk.ScrolledWindow()
        scrolled.add(self.listbox)
        vbox.pack_start(scrolled, True, True, 0)
        self.add(vbox)
        self.refresh_vm_list()
    def apply_css(self):
        css = b"""
        window { background-color: #1e1e2e; }
        .vm-item { background-color: #2c2c3c; border: none; border-radius: 0; padding: 10px; margin: 2px; color: #ffffff; }
        .round-button { border-radius: 0; padding: 0; background-color: transparent; }
        .iso-drop-area { background-color: rgba(0.9, 0.9, 0.9, 1); }
        """
        sp = Gtk.CssProvider()
        sp.load_from_data(css)
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), sp, Gtk.STYLE_PROVIDER_PRIORITY_USER)
    def on_add_vm(self, w):
        d = ISOSelectDialog(self)
        d.show_all()
    def add_vm(self, config):
        if config is None:
            return
        save_vm_config(config)
        index = load_vm_index()
        if config["path"] not in index:
            index.append(config["path"])
            save_vm_index(index)
        self.vm_configs = load_all_vm_configs()
        self.refresh_vm_list()
    def refresh_vm_list(self):
        for row in self.listbox.get_children():
            self.listbox.remove(row)
        for vm in self.vm_configs:
            row = self.create_vm_row(vm)
            self.listbox.add(row)
        self.listbox.show_all()
    def create_vm_row(self, vm):
        row = Gtk.ListBoxRow()
        row.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        hbox.get_style_context().add_class("vm-item")
        label = Gtk.Label(label=vm["name"])
        label.set_xalign(0.0)
        hbox.pack_start(label, True, True, 0)
        play_btn = Gtk.Button()
        play_btn.set_relief(Gtk.ReliefStyle.NONE)
        play_btn.set_size_request(32,32)
        play_img = Gtk.Image.new_from_icon_name("media-playback-start", Gtk.IconSize.BUTTON)
        play_btn.set_image(play_img)
        play_btn.get_style_context().add_class("round-button")
        play_btn.connect("clicked", lambda b, vm=vm: self.start_vm(vm))
        settings_btn = Gtk.Button()
        settings_btn.set_relief(Gtk.ReliefStyle.NONE)
        settings_btn.set_size_request(32,32)
        set_img = Gtk.Image.new_from_icon_name("preferences-system", Gtk.IconSize.BUTTON)
        settings_btn.set_image(set_img)
        settings_btn.get_style_context().add_class("round-button")
        settings_btn.connect("clicked", lambda b, vm=vm: self.edit_vm(vm))
        hbox.pack_end(settings_btn, False, False, 0)
        hbox.pack_end(play_btn, False, False, 0)
        row.add(hbox)
        row.connect("button-press-event", self.on_vm_item_event, vm)
        return row
    def on_vm_item_event(self, w, event, vm):
        if event.button == 3:
            menu = self.create_context_menu(vm)
            menu.popup_at_pointer(event)
    def create_context_menu(self, vm):
        menu = Gtk.Menu()
        item_start = Gtk.MenuItem(label="Start")
        item_settings = Gtk.MenuItem(label="Edit")
        item_manage_snap = Gtk.MenuItem(label="Manage Snapshots")
        item_delete = Gtk.MenuItem(label="Delete")
        item_clone = Gtk.MenuItem(label="Clone")
        item_start.connect("activate", lambda b, vm=vm: self.start_vm(vm))
        item_settings.connect("activate", lambda b, vm=vm: self.edit_vm(vm))
        item_manage_snap.connect("activate", lambda b, vm=vm: self.open_manage_snapshots(vm))
        item_delete.connect("activate", lambda b, vm=vm: self.delete_vm(vm))
        item_clone.connect("activate", lambda b, vm=vm: self.clone_vm(vm))
        menu.append(item_start)
        menu.append(item_settings)
        menu.append(item_manage_snap)
        menu.append(item_clone)
        menu.append(item_delete)
        menu.show_all()
        return menu
    def open_manage_snapshots(self, vm):
        dlg = ManageSnapshotsDialog(self, vm)
        dlg.run()
        dlg.destroy()
    def start_vm(self, vm):
        if not vm["launch_cmd"]:
            show_detailed_error_dialog("No start command!", "Launch command is missing.", self)
            return
        try:
            subprocess.Popen(vm["launch_cmd"])
        except Exception as e_launch:
            show_detailed_error_dialog(f"Error starting Virtual Machine: {e_launch}", str(e_launch), self)
    def edit_vm(self, vm):
        dialog = VMSettingsDialog(self, vm)
        if dialog.run() == Gtk.ResponseType.OK:
            updated_config = dialog.get_updated_config()
            if updated_config:
                save_vm_config(updated_config)
                self.vm_configs = load_all_vm_configs()
                self.refresh_vm_list()
        dialog.destroy()
    def delete_vm(self, vm):
        dialog = Gtk.Dialog(title="Delete Virtual Machine?", transient_for=self, flags=0)
        dialog.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Delete", Gtk.ResponseType.OK)
        box = dialog.get_content_area()
        box.add(Gtk.Label(label=f"Delete Virtual Machine '{vm['name']}' with all its files?"))
        dialog.show_all()
        resp = dialog.run()
        if resp == Gtk.ResponseType.OK:
            try:
                vm_path = vm["path"]
                conf_file = os.path.join(vm_path, f"{vm['name']}.json")
                if os.path.exists(conf_file):
                    os.remove(conf_file)
                if os.path.exists(vm["disk_image"]):
                    os.remove(vm["disk_image"])
                delete_ovmf_dir(vm)
                tpm_dir = os.path.join(vm_path, "tpm")
                if os.path.exists(tpm_dir):
                    shutil.rmtree(tpm_dir)

                index = load_vm_index()
                if vm_path in index:
                    index.remove(vm_path)
                    save_vm_index(index)
                self.vm_configs = load_all_vm_configs()
                self.refresh_vm_list()
            except Exception as e_del:
                show_detailed_error_dialog(f"Error deleting Virtual Machine: {e_del}", str(e_del), self)
        dialog.destroy()
    def clone_vm(self, vm):
        clone_dialog = VMCloneDialog(self, vm)
        if clone_dialog.run() == Gtk.ResponseType.OK:
            clone_info = clone_dialog.get_clone_info()
            if clone_info:
                progress = ProgressDialog(self, "Cloning VM...")
                new_vm_name = clone_info["new_name"]
                new_vm_path = clone_info["new_path"]
                if not new_vm_path:
                    new_vm_path = os.path.join(os.path.dirname(vm["path"]), new_vm_name)
                new_vm_config = vm.copy()
                new_vm_config["name"] = new_vm_name
                new_vm_config["path"] = new_vm_path
                new_vm_config["disk_image"] = os.path.join(new_vm_path, new_vm_name + ".img")
                ovmf_dir_orig = os.path.join(vm["path"], "ovmf")
                ovmf_dir_clone = os.path.join(new_vm_path, "ovmf")
                tpm_dir_orig = os.path.join(vm["path"], "tpm")
                tpm_dir_clone = os.path.join(new_vm_path, "tpm")

                os.makedirs(new_vm_path, exist_ok=True)
                if os.path.exists(ovmf_dir_orig):
                    shutil.copytree(ovmf_dir_orig, ovmf_dir_clone)
                if os.path.exists(tpm_dir_orig):
                    shutil.copytree(tpm_dir_orig, tpm_dir_clone)

                try:
                    shutil.copy2(vm["disk_image"], new_vm_config["disk_image"])
                    save_vm_config(new_vm_config)
                    index = load_vm_index()
                    if new_vm_config["path"] not in index:
                        index.append(new_vm_config["path"])
                        save_vm_index(index)
                    self.vm_configs = load_all_vm_configs()
                    self.refresh_vm_list()
                except Exception as e_clone:
                    show_detailed_error_dialog(f"Error cloning Virtual Machine: {e_clone}", str(e_clone), self)
                progress.destroy()
        clone_dialog.destroy()

def show_detailed_error_dialog(message, details="", parent=None):
    dialog = Gtk.Dialog(title="Error", transient_for=parent, flags=0)
    dialog.add_buttons("Close", Gtk.ResponseType.OK, "Report", 1)
    box = dialog.get_content_area()
    box.add(Gtk.Label(label=message))
    expander = Gtk.Expander(label="Details")
    textview = Gtk.TextView()
    textview.set_editable(False)
    textview.get_buffer().set_text(details)
    scrolled = Gtk.ScrolledWindow()
    scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
    scrolled.add(textview)
    expander.add(scrolled)
    box.add(expander)
    hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
    error_icon = Gtk.Image.new_from_icon_name("dialog-error", Gtk.IconSize.SMALL_TOOLBAR)
    hbox.pack_start(error_icon, False, False, 0)
    hbox.pack_end(Gtk.Label(label=""), True, True, 0)
    box.add(hbox)
    dialog.show_all()
    while True:
        response = dialog.run()
        if response == 1:
            webbrowser.open("https://github.com/Nico-Shock/QemuGUI-nqg-/issues")
        else:
            break
    dialog.destroy()

if __name__ == '__main__':
    win = QEMUManagerMain()
    win.connect("destroy", Gtk.main_quit)
    win.show_all()
    Gtk.main()
